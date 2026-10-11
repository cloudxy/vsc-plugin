#!/usr/bin/env python3
"""VSC 共用的轻量检索：素材库、知识库与作品查找都用同一套打分，结果才可比较、可解释。

不调用模型或向量库。查询按空白与标点切词；一个词整体出现在字段里得满分，否则按中文双字组合的命中比例得部分分，
因此“古寺钟声”也能命中“古寺庭院……远处钟声”。每个字段带权重，名称与标签高于正文。
"""
import re
import argparse
import json
import sys
from pathlib import Path

SPLIT = re.compile(r"[\s,，、;；:：/|]+")


def terms(query):
    return [term for term in SPLIT.split((query or "").lower()) if term]


def bigrams(term):
    return {term[index:index + 2] for index in range(len(term) - 1)}


def hit(term, text):
    """词在文本中的命中度：整词 1，否则双字组合命中比例的一半（至少两成双字组合命中才算）。"""
    if term in text:
        return 1.0
    grams = bigrams(term)
    if len(term) < 3 or not grams:
        return 0.0
    ratio = sum(1 for gram in grams if gram in text) / len(grams)
    return ratio / 2 if ratio >= 0.2 else 0.0


def score(query_terms, fields):
    """fields 为 [(权重, 文本)]；每个词取命中最好的字段。任何一个词完全没命中时返回 0（各词须同时满足）。"""
    texts = [(weight, str(value).lower()) for weight, value in fields if value]
    total = 0.0
    for term in query_terms:
        best = max((weight * hit(term, text) for weight, text in texts), default=0.0)
        if best == 0:
            return 0.0
        total += best
    return total


def flatten(value):
    """把嵌套的 JSON 值摊平成一段可检索文本。"""
    if isinstance(value, dict):
        return " ".join(f"{key} {flatten(item)}" for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return " ".join(flatten(item) for item in value)
    return "" if value is None else str(value)


def rank(items, query, fields_of, limit=20):
    """返回 [(分数, 条目)]，按分数降序；没有查询词时按原顺序全部返回。"""
    query_terms = terms(query)
    if not query_terms:
        return [(0.0, item) for item in items][:limit]
    scored = [(score(query_terms, fields_of(item)), item) for item in items]
    return sorted((pair for pair in scored if pair[0] > 0), key=lambda pair: -pair[0])[:limit]


def project_entries(project):
    """只读扫描项目索引与文本；结果是查找线索，不证明历史批准仍有效。"""
    project = Path(project)
    state = json.loads((project / "vsc.json").read_text("utf-8"))
    if not isinstance(state, dict) or not state.get("project_id"):
        raise ValueError(f"无效作品索引：{project}")
    prefix = str(project.resolve())
    result = [{"domain": "projects", "id": state["project_id"], "name": state.get("title") or project.name,
               "path": str(project.resolve() / "vsc.json"), "summary": f"Profile: {state.get('profile_id')}；作品状态和批准记录以 vsc_state 为准",
               "detail": flatten({key: state.get(key) for key in ("brief", "goals", "profile_id")})}]
    for kind, key in (("object", "objects"), ("artifact", "artifacts")):
        for item in state.get(key, []):
            if not isinstance(item, dict):
                continue
            result.append({"domain": "projects", "id": item.get("id", ""), "name": item.get("type") or item.get("kind") or kind,
                           "path": prefix + "/vsc.json", "summary": flatten({k: item.get(k) for k in ("scope", "stage", "status", "path", "depends_on", "superseded_by")}),
                           "detail": flatten(item)})
    # 不扫描原始来源、批准快照、角色上下文和构建缓存；登记信息仍可按产物 ID 查到。
    ignored = {"01-来源", "09-台账", "10-记忆", "build", "node_modules", "废弃", "__pycache__"}
    for path in sorted(project.rglob("*")):
        relative = path.relative_to(project)
        if any(part.startswith(".") or part in ignored for part in relative.parts):
            continue
        if path.name == "vsc.json" or path.suffix.lower() not in (".md", ".txt", ".json", ".srt") or not path.is_file():
            continue
        if not path.resolve().is_relative_to(project.resolve()) or path.stat().st_size > 2_000_000:
            continue
        body = path.read_text("utf-8", errors="replace")[:200_000]
        result.append({"domain": "projects", "id": str(relative), "name": path.stem, "path": str(path.resolve()),
                       "summary": f"{project.name}/{relative}", "detail": body})
    return result


def entries(domain="all", project=None, library=None, catalog=None):
    """统一检索入口；素材、公开方法与项目各自保存权威内容，不创建第二份索引。"""
    result = []
    if domain in ("all", "craft"):
        import vsc_craft
        for card in vsc_craft.load(catalog or vsc_craft.CATALOG)["cards"]:
            result.append({"domain": "craft", "id": card["id"], "name": card["name"], "path": str(catalog or vsc_craft.CATALOG),
                           "summary": card["principle"], "detail": flatten(card), "tags": card["tags"]})
    if domain in ("all", "library"):
        import vsc_library
        kinds, rights = vsc_library.taxonomy()
        for folder, item in vsc_library.load_items(vsc_library.library_root(library)):
            problems = vsc_library.item_errors(item, kinds, rights)
            if problems:
                raise ValueError(f"无效素材 {folder}：{'；'.join(problems)}")
            result.append({"domain": "library", "id": item["id"], "name": item["name"], "path": str(folder / "item.json"),
                           "summary": item["summary"], "detail": flatten(item), "tags": item.get("tags", [])})
    if domain in ("all", "projects"):
        roots = [Path(project)] if project else sorted((Path(__file__).resolve().parent.parent / "projects").glob("*/vsc.json"))
        for root in roots:
            result += project_entries(root if project else root.parent)
    return result


def entry_fields(item):
    return [(4, item["id"]), (4, item["name"]), (3, flatten(item.get("tags"))), (2, item["summary"]), (1, item.get("detail"))]


def main(argv=None):
    parser = argparse.ArgumentParser(description="在素材库、公开创作方法与作品内容中快速查找；只读，不持久化索引。")
    parser.add_argument("query", nargs="*")
    parser.add_argument("--in", dest="domain", choices=("all", "library", "craft", "projects"), default="all")
    parser.add_argument("--project")
    parser.add_argument("--library")
    parser.add_argument("--catalog")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.limit < 1:
            raise ValueError("--limit 必须大于 0")
        query = " ".join(args.query)
        found = rank(entries(args.domain, args.project, args.library, args.catalog), query, entry_fields, args.limit)
        output = []
        for value, item in found:
            detail = item.get("detail", "")
            start = next((detail.lower().find(term) for term in terms(query) if term in detail.lower()), 0)
            snippet = detail[max(0, start - 35):max(0, start - 35) + 180].replace("\n", " ")
            output.append({**{k: v for k, v in item.items() if k not in ("detail", "tags")}, "score": value, "snippet": snippet})
        if args.json:
            print(json.dumps(output, ensure_ascii=False, indent=2))
        else:
            for item in output:
                print(f"{item['score']:5.1f} [{item['domain']}] {item['id']} {item['name']} — {item['summary']}\n      {item['path']}\n      {item['snippet']}")
            if not output:
                print("没有匹配的内容")
    except (ValueError, OSError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
