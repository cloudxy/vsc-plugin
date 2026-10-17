"""Bounded, read-only graph queries over the catalog's declared authority.

Graph IDs name project-local entities, never blob identities. Layouts and graph
responses are disposable views and cannot write resource or approval facts.
"""
from .resource_service import Conflict, NotFound, ResourceError


KINDS = frozenset({"object", "media", "artifact", "source", "operation", "job", "slot", "timeline", "item", "render", "line", "state", "voice", "instance", "cue", "performance"})


def validate_query(object_id=None, focus=None, direction="both", depth=2, limit=100, offset=0, revision=None, mode="production"):
    if mode not in {"production", "creative", "usage", "impact"}:
        raise ResourceError("关系视图不合法", "invalid_graph_query")
    if direction not in {"both", "upstream", "downstream"}:
        raise ResourceError("关系方向应为 both、upstream 或 downstream", "invalid_graph_query")
    for name, value, low, high in (("depth", depth, 0, 8), ("limit", limit, 1, 300), ("offset", offset, 0, 1000000)):
        if type(value) is not int or not low <= value <= high:
            raise ResourceError("画布查询范围不合法: " + name, "invalid_graph_query")
    if focus and (not isinstance(focus, str) or ":" not in focus or focus.split(":", 1)[0] not in KINDS or not focus.split(":", 1)[1]):
        raise ResourceError("画布节点身份不合法", "invalid_graph_query")
    if focus and offset:
        raise ResourceError("聚焦展开请增加节点限额或展开边界节点，不使用概览分页", "invalid_graph_query")
    if revision is not None and (type(revision) is not int or revision < 0):
        raise ResourceError("快照 revision 不合法", "invalid_graph_query")
    return dict(object_id=object_id, focus=focus, direction=direction, depth=depth, limit=limit, offset=offset, revision=revision, mode=mode)


class ResourceGraph:
    def __init__(self, catalog):
        self.catalog = catalog

    def query(self, project_id, **kwargs):
        options = validate_query(**kwargs)
        reader = self.catalog._reader(project_id)
        if reader is not None:
            return legacy_graph(reader, project_id, **options)
        # Import the optional PostgreSQL adapter only for PostgreSQL authority.
        from vsc.adapters.persistence.postgres.resource_graph import query_graph
        return query_graph(self.catalog.service.store, project_id, **options)


def legacy_graph(reader, project_id, object_id, focus, direction, depth, limit, offset, revision, mode="production"):
    """Legacy media stays read-only; expose only its explicit binding evidence.

    Legacy readers have no snapshot transaction across filesystem inventory and
    JSON. A changed revision is rejected; incompleteness is always visible.
    """
    project = reader.project()
    before = project["revision"]
    if revision is not None and revision != before:
        raise Conflict("画布快照已变化，请刷新", "graph_revision_changed")
    nodes, edges = {}, []
    def node(kind, row, title=None):
        key = kind + ":" + row["id"]
        nodes[key] = {"id": key, "kind": kind, "entity_id": row["id"], "label": title or row.get("name") or row.get("title") or row["id"],
                      "summary": {k: row[k] for k in ("modality", "availability", "registered", "kind", "version", "status") if k in row}}
        return key
    all_objects = {row["id"]: row for row in reader.tree()["nodes"]}
    if focus:
        kind, entity_id = focus.split(":", 1)
        if kind == "media":
            rows = [reader.media(entity_id)]
        elif kind == "object":
            object_id = entity_id
            if entity_id not in all_objects:
                raise NotFound()
            rows = reader.resources(object_id=object_id, limit=limit, offset=0)["items"] if depth else []
            node("object", all_objects[entity_id])
        elif kind == "artifact":
            rows = []
            node("artifact", reader.artifact(entity_id))
        else:
            raise NotFound("旧权威尚未提供此类画布节点")
        total = len(rows)
    else:
        page = reader.resources(object_id=object_id, limit=limit, offset=offset)
        rows, total = page["items"], page["total"]
    clipped = False
    for row in rows:
        if len(nodes) >= limit:
            clipped = True
            break
        media_key = node("media", row)
        # A legacy binding approval is deliberately not called current adoption:
        # legacy has no PostgreSQL current_bindings projection.
        if depth and direction != "upstream":
            for binding in row.get("bindings", []):
                target = binding.get("target_id")
                if target not in all_objects:
                    continue
                key = "object:" + target
                if key not in nodes and len(nodes) >= limit:
                    clipped = True
                    continue
                node("object", all_objects[target])
                edges.append({"id": "legacy_binding:" + binding["id"], "source": media_key, "target": key,
                              "kind": "legacy_binding", "label": "旧用途记录 · " + binding.get("role", ""),
                              "evidence": {k: binding[k] for k in ("id", "role", "status") if k in binding}})
    if reader.project()["revision"] != before:
        raise Conflict("读取期间旧项目已变化，请刷新", "graph_revision_changed")
    more = not focus and offset + len(rows) < total
    return {"project_id": project_id, "revision": before, "nodes": list(nodes.values()), "edges": edges,
            "read_only": True, "truncated": bool(clipped or more), "next_offset": offset + len(rows) if more else None,
            "snapshot": "legacy_revision_checked", "warnings": ["旧项目只读画布：仅展示已登记用途；加工、生成与剪辑关系尚未完整索引。空白不代表没有依赖。"],
            "scope": object_id, "focus": focus, "direction": direction, "depth": depth,
            "groups": [], "limits": {"nodes": limit}, "truncation_reasons": ["node_limit"] if clipped else (["page"] if more else [])}
