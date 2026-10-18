#!/usr/bin/env python3
"""Validate a VSC Remotion render plan and scaffold a local, editable Remotion project.

The scaffold contains VSC-authored glue only. It references media that the user stages in public/;
it never copies Remotion source code or installs npm dependencies.
"""
import argparse
import hashlib
import json
import math
import re
import shutil
import sys
from pathlib import Path
from vsc.post import subtitles as subtitles

FORMAT = "vsc.remotion-render-plan/v1"
COMPOSITION_ID = re.compile(r"[A-Za-z0-9-]+\Z")
SEGMENT_ID = re.compile(r"[A-Za-z0-9_.-]+\Z")
KINDS = {"video", "image", "audio", "caption", "text"}
REMOTION_VERSION = "4.0.532"
TIMELINE_FORMAT = "vsc.timeline/v1"


def load_plan(path):
    try:
        return json.loads(Path(path).read_text("utf-8"))
    except FileNotFoundError:
        raise ValueError(f"找不到计划文件：{path}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"计划 JSON 损坏：{exc}")


def text(value):
    return isinstance(value, str) and bool(value.strip())


def render_plan(document):
    """Read the embedded plan without discarding the outer timeline as provenance."""
    return document.get("render_plan") if isinstance(document, dict) and document.get("format") == TIMELINE_FORMAT else document


def nonnegative_int(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def frame_rate(value):
    """Return composition frames/second, including exact rational specifications."""
    if isinstance(value, dict):
        if set(value) != {"numerator", "denominator"}:
            raise ValueError("fps 分数必须仅含 numerator/denominator")
        numerator, denominator = value["numerator"], value["denominator"]
        if not nonnegative_int(numerator) or not nonnegative_int(denominator) or not numerator or not denominator:
            raise ValueError("fps 分子与分母必须是正整数")
        return numerator / denominator
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0:
        return value
    raise ValueError("fps 必须是正数或正整数分数")


def unit_interval(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= 1


def validate(plan):
    plan = render_plan(plan)
    errors = []
    if not isinstance(plan, dict):
        return ["计划必须是 object"]
    if plan.get("format") != FORMAT:
        errors.append(f"format 必须为 {FORMAT}")
    if not text(plan.get("project_id")):
        errors.append("project_id 必须是非空字符串")
    if "subtitle_style" in plan:
        try:
            if not isinstance(plan["subtitle_style"], dict):
                raise ValueError("subtitle_style 必须是 object")
            subtitles.resolve_style(overrides=plan["subtitle_style"])
        except ValueError as exc:
            errors.append(str(exc))
    composition = plan.get("composition")
    if not isinstance(composition, dict):
        return errors + ["composition 必须是 object"]
    if not isinstance(composition.get("id"), str) or not COMPOSITION_ID.fullmatch(composition["id"]):
        errors.append("composition.id 只能包含字母、数字和连字符")
    for key in ("width", "height", "duration_in_frames"):
        value = composition.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            errors.append(f"composition.{key} 必须是正整数")
    try:
        frame_rate(composition.get("fps"))
    except ValueError as exc:
        errors.append(f"composition.{exc}")
    segments = plan.get("segments")
    if not isinstance(segments, list) or not segments:
        return errors + ["segments 必须是非空数组"]
    duration = composition.get("duration_in_frames", 0)
    duration = duration if nonnegative_int(duration) else 0
    ids = set()
    visual_seen = False
    for index, segment in enumerate(segments):
        label = f"segments[{index}]"
        if not isinstance(segment, dict):
            errors.append(f"{label} 必须是 object")
            continue
        segment_id = segment.get("id")
        if not isinstance(segment_id, str) or not SEGMENT_ID.fullmatch(segment_id):
            errors.append(f"{label}.id 只能包含字母、数字、点、下划线和连字符")
        elif segment_id in ids:
            errors.append(f"{label}.id 重复：{segment_id}")
        else:
            ids.add(segment_id)
        kind = segment.get("kind")
        if kind not in KINDS:
            errors.append(f"{label}.kind 必须是 {'/'.join(sorted(KINDS))}")
            continue
        for key in ("from_frame", "duration_in_frames"):
            if not nonnegative_int(segment.get(key)) or (key == "duration_in_frames" and segment.get(key, 0) == 0):
                errors.append(f"{label}.{key} 必须是 {'非负整数' if key == 'from_frame' else '正整数'}")
        if nonnegative_int(segment.get("from_frame")) and nonnegative_int(segment.get("duration_in_frames")) and duration:
            if segment["from_frame"] + segment["duration_in_frames"] > duration:
                errors.append(f"{label} 超出 composition.duration_in_frames")
        if kind in {"video", "image", "audio"}:
            source = segment.get("source")
            if not text(source) or Path(source).is_absolute() or ".." in Path(source).parts or ":" in source or "\\" in source:
                errors.append(f"{label}.source 必须是 public/ 下的安全相对路径")
        if kind in {"video", "image"}:
            visual_seen = True
            if not text(segment.get("source_shot_id")):
                errors.append(f"{label}.source_shot_id 必须回指 VSC 镜头")
        motion = segment.get("still_motion")
        if motion is not None:
            if kind != "image" or not isinstance(motion, dict) or set(motion) != {"from", "to", "easing"}:
                errors.append(f"{label}.still_motion 仅适用于 image，且须包含 from/to/easing")
            else:
                if motion["easing"] not in ("linear", "ease_in_out"):
                    errors.append(f"{label}.still_motion.easing 无效")
                for point in ("from", "to"):
                    value = motion[point]
                    if not isinstance(value, dict) or set(value) != {"x", "y", "scale"}:
                        errors.append(f"{label}.still_motion.{point} 须包含 x/y/scale")
                        continue
                    if (not unit_interval(value["x"]) or not unit_interval(value["y"])
                            or type(value["scale"]) not in (int, float) or not math.isfinite(value["scale"])
                            or not 1 <= value["scale"] <= 1.5):
                        errors.append(f"{label}.still_motion.{point} 须有 0..1 焦点和 1..1.5 缩放")
        if kind in {"caption", "text"} and not text(segment.get("text")):
            errors.append(f"{label}.text 必须是非空字符串")
        for key in ("fade_in_frames", "fade_out_frames", "audio_fade_in_frames", "audio_fade_out_frames"):
            fade = segment.get(key, 0)
            if not nonnegative_int(fade) or (nonnegative_int(segment.get("duration_in_frames")) and fade > segment["duration_in_frames"]):
                errors.append(f"{label}.{key} 必须在片段时长范围内")
        if kind in {"video", "audio"}:
            for key in ("source_in_frame", "handle_in_frames", "handle_out_frames"):
                if not nonnegative_int(segment.get(key, 0)):
                    errors.append(f"{label}.{key} 必须是非负整数（composition 帧率）")
            start, before = segment.get("source_in_frame", 0), segment.get("handle_in_frames", 0)
            if nonnegative_int(start) and nonnegative_int(before) and before > start:
                errors.append(f"{label}.handle_in_frames 超出源入点前的可用素材")
            available = segment.get("source_duration_in_frames")
            if available is not None:
                if not nonnegative_int(available) or not available:
                    errors.append(f"{label}.source_duration_in_frames 必须是正整数")
                elif all(nonnegative_int(segment.get(key, 0)) for key in ("source_in_frame", "duration_in_frames", "handle_out_frames")):
                    end = start + segment.get("duration_in_frames", 0) + segment.get("handle_out_frames", 0)
                    if end > available:
                        errors.append(f"{label} 裁切范围与尾手柄超出声明的源时长")
            if not unit_interval(segment.get("volume", 1)):
                errors.append(f"{label}.volume 必须在 0..1 范围内")
            if "muted" in segment and not isinstance(segment["muted"], bool):
                errors.append(f"{label}.muted 必须是 boolean")
            points = segment.get("volume_keyframes", [])
            if not isinstance(points, list):
                errors.append(f"{label}.volume_keyframes 必须是数组")
            else:
                previous = -1
                for point in points:
                    if not isinstance(point, dict) or not nonnegative_int(point.get("frame")) or not unit_interval(point.get("volume")):
                        errors.append(f"{label}.volume_keyframes 每项需要非负 frame 与 0..1 volume")
                        continue
                    if point["frame"] <= previous or (nonnegative_int(segment.get("duration_in_frames")) and point["frame"] >= segment["duration_in_frames"]):
                        errors.append(f"{label}.volume_keyframes 帧必须递增且位于片段内")
                    previous = point["frame"]
    if not visual_seen:
        errors.append("至少需要一个 video 或 image 片段")
    if not errors:
        try:
            fps = frame_rate(composition["fps"])
            subtitles.compile_cues([(s["from_frame"] / fps, (s["from_frame"] + s["duration_in_frames"]) / fps, s["text"])
                                    for s in sorted(segments, key=lambda s: s["from_frame"]) if s["kind"] in {"caption", "text"}],
                                   duration=duration / fps)
        except ValueError as exc:
            errors.append(str(exc))
    return errors


def compile_subtitles(plan, style, *, script_texts=None, require_font=False, media_root=None, formal_subtitles=False):
    """Use one subtitle compiler for scaffolding and editor export; never retime."""
    fps = frame_rate(plan["composition"]["fps"])
    segments = sorted((s for s in plan["segments"] if s["kind"] in {"caption", "text"}), key=lambda s: s["from_frame"])
    bound = None
    package = plan.get("subtitle_package")
    if package is not None:
        require_font = require_font or package.get("status") == "verified"
        bound = subtitles.package_cues(package, media_root or Path.cwd(), project_id=plan["project_id"],
            formal=formal_subtitles or package.get("status") == "verified")
        expected = subtitles.caption_segments(package, fps)
        fields = ("id", "line_id", "from_frame", "duration_in_frames", "subtitle_start_ms", "subtitle_end_ms")
        if len(segments) != len(expected) or any(any(actual.get(key) != wanted[key] for key in fields)
                or subtitles.display_text(actual["text"]) != subtitles.display_text(wanted["text"])
                for actual, wanted in zip(segments, expected)):
            raise subtitles.SubtitleError(["字幕片段与固定行/实测时码包不一致"])
        if abs(package["duration_ms"] - plan["composition"]["duration_in_frames"] * 1000 / fps) > .001:
            raise subtitles.SubtitleError(["字幕包与合成规格范围不一致"])
    elif formal_subtitles and segments:
        raise subtitles.SubtitleError(["正式字幕交付需要批准行、采用音频与实测时码包"])
    font, max_width = None, None
    if segments:
        if style.get("font"):
            font, max_width = subtitles.layout_font(style, plan["composition"]["width"])
        elif require_font:
            raise subtitles.SubtitleError(["严格字幕交付需要实际字体排版检查"])
    items = bound["cues"] if bound else [(s["from_frame"] / fps, (s["from_frame"] + s["duration_in_frames"]) / fps, s["text"]) for s in segments]
    compiled = subtitles.compile_cues(items,
        duration=plan["composition"]["duration_in_frames"] / fps, script_texts=script_texts, font=font, max_width=max_width,
        style=style, height=plan["composition"]["height"])
    if bound:
        compiled["checks"].update({key: value for key, value in bound["checks"].items() if key != "font_layout"})
        compiled["checks"]["render_time_resolution"] = "composition_frames; original measured milliseconds preserved"
    return compiled, {s["id"]: cue[2] for s, cue in zip(segments, compiled["cues"])}


def die(message):
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def plan_module(plan):
    return "import type {RenderPlan} from './timing';\nexport const plan: RenderPlan = " + json.dumps(plan, ensure_ascii=False, indent=2) + ";\n"


ROOT_TSX = """import {Composition} from 'remotion';
import {ShortDrama} from './ShortDrama';
import {plan} from './plan';
import {toFps} from './timing';

export const Root: React.FC = () => (
  <Composition
    id={plan.composition.id}
    component={ShortDrama}
    durationInFrames={plan.composition.duration_in_frames}
    fps={toFps(plan.composition.fps)}
    width={plan.composition.width}
    height={plan.composition.height}
    defaultProps={{plan}}
  />
);
"""

TIMING_TS = """// Pure frame math: no browser, React, or Remotion dependency.
export type Fps = number | {numerator: number; denominator: number};
export type Segment = {
  id: string; kind: 'video' | 'image' | 'audio' | 'caption' | 'text';
  from_frame: number; duration_in_frames: number; source?: string; text?: string;
  line_id?: string; subtitle_start_ms?: number; subtitle_end_ms?: number;
  source_shot_id?: string; source_in_frame?: number; source_duration_in_frames?: number;
  handle_in_frames?: number; handle_out_frames?: number;
  fade_in_frames?: number; fade_out_frames?: number; volume?: number; muted?: boolean;
  audio_fade_in_frames?: number; audio_fade_out_frames?: number;
  volume_keyframes?: {frame: number; volume: number}[];
  still_motion?: {from: {x: number; y: number; scale: number}; to: {x: number; y: number; scale: number}; easing: 'linear' | 'ease_in_out'};
};
export type RenderPlan = {
  format: string; project_id: string;
  subtitle_package?: Record<string, unknown>;
  composition: {id: string; width: number; height: number; fps: Fps; duration_in_frames: number};
  segments: Segment[];
  subtitle_style?: SubtitleStyle;
};
export type SubtitleStyle = {
  font: string | null; font_size: number; color: string; stroke_color: string; stroke_width: number;
  position: 'bottom' | 'top' | 'center' | 'custom'; custom_position: number; background: string | null; rounded: boolean;
};
export const captionPlacement = (style: SubtitleStyle, margin: number) => {
  if (style.position === 'bottom') return {bottom: `${margin * 100}%`};
  if (style.position === 'top') return {top: `${margin * 100}%`};
  const percent = style.position === 'custom' ? style.custom_position : 50;
  return {top: `${percent}%`, transform: `translateY(-${percent}%)`};
};
export const toFps = (fps: Fps): number => typeof fps === 'number' ? fps : fps.numerator / fps.denominator;
const clamp = (x: number): number => Math.max(0, Math.min(1, x));
export const stillMotionAtFrame = (segment: Segment, frame: number): {translateX: number; translateY: number; scale: number} => {
  const motion = segment.still_motion;
  if (!motion) return {translateX: 0, translateY: 0, scale: 1};
  const ratio = clamp(frame / Math.max(1, segment.duration_in_frames - 1));
  const progress = motion.easing === 'ease_in_out' ? ratio * ratio * (3 - 2 * ratio) : ratio;
  const blend = (start: number, end: number): number => start + (end - start) * progress;
  const scale = blend(motion.from.scale, motion.to.scale);
  const x = blend(motion.from.x, motion.to.x);
  const y = blend(motion.from.y, motion.to.y);
  return {translateX: (0.5 - x) * (scale - 1) * 100,
          translateY: (0.5 - y) * (scale - 1) * 100, scale};
};
export const fadeGain = (frame: number, duration: number, fadeIn: number, fadeOut: number): number => {
  const up = fadeIn ? clamp(frame / fadeIn) : 1;
  const down = fadeOut ? clamp((duration - 1 - frame) / fadeOut) : 1;
  return up * down;
};
export const volumeAtFrame = (segment: Segment, frame: number): number => {
  const points = segment.volume_keyframes ?? [];
  let envelope = 1;
  if (points.length) {
    envelope = points[0].volume;
    for (let i = 1; i < points.length; i++) {
      const previous = points[i - 1];
      const current = points[i];
      if (frame <= current.frame) {
        const ratio = clamp((frame - previous.frame) / (current.frame - previous.frame));
        envelope = previous.volume + ratio * (current.volume - previous.volume);
        break;
      }
      envelope = current.volume;
    }
  }
  return (segment.muted ? 0 : segment.volume ?? 1) * envelope * fadeGain(frame, segment.duration_in_frames, segment.audio_fade_in_frames ?? 0, segment.audio_fade_out_frames ?? 0);
};
"""

VIDEO_TSX = """import {useEffect, useLayoutEffect, useRef, useState} from 'react';
import {AbsoluteFill, Img, Sequence, staticFile, useCurrentFrame, delayRender, continueRender, cancelRender} from 'remotion';
import {Audio, Video} from '@remotion/media';
import {plan as defaultPlan} from './plan';
import {captionPlacement, fadeGain, stillMotionAtFrame, toFps, volumeAtFrame} from './timing';
import type {RenderPlan, Segment, SubtitleStyle} from './timing';

const mediaStyle: React.CSSProperties = {width: '100%', height: '100%', objectFit: 'cover'};

const safeMargin = __SAFE_MARGIN__;
const TextLayer: React.FC<{text: string; style: SubtitleStyle; height: number}> = ({text, style, height}) => {
  const ref = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    if (ref.current && (ref.current.scrollHeight > ref.current.clientHeight || ref.current.scrollWidth > ref.current.clientWidth
        || ref.current.getBoundingClientRect().height > height * (1 - 2 * safeMargin))) {
      cancelRender(new Error('Subtitle exceeds two lines or safe area; supply real speech timecodes or change approved style'));
    }
  }, [text, height, style]);
  return <AbsoluteFill>
    <div ref={ref} style={{position: 'absolute', left: '9%', width: '82%', maxHeight: style.font_size * 2.5 + (style.background ? style.font_size * .7 : 0),
      ...captionPlacement(style, safeMargin), color: style.color, fontSize: style.font_size,
      fontFamily: style.font ? 'VSCSubtitle' : 'sans-serif', fontWeight: 700, textAlign: 'center',
      whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', boxSizing: 'border-box', lineHeight: 1.25,
      WebkitTextStroke: `${style.stroke_width}px ${style.stroke_color}`, paintOrder: 'stroke fill',
      backgroundColor: style.background ? `${style.background}${style.rounded ? '8c' : ''}` : undefined,
      borderRadius: style.rounded ? style.font_size * 0.4 : 0,
      padding: style.background ? `${style.font_size * 0.35}px ${style.font_size * 0.6}px` : 0}}>{text}</div>
  </AbsoluteFill>;
};

const useSubtitleFont = (font: string | null) => {
  const [handle] = useState(() => delayRender('Loading bound subtitle font'));
  const [ready, setReady] = useState(!font);
  useLayoutEffect(() => {if (ready) continueRender(handle);}, [ready, handle]);
  useEffect(() => {
    if (!font) {setReady(true); return;}
    let cancelled = false;
    const face = new FontFace('VSCSubtitle', `url("${staticFile(font)}")`);
    face.load().then((loaded) => {
      if (!cancelled) {document.fonts.add(loaded); setReady(true);}
    }).catch((error) => {if (!cancelled) cancelRender(error);});
    return () => {cancelled = true;};
  }, [font, handle]);
  return ready;
};

const Visual: React.FC<{segment: Segment}> = ({segment}) => {
  const frame = useCurrentFrame();
  const opacity = fadeGain(frame, segment.duration_in_frames, segment.fade_in_frames ?? 0, segment.fade_out_frames ?? 0);
  if (segment.kind === 'video') return <Video src={staticFile(segment.source!)} trimBefore={segment.source_in_frame ?? 0} durationInFrames={segment.duration_in_frames} volume={volumeAtFrame(segment, frame)} muted={segment.muted ?? false} objectFit="cover" style={{width: '100%', height: '100%', opacity}} />;
  if (segment.kind === 'image') {
    const motion = stillMotionAtFrame(segment, frame);
    return <AbsoluteFill style={{overflow: 'hidden', opacity}}><Img src={staticFile(segment.source!)} style={{...mediaStyle,
      transform: `translate(${motion.translateX}%, ${motion.translateY}%) scale(${motion.scale})`}} /></AbsoluteFill>;
  }
  return null;
};

const Sound: React.FC<{segment: Segment}> = ({segment}) => {
  const frame = useCurrentFrame();
  return <Audio src={staticFile(segment.source!)} trimBefore={segment.source_in_frame ?? 0} durationInFrames={segment.duration_in_frames} volume={volumeAtFrame(segment, frame)} muted={segment.muted ?? false} />;
};

export const ShortDrama: React.FC<{plan?: RenderPlan}> = ({plan = defaultPlan}) => {
  const subtitleStyle = plan.subtitle_style ?? defaultPlan.subtitle_style!;
  const fontReady = useSubtitleFont(subtitleStyle.font);
  return <AbsoluteFill style={{backgroundColor: 'black'}}>
    {plan.segments.map((segment) => (
      <Sequence key={segment.id} name={segment.id} from={segment.from_frame} durationInFrames={segment.duration_in_frames} premountFor={Math.ceil(toFps(plan.composition.fps))}>
        {segment.kind === 'video' || segment.kind === 'image' ? <Visual segment={segment} /> : null}
        {segment.kind === 'audio' ? <Sound segment={segment} /> : null}
        {fontReady && (segment.kind === 'caption' || segment.kind === 'text') ? <TextLayer text={segment.text!} style={subtitleStyle} height={plan.composition.height} /> : null}
      </Sequence>
    ))}
  </AbsoluteFill>;
};
"""

INDEX_TS = """import {registerRoot} from 'remotion';
import {Root} from './Root';

registerRoot(Root);
"""


def scaffold(document, destination, plan_path=None, bible=None, strict_subtitles=False, *, script_texts=None, formal_subtitles=False):
    errors = validate(document)
    if errors:
        raise ValueError("；".join(errors))
    plan = json.loads(json.dumps(render_plan(document)))
    formal_subtitles = formal_subtitles or isinstance(plan.get("subtitle_package"), dict) and plan["subtitle_package"].get("status") == "verified"
    bible_bytes = Path(bible).read_bytes() if bible else None
    style, style_source = subtitles.resolve_style(bible, plan.get("subtitle_style"))
    if bible and Path(bible).read_bytes() != bible_bytes:
        raise ValueError("资产库在字幕样式解析过程中变更，请重试")
    source_bytes = (json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    if plan_path is not None:
        source_bytes = Path(plan_path).read_bytes()
        if json.loads(source_bytes) != document:
            raise ValueError("源时间线在脚手架准备过程中变更，请重试")
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    font_path, font_record, warnings = None, None, ["浏览器、Pillow 与剪映的字体排版并非逐像素等同；横竖版字幕和主体安全区仍须真实回看"]
    if style.get("font"):
        font_path = Path(style["font"])
        if not font_path.is_absolute():
            font_path = (Path(plan_path).resolve().parent if plan_path else Path.cwd()) / font_path
        if not font_path.is_file():
            raise ValueError(f"字幕字体不存在：{font_path}")
    else:
        from tools.maintenance.vendor_sync import VENDOR
        default_font = VENDOR / "noto-sans-sc/Sans/SubsetOTF/SC/NotoSansSC-Bold.otf"
        if default_font.is_file():
            font_path = default_font
        elif strict_subtitles and any(s["kind"] in {"caption", "text"} for s in plan["segments"]):
            raise ValueError("严格字幕交付需要可打包并绑定 SHA 的字体文件")
        else:
            warnings.append("未找到可打包的字幕字体，使用系统 sans-serif；字体不可复现，须配置字体后才能作为严格字幕交付依据")
    if font_path:
        style["font"] = str(font_path)
    compiled, display_by_id = compile_subtitles(plan, style, script_texts=script_texts, require_font=strict_subtitles or formal_subtitles,
        media_root=Path(plan_path).resolve().parent if plan_path else Path.cwd(), formal_subtitles=formal_subtitles)
    for segment in plan["segments"]:
        if segment["id"] in display_by_id:
            segment["text"] = display_by_id[segment["id"]]
    if font_path:
        font_sha = hashlib.sha256(font_path.read_bytes()).hexdigest()
        relative = f"fonts/vsc-{font_sha[:16]}{font_path.suffix.lower()}"
        style["font"] = relative
        font_record = {"path": "public/" + relative, "sha256": font_sha, "source_filename": font_path.name}
    plan["subtitle_style"] = style
    destination = Path(destination)
    if destination.exists() and any(destination.iterdir()):
        raise ValueError(f"拒绝覆盖非空目录：{destination}")
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "src").mkdir(exist_ok=True)
    (destination / "public").mkdir(exist_ok=True)
    if font_record:
        target = destination / font_record["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(font_path, target)
        if hashlib.sha256(target.read_bytes()).hexdigest() != font_record["sha256"]:
            raise ValueError("字体在复制过程中变更，请重新生成脚手架")
    (destination / "vsc-source-plan.json").write_bytes(source_bytes)
    manifest = {"format": "vsc.remotion-scaffold/v1", "source_plan": {"path": "vsc-source-plan.json", "sha256": source_sha, "format": document.get("format")},
                "subtitle_style": {"source": style_source, "resolved": style, "bible_sha256": hashlib.sha256(bible_bytes).hexdigest() if bible_bytes is not None else None,
                                   "font": font_record, "safe_margin_ratio": subtitles.SAFE_MARGIN}, "warnings": warnings,
                "subtitle_checks": compiled["checks"],
                "verification": {"scaffold": "generated", "typecheck": "not_run", "render": "not_run", "human_review": "not_run"}}
    (destination / "vsc-scaffold.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", "utf-8")
    safe_project = re.sub(r"[^a-z0-9-]+", "-", plan["project_id"].lower()).strip("-") or "project"
    package = {
        "name": f"vsc-{safe_project}-remotion",
        "private": True,
        "type": "module",
        "scripts": {"studio": "remotion studio src/index.ts", "render": "remotion render src/index.ts", "typecheck": "tsc --noEmit"},
        "dependencies": {"@remotion/cli": REMOTION_VERSION, "@remotion/media": REMOTION_VERSION, "remotion": REMOTION_VERSION, "react": "^19.0.0", "react-dom": "^19.0.0"},
        "devDependencies": {"@types/react": "^19.0.0", "@types/react-dom": "^19.0.0", "typescript": "^5.0.0"},
    }
    (destination / "package.json").write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", "utf-8")
    (destination / "src" / "index.ts").write_text(INDEX_TS, "utf-8")
    (destination / "src" / "Root.tsx").write_text(ROOT_TSX, "utf-8")
    (destination / "src" / "ShortDrama.tsx").write_text(VIDEO_TSX.replace("__SAFE_MARGIN__", str(subtitles.SAFE_MARGIN)), "utf-8")
    (destination / "src" / "plan.ts").write_text(plan_module(plan), "utf-8")
    (destination / "src" / "timing.ts").write_text(TIMING_TS, "utf-8")
    (destination / "tsconfig.json").write_text(json.dumps({"compilerOptions": {"target": "ES2022", "lib": ["DOM", "ES2022"], "jsx": "react-jsx", "module": "ESNext", "moduleResolution": "Bundler", "strict": True, "skipLibCheck": True, "noEmit": True}, "include": ["src"]}, indent=2) + "\n", "utf-8")
    (destination / "public" / "README.md").write_text("将计划中 source 指向的媒体按相同相对路径放入此目录。例如 takes/SH-001.mp4 对应 public/takes/SH-001.mp4。\n", "utf-8")
    (destination / "README.md").write_text("# VSC Remotion 项目\n\n1. 将选定 take、音频和其他素材放到 `public/`。\n2. `npm install`\n3. `npm run typecheck`，再 `npm run studio` 预览并由负责人确认。\n4. `npm run render -- <composition-id> out/final.mp4` 导出。\n\n`vsc-source-plan.json` 保留原始时间线，`vsc-scaffold.json` 绑定外层 SHA、共享字幕样式、已打包字体与安全区。字体加载失败或字幕高于安全区会阻断渲染；横竖版排版仍须分别回看。\n\n计划字段的语义见 VSC 仓库 docs/design/remotion.md 的「帧级字段」。\n\n脚手架生成不代表已安装、通过类型检查、成功渲染或人工审片。此项目由 VSC 计划生成；上游 Remotion Skill 在 vendor/remotion 中单独保留。\n" + "".join("\n警告：" + warning + "\n" for warning in warnings), "utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    command = parser.add_subparsers(dest="command", required=True)
    validate_parser = command.add_parser("validate", help="校验 vsc.remotion-render-plan/v1")
    validate_parser.add_argument("plan")
    scaffold_parser = command.add_parser("scaffold", help="生成本地可编辑 Remotion 项目，不安装依赖")
    scaffold_parser.add_argument("plan")
    scaffold_parser.add_argument("output")
    scaffold_parser.add_argument("--bible", help="与烧录器/剪映共用的资产库 subtitle_style")
    scaffold_parser.add_argument("--strict-subtitles", action="store_true", help="字幕字体必须能够打包并绑定 SHA")
    scaffold_parser.add_argument("--script-texts", help="固定原稿 JSON 字符串数组；核对缺字，不代表音频对齐")
    scaffold_parser.add_argument("--formal-subtitles", action="store_true", help="要求批准台词行/采用音频/实测时码固定包")
    args = parser.parse_args()
    try:
        plan = load_plan(args.plan)
        errors = validate(plan)
        if errors:
            for error in errors:
                print(f"INVALID: {error}", file=sys.stderr)
            raise SystemExit(1)
        if args.command == "validate":
            actual = render_plan(plan)
            print(f"VALID: {actual['composition']['id']}  {len(actual['segments'])} segments")
            return
        scaffold(plan, args.output, plan_path=args.plan, bible=args.bible, strict_subtitles=args.strict_subtitles,
                 script_texts=subtitles.read_script_texts(args.script_texts) if args.script_texts else None, formal_subtitles=args.formal_subtitles)
        print(f"SCAFFOLDED: {Path(args.output)}")
    except (OSError, ValueError) as exc:
        die(str(exc))


if __name__ == "__main__":
    main()
