"""Explicit decisions for continuity at adjacent episode boundaries."""
import uuid
from pathlib import Path
from vsc.adapters.persistence.sqlite import series as db
from vsc.project.state import project_lock
from vsc.production.context import (SeriesError, series_state, _scope, _boundary_shots,
    _boundary_signature, build_shot_context, stamp)

def link_boundary(project, from_shot, to_shot, strategy, by, reason, replace=False):
    if strategy not in ("continuous", "intentional_jump") or not by.strip() or not reason.strip():
        raise SeriesError("跨集衔接必须选策略并记录负责人及理由")
    state = series_state(project)
    episode, _ = _scope(state, to_shot)
    if _boundary_shots(state, episode, to_shot) != (from_shot, to_shot):
        raise SeriesError("只允许连接相邻两集的末镜与首镜")
    from_context = build_shot_context(project, from_shot)
    to_context = build_shot_context(project, to_shot)
    from_sig = _boundary_signature(from_context["visual_anchor"]["pack"], "exit")
    to_sig = _boundary_signature(to_context["visual_anchor"]["pack"], "entry")
    if strategy == "continuous" and from_sig != to_sig:
        raise SeriesError("连续衔接的地点、人物或环境状态不一致；修正状态或说明为有意跳切")
    from_state = next(item["sha256"] for item in from_context["input_versions"] if item["type"] == "vsc.scene_state")
    to_state = next(item["sha256"] for item in to_context["input_versions"] if item["type"] == "vsc.scene_state")
    with project_lock(Path(project)), db.connect(project) as connection:
        old = connection.execute("SELECT id FROM continuity_edges WHERE to_shot=? AND status='active'", (to_shot,)).fetchone()
        if old and not replace:
            raise SeriesError("跨集边界已有决定；重审后须显式 --replace")
        if replace and not old:
            raise SeriesError("没有可替换的旧边界决定")
        if old:
            connection.execute("UPDATE continuity_edges SET status='superseded' WHERE id=?", (old["id"],))
        connection.execute("INSERT INTO continuity_edges VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            ("CE-" + uuid.uuid4().hex, from_shot, to_shot, from_state, to_state,
             from_sig, to_sig, strategy, "active", by, reason, stamp()))


