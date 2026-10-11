#!/usr/bin/env python3
"""VSC 素材库：跨作品复用的人物、声音、场景、道具、动作、特效等素材，做过一次的不再重复做。

  kinds                                         列出素材种类与授权状态（来自 workflow/library.json）
  add --kind K --id ID --name N --summary S --rights R [--file PATH[:ROLE] ...] [--tag T ...] [--attr KEY=JSON ...]
      [--license L] [--commercial yes|no] [--style S] [--source URL] [--provider-ref REF ...]
  promote --project P --record R [--output ID] --kind K --id ID --name N --summary S [--tag T ...] [--attr KEY=JSON ...]
                                                把作品里的一次生成输出收进素材库，来源与提示词随记录带入
  search [QUERY] [--kind K] [--tag T] [--commercial] [--limit N]
  show ID
  use ID --project P [--bible FILE --entity E]  把素材复制进作品 06-素材/素材库/<ID>/；给出资产库时登记为该实体的参考素材，
                                                人声音色写入音色绑定，字幕样式写入全片字幕样式
  check                                         校验全部条目：字段、文件存在且 SHA-256 一致

素材库默认在工作区根目录 library/（本机内容，不进 Git），可用 --library 或环境变量 VSC_LIBRARY 指向别处。
每个条目是 library/<种类>/<ID>/item.json（vsc.library-item/v1）及同目录下的文件。授权状态为 unknown 的素材
不能用进作品；commercial 未确认为 yes 时，use 会提醒商用前须核验授权。
"""
import argparse
import contextlib
import datetime
import fcntl
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

import consistency
import vsc_search

ROOT = Path(__file__).resolve().parent.parent
TAXONOMY_PATH = ROOT / "workflow" / "library.json"
ITEM_FORMAT = "vsc.library-item/v1"
SAFE_ID = consistency.SAFE_ID
COPY_DIR = Path("06-素材") / "素材库"


class LibraryError(RuntimeError):
    """请求无效或素材库内容不一致。"""


def taxonomy():
    data = json.loads(TAXONOMY_PATH.read_text("utf-8"))
    return {kind["id"]: kind for kind in data["kinds"]}, {right["id"]: right for right in data["rights"]}


def library_root(value=None):
    return Path(value or os.environ.get("VSC_LIBRARY") or ROOT / "library")


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def item_errors(item, kinds, rights):
    if not isinstance(item, dict):
        return ["条目必须是对象"]
    errors = []
    if item.get("format") != ITEM_FORMAT:
        errors.append(f"format 必须为 {ITEM_FORMAT}")
    if not (isinstance(item.get("id"), str) and SAFE_ID.fullmatch(item["id"])):
        errors.append("id 必须是安全 ID")
    if not isinstance(item.get("kind"), str) or item["kind"] not in kinds:
        errors.append(f"kind 必须是 {'/'.join(kinds)}")
    for key in ("name", "summary"):
        if not consistency.text(item.get(key)):
            errors.append(f"{key} 必须是非空字符串")
    if not (isinstance(item.get("tags", []), list) and all(consistency.text(tag) for tag in item.get("tags", []))):
        errors.append("tags 必须是字符串数组")
    files = item.get("files", [])
    if not isinstance(files, list):
        errors.append("files 必须是数组")
        files = []
    roles = kinds.get(item.get("kind") if isinstance(item.get("kind"), str) else "", {}).get("file_roles", [])
    for index, entry in enumerate(files):
        if not isinstance(entry, dict) or not consistency.text(entry.get("path")) or Path(entry["path"]).is_absolute() or ".." in Path(entry["path"]).parts:
            errors.append(f"files[{index}].path 必须是条目目录内的相对路径")
        elif Path(entry["path"]) in (Path("item.json"), Path("来源.json")):
            errors.append(f"files[{index}].path 使用了保留文件名 item.json 或 来源.json，请先更名")
        elif not (isinstance(entry.get("sha256"), str) and consistency.SHA256.fullmatch(entry["sha256"])):
            errors.append(f"files[{index}].sha256 必须是 64 位小写十六进制")
        elif entry.get("role") is not None and roles and entry["role"] not in roles:
            errors.append(f"files[{index}].role 必须是 {'/'.join(roles)}")
    if not files and not item.get("attributes") and not item.get("provider_refs"):
        errors.append("没有文件时必须写 attributes 或 provider_refs")
    if not isinstance(item.get("attributes", {}), dict):
        errors.append("attributes 必须是对象")
    granted = item.get("rights")
    if not isinstance(granted, dict) or not isinstance(granted.get("status"), str) or granted["status"] not in rights:
        errors.append(f"rights.status 必须是 {'/'.join(rights)}")
    else:
        if granted["status"] in ("licensed", "generated", "open") and not consistency.text(granted.get("license")):
            errors.append(f"rights.status 为 {granted['status']} 时必须写 license")
        if granted.get("commercial_use") is not None and not isinstance(granted["commercial_use"], bool):
            errors.append("rights.commercial_use 只能是 true、false 或 null（未核验）")
    refs = item.get("provider_refs", [])
    if not isinstance(refs, list):
        errors.append("provider_refs 必须是数组")
        refs = []
    for index, ref in enumerate(refs):
        if not isinstance(ref, dict) or not consistency.text(ref.get("provider")) or not consistency.text(ref.get("ref")):
            errors.append(f"provider_refs[{index}] 必须写 provider 与 ref")
    return errors


