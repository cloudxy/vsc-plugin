"""Optional sound-cue contracts and projection to existing volume keyframes."""
import copy
import hashlib
import json
import math
from pathlib import PurePosixPath
from vsc.project.creative_rules import number


def fixed_ref(value):
    if not isinstance(value, dict) or not isinstance(value.get("sha256"), str) or len(value["sha256"]) != 64 or any(c not in "0123456789abcdef" for c in value["sha256"]):
        return False
    if isinstance(value.get("id"), str) and value["id"].strip():
        return True
    path = value.get("path")
    return isinstance(path, str) and path and not PurePosixPath(path).is_absolute() and ".." not in PurePosixPath(path).parts and "\\" not in path


def ducking_errors(duck, *, dialogue_cue_ids=None):
    """Validate one envelope intent; None checks specification shape only.

    A project consumer must pass its actual Cue IDs (including an empty set),
    so a recipe placeholder can never establish a project reference.
    """
    if (not isinstance(duck, dict) or set(duck) != {"gain", "attack_ms", "release_ms", "dialogue_cue_ids"}
            or not number(duck.get("gain")) or duck["gain"] > 1
            or not number(duck.get("attack_ms")) or not number(duck.get("release_ms"))
            or not isinstance(duck.get("dialogue_cue_ids"), list) or not duck["dialogue_cue_ids"]
            or any(not isinstance(identifier, str) or not identifier.strip() for identifier in duck["dialogue_cue_ids"])
            or len(set(duck["dialogue_cue_ids"])) != len(duck["dialogue_cue_ids"])):
        return ["ducking需要0..1 gain、非负attack/release毫秒及唯一非空dialogue_cue_ids"]
    if dialogue_cue_ids is not None and any(identifier not in dialogue_cue_ids for identifier in duck["dialogue_cue_ids"]):
        return ["ducking必须引用本声音计划中实际存在的dialogue_cue_ids"]
    return []


def extra_cue_errors(data):
    errors = []
    def rows(key):
        value = data.get(key, [])
        if not isinstance(value, list):
            errors.append(key + " 必须为数组")
            return []
        return value
    sfx = data.get("sfx_cues", [])
    if not isinstance(sfx, list):
        return ["sfx_cues 必须为数组"]
    known = {row.get("id") for key in ("ambience_beds", "music_cues", "dialogue_cues")
             for row in rows(key) if isinstance(row, dict) and isinstance(row.get("id"), str)}
    for index, cue in enumerate(sfx):
        label = "sfx_cues[%d]" % index
        if not isinstance(cue, dict):
            errors.append(label + " 必须为object")
            continue
        identifier = cue.get("id")
        if not isinstance(identifier, str) or not identifier.strip() or identifier in known:
            errors.append(label + ".id 缺失、重复或与其他Cue冲突")
        else:
            known.add(identifier)
        if not isinstance(cue.get("purpose"), str) or not cue["purpose"].strip():
            errors.append(label + ".purpose 需要明确声音用途或静默理由")
        start, end = cue.get("start_ms"), cue.get("end_ms")
        if not number(start) or not number(end) or end <= start or not number(data.get("duration_ms")) or end > data["duration_ms"]:
            errors.append(label + " 时码必须递增并位于sequence时长内")
        if cue.get("silence") is True:
            if cue.get("media") or cue.get("spec_ref"):
                errors.append(label + " 静默不能同时声明音效素材")
        else:
            if "silence" in cue and type(cue["silence"]) is not bool:
                errors.append(label + ".silence 必须为boolean")
            if not fixed_ref(cue.get("media")) and not fixed_ref(cue.get("spec_ref")):
                errors.append(label + " 必须固定media或spec_ref的路径/ID与SHA")
            if not fixed_ref(cue.get("source_ref")):
                errors.append(label + ".source_ref 必须固定来源与SHA")
            if cue.get("usage_rights") not in {"owned", "licensed", "project_generated"}:
                errors.append(label + ".usage_rights 无效")
    dialogue = {row["id"] for row in rows("dialogue_cues") if isinstance(row, dict) and isinstance(row.get("id"), str)}
    for index, cue in enumerate(rows("music_cues")):
        if not isinstance(cue, dict):
            continue
        label = "music_cues[%d]" % index
        if "bpm" in cue and (not number(cue["bpm"], positive=True) or not 20 <= cue["bpm"] <= 300):
            errors.append(label + ".bpm 必须为20..300有限数值的设计意图")
        if "dynamics" in cue and (not isinstance(cue["dynamics"], str) or cue["dynamics"] not in {"pp", "p", "mp", "mf", "f", "ff"}):
            errors.append(label + ".dynamics 必须为pp/p/mp/mf/f/ff设计意图")
        if "instrumentation" in cue and (not isinstance(cue["instrumentation"], list) or not cue["instrumentation"]
                or any(not isinstance(x, str) or not x.strip() for x in cue["instrumentation"])):
            errors.append(label + ".instrumentation 必须为非空乐器文本数组")
        if "ducking" in cue:
            errors.extend(label + "." + problem for problem in ducking_errors(cue["ducking"], dialogue_cue_ids=dialogue))
    return errors


