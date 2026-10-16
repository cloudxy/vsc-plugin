"""Read-only SQL projection of registered relationships, bounded per request.

One REPEATABLE READ transaction pins the revision and every relation query.
No graph table, raw request, source URI, document body or credential is exposed.
Every branch filters project_id; joins include project_id even when IDs happen
to be globally unique. This adapter never opens a legacy authority.
"""
from sqlalchemy import bindparam, text
from vsc.assets.resource_service import Conflict, NotFound
from .values import checked_id, clean


def _json(fields, alias="r"):
    return "jsonb_build_object(" + ",".join("'%s',%s.%s" % (field, alias, field) for field in fields) + ")"


def _node(table, kind, title, fields=()):
    return ("SELECT '%s:' || r.id::text id, '%s' kind, r.id::text entity_id, %s label, %s summary "
            "FROM %s r WHERE r.project_id=:project") % (kind, kind, title, _json(fields), table)


NODES = " UNION ALL ".join([
    _node("creative_objects", "object", "r.display_code || ' · ' || r.title", ("kind",)),
    _node("media_items", "media", "r.name", ("modality",)),
    _node("artifact_versions", "artifact", "r.artifact_key || ' v' || r.version", ("artifact_type", "version", "sha256", "stage")),
    _node("source_versions", "source", "r.source_key || ' v' || r.version", ("kind", "version", "sha256")),
    _node("media_operations", "operation", "r.operation_type", ("status", "tool", "tool_version")),
    _node("generation_jobs", "job", "r.purpose || ' #' || r.candidate_no", ("status", "modality", "model_version")),
    _node("binding_slots", "slot", "r.role || ' · ' || r.slot_key", ("role",)),
    _node("timeline_versions", "timeline", "'时间线 ' || left(r.id::text,8)", ("fps_num", "fps_den")),
    _node("timeline_items", "item", "r.track_key || ' #' || r.ordinal", ("offset_frame", "duration_frames")),
    _node("render_versions", "render", "'渲染 · ' || r.tool", ("tool_version",)),
])


def _edge(table, kind, source, target, label, fields=(), identity="r.id::text", joins="", extra=""):
    return ("SELECT '%s:' || %s id, %s source, %s target, '%s' kind, '%s' label, %s evidence "
            "FROM %s r %s WHERE r.project_id=:project %s") % (
                kind, identity, source, target, kind, label, _json(fields), table, joins, extra)


def _ref(kind, column):
    return "'%s:' || %s::text" % (kind, column)


_EDGES = []
def _relation(table, kind, sk, sc, tk, tc, label, fields=(), **kw):
    _EDGES.append(_edge(table, kind, _ref(sk, sc), _ref(tk, tc), label, fields, **kw))


for _table in ("episodes", "scenes", "sequences", "shots"):
    _relation(_table, "structure", "object", "r.parent_id", "object", "r.id", "包含")
_relation("artifact_object_scopes", "spec_scope", "artifact", "r.artifact_id", "object", "r.object_id", "规格范围",
          identity="r.artifact_id::text || ':' || r.object_id::text")
_relation("artifact_dependencies", "version_input", "artifact", "r.dependency_id", "artifact", "r.artifact_id", "固定版本依赖",
          identity="r.dependency_id::text || ':' || r.artifact_id::text")
_relation("media_sources", "source", "source", "r.source_id", "media", "r.media_id", "登记来源", ("id", "role"))
_relation("operation_inputs", "operation_input", "media", "r.media_id", "operation", "r.operation_id", "加工输入",
          ("id", "role", "layer_order", "start_ms", "end_ms", "mask_input_id"))
_relation("operation_outputs", "operation_output", "operation", "r.operation_id", "media", "r.media_id", "加工输出", ("id", "role", "ordinal"))
_relation("job_input_media", "generation_input", "media", "r.media_id", "job", "r.job_id", "生成输入",
          ("id", "role", "ordinal", "blob_sha256", "binding_decision_id"))
