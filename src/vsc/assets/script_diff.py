#!/usr/bin/env python3
"""剧本工作副本与固定版本的结构差异。纯函数，不访问数据库或网络。

差异按稳定身份计算：场次以 scene.id、行以 actions/dialogue/silence 内的 line id 对齐；
正文删除后旧行不再出现在新稿，批注锚点仍按原 id 保留，不漂移到其他行。
"""


def _scenes(document):
    if not isinstance(document, dict) or not isinstance(document.get("scenes"), list):
        return []
    return [scene for scene in document["scenes"] if isinstance(scene, dict)]


def _lines(scene, key):
    rows = scene.get(key)
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _line_text(row):
    return row.get("text", "")


def compare_documents(before, after):
    """Return scene/line level changes between two screenplay documents."""
    before = before if isinstance(before, dict) else {}
    after = after if isinstance(after, dict) else {}
    old_scenes, new_scenes = _scenes(before), _scenes(after)
    old_by_id = {scene.get("id"): scene for scene in old_scenes}
    new_by_id = {scene.get("id"): scene for scene in new_scenes}
    old_order = [scene.get("id") for scene in old_scenes]
    new_order = [scene.get("id") for scene in new_scenes]
    scenes = {"added": [i for i in new_order if i not in old_by_id],
              "removed": [i for i in old_order if i not in new_by_id],
              "moved": [i for i in new_order if i in old_by_id
                        and [j for j in old_order if j in new_by_id].index(i)
                        != [j for j in new_order if j in old_by_id].index(i)]}
    lines = []
    # Root provenance and scope are part of the reviewed document, even when
    # every visible line stays unchanged.
    root_changes = []
    for field in sorted((set(before or {}) | set(after or {})) - {"scenes"}):
        was, now = (before or {}).get(field), (after or {}).get(field)
        if was != now:
            root_changes.append({"scene_id": None, "line_id": None, "kind": "document",
                                 "change": "changed", "field": field, "before": was, "after": now})
    lines.extend(root_changes)
    for scene_id in new_order:
        if scene_id not in old_by_id:
            for key in ("actions", "dialogue", "silence"):
                for row in _lines(new_by_id[scene_id], key):
                    lines.append({"scene_id": scene_id, "line_id": row.get("id"), "kind": key,
                                  "change": "added", "before": None, "after": _line_text(row)})
            continue
        old_scene, new_scene = old_by_id[scene_id], new_by_id[scene_id]
        for field in sorted((set(old_scene) | set(new_scene)) - {"id", "actions", "dialogue", "silence"}):
            if old_scene.get(field) != new_scene.get(field):
                lines.append({"scene_id": scene_id, "line_id": None, "kind": "scene",
                              "change": "changed", "field": field,
                              "before": old_scene.get(field), "after": new_scene.get(field)})
        for key in ("actions", "dialogue", "silence"):
            old_rows = {row.get("id"): row for row in _lines(old_scene, key)}
            new_rows = {row.get("id"): row for row in _lines(new_scene, key)}
            old_shared = [value for value in old_rows if value in new_rows]
            new_shared = [value for value in new_rows if value in old_rows]
            if old_shared != new_shared:
                for line_id in new_shared:
                    if old_shared.index(line_id) != new_shared.index(line_id):
                        lines.append({"scene_id": scene_id, "line_id": line_id, "kind": key,
                                      "change": "moved", "field": "order",
                                      "before": old_shared.index(line_id), "after": new_shared.index(line_id)})
            for line_id, row in new_rows.items():
                if line_id not in old_rows:
                    lines.append({"scene_id": scene_id, "line_id": line_id, "kind": key,
                                  "change": "added", "before": None, "after": _line_text(row)})
                    continue
                previous = old_rows[line_id]
                fields = {field: (previous.get(field), row.get(field))
                          for field in sorted((set(previous) | set(row)) - {"id"})
                          if previous.get(field) != row.get(field)}
                for field, (was, now) in fields.items():
                    lines.append({"scene_id": scene_id, "line_id": line_id, "kind": key,
                                  "change": "changed", "field": field, "before": was, "after": now})
            for line_id, row in old_rows.items():
                if line_id not in new_rows:
                    lines.append({"scene_id": scene_id, "line_id": line_id, "kind": key,
                                  "change": "removed", "before": _line_text(row), "after": None})
    for scene_id in scenes["removed"]:
        for key in ("actions", "dialogue", "silence"):
            for row in _lines(old_by_id[scene_id], key):
                lines.append({"scene_id": scene_id, "line_id": row.get("id"), "kind": key,
                              "change": "removed", "before": _line_text(row), "after": None})
    return {"scenes": scenes, "lines": lines,
            "changed": bool(scenes["added"] or scenes["removed"] or scenes["moved"] or lines)}
