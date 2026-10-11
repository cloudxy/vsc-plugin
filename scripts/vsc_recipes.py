#!/usr/bin/env python3
"""原生制作规格包：list/search/show/validate/install；离线规格，不是已生成媒体。"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import vsc_library as library
import vsc_search

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "knowledge/asset-recipes.json"
FORMAT = "vsc.asset-recipes/v1"
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+\Z")


def strings(value):
    return isinstance(value, list) and bool(value) and all(isinstance(x, str) and x.strip() for x in value)


def errors(data):
    """校验完整规格包（包括 taxonomy 覆盖与各类可制作字段），不把文本当媒体凭证。"""
    if not isinstance(data, dict):
        return ["规格包必须是对象"]
    problems = []
    if data.get("format") != FORMAT:
        problems.append(f"format 必须为 {FORMAT}")
    if not isinstance(data.get("version"), str) or not VERSION.fullmatch(data["version"]):
        problems.append("version 必须是三段数字版本")
    recipes = data.get("recipes")
    if not isinstance(recipes, list) or not recipes:
        return problems + ["recipes 必须是非空数组"]
    kinds, _ = library.taxonomy()
    seen, coverage = set(), set()
    for index, recipe in enumerate(recipes):
        if not isinstance(recipe, dict):
            problems.append(f"recipes[{index}] 必须是对象")
            continue
        rid, kind = recipe.get("id"), recipe.get("kind")
        label = rid if isinstance(rid, str) else str(index)
        if not isinstance(rid, str) or not library.SAFE_ID.fullmatch(rid) or rid in seen:
            problems.append(f"{label}: id 必须是唯一安全 ID")
        else:
            seen.add(rid)
        if not isinstance(kind, str) or kind not in kinds:
            problems.append(f"{label}: kind 必须来自 workflow/library.json")
        else:
            coverage.add(kind)
        for key in ("name", "summary"):
            if not isinstance(recipe.get(key), str) or not recipe[key].strip():
                problems.append(f"{label}: {key} 必须非空")
        if not isinstance(recipe.get("version"), str) or not VERSION.fullmatch(recipe["version"]):
            problems.append(f"{label}: version 必须是三段数字版本")
        if not strings(recipe.get("tags")):
            problems.append(f"{label}: tags 必须是非空字符串数组")
        if "craft_refs" in recipe and (not isinstance(recipe["craft_refs"], list) or
                                       not all(isinstance(x, str) and library.SAFE_ID.fullmatch(x) for x in recipe["craft_refs"])):
            problems.append(f"{label}: craft_refs 必须是安全 ID 数组")
        rights = recipe.get("rights")
        if not isinstance(rights, dict) or rights.get("status") != "owned" or rights.get("scope") != "specification_only" or not isinstance(rights.get("license"), str) or not rights["license"].strip():
            problems.append(f"{label}: rights 必须标明 owned、specification_only 和 license")
        spec = recipe.get("spec")
        if not isinstance(spec, dict):
            problems.append(f"{label}: spec 必须是对象")
            continue
        for key in ("fixed", "variable", "inputs", "procedure", "acceptance", "deliverables"):
            if not strings(spec.get(key)):
                problems.append(f"{label}: spec.{key} 必须是非空字符串数组")
        required = []
        if kind in ("motion", "fight", "performance", "camera_move", "transition"):
            required += ["entry_state", "exit_state", "camera", "duration", "beats"]
        if kind in ("motion", "fight"):
            required += ["safety"]
        if kind == "voice":
            required += ["speaker_binding", "delivery", "rights_gate"]
            if spec.get("speaker_binding") != {"speaker_id": "<PROJECT_SPEAKER_ID>", "provider": None, "voice_id": None, "lock_after_selection": True}:
                problems.append(f"{label}: speaker_binding 必须保留固定 speaker 占位与空 provider/voice_id")
        if kind in ("ambience", "sfx", "music"):
            required += ["loop", "dialogue_space", "rights_gate", "entry", "exit", "delivery"]
        for key in required:
            if key == "speaker_binding":
                continue  # 以上已精确检查占位绑定的结构和值。
            if key in ("beats", "safety"):
                valid = strings(spec.get(key))
            else:
                valid = isinstance(spec.get(key), str) and bool(spec[key].strip())
            if not valid:
                problems.append(f"{label}: spec.{key} 必须是非空{'字符串数组' if key in ('beats', 'safety') else '字符串'}")
    missing = sorted(set(kinds) - coverage)
    if missing:
        problems.append("缺少分类：" + "/".join(missing))
    return problems


def load(path=CATALOG):
    data = json.loads(Path(path).read_text("utf-8"))
    problems = errors(data)
    if problems:
        raise ValueError("；".join(problems))
    return data


def fields(recipe):
    kinds, _ = library.taxonomy()
    return [(4, recipe["id"]), (4, recipe["name"]), (3, " ".join(recipe["tags"])),
            (2, recipe["summary"]), (2, kinds[recipe["kind"]]["label"]), (1, vsc_search.flatten(recipe["spec"]))]


def attributes(recipe):
    digest = hashlib.sha256(json.dumps(recipe, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return {"asset_type": "specification", "is_media": False, "requires_human_selection": True,
            "recipe": {"id": recipe["id"], "version": recipe["version"], "sha256": digest},
            "spec": recipe["spec"], "craft_refs": recipe.get("craft_refs", []),
            "rights_scope": "specification_only"}


def install(recipes, root):
    """在现有库锁内预检全部冲突，再调用 library.add；不自行构造 item.json。"""
    root = library.library_root(root)
    kinds, rights = library.taxonomy()
    result = []
    with library.mutation_lock(root):
        existing = {}
        for folder, item in library.load_items(root):
            library.checked_item(folder, item, kinds, rights)
            if item.get("id") in existing:
                raise ValueError(f"素材库 ID 重复：{item.get('id')}")
            existing[item.get("id")] = (folder, item)
        pending = []
        for recipe in recipes:
            rid = recipe["id"]
            target = root / recipe["kind"] / rid
            if target.is_symlink() or target.parent.is_symlink() or not target.resolve().is_relative_to(root.resolve()):
                raise ValueError(f"安装路径不能通过符号链接越出素材库：{rid}")
            attrs = attributes(recipe)
            if rid in existing:
                folder, item = existing[rid]
                library.checked_item(folder, item, kinds, rights)
                same = (folder.resolve() == target.resolve() and item.get("kind") == recipe["kind"] and
                        item.get("name") == recipe["name"] and item.get("summary") == recipe["summary"] and
                        item.get("tags") == recipe["tags"] and item.get("attributes") == attrs and
                        item.get("rights") == {"status": "owned", "license": recipe["rights"]["license"], "commercial_use": True, "source": None} and
                        not item.get("files") and not item.get("provider_refs") and item.get("style") is None)
                if not same:
                    raise ValueError(f"版本冲突或不同内容：{rid}；不覆盖，请使用新 ID")
                result.append(("UNCHANGED", folder / "item.json"))
            else:
                if target.exists():
                    raise ValueError(f"安装目录已存在：{target}；不覆盖")
                pending.append((recipe, attrs))
        for recipe, attrs in pending:
            args = SimpleNamespace(library=str(root), kind=recipe["kind"], id=recipe["id"], name=recipe["name"],
                                   summary=recipe["summary"], tag=recipe["tags"], style=None,
                                   attr=[f"{key}={json.dumps(value, ensure_ascii=False)}" for key, value in attrs.items()],
                                   rights="owned", license=recipe["rights"]["license"], commercial="yes", source=None,
                                   provider_ref=[], file=[])
            result.append(("INSTALLED", library.add(args)))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default=str(CATALOG), help="规格包 JSON（只读输入）")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("list", "search"):
        command = sub.add_parser(name)
        if name == "search":
            command.add_argument("query", nargs="*")
        command.add_argument("--kind")
        command.add_argument("--limit", type=int, default=100)
        command.add_argument("--json", action="store_true")
    sub.add_parser("show").add_argument("id")
    sub.add_parser("validate").add_argument("file", nargs="?")
    command = sub.add_parser("install")
    selection = command.add_mutually_exclusive_group(required=True)
    selection.add_argument("id", nargs="?")
    selection.add_argument("--all", action="store_true")
    command.add_argument("--library", help="目标素材库；默认 VSC_LIBRARY 或 library/")
    args = parser.parse_args(argv)
    try:
        data = load(args.file or args.catalog) if args.command == "validate" else load(args.catalog)
        recipes = data["recipes"]
        if args.command == "validate":
            print(f"VALID: {len(recipes)} 条原创制作规格，覆盖全部 {len(library.taxonomy()[0])} 类；不是媒体")
        elif args.command in ("show", "install"):
            selected = recipes if args.command == "install" and args.all else [x for x in recipes if x["id"] == args.id]
            if not selected:
                raise ValueError(f"没有规格 {args.id}")
            if args.command == "show":
                print(json.dumps(selected[0], ensure_ascii=False, indent=2))
            else:
                for status, path in install(selected, args.library):
                    print(f"{status}: {path}")
        else:
            if args.limit < 1:
                raise ValueError("--limit 必须大于 0")
            if args.kind and args.kind not in library.taxonomy()[0]:
                raise ValueError(f"未知种类 {args.kind}")
            selected = [x for x in recipes if not args.kind or x["kind"] == args.kind]
            found = vsc_search.rank(selected, " ".join(getattr(args, "query", [])), fields, args.limit)
            if args.json:
                print(json.dumps([{"score": score, **recipe} for score, recipe in found], ensure_ascii=False, indent=2))
            else:
                for score, recipe in found:
                    print(f"{score:5.1f} {recipe['id']} [{recipe['kind']}] {recipe['name']} — {recipe['summary']}（制作规格，待人工选择）")
                if not found:
                    print("没有匹配的规格")
    except (ValueError, OSError, library.LibraryError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
