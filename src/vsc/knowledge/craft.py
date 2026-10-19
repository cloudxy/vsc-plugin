#!/usr/bin/env python3
"""公开创作方法库：search [词...]、show ID [--with-teaching]、validate [FILE]。方法建议不继承项目批准。"""
from vsc.bootstrap import repository_root
import argparse
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import re
import sys
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

from vsc.knowledge import search as vsc_search

ROOT = repository_root()
CATALOG = ROOT / "knowledge/craft.json"
FORMAT = "vsc.craft-catalog/v1"
TEACHING_DIGEST_FORMAT = "vsc.craft-teaching-digest/v1"
TEACHING_SOFT_TARGET_CHARS = 1600
_ANCHOR_ID = re.compile(r"[A-Za-z0-9_.:-]+\Z")
_ANCHOR_TAG = re.compile(r"<a\s+id\s*=\s*(['\"])([^'\"]+)\1\s*>\s*</a\s*>", re.IGNORECASE)
_HEADING = re.compile(r" {0,3}(#{1,6})(?:[ \t]+|$)")
_FENCE = re.compile(r" {0,3}(`{3,}|~{3,})(.*)$")


def teaching_path(ref):
    """Accept only canonical, root-contained Skill reference Markdown files."""
    if not isinstance(ref, dict) or set(ref) != {"path", "anchor"}:
        raise ValueError("teaching_ref 必须是仅含 path、anchor 的对象")
    path, anchor = ref["path"], ref["anchor"]
    if not isinstance(path, str) or not path or "\\" in path or "\x00" in path:
        raise ValueError("teaching_ref.path 必须是根内 POSIX 相对路径")
    relative = PurePosixPath(path)
    if (relative.is_absolute() or relative.as_posix() != path or ".." in relative.parts
            or len(relative.parts) != 4 or relative.parts[0] != "skills"
            or relative.parts[2] != "references" or relative.suffix != ".md"):
        raise ValueError("teaching_ref.path 仅允许 skills/*/references/*.md，不允许绝对路径或 ..")
    if not isinstance(anchor, str) or not _ANCHOR_ID.fullmatch(anchor):
        raise ValueError("teaching_ref.anchor 必须是非空 ASCII 锚点（字母、数字、_.:-）")
    root = ROOT.resolve()
    try:
        resolved = (root / path).resolve(strict=True)
        actual = resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError(f"教学路径不存在或软链越出工作流根目录：{path}") from exc
    if (len(actual.parts) != 4 or actual.parts[0] != "skills"
            or actual.parts[2] != "references" or actual.suffix != ".md" or not resolved.is_file()):
        raise ValueError(f"教学路径须解析为 skills/*/references/*.md 文件：{path}")
    return resolved


def read_teaching(ref):
    """Read an explicit ATX section verbatim after LF normalization; never execute it."""
    path = teaching_path(ref)
    body = path.read_bytes().decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    parts = body.split("\n")
    lines = [line + "\n" for line in parts[:-1]] + [parts[-1]]
    headings, occurrences, fence = [], [], None
    for index, line in enumerate(lines):
        # A closing fence must use the opener's character and at least its length.
        marker = _FENCE.fullmatch(line.removesuffix("\n"))
        if fence:
            if (marker and marker[1][0] == fence[0] and len(marker[1]) >= fence[1]
                    and not marker[2].strip()):
                fence = None
            continue
        if marker and (marker[1][0] != "`" or "`" not in marker[2]):
            fence = (marker[1][0], len(marker[1]))
            continue
        heading = _HEADING.match(line)
        if heading:
            headings.append((index, len(heading[1])))
        for match in _ANCHOR_TAG.finditer(line):
            if match[2] == ref["anchor"]:
                occurrences.append((index, len(heading[1]) if heading else None))
    if not occurrences:
        raise ValueError(f"教学锚点缺失：{ref['anchor']}")
    if len(occurrences) != 1:
        raise ValueError(f"教学锚点重复：{ref['anchor']}")
    start, level = occurrences[0]
    if level is None:
        raise ValueError(f"教学锚点必须附于 ATX 标题同行：{ref['anchor']}")
    end = next((index for index, depth in headings if index > start and depth <= level), len(lines))
    if not any(line.strip() for line in lines[start + 1:end]):
        raise ValueError(f"教学章节没有正文：{ref['anchor']}")
    return {"path": ref["path"], "anchor": ref["anchor"], "body": "".join(lines[start:end])}


def teaching_digest(card, source_details, teaching):
    payload = {"format": TEACHING_DIGEST_FORMAT, "method_id": card["id"], "card": card,
               "source_details": sorted(source_details, key=lambda source: source["id"]), "teaching": teaching}
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def release_version():
    declaration = ROOT / ".zcode-plugin/plugin.json"
    if declaration.is_file():
        return json.loads(declaration.read_text("utf-8"))["version"]
    try:
        return version("vsc-workflow")
    except PackageNotFoundError:
        return None


