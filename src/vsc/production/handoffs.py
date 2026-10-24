#!/usr/bin/env python3
"""Small, version-bound production handoffs. Validation never approves creative work.

validation_errors checks documents alone. project_errors also checks the registered
object tree, exact dependencies and real bytes. The optional callback has the same
signature as vsc_artifacts.validate_artifact(project, state, artifact).
"""
import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path

from vsc.post.remotion_plan import frame_rate, validate as validate_render_plan

FORMATS = {"vsc." + name + "/v1" for name in (
    "screenplay", "coverage-plan", "selected-takes", "animatic", "timeline", "mix", "delivery-manifest")}
SHA = re.compile(r"[0-9a-f]{64}\Z")
AUDIO_ROLES = {"none", "native", "dialogue", "narration", "ambience", "music", "sfx"}
USAGE_RIGHTS = {"owned", "licensed", "project_generated"}
TYPE_FORMATS = {"vsc." + name.replace("-", "_"): "vsc." + name + "/v1" for name in (
    "screenplay", "coverage-plan", "selected-takes", "animatic", "timeline", "mix", "delivery-manifest",
    "generation-record", "adaptation-plan", "sound-plan", "shot-plan", "media-qa", "sample-review")}
TYPE_FORMATS.update({"vsc.adaptation_plan": "vsc.adaptation-map/v1", "vsc.sound_plan": "vsc.sound-cue-sheet/v1",
                     "vsc.sound_cue_sheet": "vsc.sound-cue-sheet/v1", "vsc.shot_plan": "vsc.continuity-plan/v1",
                     "vsc.continuity_plan": "vsc.continuity-plan/v1"})


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def text(value):
    return isinstance(value, str) and bool(value.strip())


def sha(value):
    return isinstance(value, str) and bool(SHA.fullmatch(value))


def positive(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def safe_relative(value):
    return (text(value) and not Path(value).is_absolute() and value not in (".", "")
            and ".." not in Path(value).parts and "\\" not in value and ":" not in value)


def local_file(root, relative):
    """Resolve only project-contained regular files, including symlink targets."""
    root = Path(root).resolve()
    if not safe_relative(relative):
        raise ValueError(f"必须为安全相对文件路径：{relative}")
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f"文件缺失或路径/符号链接越界：{relative}")
    return path


def artifact_ref(value):
    return isinstance(value, dict) and text(value.get("id")) and sha(value.get("sha256"))


def media_ref(value):
    return isinstance(value, dict) and safe_relative(value.get("path")) and sha(value.get("sha256"))


def selections_for(data):
    """Resolve visual takes independently of record ordering; ambiguity is an error."""
    errors = validation_errors(data)
    if errors or data.get("format") != "vsc.selected-takes/v1":
        raise ValueError("无效selected-takes：" + "; ".join(errors))
    grouped = {}
    for row in data["items"]:
        if row.get("shot_id"):
            grouped.setdefault(row["shot_id"], []).append(row)
    result = {}
    for shot_id, rows in grouped.items():
        visual = [row for row in rows if row["purpose"] == "visual"]
        candidates = visual or rows
        if len(candidates) != 1:
            raise ValueError("镜头选择存在歧义：" + shot_id)
        row = candidates[0]
        result[shot_id] = {"output_id": row["output_id"], "sha256": row["media"]["sha256"]}
    return result


class _Check:
    def __init__(self):
        self.errors = []

    def need(self, condition, message):
        if not condition:
            self.errors.append(message)

    def texts(self, value, label, nonempty=False):
        self.need(isinstance(value, list) and (bool(value) or not nonempty)
                  and all(text(x) for x in value), label + " 必须是文本数组")

    def rows(self, value, label, nonempty=False):
        if not isinstance(value, list) or (nonempty and not value):
            self.errors.append(label + " 必须是" + ("非空" if nonempty else "") + "数组")
            return []
        rows = []
        ids = set()
        for i, row in enumerate(value):
            if not isinstance(row, dict):
                self.errors.append(f"{label}[{i}] 必须为 object")
                continue
            if "id" in row:
                self.need(text(row["id"]) and row["id"] not in ids, label + ".id 必须非空且唯一")
                if isinstance(row["id"], str):
                    ids.add(row["id"])
            rows.append(row)
        return rows

    def ref(self, value, label):
        self.need(artifact_ref(value), label + " 必须绑定 {id, sha256} 完整版本")

    def media(self, value, label):
        self.need(media_ref(value), label + " 必须绑定安全相对 path 与完整 sha256")


