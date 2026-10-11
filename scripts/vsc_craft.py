#!/usr/bin/env python3
"""公开创作方法库：search [词...]、show ID、validate [FILE]。条目是有来源的方法建议，不继承项目批准。"""
import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

import vsc_search

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "knowledge/craft.json"
FORMAT = "vsc.craft-catalog/v1"


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
    sub.add_parser("show").add_argument("id")
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
            print(json.dumps({**card, "source_details": [x for x in data["sources"] if x["id"] in card["sources"]]}, ensure_ascii=False, indent=2))
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