def apply_music_recipe(document, recipe, *, cue_id, dialogue_cue_ids=()):
    """Choose a native specification into a new draft, never an approval."""
    if recipe.get("kind") != "music" or not isinstance(recipe.get("spec", {}).get("sound_intent"), dict):
        raise ValueError("所选原生music规格没有可消费的sound_intent")
    intent = recipe["spec"]["sound_intent"]
    if not intent or set(intent) - {"bpm", "dynamics", "instrumentation"}:
        raise ValueError("music规格仅能投影bpm/dynamics/instrumentation设计意图")
    result = copy.deepcopy(document)
    selected = [row for row in result.get("music_cues", []) if row.get("id") == cue_id]
    if len(selected) != 1:
        raise ValueError("须明确选择当前Sound Cue表唯一music Cue ID")
    cue = selected[0]
    cue.update(copy.deepcopy(intent))
    if "ducking" in recipe["spec"]:
        cue["ducking"] = copy.deepcopy(recipe["spec"]["ducking"])
        # The reusable placeholder establishes no project fact. Only the
        # explicit target selection supplies real IDs from this sound plan.
        cue["ducking"]["dialogue_cue_ids"] = list(dialogue_cue_ids)
    problems = extra_cue_errors(result)
    if problems:
        raise ValueError("；".join(problems))
    cue["recipe_ref"] = {"id": recipe["id"], "version": recipe["version"], "sha256": hashlib.sha256(
        json.dumps(recipe, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}
    return result


def ducking_keyframes(segment, cue, sound_plan, fps, sequence_offset=0):
    duck = cue["ducking"]
    dialogue = {row["id"]: row for row in sound_plan.get("dialogue_cues", [])}
    count = segment["duration_in_frames"]
    start = segment["from_frame"]
    windows = []
    for identifier in duck["dialogue_cue_ids"]:
        row = dialogue[identifier]
        if not number(row.get("start_ms")) or not number(row.get("end_ms")) or row["end_ms"] <= row["start_ms"]:
            raise ValueError("ducking引用的对白Cue缺少真实递增时码: " + identifier)
        windows.append(((sequence_offset + row["start_ms"] * fps / 1000) - start,
                        (sequence_offset + row["end_ms"] * fps / 1000) - start))
    attack, release, gain = duck["attack_ms"] * fps / 1000, duck["release_ms"] * fps / 1000, duck["gain"]
    def each(frame, window):
        first, last = window
        if frame < first:
            return 1 if not attack else 1 - (1 - gain) * max(0, min(1, (frame - first + attack) / attack))
        if frame <= last:
            return gain
        return 1 if not release else gain + (1 - gain) * max(0, min(1, (frame - last) / release))
    def at(frame):
        return min(each(frame, window) for window in windows)
    points = {0, count - 1}
    for first, last in windows:
        for value in (first - attack, first, last, last + release):
            points.update(max(0, min(count - 1, math.floor(value) + delta)) for delta in (0, 1))
    base = sorted(points)
    for first, last in zip(base, base[1:]):
        if last <= first:
            continue
        slopes = [(each(first, window), (each(last, window) - each(first, window)) / (last - first)) for window in windows]
        for index, (a, slope_a) in enumerate(slopes):
            for b, slope_b in slopes[index + 1:]:
                if abs(slope_a - slope_b) > 1e-12:
                    cross = first + (b - a) / (slope_a - slope_b)
                    if first < cross < last:
                        points.update(max(first, min(last, math.floor(cross) + delta)) for delta in (0, 1))
    return [{"frame": frame, "volume": round(at(frame), 9)} for frame in sorted(points)]


def project_ducking(timeline, sound_plans):
    """Pure projection into the existing timeline envelope, no new authority."""
    from vsc.post.remotion_plan import frame_rate
    result = copy.deepcopy(timeline)
    plan = result.get("render_plan", result)
    fps = frame_rate(plan["composition"]["fps"])
    segments = {row["id"]: row for row in plan["segments"]}
    bindings = {row["segment_id"]: row for row in result.get("bindings", [])}
    report = []
    for sound in sound_plans:
        errors = extra_cue_errors(sound)
        if errors:
            raise ValueError("；".join(errors))
        for cue in sound.get("music_cues", []):
            if not cue.get("ducking"):
                continue
            selected = [segments[key] for key, binding in bindings.items() if binding.get("cue_id") == cue["id"] and key in segments]
            if not selected:
                raise ValueError("ducking音乐Cue没有绑定实际timeline音轨: " + cue["id"])
            offset = min(segment["from_frame"] for segment in selected) - cue["start_ms"] * fps / 1000
            for segment in selected:
                points = ducking_keyframes(segment, cue, sound, fps, offset)
                segment["volume_keyframes"] = points
                report.append({"segment_id": segment["id"], "cue_id": cue["id"], "applied": "volume_keyframes",
                    "design_only": {k: cue[k] for k in ("bpm", "dynamics", "instrumentation") if k in cue}})
    return result, report