def validation_errors(data):
    c = _Check()
    if not isinstance(data, dict):
        return ["交接契约必须为 object"]
    fmt = data.get("format")
    from vsc.project.creative_rules import rule_errors, document_diagnostics
    c.errors.extend(rule_errors(data.get("creative_rules", {})))
    c.need(isinstance(fmt, str) and fmt in FORMATS, "未知交接 format")
    for key in ("project_id", "scope"):
        c.need(text(data.get(key)), key + " 必须是非空文本")
    if fmt == "vsc.screenplay/v1":
        c.need(text(data.get("body")), "body 必须保留剧本正文或正文说明")
        for ref in c.rows(data.get("adaptation_refs"), "adaptation_refs", True):
            c.ref(ref, "adaptation_refs")
        unit_ids = set()
        for scene in c.rows(data.get("scenes"), "scenes", True):
            c.need(text(scene.get("id")), "scene.id 必填")
            c.need(positive(scene.get("estimated_duration_ms")), "scene.estimated_duration_ms 必须为正数")
            units = []
            for key in ("actions", "dialogue", "silence"):
                rows = c.rows(scene.get(key), "scene." + key)
                units.extend(rows)
                for row in rows:
                    identifier = row.get("id")
                    c.need(text(identifier) and identifier not in unit_ids, "剧本单元/对白行 id 必须在全文唯一")
                    if isinstance(identifier, str):
                        unit_ids.add(identifier)
                    c.texts(row.get("narrative_refs"), "narrative_refs", True)
                    if key == "silence":
                        c.need(positive(row.get("duration_ms")) and text(row.get("purpose")), "静默必须有正 duration_ms 与 purpose")
                    else:
                        c.need(text(row.get("text")), key + ".text 必填")
                    if key == "dialogue":
                        c.need(text(row.get("speaker")), "dialogue.speaker 必填")
            c.need(bool(units), "每场至少需要行动、对白或静默单元")
    elif fmt == "vsc.coverage-plan/v1":
        c.ref(data.get("screenplay"), "screenplay")
        for scene in c.rows(data.get("scenes"), "scenes"):
            c.need(text(scene.get("id")), "scene.id 必填")
            for seq in c.rows(scene.get("sequences"), "sequences"):
                c.need(text(seq.get("id")), "sequence.id 必填")
                c.ref(seq.get("shot_plan"), "shot_plan")
                c.ref(seq.get("sound_plan"), "sound_plan")
                for shot in c.rows(seq.get("shots"), "shots"):
                    c.need(text(shot.get("id")), "shot.id 必填")
                    c.texts(shot.get("screenplay_unit_ids"), "screenplay_unit_ids", True)
        for omit in c.rows(data.get("omissions"), "omissions"):
            c.need(text(omit.get("object_id")) and text(omit.get("decision_id")), "省略必须绑定 object_id 与真实 decision_id")
    elif fmt == "vsc.selected-takes/v1":
        for row in c.rows(data.get("items"), "items", True):
            for key in ("id", "take_id", "output_id", "scope", "purpose", "usage_rights", "selected_by"):
                c.need(text(row.get(key)), "selected item." + key + " 必填")
            c.need(isinstance(row.get("usage_rights"), str) and row["usage_rights"] in USAGE_RIGHTS,
                   "selected item.usage_rights必须为owned/licensed/project_generated；未知或temp_only不能正式选择")
            c.need(text(row.get("shot_id")) or (row.get("shot_id") is None and text(row.get("cue_id"))), "选择必须绑定 shot_id 或独立声音 cue_id")
            c.media(row.get("media"), "selected item.media")
            source = row.get("source")
            c.need(isinstance(source, dict) and source.get("kind") in ("generation", "manual"), "source.kind 必须为 generation/manual")
            if isinstance(source, dict):
                c.ref(source.get("artifact"), "source.artifact")
                if source.get("kind") == "manual":
                    c.need(text(source.get("imported_by")) and text(source.get("provenance")), "手工来源必须记录 imported_by 与 provenance")
    elif fmt == "vsc.animatic/v1":
        c.media(data.get("media"), "animatic.media")
        c.ref(data.get("coverage_plan"), "coverage_plan")
        for ref in c.rows(data.get("plans"), "plans", True):
            c.ref(ref, "plans")
        for row in c.rows(data.get("temporary_audio"), "temporary_audio"):
            c.media(row, "temporary_audio")
            c.need(text(row.get("purpose")), "temporary_audio.purpose 必填")
        c.texts(data.get("unresolved_issues"), "unresolved_issues")
    elif fmt == "vsc.timeline/v1":
        c.ref(data.get("selected_takes"), "selected_takes")
        for ref in c.rows(data.get("sound_plans"), "sound_plans"):
            c.ref(ref, "sound_plans")
        try:
            c.errors.extend("render_plan: " + problem for problem in validate_render_plan(data.get("render_plan")))
        except (ValueError, KeyError, TypeError) as exc:
            c.errors.append("render_plan结构无效：" + str(exc))
        binding_ids = set()
        for row in c.rows(data.get("bindings"), "bindings", True):
            for key in ("segment_id", "selected_item_id", "purpose", "usage_rights"):
                c.need(text(row.get(key)), "binding." + key + " 必填")
            c.need(isinstance(row.get("usage_rights"), str) and row["usage_rights"] in USAGE_RIGHTS, "binding.usage_rights无效")
            segment_id = row.get("segment_id")
            c.need(text(segment_id) and segment_id not in binding_ids, "每个媒体segment只能有一个binding")
            if isinstance(segment_id, str):
                binding_ids.add(segment_id)
            c.need(sha(row.get("sha256")), "binding.sha256 必须为获选媒体完整SHA")
            c.need(isinstance(row.get("audio_role"), str) and row["audio_role"] in AUDIO_ROLES, "binding.audio_role 无效")
            c.need(row.get("cue_id") is None or text(row.get("cue_id")), "binding.cue_id 必须为null或文本")
            if "output_id" in row:
                c.need(text(row["output_id"]), "binding.output_id 必须为非空文本")
            if "reuse_declared" in row:
                c.need(type(row["reuse_declared"]) is bool, "binding.reuse_declared 必须为boolean")
            if "reuse_reason" in row:
                c.need(text(row["reuse_reason"]), "binding.reuse_reason 必须为非空文本")
            if row.get("reuse_declared") is True:
                c.need(text(row.get("reuse_reason")), "有意重播必须给出明确 binding.reuse_reason 依据")
    elif fmt == "vsc.mix/v1":
        c.ref(data.get("timeline"), "timeline")
        for ref in c.rows(data.get("sound_plans"), "sound_plans"):
            c.ref(ref, "sound_plans")
        for row in c.rows(data.get("layers"), "layers"):
            c.need(text(row.get("segment_id")) and text(row.get("cue_id")), "mix layer必须绑定segment_id/cue_id")
            c.ref(row.get("sound_plan"), "layer.sound_plan")
            c.need(isinstance(row.get("audio_role"), str) and row["audio_role"] in AUDIO_ROLES - {"none"}, "layer.audio_role无效")
        for row in c.rows(data.get("boundaries"), "boundaries"):
            c.ref(row.get("sound_plan"), "boundary.sound_plan")
            c.need(text(row.get("boundary_id")) and text(row.get("reviewed_by")) and text(row.get("evidence")), "声音边界复核必须有boundary_id、reviewed_by、evidence")
            c.need(row.get("result") == "passed", "声音边界复核未通过")
            c.texts(row.get("segment_ids"), "boundary.segment_ids", True)
    elif fmt == "vsc.delivery-manifest/v1":
        c.need(text(data.get("delivery_id")), "delivery_id 必填")
        for row in c.rows(data.get("release_variants"), "release_variants", True):
            c.need(text(row.get("id")) and text(row.get("scope")), "交付版本必须有id/scope")
            c.media(row.get("render"), "variant.render")
            for sub in c.rows(row.get("subtitles"), "subtitles"):
                c.media(sub, "subtitle")
            for key in ("timeline", "mix", "qa"):
                c.ref(row.get(key), "variant." + key)
            for ref in c.rows(row.get("reviews"), "reviews", True):
                c.ref(ref, "variant.reviews")
            spec = row.get("specification", {})
            c.need(isinstance(spec, dict), "specification 必须为object")
            if isinstance(spec, dict):
                for key in ("width", "height", "duration_in_frames"):
                    c.need(isinstance(spec.get(key), int) and not isinstance(spec[key], bool) and spec[key] > 0, "specification." + key + " 必须为正整数")
                try:
                    frame_rate(spec.get("fps"))
                except ValueError as exc:
                    c.errors.append("specification: " + str(exc))
        for row in c.rows(data.get("package_media"), "package_media"):
            c.media(row, "package_media")
            c.need(isinstance(row.get("usage_rights"), str) and row["usage_rights"] in USAGE_RIGHTS
                   and row.get("package_permission") is True, "复制媒体必须明确有效usage_rights与package_permission:true")
        for row in c.rows(data.get("engineering_files"), "engineering_files"):
            c.media(row, "engineering_files")
        c.need(isinstance(data.get("tool_versions"), dict), "tool_versions 必须为object")
        c.need(isinstance(data.get("render_parameters"), dict), "render_parameters 必须为object")
    if not c.errors and data.get("creative_rules"):
        c.errors.extend(document_diagnostics(data, data["creative_rules"])["errors"])
    return c.errors