def load_items(root):
    items = []
    for path in sorted(Path(root).glob("*/*/item.json")):
        try:
            item = json.loads(path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LibraryError(f"{path}：无法读取：{exc}") from None
        if not isinstance(item, dict):
            raise LibraryError(f"{path}：条目必须是对象")
        items.append((path.parent, item))
    return items


def find(root, item_id):
    for folder, item in load_items(root):
        if item.get("id") == item_id:
            return folder, item
    raise LibraryError(f"素材库中没有 {item_id}")


def save(folder, item, kinds, rights):
    errors = item_errors(item, kinds, rights)
    if errors:
        raise LibraryError("条目无效：" + "；".join(errors))
    folder.mkdir(parents=True, exist_ok=True)
    write_json(folder / "item.json", item)


def write_json(path, value):
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=".tmp-", delete=False) as handle:
        tmp = Path(handle.name)
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    try:
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


@contextlib.contextmanager
def mutation_lock(root, project=None):
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".library.lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            if project:
                # 与项目 CLI 共用锁，但不修改其 vsc.json 或批准记录。
                with (Path(project) / ".vsc.lock").open("a") as project_handle:
                    fcntl.flock(project_handle, fcntl.LOCK_EX)
                    try:
                        yield
                    finally:
                        fcntl.flock(project_handle, fcntl.LOCK_UN)
            else:
                yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def checked_item(folder, item, kinds, rights):
    errors = item_errors(item, kinds, rights)
    if errors:
        raise LibraryError("条目无效：" + "；".join(errors))
    for entry in item.get("files", []):
        path = folder / entry["path"]
        if not path.resolve().is_relative_to(folder.resolve()):
            raise LibraryError("素材文件不能通过符号链接越出条目目录")
        if not path.is_file() or sha256(path) != entry["sha256"]:
            raise LibraryError(f"素材库文件不存在或 SHA-256 不一致：{path}")


def parse_attrs(pairs):
    attributes = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            raise LibraryError(f"--attr 应写成 KEY=JSON：{pair}")
        try:
            attributes[key] = json.loads(value)
        except json.JSONDecodeError:
            attributes[key] = value
    return attributes


def copy_in(folder, source, role=None):
    source = Path(source)
    if not source.is_file():
        raise LibraryError(f"文件不存在：{source}")
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / source.name
    if target.exists() and sha256(target) != sha256(source):
        raise LibraryError(f"条目内已有同名但内容不同的文件：{source.name}")
    shutil.copy2(source, target)
    entry = {"path": source.name, "sha256": sha256(target)}
    return {**entry, "role": role} if role else entry


def new_item(args, kinds, rights):
    if args.kind not in kinds:
        raise LibraryError(f"未知种类 {args.kind}；可用：{'/'.join(kinds)}")
    if not SAFE_ID.fullmatch(args.id):
        raise LibraryError("id 必须是安全 ID")
    root = library_root(args.library)
    if any(item.get("id") == args.id for _, item in load_items(root)):
        raise LibraryError(f"素材库已有 {args.id}；复用它，或换一个 ID")
    return root / args.kind / args.id, {"format": ITEM_FORMAT, "id": args.id, "kind": args.kind, "name": args.name, "summary": args.summary,
                                        "tags": args.tag, "style": args.style, "files": [], "attributes": parse_attrs(args.attr),
                                        "created_at": now(), "used_by": []}


