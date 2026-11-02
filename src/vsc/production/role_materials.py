"""Compile bounded, local professional reading into a tool-free role request.

This is a pure compiler, not a dispatch or approval store. Callers persist the
manifest with their original task, then recompile with expected_manifest before
submission. Source links are provenance only; this module never follows them.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from vsc.assets.resource_service import ResourceError
from vsc.bootstrap import repository_root

FORMAT = "vsc.role-materials/v1"
MAX_CHARS = 24000
_CREATIVE = "skills/vsc/references/creative-production.md"
_REVIEW = "skills/vsc/references/review-and-feedback.md"
_BLOCKING = "skills/vsc-direct/references/blocking-coverage.md"
_VISUAL = "skills/vsc-assets/references/visual-attention-light.md"
_ACTION = "skills/vsc-script/references/scene-action.md"
_SUBTEXT = "skills/vsc-script/references/subtext-performance.md"
_REQUEST = "skills/vsc-produce/references/request-composition.md"
_RHYTHM = "skills/vsc-post/references/sound-picture-rhythm.md"
_VOICE = "skills/vsc-sound/references/voice-space.md"

# An explicit local selection map. Neither a prompt nor a method's URL can add
# paths to this map. Sections include their nested examples and counterexamples.
REFERENCES = {
    "source-form": (_CREATIVE, "heading:先判断来源，再确定作品形式"),
    "decomposition": (_CREATIVE, "heading:专业拆解如何落到产物"),
    "consumer-check": (_REVIEW, "anchor:consumer-check"),
    **{key: (_BLOCKING, "anchor:" + key) for key in (
        "usable-shot", "space-blocking", "axis-map", "eyeline-match", "camera-choice", "reference-structure")},
    **{key: (_VISUAL, "anchor:" + key) for key in (
        "reference-delivery", "focus-attention", "color-pattern", "light-identity", "effect-action-sync")},
    **{key: (_ACTION, "anchor:" + key) for key in (
        "visual-dialogue", "short-film-focus", "rewrite-local", "reveal-detail")},
    **{key: (_SUBTEXT, "anchor:" + key) for key in ("dialogue-subtext", "gesture-subtext")},
    **{key: (_REQUEST, "anchor:" + key) for key in (
        "prompt-organization", "frame-pairing", "negative-and-iteration")},
    **{key: (_RHYTHM, "anchor:" + key) for key in ("sound-bridge", "offscreen-cause", "match-action")},
    **{key: (_VOICE, "anchor:" + key) for key in ("sound-world", "dialogue-space")},
}

# task -> (role, main Skill, relevant reference keys)
TASKS = {
    "assets": ("asset-director", "vsc-assets", ("reference-delivery", "decomposition")),
    "asset-extraction": ("asset-director", "vsc-assets", ("reference-delivery", "decomposition")),
    "asset-matching": ("asset-director", "vsc-assets", ("reference-delivery", "consumer-check")),
    "blocking": ("director", "vsc-direct", ("space-blocking", "axis-map")),
    "script": ("director", "vsc-direct", ("usable-shot", "camera-choice", "consumer-check")),
    "story-outline": ("adaptation-editor", "vsc-adapt", ("source-form", "short-film-focus")),
    "storyboard-upgrade": ("director", "vsc-direct", ("usable-shot", "visual-dialogue", "camera-choice")),
    "storyboard-grouping": ("director", "vsc-direct", ("axis-map", "eyeline-match")),
    "blocking-continuity": ("continuity-supervisor", "vsc-continuity", ("axis-map", "match-action")),
    "storyboard-image": ("director", "vsc-direct", ("usable-shot", "reference-delivery")),
    "image-generation": ("generation-producer", "vsc-produce", ("prompt-organization", "reference-delivery")),
    "video-generation": ("generation-producer", "vsc-produce", ("prompt-organization", "frame-pairing")),
    "async-media": ("generation-producer", "vsc-produce", ("negative-and-iteration", "consumer-check")),
    "storyboard-reuse": ("director", "vsc-direct", ("usable-shot", "frame-pairing")),
    "sound-plan": ("music-supervisor", "vsc-sound", ("sound-world", "sound-bridge")),
    "prompt-optimize": ("director", "vsc-direct", ("prompt-organization", "usable-shot")),
    "prompt-recognize": ("director", "vsc-direct", ("reference-structure",)),
    "prompt-translate": ("director", "vsc-direct", ()),
    "novel-synopsis": ("story-analyst", "vsc-adapt", ("source-form", "decomposition")),
    "novel-characters": ("story-analyst", "vsc-adapt", ("source-form", "decomposition")),
    "novel-outline": ("adaptation-editor", "vsc-adapt", ("source-form", "short-film-focus")),
    "novel-scenes": ("screenwriter", "vsc-script", ("visual-dialogue", "dialogue-subtext")),
    "novel-body": ("screenwriter", "vsc-script", ("visual-dialogue", "dialogue-subtext")),
    "novel-qa_notes": ("screenwriter", "vsc-script", ("rewrite-local", "consumer-check")),
}
TASKS.update({
    "vsc-assets": TASKS["assets"], "vsc-direct": TASKS["script"],
    "vsc-script": ("screenwriter", "vsc-script", ("visual-dialogue", "dialogue-subtext", "consumer-check")),
})

_HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.+?)\s*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_ANCHOR = re.compile(r"<a\s+id=['\"]([^'\"]+)['\"]\s*>\s*</a>")


def _fail(message, code="role_materials_invalid"):
    raise ResourceError(message, code, 409)


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode("utf-8")).hexdigest()


def _read(root, path):
    try:
        resolved = (root / path).resolve(strict=True)
        resolved.relative_to(root)
        if not resolved.is_file() or resolved.stat().st_size > 512000:
            _fail("专业材料不是有界正文文件：" + path)
        raw = resolved.read_bytes()
        if len(raw) > 512000:
            _fail("专业材料不是有界正文文件：" + path)
        return raw.decode("utf-8"), _sha(raw)
    except (OSError, RuntimeError, UnicodeError, ValueError) as exc:
        raise ResourceError("专业材料缺失或路径越界：" + path, "role_materials_missing", 409) from exc


def _section(text, selector):
    """Read one ATX section, including children, ignoring fenced examples."""
    if selector == "full":
        return text
    mode, value = selector.split(":", 1)
    lines = text.splitlines(keepends=True)
    headings, matches, fence = [], [], None
    for index, line in enumerate(lines):
        marker = _FENCE.match(line.rstrip("\r\n"))
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= fence[1] and not marker[2].strip():
                fence = None
            continue
        if marker and (marker[1][0] != "`" or "`" not in marker[2]):
            fence = (marker[1][0], len(marker[1]))
            continue
        heading = _HEADING.match(line.rstrip("\r\n"))
        if heading:
            headings.append((index, len(heading[1])))
        if ((mode == "anchor" and value in _ANCHOR.findall(line)) or
                (mode == "heading" and heading and heading[2].rstrip(" #") == value)):
            matches.append(index)
    if len(matches) != 1:
        _fail("专业材料章节缺失或重复：" + selector, "role_materials_missing")
    start = matches[0]
    header = next(((index, level) for index, level in headings if index >= start), None)
    if not header or any(line.strip() for line in lines[start + 1:header[0]]):
        _fail("专业材料章节没有对应标题：" + selector, "role_materials_missing")
    end = next((index for index, level in headings if index > header[0] and level <= header[1]), len(lines))
    # A standalone anchor belongs to the following heading, not this section.
    before = end - 1
    while before > header[0] and not lines[before].strip():
        before -= 1
    if before > header[0] and _ANCHOR.fullmatch(lines[before].strip()):
        end = before
    if not any(line.strip() for line in lines[header[0] + 1:end]):
        _fail("专业材料章节没有正文：" + selector, "role_materials_missing")
    return "".join(lines[start:end])


def compile_role_materials(role_id, skill_id, task, *, method_ids=(), expected_manifest=None,
                           root=None, max_chars=MAX_CHARS):
    """Return actual selected text and a small immutable, JSON-safe manifest.

    root is a trusted installation/test override, never a model-provided path.
    max_chars can lower the fixed ceiling; overflow fails without truncating.
    """
    selection = TASKS.get(task) if isinstance(task, str) else None
    if not selection or selection[:2] != (role_id, skill_id):
        _fail("专业角色、Skill 与任务用途不匹配")
    if (not isinstance(method_ids, (list, tuple)) or len(method_ids) > 3 or
            any(not isinstance(item, str) for item in method_ids) or len(set(method_ids)) != len(method_ids)):
        _fail("请选择至多三个不同的固定方法 ID")
    if type(max_chars) is not int or not 1 <= max_chars <= MAX_CHARS:
        _fail("专业材料预算必须介于 1 与 24000 字符之间")
    root = Path(root).resolve() if root is not None else repository_root().resolve()
    materials, seen, files = [], set(), {}

    def read(path):
        if path not in files:
            files[path] = _read(root, path)
        return files[path]

    def add(kind, path, selector="full", selected_text=None):
        if (path, selector) in seen:
            return
        text, digest = read(path)
        body = selected_text if selected_text is not None else _section(text, selector)
        materials.append({"kind": kind, "path": path, "selector": selector, "sha256": digest,
                          "text_sha256": _sha(body), "text": body})
        seen.add((path, selector))

    add("role", "agents/" + role_id + ".md")
    add("skill", "skills/" + skill_id + "/SKILL.md")
    for key in selection[2]:
        add("reference", *REFERENCES[key])
    if method_ids:
        raw, _ = read("knowledge/craft.json")
        try:
            catalog = json.loads(raw)
            cards = {card["id"]: card for card in catalog["cards"]}
            sources = {source["id"]: source for source in catalog["sources"]}
            for method_id in method_ids:
                card = cards.get(method_id)
                if not card or skill_id.removeprefix("vsc-") not in card["stages"]:
                    _fail("所选方法不属于当前专业任务：" + method_id)
                ref = card.get("teaching_ref")
                if ref and (ref["path"], "anchor:" + ref["anchor"]) not in REFERENCES.values():
                    _fail("所选方法没有受控的本地教学路径：" + method_id)
                from vsc.knowledge.craft import teaching_digest
                source_details = [sources[key] for key in card["sources"]]
                teaching = None
                if ref:
                    teaching_text = _section(read(ref["path"])[0], "anchor:" + ref["anchor"])
                    teaching = {**ref, "body": teaching_text.replace("\r\n", "\n").replace("\r", "\n")}
                body = _json({"card": card, "source_details": source_details,
                              "catalog_version": catalog["version"], "teaching_available": ref is not None,
                              "teaching_sha256": teaching_digest(card, source_details, teaching)})
                add("method", "knowledge/craft.json", "method:" + method_id, body)
                if ref:
                    add("reference", ref["path"], "anchor:" + ref["anchor"])
        except (ValueError, TypeError, KeyError) as exc:
            raise ResourceError("专业方法目录结构无效", "role_materials_invalid", 409) from exc
    total = sum(len(item["text"]) for item in materials)
    if total > max_chars:
        _fail("专业材料超过固定预算，请缩小选用方法；不会截断正文", "role_materials_budget_exceeded")
    identity = {"format": FORMAT, "role_id": role_id, "skill_id": skill_id, "task": task, "method_ids": list(method_ids)}
    manifest = {**identity, "entries": [{key: value for key, value in item.items() if key != "text"} for item in materials],
                "total_chars": total, "max_chars": max_chars}
    manifest["sha256"] = _sha(_json(manifest))
    if expected_manifest is not None and expected_manifest != manifest:
        _fail("固定专业材料已变化，请建立新的原始任务；不会静默换稿", "role_materials_changed")
    return {**identity, "materials": materials, "manifest": manifest}


def validate_role_materials(bundle, *, root=None):
    """Reject fabricated text, stale files or a mismatched manifest before launch."""
    if not isinstance(bundle, dict) or not isinstance(bundle.get("manifest"), dict):
        _fail("专业材料包缺少固定清单")
    manifest = bundle["manifest"]
    current = compile_role_materials(bundle.get("role_id"), bundle.get("skill_id"), bundle.get("task"),
        method_ids=bundle.get("method_ids", ()), expected_manifest=manifest, root=root,
        max_chars=manifest.get("max_chars", MAX_CHARS))
    if bundle != current:
        _fail("专业材料正文与固定清单不一致", "role_materials_changed")
    return current