def _within(objects, identifier, scope):
    seen = set()
    while identifier and identifier not in seen:
        if identifier == scope:
            return True
        seen.add(identifier)
        identifier = objects.get(identifier, {}).get("parent")
    return scope == "project"


def _units(screenplay):
    return {row["id"]: (scene["id"], row) for scene in screenplay.get("scenes", [])
            for key in ("actions", "dialogue", "silence") for row in scene.get(key, [])}


def _cues(plan):
    return {row["id"]: row for key in ("ambience_beds", "music_cues", "dialogue_cues", "sfx_cues")
            for row in plan.get(key, []) if isinstance(row, dict) and text(row.get("id"))}


class _Project:
    def __init__(self, project, state, item, callback):
        self.project, self.state, self.item, self.callback = Path(project), state, item, callback
        self.objects = {row["id"]: row for row in state.get("objects", [])}
        self.artifacts = {row["id"]: row for row in state.get("artifacts", [])}
        self.errors, self.cache = [], {}
        self.scope = item.get("scope", "project")

    def object(self, identifier, kind, scope=None):
        obj = self.objects.get(identifier)
        if not obj or obj.get("kind") != kind:
            self.errors.append(f"引用不存在的{kind}对象：{identifier}")
            return {}
        if not _within(self.objects, identifier, self.scope if scope is None else scope):
            self.errors.append(f"对象不在声明范围内：{identifier}")
        return obj

    def media(self, media, label):
        try:
            path = local_file(self.project, media["path"])
            if digest(path) != media["sha256"]:
                self.errors.append(label + " 媒体SHA漂移：" + media["path"])
        except (ValueError, KeyError, OSError) as exc:
            self.errors.append(label + "：" + str(exc))

    def ref(self, ref, label, types=None, require_approved=True):
        if not artifact_ref(ref):
            self.errors.append(label + " 版本引用无效")
            return {}
        identifier = ref["id"]
        artifact = self.artifacts.get(identifier)
        if not artifact:
            self.errors.append(label + " 产物未登记：" + identifier)
            return {}
        if identifier not in self.item.get("depends_on", []):
            self.errors.append(label + " 必须列为明确依赖：" + identifier)
        if self.item.get("dependency_versions", {}).get(identifier) != ref["sha256"]:
            self.errors.append(label + " dependency_versions不匹配：" + identifier)
        if artifact.get("sha256") != ref["sha256"]:
            self.errors.append(label + " 版本SHA不匹配：" + identifier)
        if (require_approved and artifact.get("status") != "approved") or artifact.get("superseded_by") or artifact.get("legacy_unverified"):
            self.errors.append(label + " 不是有效批准版本：" + identifier)
        if types and artifact.get("type") not in types:
            self.errors.append(label + " 产物类型错误：" + identifier)
        if identifier in self.cache:
            return self.cache[identifier]
        try:
            path = local_file(self.project, artifact.get("path"))
            if digest(path) != ref["sha256"]:
                self.errors.append(label + " 版本文件已变化：" + identifier)
                return {}
            if self.callback:
                problems = (self.callback(self.project, self.state, artifact) if require_approved else
                            self.callback(self.project, self.state, artifact, require_approved=False))
                self.errors.extend(label + "：" + problem for problem in problems)
            if path.stat().st_size > 16 * 1024 * 1024:
                return {}
            try:
                result = json.loads(path.read_text("utf-8"))
            except (ValueError, UnicodeError):
                result = {}
            expected = TYPE_FORMATS.get(artifact.get("type"))
            if expected and (not isinstance(result, dict) or result.get("format") != expected):
                self.errors.append(label + " 内容format与登记类型不一致：" + identifier)
                return {}
            if isinstance(result, dict) and result.get("format") in FORMATS:
                problems = validation_errors(result)
                if problems:
                    self.errors.extend(label + " 内容结构无效：" + problem for problem in problems)
                    return {}
            if isinstance(result, dict):
                arrays = {"vsc.adaptation_plan": ("screen_units", "source_units"), "vsc.generation_record": ("outputs",),
                          "vsc.shot_plan": ("shots",), "vsc.continuity_plan": ("shots",),
                          "vsc.sound_plan": ("ambience_beds", "music_cues", "dialogue_cues", "sfx_cues", "boundaries"),
                          "vsc.sound_cue_sheet": ("ambience_beds", "music_cues", "dialogue_cues", "sfx_cues", "boundaries")}.get(artifact.get("type"), ())
                for key in arrays:
                    rows = result.get(key, [])
                    if not isinstance(rows, list) or not all(isinstance(row, dict) and text(row.get("id")) for row in rows):
                        self.errors.append(label + " 内容数组无效：" + key)
                        return {}
                if artifact.get("type") == "vsc.media_qa" and (not isinstance(result.get("render"), dict) or not isinstance(result["render"].get("metadata"), dict)):
                    self.errors.append(label + " 缺少真实成片metadata")
                    return {}
                if artifact.get("type") == "vsc.sample_review" and not isinstance(result.get("assessments"), dict):
                    self.errors.append(label + " 缺少结构化assessments")
                    return {}
            self.cache[identifier] = result if isinstance(result, dict) else {}
            return self.cache[identifier]
        except (ValueError, OSError) as exc:
            self.errors.append(label + "：" + str(exc))
            return {}