def add(args):
    kinds, rights = taxonomy()
    folder, item = new_item(args, kinds, rights)
    commercial = {"yes": True, "no": False, None: None}[args.commercial]
    item["rights"] = {"status": args.rights, "license": args.license, "commercial_use": commercial, "source": args.source}
    item["provider_refs"] = [{"provider": "volcengine_ark" if ref.startswith("asset://") else "external", "ref": ref} for ref in args.provider_ref]
    with tempfile.TemporaryDirectory(prefix=".add-", dir=library_root(args.library)) as temp:
        stage = Path(temp) / "item"
        for spec in args.file:
            path, _, role = spec.rpartition(":") if re.search(r":[a-z_0-9]+$", spec) else (spec, "", "")
            item["files"].append(copy_in(stage, path, role or None))
        save(stage, item, kinds, rights)
        folder.parent.mkdir(parents=True, exist_ok=True)
        stage.rename(folder)
    return folder / "item.json"


def promote(args):
    kinds, rights = taxonomy()
    project = Path(args.project)
    record_path = Path(args.record)
    record = consistency.load(record_path, consistency.RECORD_FORMAT)
    errors = consistency.record_errors(record)
    if errors:
        raise LibraryError("生成记录无效：" + "；".join(errors))
    project_id = json.loads((project / "vsc.json").read_text("utf-8"))["project_id"]
    if record.get("project_id") != project_id or record.get("status") not in ("succeeded", "partial"):
        raise LibraryError("只能收入本作品中成功或部分成功的生成输出")
    outputs = [output for output in record.get("outputs", []) if not args.output or output.get("id") == args.output]
    if not outputs:
        raise LibraryError("生成记录中没有指定的输出")
    if len(outputs) > 1 and not args.output:
        raise LibraryError("有多个输出，请用 --output 明确选择素材")
    output = outputs[0]
    folder, item = new_item(args, kinds, rights)
    engine = record.get("engine", {})
    item["rights"] = {"status": "generated", "license": f"{engine.get('provider')} 服务条款", "commercial_use": None, "source": None}
    try:
        shown = str(record_path.resolve().relative_to(project.resolve()))
    except ValueError:
        shown = str(record_path)
    item["provenance"] = {"project_id": record.get("project_id"), "record": shown, "provider": engine.get("provider"),
                          "model": engine.get("model"), "prompt": record.get("inputs", {}).get("prompt"), "generated_at": record.get("finished_at")}
    item["provider_refs"] = ([{"provider": engine.get("provider"), "ref": "trusted_original", "until": output["face_trust_until"]}]
                             if output.get("face_trust_until") else [])
    source = project / output["path"]
    if not source.resolve().is_relative_to(project.resolve()):
        raise LibraryError("生成输出不能越出作品目录")
    if not source.is_file() or sha256(source) != output["sha256"]:
        raise LibraryError("作品中的文件与生成记录的 SHA-256 不一致，不能收入素材库")
    with tempfile.TemporaryDirectory(prefix=".promote-", dir=library_root(args.library)) as temp:
        stage = Path(temp) / "item"
        entry = copy_in(stage, source, args.role)
        entry.update({key: output[key] for key in ("source_url", "source_url_expires_at", "face_trust_until") if output.get(key)})
        item["files"].append(entry)
        save(stage, item, kinds, rights)
        folder.parent.mkdir(parents=True, exist_ok=True)
        stage.rename(folder)
    return folder / "item.json"


def fields_of(kinds):
    def fields(pair):
        _, item = pair
        kind = kinds.get(item.get("kind"), {})
        return [(4, item.get("id")), (4, item.get("name")), (3, " ".join(item.get("tags", []))), (2, item.get("summary")),
                (2, f"{kind.get('label', '')} {kind.get('group', '')} {item.get('kind')}"), (1, item.get("style")),
                (1, vsc_search.flatten(item.get("attributes"))), (1, vsc_search.flatten(item.get("provenance", {}).get("prompt")))]
    return fields


def search(args):
    kinds, rights = taxonomy()
    items = [pair for pair in load_items(library_root(args.library))
             if (not args.kind or pair[1].get("kind") == args.kind) and (not args.tag or set(args.tag) <= set(pair[1].get("tags", [])))
             and (not args.commercial or pair[1].get("rights", {}).get("commercial_use") is True)]
    found = vsc_search.rank(items, " ".join(args.query), fields_of(kinds), args.limit)
    for value, (_, item) in found:
        label = kinds.get(item.get("kind"), {}).get("label", item.get("kind"))
        status = rights.get(item.get("rights", {}).get("status"), {}).get("label", "?")
        print(f"{value:5.1f}  {item['id']}  [{label}]  {item['name']} — {item['summary']}  （{status}）")
    if not found:
        print("没有匹配的素材")