def errors(data):
    if not isinstance(data, dict):
        return ["方法库必须是对象"]
    problems = []
    if data.get("format") != FORMAT:
        problems.append(f"format 必须是 {FORMAT}")
    sources = data.get("sources")
    cards = data.get("cards")
    if not isinstance(sources, list) or not sources:
        return problems + ["sources 必须是非空数组"]
    known = set()
    for item in sources:
        if not isinstance(item, dict):
            problems.append("source 必须是对象")
            continue
        sid = item.get("id")
        if not isinstance(sid, str) or not sid or sid in known:
            problems.append("source.id 必须是唯一非空字符串")
        else:
            known.add(sid)
        for key in ("title", "publisher", "checked_at"):
            if not isinstance(item.get(key), str) or not item[key].strip():
                problems.append(f"source {sid} 缺 {key}")
        url = urlparse(item.get("url") if isinstance(item.get("url"), str) else "")
        if url.scheme != "https" or not url.netloc:
            problems.append(f"source {sid} 必须有 HTTPS 来源链接")
    if not isinstance(cards, list) or not cards:
        return problems + ["cards 必须是非空数组"]
    seen = set()
    for card in cards:
        if not isinstance(card, dict):
            problems.append("card 必须是对象")
            continue
        cid = card.get("id")
        if not isinstance(cid, str) or not cid or cid in seen:
            problems.append("card.id 必须唯一且非空")
        else:
            seen.add(cid)
        for key in ("name", "category", "principle", "source_basis"):
            if not isinstance(card.get(key), str) or not card[key].strip():
                problems.append(f"{cid} 缺 {key}")
        for key in ("tags", "stages", "steps", "pitfalls", "sources"):
            value = card.get(key)
            if not isinstance(value, list) or not value or not all(isinstance(x, str) and x.strip() for x in value):
                problems.append(f"{cid}.{key} 必须是非空字符串数组")
        refs = card.get("sources", [])
        if isinstance(refs, list) and any(not isinstance(ref, str) or ref not in known for ref in refs):
            problems.append(f"{cid} 引用了未知来源")
        if "teaching_ref" in card:
            try:
                read_teaching(card["teaching_ref"])
            except (ValueError, OSError) as exc:
                problems.append(f"{cid}: {exc}")
    return problems


def load(path=CATALOG):
    data = json.loads(Path(path).read_text("utf-8"))
    problems = errors(data)
    if problems:
        raise ValueError("；".join(problems))
    return data


def fields(card):
    return [(4, card["id"]), (4, card["name"]), (3, " ".join(card["tags"])), (2, card["category"]),
            (2, card["principle"]), (1, vsc_search.flatten(card))]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default=str(CATALOG))
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("search")
    command.add_argument("query", nargs="*")
    command.add_argument("--category")
    command.add_argument("--stage")
    command.add_argument("--limit", type=int, default=20)
    command = sub.add_parser("show")
    command.add_argument("id")
    command.add_argument("--with-teaching", action="store_true", help="读取完整教学章节及固定内容摘要")
    command.add_argument("--expected-sha", help="校验固定教学内容 SHA-256；隐含 --with-teaching")
    sub.add_parser("validate").add_argument("file", nargs="?")
    args = parser.parse_args(argv)
    try:
        data = load(args.file or args.catalog) if args.command == "validate" else load(args.catalog)
        if args.command == "validate":
            print(f"VALID: {len(data['cards'])} 条方法，{len(data['sources'])} 个来源")
        elif args.command == "show":
            card = next((card for card in data["cards"] if card["id"] == args.id), None)
            if card is None:
                raise ValueError(f"没有方法 {args.id}")
            sources = [x for x in data["sources"] if x["id"] in card["sources"]]
            result = {**card, "source_details": sources}
            if args.with_teaching or args.expected_sha is not None:
                teaching = read_teaching(card["teaching_ref"]) if "teaching_ref" in card else None
                sha = teaching_digest(card, sources, teaching)
                if args.expected_sha is not None and args.expected_sha != sha:
                    raise ValueError(f"教学摘要不匹配：{args.id}；请重建固定输入/context，不能静默使用最新正文")
                chars = len(teaching["body"]) if teaching else 0
                result.update(teaching=teaching, teaching_sha256=sha, release_version=release_version(),
                              teaching_chars=chars, teaching_soft_target_chars=TEACHING_SOFT_TARGET_CHARS,
                              teaching_over_soft_target=chars > TEACHING_SOFT_TARGET_CHARS)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            cards = [card for card in data["cards"] if (not args.category or card["category"] == args.category)
                     and (not args.stage or args.stage in card["stages"])]
            found = vsc_search.rank(cards, " ".join(args.query), fields, max(1, args.limit))
            for score, card in found:
                print(f"{score:5.1f} {card['id']} [{card['category']}] {card['name']} — {card['principle']}")
            if not found:
                print("没有匹配的方法")
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