def project_errors(data, project, state, item, validate_callback=None):
    errors = validation_errors(data)
    if errors:
        return errors
    p = _Project(project, state, item, validate_callback)
    scope = data["scope"]
    if data["project_id"] != state.get("project_id"):
        p.errors.append("project_id 不属于当前项目")
    if scope != p.scope or (scope != "project" and scope not in p.objects):
        p.errors.append("scope 必须等于登记范围且范围对象真实存在")
    fmt = data["format"]
    if fmt == "vsc.screenplay/v1":
        narrative = {}
        for ref in data["adaptation_refs"]:
            plan = p.ref(ref, "adaptation_refs", {"vsc.adaptation_plan"})
            narrative.update({row["id"]: row for row in plan.get("screen_units", [])})
        for scene in data["scenes"]:
            p.object(scene["id"], "scene")
            for key in ("actions", "dialogue", "silence"):
                for row in scene[key]:
                    for ref in row["narrative_refs"]:
                        if ref not in narrative or narrative[ref].get("scene_id") != scene["id"]:
                            p.errors.append(f"叙事引用不存在或不属于当前场：{row['id']} -> {ref}")
    elif fmt == "vsc.coverage-plan/v1":
        screenplay = p.ref(data["screenplay"], "screenplay", {"vsc.screenplay"})
        units = _units(screenplay)
        omitted = set()
        decisions = {row["id"]: row for row in state.get("decisions", [])}
        for row in data["omissions"]:
            identifier = row["object_id"]
            obj = p.objects.get(identifier)
            decision = decisions.get(row["decision_id"], {})
            if (not obj or obj.get("kind") not in {"scene", "sequence", "shot"}
                    or not _within(p.objects, identifier, scope)):
                p.errors.append("省略对象不存在或不在范围：" + identifier)
            elif (decision.get("outcome") != "accepted" or decision.get("target") != identifier
                  or decision.get("kind") not in {"omission", "scope_omission"}
                  or not text(decision.get("by")) or not text(decision.get("reason"))):
                p.errors.append("省略没有真实accepted决定：" + identifier)
            elif identifier in omitted:
                p.errors.append("重复省略对象：" + identifier)
            else:
                omitted.add(identifier)
        expected = {obj["id"] for obj in p.objects.values() if obj.get("kind") in {"scene", "sequence", "shot"}
                    and _within(p.objects, obj["id"], scope)
                    and not any(_within(p.objects, obj["id"], excluded) for excluded in omitted)}
        present, covered, spoken = set(), set(), set()
        def include(identifier, kind, parent=None):
            obj = p.object(identifier, kind)
            if identifier in present:
                p.errors.append("覆盖对象重复：" + identifier)
            present.add(identifier)
            if identifier not in expected:
                p.errors.append("覆盖包含已省略/范围外对象：" + identifier)
            if parent and obj.get("parent") != parent:
                p.errors.append("覆盖对象父级不一致：" + identifier)
        for scene in data["scenes"]:
            include(scene["id"], "scene")
            if scene["id"] not in {row.get("id") for row in screenplay.get("scenes", [])}:
                p.errors.append("覆盖场次不在绑定剧本：" + scene["id"])
            for seq in scene["sequences"]:
                include(seq["id"], "sequence", scene["id"])
                shots = p.ref(seq["shot_plan"], "shot_plan", {"vsc.shot_plan", "vsc.continuity_plan"})
                sound = p.ref(seq["sound_plan"], "sound_plan", {"vsc.sound_plan", "vsc.sound_cue_sheet"})
                spoken.update(cue.get('line_id') for cue in sound.get('dialogue_cues', []) if isinstance(cue, dict))
                for plan, label in ((shots, "shot_plan"), (sound, "sound_plan")):
                    if plan.get("sequence_id") != seq["id"]:
                        p.errors.append(label + " 不属于声明sequence：" + seq["id"])
                planned = {row.get("id") for row in shots.get("shots", [])}
                for shot in seq["shots"]:
                    include(shot["id"], "shot", seq["id"])
                    if shot["id"] not in planned:
                        p.errors.append("镜头未包含在绑定shot_plan：" + shot["id"])
                    for unit_id in shot["screenplay_unit_ids"]:
                        if unit_id not in units or units[unit_id][0] != scene["id"]:
                            p.errors.append("覆盖了不存在或他场剧本单元：" + unit_id)
                        covered.add(unit_id)
        for identifier in sorted(expected - present):
            p.errors.append("覆盖缺失对象：" + identifier)
        expected_units = {identifier for identifier, (scene, _) in units.items() if scene in expected}
        for identifier in sorted(expected_units - covered):
            p.errors.append("覆盖缺失剧本单元：" + identifier)
        if state.get('profile_snapshot', {}).get('contract_policy') == 'production-v2':
            dialogue = {line['id'] for scene in screenplay.get('scenes', []) if scene['id'] in expected
                        for line in scene.get('dialogue', [])}
            for identifier in sorted(dialogue - spoken):
                p.errors.append('覆盖缺失对白声音Cue：' + identifier)
    elif fmt == "vsc.selected-takes/v1":
        from vsc.production.run_trial import adoption_errors
        p.errors.extend(adoption_errors(data, project, state, item))
        selections = set()
        for row in data["items"]:
            p.media(row["media"], "选择 " + row["id"])
            shot_id = row.get("shot_id")
            if shot_id:
                p.object(shot_id, "shot")
            if not _within(p.objects, row["scope"], scope) or (row["scope"] != "project" and row["scope"] not in p.objects):
                p.errors.append("获选item.scope超出声明范围：" + row["id"])
            if shot_id and not _within(p.objects, shot_id, row["scope"]):
                p.errors.append("获选镜头不在item.scope：" + row["id"])
            take = p.object(row["take_id"], "take")
            if shot_id and take.get("parent") != shot_id:
                p.errors.append("选择take不属于镜头：" + row["take_id"])
            source = row["source"]
            baseline = p.ref(source["artifact"], "selected.source", {"vsc.generation_record"} if source["kind"] == "generation" else None,
                             require_approved=source["kind"] != "generation")
            if take.get("artifact") != source["artifact"]["id"]:
                p.errors.append("take对象未绑定选定来源版本：" + row["take_id"])
            key = (shot_id, row.get("cue_id"), row["purpose"])
            if key in selections:
                p.errors.append("同一镜头/Cue用途存在重复选择：" + row["id"])
            selections.add(key)
            if source["kind"] == "generation":
                outputs = [out for out in baseline.get("outputs", []) if out.get("id") == row["output_id"]]
                if baseline.get("status") != "succeeded" or baseline.get("shot_id") != shot_id or len(outputs) != 1:
                    p.errors.append("获选生成记录/镜头/output_id不匹配：" + row["id"])
                elif any(outputs[0].get(key) != row["media"][key] for key in ("path", "sha256")):
                    p.errors.append("获选输出路径或SHA与生成记录不一致：" + row["id"])
            elif source["artifact"]["sha256"] != row["media"]["sha256"]:
                p.errors.append("手工导入必须绑定登记媒体本身的SHA：" + row["id"])
        from vsc.adapters.persistence.sqlite import series as series_db
        if state.get("profile_snapshot", {}).get("storage_policy") == series_db.POLICY:
            # The series database is the media and rights authority; the list must not contradict it.
            import sqlite3
            from vsc.post.selection import selection_errors
            try:
                p.errors.extend(selection_errors(project, data))
            except (ValueError, OSError, sqlite3.Error) as exc:
                p.errors.append("系列素材库核对失败：" + str(exc))
    elif fmt == "vsc.animatic/v1":
        p.media(data["media"], "预演")
        try:
            from vsc.adapters.media.qa import LocalProbeAdapter, ProbeFailure
            metadata = LocalProbeAdapter().probe(local_file(project, data["media"]["path"]))
            if not any(row.get("codec_type") == "video" for row in metadata.get("streams", [])):
                p.errors.append("预演没有可播放video stream")
        except (ValueError, OSError, ProbeFailure) as exc:
            p.errors.append("预演实际媒体无法完整播放验证：" + str(exc))
        p.ref(data["coverage_plan"], "coverage_plan", {"vsc.coverage_plan"})
        for ref in data["plans"]:
            p.ref(ref, "animatic.plans", {"vsc.shot_plan", "vsc.sound_plan", "vsc.timeline", "vsc.continuity_plan"})
        for media in data["temporary_audio"]:
            p.media(media, "临时声轨")
    elif fmt == "vsc.timeline/v1":
        _timeline_errors(data, p)
    elif fmt == "vsc.mix/v1":
        _mix_errors(data, p)
    elif fmt == "vsc.delivery-manifest/v1":
        _delivery_errors(data, p)
    return p.errors