def use(args):
    kinds, rights = taxonomy()
    root = library_root(args.library)
    folder, item = find(root, args.id)
    checked_item(folder, item, kinds, rights)
    status = item.get("rights", {}).get("status")
    if status == "unknown" and not args.allow_unverified:
        raise LibraryError(f"{args.id} 授权未核验，不能用进作品（研究对照可加 --allow-unverified）")
    warnings = []
    if status == "temp_only":
        warnings.append(f"{args.id} 仅限预演，不得进入交付物")
    if item.get("rights", {}).get("commercial_use") is not True:
        warnings.append(f"{args.id} 尚未确认可商用：商用前须核验授权（{item.get('rights', {}).get('license') or '未写许可'}）")
    project = Path(args.project)
    project_id = json.loads((project / "vsc.json").read_text("utf-8"))["project_id"]
    manifest = project / COPY_DIR / item["id"] / "来源.json"
    if manifest.is_symlink() or not manifest.resolve().is_relative_to(project.resolve()):
        raise LibraryError("来源清单路径不能通过符号链接越出作品或覆盖链接")
    if args.bible:
        bible = consistency.load(args.bible, consistency.BIBLE_FORMAT)
        if bible.get("project_id") != project_id:
            raise LibraryError("资产库与目标作品的 project_id 不一致")
        if not Path(args.bible).resolve().is_relative_to(project.resolve()):
            raise LibraryError("资产库必须位于目标作品目录内")
    copies = []
    planned = []
    for entry in item.get("files", []):
        source = folder / entry["path"]
        if sha256(source) != entry["sha256"]:
            raise LibraryError(f"素材库文件已被改动：{source}")
        target = project / COPY_DIR / item["id"] / entry["path"]
        if not target.resolve().is_relative_to(project.resolve()):
            raise LibraryError("目标路径不能通过符号链接越出作品")
        if target.exists() and sha256(target) != entry["sha256"]:
            raise LibraryError(f"作品中已存在不同内容的素材：{target}；请使用新素材 ID")
        planned.append((source, target))
        copies.append({"path": str(target.relative_to(project)), "sha256": entry["sha256"], "view": entry.get("role") or item["kind"], "library": item["id"]})
    changed = bind(args, item, kinds, copies, write=False) if args.bible else None
    for source, target in planned:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    write_json(manifest, {"format": "vsc.library-use/v1", "item_id": item["id"], "project_id": project_id,
                         "provider": item.get("provenance", {}).get("provider"), "rights": item["rights"],
                         "attributes": item.get("attributes", {}), "provider_refs": item.get("provider_refs", []),
                         "files": [{**entry, "path": copy["path"]} for entry, copy in zip(item.get("files", []), copies)]})
    if args.bible:
        write_json(Path(args.bible), changed)
    used = [entry for entry in item.get("used_by", []) if entry.get("project_id") != project_id]
    item["used_by"] = used + [{"project_id": project_id, "at": now()}]
    save(folder, item, kinds, rights)
    for warning in warnings:
        print(f"WARN {warning}", file=sys.stderr)
    return copies


def bind(args, item, kinds, copies, write=True):
    bible_path = Path(args.bible)
    bible = consistency.load(bible_path, consistency.BIBLE_FORMAT)
    attributes = item.get("attributes", {})
    if item["kind"] == "subtitle_style":
        bible["subtitle_style"] = attributes
    else:
        if not args.entity:
            raise LibraryError("登记进资产库需要 --entity")
        index = consistency.entity_index(bible)
        entity = index.get(args.entity)
        if item["kind"] == "voice":
            if entity is None:
                raise LibraryError(f"资产库中没有人物 {args.entity}，无法绑定音色")
            entity["voice"] = {key: attributes[key] for key in ("engine", "voice", "rate", "rights") if key in attributes}
            entity["voice"]["library"] = item["id"]
        else:
            expected = kinds[item["kind"]].get("bible_kind")
            if entity is not None and expected != entity.get("kind"):
                raise LibraryError("素材种类与目标实体种类不一致")
            if entity is None:
                bible_kind = kinds[item["kind"]].get("bible_kind")
                if not bible_kind:
                    raise LibraryError(f"{kinds[item['kind']]['label']} 不是资产库实体，不能新建 {args.entity}；只复制文件时去掉 --bible")
                entity = {"id": args.entity, "kind": bible_kind, "name": item["name"], "identity": attributes.get("identity", []),
                          "variants": attributes.get("variants") or {"default": item["summary"]},
                          "generation": {"prompt": attributes.get("prompt") or item["summary"]}, "references": []}
                bible["entities"].append(entity)
            known = {ref.get("sha256") for ref in entity.setdefault("references", [])}
            entity["references"] += [ref for ref in copies if ref["sha256"] not in known]
    errors = consistency.bible_errors(bible)
    if errors:
        raise LibraryError("登记后资产库无效（未写入）：" + "；".join(errors))
    if write:
        write_json(bible_path, bible)
    return bible


