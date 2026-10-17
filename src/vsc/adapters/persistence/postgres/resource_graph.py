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
    _node("script_lines", "line", "r.line_key || ' · ' || left(r.text,100)", ("line_kind", "scene_id", "script_version_id")),
    _node("state_versions", "state", "'场镜状态 ' || left(r.id::text,8)", ("scene_id", "shot_id", "artifact_id")),
    _node("voice_spec_versions", "voice", "'声线规格 ' || left(r.id::text,8)", ("voice_id", "artifact_id")),
    _node("asset_use_instances", "instance", "r.label", ("asset_id", "spec_version_id", "scene_id", "shot_id", "artifact_id")),
    _node("sound_cues", "cue", "r.label", ("cue_kind", "scope_object_id", "artifact_id")),
    _node("execution_instances", "performance", "r.label", ("domain", "method_artifact_id", "artifact_id")),
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
# Semantic/usage edges are evidence projections, never approval mutations.
for table,owner,kind in (("script_lines","script_version_id","line"),("state_versions","artifact_id","state"),
        ("voice_spec_versions","artifact_id","voice"),("asset_use_instances","artifact_id","instance"),
        ("sound_cues","artifact_id","cue"),("execution_instances","artifact_id","performance")):
    _relation(table,"creative_version_"+kind,"artifact","r."+owner,kind,"r.id","固定关系版本")
for table,kind,sk,sc,tk,tc,label in (
    ("script_lines","line_scene","line","id","object","scene_id","剧本场次"),
    ("script_lines","line_speaker","object","speaker_id","line","id","台词人物"),
    ("shot_line_coverage","line_coverage","line","line_id","object","shot_id","固定剧本覆盖"),
    ("state_versions","state_shot","state","id","object","shot_id","逐镜状态"),
    ("state_versions","state_scene","state","id","object","scene_id","场次状态"),
    ("state_entity_refs","state_asset","object","asset_id","state","state_id","状态参与者"),
    ("character_voice_bindings","character_voice","object","character_id","voice","voice_spec_id","人物声线"),
    ("asset_use_instances","instance_identity","object","asset_id","instance","id","身份的使用实例"),
    ("asset_use_instances","instance_shot","instance","id","object","shot_id","实例用于镜头"),
    ("asset_use_instances","instance_scene","instance","id","object","scene_id","实例所在场"),
    ("asset_use_instances","instance_state","state","state_id","instance","id","实例固定状态"),
    ("instance_interactions","interaction","instance","subject_id","instance","object_id","实例交互"),
    ("sound_cues","cue_line","line","line_id","cue","id","台词声音Cue"),
    ("sound_cues","cue_voice","voice","voice_spec_id","cue","id","Cue固定声线"),
    ("sound_cues","cue_subtitle","cue","id","artifact","subtitle_version_id","固定字幕同步规格"),
    ("sound_cues","cue_lipsync","cue","id","artifact","lipsync_version_id","固定口型同步规格"),
    ("sound_cues","cue_execution","performance","execution_id","cue","id","声音表演"),
    ("cue_shots","cue_shot","cue","cue_id","object","shot_id","声音覆盖镜头"),
    ("cue_slots","cue_slot","cue","cue_id","slot","slot_id","Cue用途候选与采用"),
    ("cue_timeline_items","cue_item","cue","cue_id","item","item_id","Cue时间线用料"),
    ("execution_instances","execution_method","artifact","method_artifact_id","performance","id","固定方法规格"),
    ("execution_instances","execution_line","line","line_id","performance","id","表演固定台词"),
    ("execution_instances","execution_voice","voice","voice_spec_id","performance","id","表演固定声线"),
    ("execution_shots","execution_shot","performance","execution_id","object","shot_id","执行镜头范围"),
    ("execution_participants","execution_participant","instance","instance_id","performance","execution_id","执行参与者"),
    ("execution_materials","execution_material","media","media_id","performance","execution_id","执行参考素材"),
    ("execution_slots","execution_slot","performance","execution_id","slot","slot_id","执行用途候选与采用")):
    evidence={"shot_line_coverage":("id","coverage_version_id","start_char","end_char"),
        "instance_interactions":("id","artifact_id","relation","hand"),"cue_shots":("id","start_ms","end_ms"),
        "state_entity_refs":("id","spec_version_id","relation"),"execution_participants":("id","role"),
        "execution_materials":("id","role"),"execution_slots":("id","role")}.get(table,("id",))
    _relation(table,kind,sk,"r."+sc,tk,"r."+tc,label,evidence,extra="AND r.%s IS NOT NULL AND r.%s IS NOT NULL"%(sc,tc))
CREATIVE_EDGE_KINDS = {"structure", "spec_scope", "version_input"} | {sql.split("'")[1].split(':')[0] for sql in _EDGES if any(x in sql for x in ("script_lines r", "shot_line_coverage r", "state_versions r", "state_entity_refs r", "voice_spec_versions r", "character_voice_bindings r", "asset_use_instances r", "instance_interactions r", "sound_cues r", "cue_shots r", "cue_slots r", "cue_timeline_items r", "execution_"))}
EDGES = " UNION ALL ".join(_EDGES)


def _rows(conn, sql, params, expanding=()):
    stmt = text(sql)
    if expanding:
        stmt = stmt.bindparams(*(bindparam(name, expanding=True) for name in expanding))
    return [dict(row) for row in conn.execute(stmt, params).mappings()]