def _timeline_errors(data, p):
    selected = p.ref(data["selected_takes"], "selected_takes", {"vsc.selected_takes"})
    chosen = {row["id"]: row for row in selected.get("items", [])}
    cues = {}
    for ref in data["sound_plans"]:
        plan = p.ref(ref, "sound_plans", {"vsc.sound_plan", "vsc.sound_cue_sheet"})
        for identifier, cue in _cues(plan).items():
            if identifier in cues:
                p.errors.append("声音计划Cue id冲突：" + identifier)
            cues[identifier] = cue
    plan = data["render_plan"]
    if plan["project_id"] != data["project_id"]:
        p.errors.append("render_plan.project_id 不一致")
    media_segments = {s["id"]: s for s in plan["segments"] if s["kind"] in {"video", "image", "audio"}}
    bindings = {row["segment_id"]: row for row in data["bindings"]}
    for identifier in sorted(set(media_segments) - set(bindings)):
        p.errors.append("媒体segment没有获选绑定：" + identifier)
    for identifier, binding in bindings.items():
        segment = media_segments.get(identifier)
        choice = chosen.get(binding["selected_item_id"])
        if not segment or not choice:
            p.errors.append("segment或获选item不存在：" + identifier)
            continue
        if segment.get("source") != choice["media"]["path"] or binding["sha256"] != choice["media"]["sha256"]:
            p.errors.append("时间线使用未选媒体或SHA漂移：" + identifier)
        if segment.get("overlay"):
            if choice["purpose"] != "vfx_overlay" or binding["purpose"] != "vfx_overlay" or segment["source_sha256"] != binding["sha256"]:
                p.errors.append("overlay必须固定独立获选plate及vfx_overlay用途/SHA：" + identifier)
        elif choice["purpose"] == "vfx_overlay":
            p.errors.append("获选plate不能隐式变成全幅主镜：" + identifier)
        p.media({"path": segment["source"], "sha256": binding["sha256"]}, "timeline " + identifier)
        if segment["kind"] in {"video", "image"}:
            p.object(segment.get("source_shot_id"), "shot")
            if segment.get("source_shot_id") != choice.get("shot_id"):
                p.errors.append("时间线镜头与选中take不一致：" + identifier)
        if binding["purpose"] != choice["purpose"] or binding["usage_rights"] != choice["usage_rights"]:
            p.errors.append("时间线用途/rights与选择清单不一致：" + identifier)
        if choice.get("cue_id") and choice["cue_id"] != binding.get("cue_id"):
            p.errors.append("时间线Cue与选中声音take不一致：" + identifier)
        cue = cues.get(binding.get("cue_id"), {})
        if cue.get("media") and (cue["media"].get("path") != segment.get("source") or cue["media"].get("sha256") != binding["sha256"]):
            p.errors.append("SFX实际用料与固定Cue媒体不一致：" + identifier)
        audible = segment["kind"] in {"audio", "video"} and not segment.get("muted", False) and segment.get("volume", 1) > 0
        if audible and (binding["audio_role"] == "none" or binding.get("cue_id") not in cues):
            p.errors.append("实际可听媒体必须绑定音频用途与真实Cue：" + identifier)
        if not audible and binding["audio_role"] != "none":
            p.errors.append("静音媒体不能宣称声音用途：" + identifier)
    from vsc.story.performance import timeline_performance_errors
    p.errors.extend(timeline_performance_errors(data, p.project, p.state, p.item))