def check(args):
    kinds, rights = taxonomy()
    problems, seen = [], set()
    items = load_items(library_root(args.library))
    for folder, item in items:
        label = item.get("id") or str(folder)
        errors = item_errors(item, kinds, rights)
        problems += [f"{label}：{error}" for error in errors]
        if errors:
            continue
        if item.get("id") in seen:
            problems.append(f"{label}：ID 重复")
        seen.add(item.get("id"))
        if folder.parent.name != item.get("kind") or folder.name != item.get("id"):
            problems.append(f"{label}：目录应为 {item.get('kind')}/{item.get('id')}")
        for entry in item.get("files", []):
            path = folder / entry.get("path", "")
            if not path.resolve().is_relative_to(folder.resolve()):
                problems.append(f"{label}：文件越出条目目录 {entry.get('path')}")
            elif not path.is_file():
                problems.append(f"{label}：文件不存在 {entry.get('path')}")
            elif sha256(path) != entry.get("sha256"):
                problems.append(f"{label}：文件内容与 SHA-256 不一致 {entry.get('path')}")
    return len(items), problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--library", help="素材库目录，默认 VSC_LIBRARY 或工作区 library/")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("kinds")
    describe = argparse.ArgumentParser(add_help=False)
    describe.add_argument("--kind", required=True)
    describe.add_argument("--id", required=True)
    describe.add_argument("--name", required=True)
    describe.add_argument("--summary", required=True)
    describe.add_argument("--tag", action="append", default=[])
    describe.add_argument("--attr", action="append", default=[])
    describe.add_argument("--style")
    command = sub.add_parser("add", parents=[describe])
    command.add_argument("--rights", required=True)
    command.add_argument("--license")
    command.add_argument("--commercial", choices=("yes", "no"))
    command.add_argument("--source")
    command.add_argument("--file", action="append", default=[], help="PATH 或 PATH:ROLE")
    command.add_argument("--provider-ref", action="append", default=[], help="例如 asset://<素材 ID>")
    command = sub.add_parser("promote", parents=[describe])
    command.add_argument("--project", required=True)
    command.add_argument("--record", required=True)
    command.add_argument("--output")
    command.add_argument("--role")
    command = sub.add_parser("search")
    command.add_argument("query", nargs="*")
    command.add_argument("--kind")
    command.add_argument("--tag", action="append", default=[])
    command.add_argument("--commercial", action="store_true", help="只看已确认可商用的素材")
    command.add_argument("--limit", type=int, default=20)
    command = sub.add_parser("show")
    command.add_argument("id")
    command = sub.add_parser("use")
    command.add_argument("id")
    command.add_argument("--project", required=True)
    command.add_argument("--bible")
    command.add_argument("--entity")
    command.add_argument("--allow-unverified", action="store_true")
    sub.add_parser("check")
    sub.add_parser("validate").add_argument("file")
    args = parser.parse_args(argv)
    try:
        if args.command == "kinds":
            kinds, rights = taxonomy()
            for kind in kinds.values():
                print(f"{kind['group']}  {kind['id']:<15}{kind['label']}：{kind['summary']}")
            print("授权状态：" + "；".join(f"{right['id']}（{right['label']}）" for right in rights.values()))
        elif args.command in ("add", "promote"):
            with mutation_lock(library_root(args.library)):
                print(add(args) if args.command == "add" else promote(args))
        elif args.command == "search":
            search(args)
        elif args.command == "show":
            folder, item = find(library_root(args.library), args.id)
            print(json.dumps({**item, "folder": str(folder)}, ensure_ascii=False, indent=2))
        elif args.command == "use":
            with mutation_lock(library_root(args.library), args.project):
                for ref in use(args):
                    print(ref["path"])
        elif args.command == "validate":
            kinds, rights = taxonomy()
            errors = item_errors(json.loads(Path(args.file).read_text("utf-8")), kinds, rights)
            if errors:
                raise LibraryError("；".join(errors))
            print("VALID: 素材条目")
        else:
            count, problems = check(args)
            for problem in problems:
                print(f"INVALID: {problem}", file=sys.stderr)
            if problems:
                return 1
            print(f"VALID: 素材库 {count} 个条目")
    except (LibraryError, ValueError, OSError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