def query_graph(store, project_id, object_id=None, focus=None, direction="both", depth=2, limit=100, offset=0, revision=None, mode="production"):
    p = checked_id(project_id)
    with store.engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn, conn.begin():
        conn.execute(text("SET TRANSACTION READ ONLY"))
        project = store._project(conn, p)
        if revision is not None and revision != project["revision"]:
            raise Conflict("画布快照已变化，请刷新后继续展开", "graph_revision_changed")
        visible_edges = EDGES
        if mode == "creative":
            visible_edges = " UNION ALL ".join(sql for sql in _EDGES if sql.split("'")[1].split(':')[0] in CREATIVE_EDGE_KINDS)
        elif mode == "impact":
            causal = {"version_input","spec_input","run_input","generation_input","generation_output","operation_input","operation_output",
                "selected","slot_target","timeline_media","timeline_item","render_timeline","render_spec","subtitle_input","style_input","render_input","render_output"}
            visible_edges = " UNION ALL ".join(sql for sql in _EDGES if sql.split("'")[1].split(':')[0] in causal)
            direction = "downstream"
        elif mode == "usage":
            visible_edges = " UNION ALL ".join(sql for sql in _EDGES if sql.split("'")[1].split(':')[0] not in {"generation_input","spec_input","run_input","operation_input","operation_output","version_input"})
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
            relations = _rows(conn, "SELECT * FROM (" + visible_edges + ") e WHERE " + clause + " ORDER BY id LIMIT :edge_limit",
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
            edges = _rows(conn, "SELECT * FROM (" + visible_edges + ") e WHERE source IN :ids AND target IN :ids ORDER BY id LIMIT :edge_limit",
                          dict(params, ids=ids, edge_limit=edge_limit + 1), ("ids",))
            if len(edges) > edge_limit:
                reasons.add("edge_limit")
                edges = edges[:edge_limit]
            boundary = {"upstream": "target IN :ids AND source NOT IN :ids", "downstream": "source IN :ids AND target NOT IN :ids", "both": "(source IN :ids AND target NOT IN :ids) OR (target IN :ids AND source NOT IN :ids)"}[direction]
            if _rows(conn, "SELECT id FROM (" + visible_edges + ") e WHERE " + boundary + " LIMIT 1", dict(params, ids=ids), ("ids",)):
                reasons.add("depth_or_scope")
            media_ids = [n["entity_id"] for n in selected.values() if n["kind"] == "media"]
            if media_ids:
                summaries = _rows(conn, "SELECT m.id::text id,b.duration_ms,EXISTS(SELECT 1 FROM blob_locations l WHERE l.blob_id=m.blob_id AND l.available) located FROM media_items m JOIN media_blobs b ON b.id=m.blob_id WHERE m.project_id=:project AND m.id::text IN :media_ids", dict(params, media_ids=media_ids), ("media_ids",))
                for row in summaries:
                    selected["media:" + row["id"]]["summary"].update(duration_ms=row["duration_ms"], availability="registered_location_unverified" if row["located"] else "missing_location")
        if object_id:
            from .workbench import CTE,QUERIES
            mapping={"object":"SELECT id FROM scope_ids", "artifact":"SELECT id FROM scoped_versions", "slot":"SELECT id FROM scoped_slots",
                "instance":"SELECT id FROM scoped_instances", "cue":"SELECT id FROM scoped_cues", "performance":"SELECT id FROM scoped_executions",
                "line":QUERIES["lines"], "state":QUERIES["states"], "voice":"SELECT DISTINCT voice_spec_id FROM ("+QUERIES["voices"]+") voices", "media":QUERIES["materials"]}
            parts=[]
            for kind,sql in mapping.items():
                parts.append("SELECT '%s' kind,count(*) total FROM (%s) counted"%(kind,sql))
            groups=_rows(conn,CTE+" UNION ALL ".join(parts),dict(params,p=p,scope=checked_id(object_id)))
        else:
            groups = _rows(conn, "SELECT kind,count(*) total FROM (" + NODES + ") n GROUP BY kind ORDER BY kind", params)
        for group in groups:
            group["scope_total"]=group["total"]
            group["loaded_count"]=sum(n["kind"]==group["kind"] for n in selected.values())
        media_ids=[n["entity_id"] for n in selected.values() if n["kind"]=="media"]
        if media_ids:
            for rendition in store._renditions(conn,p,media_ids):
                selected["media:"+rendition["media_id"]]["summary"].setdefault("renditions",[]).append({"purpose":rendition["purpose"]})
        impact = None
        if mode == "impact":
            distances = {focus:0} if focus else {}
            reasons_by_node = {}
            for _ in range(depth+1):
                for edge in edges:
                    if edge["source"] in distances and edge["target"] not in distances:
                        distances[edge["target"]] = distances[edge["source"]]+1
                        reasons_by_node[edge["target"]] = edge["label"]
            for node in selected.values():
                distance=distances.get(node["id"])
                node["impact"]={"classification":"affected_pending_review" if distance else "unknown",
                    "distance":distance,"direct":distance==1,"reason":reasons_by_node.get(node["id"],"选择变更源后按固定输入和实际用料查询；未比较替代内容")}
            impact={"source":focus,"unaffected_proven":False,"complete":not reasons,
                "unknown_reason":"未登记依赖和截断部分无法判断；待复核不等于必须重做，替换内容需比较实际要求与固定输入。"}
        return clean({"project_id": p, "impact": impact, "revision": project["revision"], "snapshot": "repeatable_read",
                      "read_only": True, "nodes": list(selected.values()), "edges": edges,
                      "groups": groups, "mode": mode, "groups_scope": "object_scope" if object_id else "project", "scope": object_id, "focus": focus, "direction": direction, "depth": depth,
                      "truncated": bool(reasons), "truncation_reasons": sorted(reasons), "next_offset": next_offset,
                      "limits": {"nodes": limit, "edges": edge_limit},
                      "warnings": ["画布只展示已登记关系；空白不代表没有尚未登记的依赖。媒体位置未在画布内校验，点击详情检查实际字节。"]})