def _mix_errors(data, p):
    timeline = p.ref(data["timeline"], "timeline", {"vsc.timeline"})
    plans = {ref["id"]: p.ref(ref, "sound_plans", {"vsc.sound_plan", "vsc.sound_cue_sheet"}) for ref in data["sound_plans"]}
    render = timeline.get("render_plan", {})
    segments = {row["id"]: row for row in render.get("segments", [])}
    bindings = {row["segment_id"]: row for row in timeline.get("bindings", [])}
    layers = {}
    for layer in data["layers"]:
        identifier = layer["segment_id"]
        if identifier in layers:
            p.errors.append("声音层重复：" + identifier)
        layers[identifier] = layer
        segment, binding = segments.get(identifier, {}), bindings.get(identifier, {})
        ref = layer["sound_plan"]
        plan = plans.get(ref["id"], {})
        if ref not in data["sound_plans"]:
            p.errors.append("声音层未绑定声明计划版本：" + identifier)
        cue = _cues(plan).get(layer["cue_id"])
        if (not cue or binding.get("cue_id") != layer["cue_id"]
                or binding.get("audio_role") != layer["audio_role"]):
            p.errors.append("声音层Cue/音频用途与时间线不一致：" + identifier)
        if cue and cue.get("silence") is True:
            p.errors.append("声明静默的Cue不能绑定实际可听音轨：" + identifier)
        if segment.get("kind") not in {"audio", "video"} or segment.get("muted", False) or segment.get("volume", 1) <= 0:
            p.errors.append("声音层没有实际可听片段：" + identifier)
    for identifier, binding in bindings.items():
        if binding.get("audio_role") != "none" and identifier not in layers:
            p.errors.append("混音缺失实际声音层：" + identifier)
    # Every declared cue must occur; continuous beds/music must span their cue.
    try:
        fps = frame_rate(render.get("composition", {}).get("fps"))
    except ValueError:
        p.errors.append("绑定timeline没有有效帧率")
        return
    for plan_id, plan in plans.items():
        seq_id = plan.get("sequence_id")
        visuals = [s for s in segments.values() if s.get("kind") in {"video", "image"} and not s.get("overlay")
                   and _within(p.objects, s.get("source_shot_id"), seq_id)]
        offset = min((s["from_frame"] for s in visuals), default=0)
        for cue_id, cue in _cues(plan).items():
            if cue.get("silence") is True:
                continue
            matches = [segments[x] for x, layer in layers.items() if layer["cue_id"] == cue_id and layer["sound_plan"]["id"] == plan_id and x in segments]
            if not matches:
                p.errors.append("混音缺失计划Cue：" + cue_id)
                continue
            if "start_ms" in cue and "end_ms" in cue:
                start = offset + cue["start_ms"] * fps / 1000
                end = offset + cue["end_ms"] * fps / 1000
                cursor = start
                for segment in sorted(matches, key=lambda s: s["from_frame"]):
                    if segment["from_frame"] > cursor + 1:
                        break
                    cursor = max(cursor, segment["from_frame"] + segment["duration_in_frames"])
                if cursor < end - 1:
                    p.errors.append("Cue实际音轨覆盖不足：" + cue_id)
        declared = {(plan_id, b["id"]): b for b in plan.get("boundaries", [])}
        reviews = {(r["sound_plan"]["id"], r["boundary_id"]): r for r in data["boundaries"]}
        for key, boundary in declared.items():
            review = reviews.get(key)
            if not review or review["sound_plan"] not in data["sound_plans"]:
                p.errors.append("声音边界没有固定版本复核：" + boundary["id"])
                continue
            audio = [segments[x] for x in review["segment_ids"] if x in segments and x in layers]
            if len(audio) != len(review["segment_ids"]):
                p.errors.append("边界复核引用不存在声音层：" + boundary["id"])
            cue_ids = {boundary[key] for key in ("ambience_bed_id", "music_cue_id", "dialogue_cue_id", "sfx_cue_id") if boundary.get(key)}
            if cue_ids and not all(layers[s["id"]]["cue_id"] in cue_ids for s in audio):
                p.errors.append("边界复核声音层不属于声明Cue：" + boundary["id"])
            from_shots = [s for s in visuals if s.get("source_shot_id") == boundary.get("from_shot")]
            to_shots = [s for s in visuals if s.get("source_shot_id") == boundary.get("to_shot")]
            if not from_shots or not to_shots:
                p.errors.append("声音边界的前后镜头未进入timeline：" + boundary["id"])
                continue
            cut = min(s["from_frame"] for s in to_shots)
            amount = boundary.get("tail_ms", boundary.get("lead_ms", 0)) * fps / 1000
            strategy = boundary.get("strategy")
            if strategy == "L_cut" and not any(s["from_frame"] < cut and s["from_frame"] + s["duration_in_frames"] >= cut + amount - 1 for s in audio):
                p.errors.append("声明L_cut但实际声音未延后：" + boundary["id"])
            if strategy == "J_cut" and not any(s["from_frame"] <= cut - amount + 1 and s["from_frame"] + s["duration_in_frames"] > cut for s in audio):
                p.errors.append("声明J_cut但实际声音未提前：" + boundary["id"])
    valid_boundaries = {(pid, b["id"]) for pid, plan in plans.items() for b in plan.get("boundaries", [])}
    for review in data["boundaries"]:
        if (review["sound_plan"]["id"], review["boundary_id"]) not in valid_boundaries:
            p.errors.append("复核引用不存在的声音边界：" + review["boundary_id"])
    try:
        from vsc.post.sound_rules import project_ducking
        projected, applied = project_ducking(timeline, list(plans.values()))
        expected = {segment["id"]: segment for segment in projected.get("render_plan", {}).get("segments", [])}
        for item in applied:
            identifier = item["segment_id"]
            if segments[identifier].get("volume_keyframes") != expected[identifier]["volume_keyframes"]:
                p.errors.append("声明ducking未进入实际timeline音量包络：" + identifier)
    except ValueError as exc:
        p.errors.append(str(exc))