_relation("job_input_versions", "spec_input", "artifact", "r.artifact_id", "job", "r.job_id", "规格输入", ("id", "role", "sha256"))
_relation("generation_jobs", "run_input", "artifact", "r.run_version_id", "job", "r.id", "固定运行版本")
_relation("generation_jobs", "job_target", "object", "coalesce(r.shot_id,r.asset_id)", "job", "r.id", "制作对象")
_relation("job_outputs", "generation_output", "job", "r.job_id", "media", "r.media_id", "生成输出", ("id", "asset_type"))
_relation("binding_slots", "slot_target", "slot", "r.id", "object", "r.target_object_id", "用途对象", ("id", "role"))
_relation("binding_candidates", "candidate", "media", "r.media_id", "slot", "r.slot_id", "候选", ("id", "spec_version_id", "context_sha256"))
_EDGES.append(_edge("current_bindings", "selected", _ref("media", "c.media_id"), _ref("slot", "r.slot_id"), "当前采用",
                   ("candidate_id", "decision_id"), identity="r.decision_id::text",
                   joins="JOIN binding_candidates c ON c.project_id=r.project_id AND c.id=r.candidate_id AND c.slot_id=r.slot_id"))
for _column, _kind, _label in (("run_version_id", "trial_adoption", "试片正式采用（历史决定）"),
                              ("animatic_version_id", "adoption_animatic", "正式采用的预演依据")):
    _EDGES.append(_edge("binding_trial_adoptions", _kind, _ref("artifact", "r." + _column), _ref("slot", "d.slot_id"), _label,
                       ("decision_id", "run_version_id", "animatic_version_id", "animatic_approval_id"),
                       identity="r.decision_id::text || ':' || r.run_version_id::text",
                       joins="JOIN binding_decisions d ON d.project_id=r.project_id AND d.id=r.decision_id"))
_relation("timeline_versions", "timeline_spec", "artifact", "r.artifact_id", "timeline", "r.id", "时间线版本")
_relation("timeline_versions", "timeline_scope", "timeline", "r.id", "object", "r.episode_id", "剪辑范围")
_relation("timeline_item_media", "timeline_media", "media", "r.media_id", "item", "r.item_id", "时间线用料",
          ("id", "role", "source_in_frame", "source_out_frame", "blob_sha256", "binding_decision_id"))
_relation("timeline_items", "timeline_item", "item", "r.id", "timeline", "r.timeline_id", "剪辑片段", ("id", "offset_frame", "duration_frames"))
_relation("timeline_items", "item_shot", "object", "r.shot_id", "item", "r.id", "镜头用料", extra="AND r.shot_id IS NOT NULL")
_relation("render_versions", "render_timeline", "timeline", "r.timeline_id", "render", "r.id", "渲染时间线")
for _col, _kind, _label in (("artifact_id", "render_spec", "渲染规格"), ("subtitle_version_id", "subtitle_input", "字幕版本"), ("style_version_id", "style_input", "样式版本")):
    _relation("render_versions", _kind, "artifact", "r." + _col, "render", "r.id", _label, extra="AND r.%s IS NOT NULL" % _col)
_relation("render_inputs", "render_input", "media", "r.media_id", "render", "r.render_id", "渲染用料", ("id", "role", "blob_sha256", "binding_decision_id"))
_relation("render_outputs", "render_output", "render", "r.render_id", "media", "r.media_id", "渲染输出", ("id", "role"))
EDGES = " UNION ALL ".join(_EDGES)


def _rows(conn, sql, params, expanding=()):
    stmt = text(sql)
    if expanding:
        stmt = stmt.bindparams(*(bindparam(name, expanding=True) for name in expanding))
    return [dict(row) for row in conn.execute(stmt, params).mappings()]


