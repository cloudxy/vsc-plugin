#!/usr/bin/env python3
"""Validate a VSC Remotion render plan and scaffold a local, editable Remotion project.

The scaffold contains VSC-authored glue only. It references media that the user stages in public/;
it never copies Remotion source code or installs npm dependencies.
"""
import argparse
import json
import math
import re
import sys
from pathlib import Path

FORMAT = "vsc.remotion-render-plan/v1"
COMPOSITION_ID = re.compile(r"[A-Za-z0-9-]+\Z")
SEGMENT_ID = re.compile(r"[A-Za-z0-9_.-]+\Z")
KINDS = {"video", "image", "audio", "caption", "text"}
REMOTION_VERSION = "4.0.532"


def load_plan(path):
    try:
        return json.loads(Path(path).read_text("utf-8"))
    except FileNotFoundError:
        raise ValueError(f"找不到计划文件：{path}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"计划 JSON 损坏：{exc}")


def text(value):
    return isinstance(value, str) and bool(value.strip())


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
    errors = []
    if not isinstance(plan, dict):
        return ["计划必须是 object"]
    if plan.get("format") != FORMAT:
        errors.append(f"format 必须为 {FORMAT}")
    if not text(plan.get("project_id")):
        errors.append("project_id 必须是非空字符串")
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
    return errors


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
  source_shot_id?: string; source_in_frame?: number; source_duration_in_frames?: number;
  handle_in_frames?: number; handle_out_frames?: number;
  fade_in_frames?: number; fade_out_frames?: number; volume?: number; muted?: boolean;
  audio_fade_in_frames?: number; audio_fade_out_frames?: number;
  volume_keyframes?: {frame: number; volume: number}[];
};
export type RenderPlan = {
  format: string; project_id: string;
  composition: {id: string; width: number; height: number; fps: Fps; duration_in_frames: number};
  segments: Segment[];
};
export const toFps = (fps: Fps): number => typeof fps === 'number' ? fps : fps.numerator / fps.denominator;
const clamp = (x: number): number => Math.max(0, Math.min(1, x));
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

VIDEO_TSX = """import {AbsoluteFill, Img, Sequence, staticFile, useCurrentFrame} from 'remotion';
import {Audio, Video} from '@remotion/media';
import {plan as defaultPlan} from './plan';
import {fadeGain, toFps, volumeAtFrame} from './timing';
import type {RenderPlan, Segment} from './timing';

const mediaStyle: React.CSSProperties = {width: '100%', height: '100%', objectFit: 'cover'};

const TextLayer: React.FC<{text: string}> = ({text}) => (
  <AbsoluteFill style={{alignItems: 'center', justifyContent: 'flex-end', padding: 72, color: 'white', fontSize: 42, fontWeight: 700, textAlign: 'center', textShadow: '0 2px 8px black'}}>
    <div>{text}</div>
  </AbsoluteFill>
);

const Visual: React.FC<{segment: Segment}> = ({segment}) => {
  const frame = useCurrentFrame();
  const opacity = fadeGain(frame, segment.duration_in_frames, segment.fade_in_frames ?? 0, segment.fade_out_frames ?? 0);
  const style = {...mediaStyle, opacity};
  if (segment.kind === 'video') return <Video src={staticFile(segment.source!)} trimBefore={segment.source_in_frame ?? 0} durationInFrames={segment.duration_in_frames} volume={volumeAtFrame(segment, frame)} muted={segment.muted ?? false} objectFit="cover" style={{width: '100%', height: '100%', opacity}} />;
  if (segment.kind === 'image') return <Img src={staticFile(segment.source!)} style={style} />;
  return null;
};

const Sound: React.FC<{segment: Segment}> = ({segment}) => {
  const frame = useCurrentFrame();
  return <Audio src={staticFile(segment.source!)} trimBefore={segment.source_in_frame ?? 0} durationInFrames={segment.duration_in_frames} volume={volumeAtFrame(segment, frame)} muted={segment.muted ?? false} />;
};

export const ShortDrama: React.FC<{plan?: RenderPlan}> = ({plan = defaultPlan}) => (
  <AbsoluteFill style={{backgroundColor: 'black'}}>
    {plan.segments.map((segment) => (
      <Sequence key={segment.id} name={segment.id} from={segment.from_frame} durationInFrames={segment.duration_in_frames} premountFor={Math.ceil(toFps(plan.composition.fps))}>
        {segment.kind === 'video' || segment.kind === 'image' ? <Visual segment={segment} /> : null}
        {segment.kind === 'audio' ? <Sound segment={segment} /> : null}
        {segment.kind === 'caption' || segment.kind === 'text' ? <TextLayer text={segment.text!} /> : null}
      </Sequence>
    ))}
  </AbsoluteFill>
);
"""

INDEX_TS = """import {registerRoot} from 'remotion';
import {Root} from './Root';

registerRoot(Root);
"""


def scaffold(plan, destination):
    destination = Path(destination)
    if destination.exists() and any(destination.iterdir()):
        raise ValueError(f"拒绝覆盖非空目录：{destination}")
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "src").mkdir(exist_ok=True)
    (destination / "public").mkdir(exist_ok=True)
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
    (destination / "src" / "ShortDrama.tsx").write_text(VIDEO_TSX, "utf-8")
    (destination / "src" / "plan.ts").write_text(plan_module(plan), "utf-8")
    (destination / "src" / "timing.ts").write_text(TIMING_TS, "utf-8")
    (destination / "tsconfig.json").write_text(json.dumps({"compilerOptions": {"target": "ES2022", "lib": ["DOM", "ES2022"], "jsx": "react-jsx", "module": "ESNext", "moduleResolution": "Bundler", "strict": True, "skipLibCheck": True, "noEmit": True}, "include": ["src"]}, indent=2) + "\n", "utf-8")
    (destination / "public" / "README.md").write_text("将计划中 source 指向的媒体按相同相对路径放入此目录。例如 takes/SH-001.mp4 对应 public/takes/SH-001.mp4。\n", "utf-8")
    (destination / "README.md").write_text("# VSC Remotion 项目\n\n1. 将选定 take、音频和其他素材放到 `public/`。\n2. `npm install`\n3. `npm run typecheck`，再 `npm run studio` 预览并由负责人确认。\n4. `npm run render -- <composition-id> out/final.mp4` 导出。\n\n计划字段的语义见 VSC 仓库 docs/design/remotion.md 的「帧级字段」。\n\n脚手架生成不代表已安装、通过类型检查、成功渲染或人工审片。此项目由 VSC 计划生成；上游 Remotion Skill 在 vendor/remotion 中单独保留。\n", "utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    command = parser.add_subparsers(dest="command", required=True)
    validate_parser = command.add_parser("validate", help="校验 vsc.remotion-render-plan/v1")
    validate_parser.add_argument("plan")
    scaffold_parser = command.add_parser("scaffold", help="生成本地可编辑 Remotion 项目，不安装依赖")
    scaffold_parser.add_argument("plan")
    scaffold_parser.add_argument("output")
    args = parser.parse_args()
    try:
        plan = load_plan(args.plan)
        errors = validate(plan)
        if errors:
            for error in errors:
                print(f"INVALID: {error}", file=sys.stderr)
            raise SystemExit(1)
        if args.command == "validate":
            print(f"VALID: {plan['composition']['id']}  {len(plan['segments'])} segments")
            return
        scaffold(plan, args.output)
        print(f"SCAFFOLDED: {Path(args.output)}")
    except ValueError as exc:
        die(str(exc))


if __name__ == "__main__":
    main()