def _delivery_errors(data, p):
    packaged = {}
    for media in data["package_media"]:
        p.media(media, "package_media")
        if media["path"] in packaged:
            p.errors.append("package_media路径重复：" + media["path"])
        packaged[media["path"]] = media
    for media in data["engineering_files"]:
        p.media(media, "engineering_files")
    variant_scopes = set()
    for variant in data["release_variants"]:
        variant_scopes.add(variant["scope"])
        if not _within(p.objects, variant["scope"], data["scope"]) or (variant["scope"] != "project" and variant["scope"] not in p.objects):
            p.errors.append("发行版本超出manifest范围：" + variant["id"])
        for media in [variant["render"], *variant["subtitles"]]:
            p.media(media, "交付 " + variant["id"])
            if not any(media["path"] == row["path"] and media["sha256"] == row["sha256"] for row in packaged.values()):
                p.errors.append("成片/字幕未获明确打包授权：" + media["path"])
        timeline = p.ref(variant["timeline"], "variant.timeline", {"vsc.timeline"})
        mix = p.ref(variant["mix"], "variant.mix", {"vsc.mix"})
        qa = p.ref(variant["qa"], "variant.qa", {"vsc.media_qa"})
        if mix.get("timeline") != variant["timeline"]:
            p.errors.append("交付mix未绑定同一timeline版本：" + variant["id"])
        composition = timeline.get("render_plan", {}).get("composition", {})
        if any(composition.get(k) != variant["specification"].get(k) for k in ("width", "height", "fps", "duration_in_frames")):
            p.errors.append("交付规格与固定timeline不一致：" + variant["id"])
        if (qa.get("plan_sha256") != variant["timeline"]["sha256"] or qa.get("status") != "passed"
                or qa.get("simulated") is not False or qa.get("eligible_for_review") is not True
                or qa.get("render", {}).get("status") != "passed"
                or qa.get("render", {}).get("metadata", {}).get("sha256") != variant["render"]["sha256"]):
            p.errors.append("QA没有绑定同一真实成片和timeline：" + variant["id"])
        for subtitle in variant["subtitles"]:
            try:
                from vsc.post.subtitles import parse_srt
                if Path(subtitle["path"]).suffix.lower() != ".srt":
                    raise ValueError("当前正式交付字幕仅支持严格SRT")
                duration = composition["duration_in_frames"] / frame_rate(composition["fps"])
                parse_srt(local_file(p.project, subtitle["path"]).read_text("utf-8"), strict=True, duration=duration)
            except (ValueError, OSError, KeyError) as exc:
                p.errors.append("交付字幕无效：" + str(exc))
        for ref in variant["reviews"]:
            review = p.ref(ref, "variant.review", {"vsc.sample_review"})
            if review.get("technical_report_sha256") != variant["qa"]["sha256"]:
                p.errors.append("审片没有绑定同一QA：" + variant["id"])
            scope = review.get("scope", {})
            if (review.get("evidence_mode") != "structured" or review.get("render_sha256") != variant["render"]["sha256"]
                    or not isinstance(scope, dict) or scope.get("kind") != "complete" or scope.get("start_frame") != 0
                    or scope.get("end_frame") != composition.get("duration_in_frames") or scope.get("delivery_id") != data["delivery_id"]):
                p.errors.append("完整审片范围/成片SHA/delivery_id与本次交付不一致：" + variant["id"])
            assessments = review.get("assessments", {})
            if not text(review.get("reviewer")) or any(not isinstance(assessments.get(k), dict) or assessments[k].get("result") != "pass" for k in (
                    "story_and_motivation", "physical_continuity", "emotional_continuity", "edit_coverage", "dialogue_and_music")):
                p.errors.append("交付缺少完整具名人工审片通过证据：" + variant["id"])
        selected_ref = timeline.get("selected_takes", {})
        selected_artifact = p.artifacts.get(selected_ref.get("id"), {})
        try:
            selected = json.loads(local_file(p.project, selected_artifact.get("path")).read_text("utf-8"))
        except (OSError, ValueError):
            selected = {}
        choices = {row["id"]: row for row in selected.get("items", [])}
        for binding in timeline.get("bindings", []):
            choice = choices.get(binding["selected_item_id"], {})
            media = choice.get("media", {})
            copy = packaged.get(media.get("path"), {})
            if copy.get("sha256") != media.get("sha256") or copy.get("usage_rights") != choice.get("usage_rights"):
                p.errors.append("时间线依赖媒体未在显式授权清单：" + str(media.get("path")))
    # Every episode in the declared range needs an actual release variant.
    episodes = [obj["id"] for obj in p.objects.values() if obj.get("kind") == "episode" and _within(p.objects, obj["id"], data["scope"])]
    for episode in episodes:
        if not any(_within(p.objects, episode, scope) for scope in variant_scopes):
            p.errors.append("发行版本缺少声明范围内集：" + episode)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate",))
    parser.add_argument("file")
    args = parser.parse_args()
    try:
        errors = validation_errors(json.loads(Path(args.file).read_text("utf-8")))
    except (OSError, ValueError) as exc:
        errors = [str(exc)]
    if errors:
        print("HANDOFF: FAIL\n" + "\n".join(errors))
        return 1
    print("HANDOFF: PASS（仅结构；项目引用、媒体与人工批准另行核验）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
