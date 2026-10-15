#!/usr/bin/env python3
"""Bind spoken lines, acting choices and measured takes without inferring lip sync.

These read-only checks compare registered versions and decoded media. A named
reviewer remains responsible for performance, intelligibility and actual lip sync.
"""
import json
import math
from pathlib import Path

from vsc.adapters.media.qa import LocalProbeAdapter, ProbeFailure, stream_duration
from vsc.post.remotion_plan import frame_rate
from vsc.production.handoffs import artifact_ref, digest, local_file, positive, text

LIP_INTENTS = {"required", "offscreen", "voiceover"}


def _load_ref(project, state, owner, ref, errors, label, types=None, approved=True):
    if not artifact_ref(ref):
        errors.append(label + " 缺少固定{id,sha256}版本")
        return {}, {}
    artifact = next((a for a in state.get("artifacts", []) if a.get("id") == ref["id"]), {})
    if (not artifact or ref["id"] not in owner.get("depends_on", [])
            or owner.get("dependency_versions", {}).get(ref["id"]) != ref["sha256"]
            or artifact.get("sha256") != ref["sha256"]):
        errors.append(label + " 不是已登记且明确依赖的固定版本")
        return {}, {}
    if (approved and artifact.get("status") != "approved") or artifact.get("superseded_by"):
        errors.append(label + " 版本未批准或已失效")
    if types and artifact.get("type") not in types:
        errors.append(label + " 产物类型不匹配")
    try:
        path = local_file(project, artifact.get("path"))
        if digest(path) != ref["sha256"]:
            raise ValueError("版本文件SHA变化")
        data = json.loads(path.read_text("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("版本内容必须为object")
        return data, artifact
    except (OSError, ValueError, UnicodeError) as exc:
        errors.append(label + " 不可读取：" + str(exc))
        return {}, artifact


def _lines(project, state, owner, errors):
    lines = {}
    artifacts = {a["id"]: a for a in state.get("artifacts", [])}
    for identifier in owner.get("depends_on", []):
        artifact = artifacts.get(identifier, {})
        if artifact.get("type") != "vsc.screenplay":
            continue
        document, _ = _load_ref(project, state, owner, {"id": identifier, "sha256": artifact.get("sha256")}, errors, "对白剧本", {"vsc.screenplay"})
        for scene in document.get("scenes", []):
            for line in scene.get("dialogue", []):
                identifier = line.get("id")
                if not text(identifier):
                    errors.append("依赖剧本存在无效对白行ID")
                    continue
                if identifier in lines:
                    errors.append("依赖剧本对白行ID有歧义：" + identifier)
                lines[identifier] = {"line": line, "scene_id": scene.get("id"), "artifact": artifact}
    return lines


def _cue_errors(cue, lines, objects, sequence_id):
    errors = []
    if not isinstance(cue, dict):
        return ["dialogue_cues每项必须为object"]
    for key in ("id", "line_id", "text", "speaker", "acting_choice"):
        if not text(cue.get(key)):
            errors.append("dialogue_cue." + key + " 必填")
    if not isinstance(cue.get("lip_sync_intent"), str) or cue["lip_sync_intent"] not in LIP_INTENTS:
        errors.append("dialogue_cue.lip_sync_intent必须为required/offscreen/voiceover")
    line = lines.get(cue.get("line_id"), {}) if text(cue.get("line_id")) else {}
    if not line:
        errors.append("对白Cue引用不存在或未依赖的line_id：" + str(cue.get("line_id")))
    else:
        for key in ("text", "speaker"):
            if cue.get(key) != line["line"].get(key):
                errors.append("对白Cue " + key + " 与固定剧本不一致：" + cue["line_id"])
        scene_id = objects.get(sequence_id, {}).get("parent")
        if not scene_id or line["scene_id"] != scene_id:
            errors.append("对白Cue行不属于当前sequence的场次：" + cue["line_id"])
    native = cue.get("line_ids")
    if native is not None:
        if (not isinstance(native, list) or not native or not all(text(x) for x in native)
                or len(set(native)) != len(native) or cue.get("line_id") not in native):
            errors.append("原生音画line_ids需唯一且包含主line_id")
        else:
            for identifier in native:
                if identifier not in lines or lines[identifier]["scene_id"] != objects.get(sequence_id, {}).get("parent"):
                    errors.append("原生音画绑定不存在或他场对白行：" + identifier)
        if not text(cue.get("native_approved_by")):
            errors.append("原生音画对白需要真实native_approved_by逐条审听/口型绑定")
    return errors


def project_sound_errors(data, project, state, item):
    """A silent sound plan has no extra requirements; spoken cues pin real lines."""
    cues = data.get("dialogue_cues", [])
    if not isinstance(cues, list):
        return ["dialogue_cues必须为数组"]
    if not cues:
        return []
    errors = []
    lines = _lines(project, state, item, errors)
    if not lines:
        errors.append("有对白的sound_plan必须明确依赖已批准screenplay版本")
    objects = {o["id"]: o for o in state.get("objects", [])}
    seen = set()
    for cue in cues:
        errors.extend(_cue_errors(cue, lines, objects, data.get("sequence_id")))
        if not isinstance(cue, dict):
            continue
        identifier = cue.get("id")
        if text(identifier):
            if identifier in seen:
                errors.append("dialogue_cue.id重复：" + identifier)
            seen.add(identifier)
        start, end = cue.get("start_ms"), cue.get("end_ms")
        if (not isinstance(start, (int, float)) or isinstance(start, bool) or not math.isfinite(start) or start < 0
                or not positive(end) or end <= start or not positive(data.get("duration_ms"))
                or end > data["duration_ms"]):
            errors.append("对白Cue时间必须位于sound_plan.duration_ms内")
    return errors


def timeline_performance_errors(data, project, state, item):
    """Bind each consumed spoken take to a cue and its actual decoded duration."""
    bindings = [b for b in data.get("bindings", []) if b.get("audio_role") in {"dialogue", "narration", "native"}]
    if not bindings:
        return []
    errors = []
    selected, selected_item = _load_ref(project, state, item, data.get("selected_takes"), errors, "对白获选清单", {"vsc.selected_takes"})
    choices = {row["id"]: row for row in selected.get("items", [])}
    cue_index = {}
    for ref in data.get("sound_plans", []):
        plan, plan_item = _load_ref(project, state, item, ref, errors, "对白声音计划", {"vsc.sound_plan", "vsc.sound_cue_sheet"})
        errors.extend(project_sound_errors(plan, project, state, plan_item))
        lines = _lines(project, state, plan_item, errors) if plan.get("dialogue_cues") else {}
        for cue in plan.get("dialogue_cues", []):
            if isinstance(cue, dict) and text(cue.get("id")):
                if cue["id"] in cue_index:
                    errors.append("对白Cue ID跨计划有歧义：" + cue["id"])
                cue_index[cue["id"]] = (cue, lines)
    segments = {s["id"]: s for s in data.get("render_plan", {}).get("segments", [])}
    try:
        fps = frame_rate(data.get("render_plan", {}).get("composition", {}).get("fps"))
    except ValueError as exc:
        return errors + [str(exc)]
    measured = {}
    for binding in bindings:
        identifier = binding.get("segment_id")
        segment, choice = segments.get(identifier, {}), choices.get(binding.get("selected_item_id"), {})
        cue, lines = cue_index.get(binding.get("cue_id"), ({}, {}))
        role = binding["audio_role"]
        if role == "native" and not cue:
            continue  # Native ambience with no spoken lines is checked by media QA.
        if not cue or not choice or not segment:
            errors.append("对白/旁白segment必须绑定真实dialogue_cue及获选item：" + str(identifier))
            continue
        if role == "native":
            if segment.get("kind") != "video" or not cue.get("line_ids") or not text(cue.get("native_approved_by")):
                errors.append("原生音画video必须有line_ids/native_approved_by：" + str(identifier))
            try:
                media = choice.get("media", {})
                path = local_file(project, media.get("path"))
                if digest(path) != media.get("sha256"):
                    raise ValueError("原生音画获选媒体SHA变化")
                metadata = LocalProbeAdapter().probe(path)
                if not positive(stream_duration(metadata, "audio")) or not positive(stream_duration(metadata, "video")):
                    raise ValueError("原生音画需要真实可解码video及audio stream")
            except (OSError, ValueError, ProbeFailure) as exc:
                errors.append("原生音画真实媒体核验失败：" + str(exc))
            continue
        if role == "narration" and cue.get("lip_sync_intent") != "voiceover":
            errors.append("旁白Cue必须明确voiceover意图：" + str(identifier))
        source = choice.get("source", {})
        performance, inputs, output = {}, {}, {}
        if source.get("kind") == "generation":
            record, _ = _load_ref(project, state, selected_item, source.get("artifact"), errors, "对白生成记录", {"vsc.generation_record"}, approved=False)
            outputs = [row for row in record.get("outputs", []) if row.get("id") == choice.get("output_id")]
            if record.get("status") != "succeeded" or len(outputs) != 1:
                errors.append("对白生成记录未成功或output_id不唯一：" + str(identifier))
                continue
            output, inputs = outputs[0], record.get("inputs", {})
            performance = output.get("performance", {})
            if not isinstance(inputs, dict) or not isinstance(performance, dict):
                errors.append("对白生成inputs/output.performance必须为object：" + str(identifier))
                continue
            if any(output.get(key) != choice.get("media", {}).get(key) for key in ("path", "sha256")):
                errors.append("对白生成output与获选媒体不一致：" + str(identifier))
            for key in ("line_id", "acting_choice", "lip_sync_intent"):
                if inputs.get(key) != performance.get(key):
                    errors.append("表演record输入/output不一致：" + key)
            line = lines.get(cue.get("line_id"), {})
            screenplay = inputs.get("screenplay", {})
            if not line or screenplay.get("sha256") != line["artifact"].get("sha256"):
                errors.append("对白生成未固定同一screenplay SHA：" + str(identifier))
            else:
                try:
                    if digest(local_file(project, screenplay.get("path"))) != screenplay.get("sha256"):
                        raise ValueError("SHA变化")
                except (OSError, ValueError) as exc:
                    errors.append("对白生成剧本输入失效：" + str(exc))
            speaker = inputs.get("entity", output.get("entity", inputs.get("speaker")))
            if inputs.get("text") != cue.get("text") or speaker != cue.get("speaker"):
                errors.append("对白生成文本/人物speaker与Cue不一致；供应商voice需显式entity映射：" + str(identifier))
        elif source.get("kind") == "manual":
            performance = choice.get("performance", {})
            if not isinstance(performance, dict) or not text(performance.get("reviewed_by")):
                errors.append("手工声音需要具名performance.reviewed_by：" + str(identifier))
            if not isinstance(performance, dict) or any(performance.get(key) != cue.get(key) for key in ("text", "speaker")):
                errors.append("手工声音text/speaker与Cue不一致：" + str(identifier))
        else:
            errors.append("对白来源必须为generation/manual：" + str(identifier))
        if not isinstance(performance, dict):
            errors.append("对白output.performance必须为object：" + str(identifier))
            continue
        for key in ("line_id", "acting_choice", "lip_sync_intent"):
            if performance.get(key) != cue.get(key):
                errors.append("对白表演与Cue不一致：" + key + " / " + str(identifier))
        duration = performance.get("measured_duration_seconds")
        if not positive(duration):
            errors.append("对白表演必须记录真实measured_duration_seconds：" + str(identifier))
            continue
        try:
            media = choice.get("media", {})
            path = local_file(project, media.get("path"))
            if digest(path) != media.get("sha256"):
                raise ValueError("获选对白媒体SHA变化")
            if path not in measured:
                metadata = LocalProbeAdapter().probe(path)
                actual = stream_duration(metadata, "audio")
                if not positive(actual):
                    raise ValueError("获选声音没有真实可解码audio stream")
                measured[path] = actual
            tolerance = max(0.02, 1 / fps)
            if abs(measured[path] - duration) > tolerance:
                errors.append("声明对白实测时长与真实媒体不一致：" + str(identifier))
            if (segment.get("source_in_frame", 0) + segment.get("duration_in_frames", 0)) / fps > measured[path] + tolerance:
                errors.append("时间线对白裁切范围超出真实声音源时长：" + str(identifier))
            if segment.get("duration_in_frames", 0) / fps + tolerance < duration:
                errors.append("时间线片段不足以覆盖完整对白实测时长：" + str(identifier))
            if (cue.get("end_ms", 0) - cue.get("start_ms", 0)) / 1000 + tolerance < duration:
                errors.append("计划Cue窗口短于对白实测时长：" + str(identifier))
        except (OSError, ValueError, ProbeFailure) as exc:
            errors.append("对白真实媒体核验失败：" + str(exc))
    return errors