def query_graph(store, project_id, object_id=None, focus=None, direction="both", depth=2, limit=100, offset=0, revision=None):
    p = checked_id(project_id)
    with store.engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn, conn.begin():
        conn.execute(text("SET TRANSACTION READ ONLY"))
        project = store._project(conn, p)
        if revision is not None and revision != project["revision"]:
            raise Conflict("画布快照已变化，请刷新后继续展开", "graph_revision_changed")
        params = {"project": p, "limit": limit + 1, "offset": offset}
        reasons, next_offset = set(), None
        if focus:
            kind, row_id = focus.split(":", 1)
            params["focus"] = kind + ":" + checked_id(row_id)
            seeds = _rows(conn, "SELECT * FROM (" + NODES + ") n WHERE id=:focus", params)
            if not seeds:
                raise NotFound("此项目内没有该画布节点")
        elif object_id:
            params["scope"] = checked_id(object_id)
            if not _rows(conn, "SELECT id FROM creative_objects WHERE project_id=:project AND id=:scope", params):
                raise NotFound("此项目内没有该结构对象")
            hierarchy = " UNION ALL ".join("SELECT parent_id,id FROM %s WHERE project_id=:project" % t for t in ("episodes", "scenes", "sequences", "shots"))
            seeds = _rows(conn, "WITH RECURSIVE hierarchy AS (" + hierarchy + "), scope(id) AS (SELECT CAST(:scope AS uuid) UNION SELECT h.id FROM hierarchy h JOIN scope s ON h.parent_id=s.id) SELECT * FROM (" + NODES + ") n WHERE kind='object' AND entity_id IN (SELECT id::text FROM scope) ORDER BY id LIMIT :limit OFFSET :offset", params)
        else:
            seeds = _rows(conn, "SELECT * FROM (" + NODES + ") n ORDER BY kind,id LIMIT :limit OFFSET :offset", params)
        if len(seeds) > limit:
            reasons.add("page")
            next_offset = offset + limit
        selected = {row["id"]: row for row in seeds[:limit]}
        frontier = set(selected)
        edge_limit = max(100, limit * 16)
        for _ in range(depth):
            if not frontier:
                break
            clause = {"upstream": "target IN :frontier", "downstream": "source IN :frontier", "both": "source IN :frontier OR target IN :frontier"}[direction]
            relations = _rows(conn, "SELECT * FROM (" + EDGES + ") e WHERE " + clause + " ORDER BY id LIMIT :edge_limit",
                              dict(params, frontier=sorted(frontier), edge_limit=edge_limit + 1), ("frontier",))
            if len(relations) > edge_limit:
                reasons.add("edge_limit")
            unseen = set()
            for edge in relations[:edge_limit]:
                if direction != "upstream":
                    unseen.add(edge["target"])
                if direction != "downstream":
                    unseen.add(edge["source"])
            unseen -= selected.keys()
            room = limit - len(selected)
            if len(unseen) > room:
                reasons.add("node_limit")
            frontier = set(sorted(unseen)[:room])
            if frontier:
                rows = _rows(conn, "SELECT * FROM (" + NODES + ") n WHERE id IN :ids", dict(params, ids=sorted(frontier)), ("ids",))
                selected.update((row["id"], row) for row in rows)
        edges = []
        if selected:
            ids = sorted(selected)
            edges = _rows(conn, "SELECT * FROM (" + EDGES + ") e WHERE source IN :ids AND target IN :ids ORDER BY id LIMIT :edge_limit",
                          dict(params, ids=ids, edge_limit=edge_limit + 1), ("ids",))
            if len(edges) > edge_limit:
                reasons.add("edge_limit")
                edges = edges[:edge_limit]
            boundary = {"upstream": "target IN :ids AND source NOT IN :ids", "downstream": "source IN :ids AND target NOT IN :ids", "both": "(source IN :ids AND target NOT IN :ids) OR (target IN :ids AND source NOT IN :ids)"}[direction]
            if _rows(conn, "SELECT id FROM (" + EDGES + ") e WHERE " + boundary + " LIMIT 1", dict(params, ids=ids), ("ids",)):
                reasons.add("depth_or_scope")
            media_ids = [n["entity_id"] for n in selected.values() if n["kind"] == "media"]
            if media_ids:
                summaries = _rows(conn, "SELECT m.id::text id,b.duration_ms,EXISTS(SELECT 1 FROM blob_locations l WHERE l.blob_id=m.blob_id AND l.available) located FROM media_items m JOIN media_blobs b ON b.id=m.blob_id WHERE m.project_id=:project AND m.id::text IN :media_ids", dict(params, media_ids=media_ids), ("media_ids",))
                for row in summaries:
                    selected["media:" + row["id"]]["summary"].update(duration_ms=row["duration_ms"], availability="registered_location_unverified" if row["located"] else "missing_location")
        groups = _rows(conn, "SELECT kind,count(*) total FROM (" + NODES + ") n GROUP BY kind ORDER BY kind", params)
        return clean({"project_id": p, "revision": project["revision"], "snapshot": "repeatable_read",
                      "read_only": True, "nodes": list(selected.values()), "edges": edges,
                      "groups": groups, "scope": object_id, "focus": focus, "direction": direction, "depth": depth,
                      "truncated": bool(reasons), "truncation_reasons": sorted(reasons), "next_offset": next_offset,
                      "limits": {"nodes": limit, "edges": edge_limit},
                      "warnings": ["画布只展示已登记关系；空白不代表没有尚未登记的依赖。媒体位置未在画布内校验，点击详情检查实际字节。"]})
