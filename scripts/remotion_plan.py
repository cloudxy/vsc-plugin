#!/usr/bin/env python3
"""Validate a VSC Remotion render plan and scaffold a local, editable Remotion project.

The scaffold contains VSC-authored glue only. It references media that the user stages in public/;
it never copies Remotion source code or installs npm dependencies.
"""
import argparse
import json
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


def validate(plan):
    errors = []
    if plan.get("format") != FORMAT:
        errors.append(f"format 必须为 {FORMAT}")
    if not text(plan.get("project_id")):
        errors.append("project_id 必须是非空字符串")
    composition = plan.get("composition")
    if not isinstance(composition, dict):
        return errors + ["composition 必须是 object"]
    if not isinstance(composition.get("id"), str) or not COMPOSITION_ID.fullmatch(composition["id"]):
        errors.append("composition.id 只能包含字母、数字和连字符")
    for key in ("width", "height", "fps", "duration_in_frames"):
        value = composition.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            errors.append(f"composition.{key} 必须是正整数")
    segments = plan.get("segments")
    if not isinstance(segments, list) or not segments:
        return errors + ["segments 必须是非空数组"]
    duration = composition.get("duration_in_frames", 0)
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
            if not text(source) or Path(source).is_absolute() or ".." in Path(source).parts:
                errors.append(f"{label}.source 必须是 public/ 下的安全相对路径")
        if kind in {"video", "image"}:
            visual_seen = True
            if not text(segment.get("source_shot_id")):
                errors.append(f"{label}.source_shot_id 必须回指 VSC 镜头")
        if kind in {"caption", "text"} and not text(segment.get("text")):
            errors.append(f"{label}.text 必须是非空字符串")
        fade = segment.get("fade_in_frames", 0)
        if not nonnegative_int(fade) or (nonnegative_int(segment.get("duration_in_frames")) and fade > segment["duration_in_frames"]):
            errors.append(f"{label}.fade_in_frames 必须在片段时长范围内")
    if not visual_seen:
        errors.append("至少需要一个 video 或 image 片段")
    return errors


def die(message):
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def plan_module(plan):
    return "export const plan = " + json.dumps(plan, ensure_ascii=False, indent=2) + " as const;\n"


ROOT_TSX = """import {Composition} from 'remotion';
import {ShortDrama} from './ShortDrama';
import {plan} from './plan';

export const Root: React.FC = () => (
  <Composition
    id={plan.composition.id}
    component={ShortDrama}
    durationInFrames={plan.composition.duration_in_frames}
    fps={plan.composition.fps}
    width={plan.composition.width}
    height={plan.composition.height}
    defaultProps={{plan}}
  />
);
"""

VIDEO_TSX = """import {AbsoluteFill, Img, Sequence, interpolate, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {Audio, Video} from '@remotion/media';
import {plan as defaultPlan} from './plan';

type Segment = (typeof defaultPlan.segments)[number];
const mediaStyle: React.CSSProperties = {width: '100%', height: '100%', objectFit: 'cover'};

const TextLayer: React.FC<{text: string}> = ({text}) => (
  <AbsoluteFill style={{alignItems: 'center', justifyContent: 'flex-end', padding: 72, color: 'white', fontSize: 42, fontWeight: 700, textAlign: 'center', textShadow: '0 2px 8px black'}}>
    <div>{text}</div>
  </AbsoluteFill>
);

const Visual: React.FC<{segment: Segment}> = ({segment}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const fade = 'fade_in_frames' in segment ? (segment.fade_in_frames ?? 0) : 0;
  const opacity = fade > 0 ? interpolate(frame, [0, fade], [0, 1], {extrapolateRight: 'clamp'}) : 1;
  const style = {...mediaStyle, opacity};
  if (segment.kind === 'video') return <Video src={staticFile(segment.source)} premountFor={fps} style={style} />;
  if (segment.kind === 'image') return <Img src={staticFile(segment.source)} style={style} />;
  return null;
};

export const ShortDrama: React.FC<{plan?: typeof defaultPlan}> = ({plan = defaultPlan}) => (
  <AbsoluteFill style={{backgroundColor: 'black'}}>
    {plan.segments.map((segment) => (
      <Sequence key={segment.id} from={segment.from_frame} durationInFrames={segment.duration_in_frames} premountFor={plan.composition.fps}>
        {segment.kind === 'video' || segment.kind === 'image' ? <Visual segment={segment} /> : null}
        {segment.kind === 'audio' ? <Audio src={staticFile(segment.source)} premountFor={plan.composition.fps} /> : null}
        {segment.kind === 'caption' || segment.kind === 'text' ? <TextLayer text={segment.text} /> : null}
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
        "scripts": {"studio": "remotion studio src/index.ts", "render": "remotion render src/index.ts"},
        "dependencies": {"@remotion/media": REMOTION_VERSION, "remotion": REMOTION_VERSION, "react": "^19.0.0", "react-dom": "^19.0.0"},
        "devDependencies": {"@types/react": "^19.0.0", "@types/react-dom": "^19.0.0", "typescript": "^5.0.0"},
    }
    (destination / "package.json").write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", "utf-8")
    (destination / "src" / "index.ts").write_text(INDEX_TS, "utf-8")
    (destination / "src" / "Root.tsx").write_text(ROOT_TSX, "utf-8")
    (destination / "src" / "ShortDrama.tsx").write_text(VIDEO_TSX, "utf-8")
    (destination / "src" / "plan.ts").write_text(plan_module(plan), "utf-8")
    (destination / "public" / "README.md").write_text("将计划中 source 指向的媒体按相同相对路径放入此目录。例如 takes/SH-001.mp4 对应 public/takes/SH-001.mp4。\n", "utf-8")
    (destination / "README.md").write_text("# VSC Remotion 项目\n\n1. 将选定 take、音频和其他素材放到 `public/`。\n2. `npm install`\n3. `npm run studio` 预览并由负责人确认。\n4. `npm run render -- <composition-id> out/final.mp4` 导出。\n\n此项目由 VSC 计划生成；上游 Remotion Skill 在 vendor/remotion 中单独保留。\n", "utf-8")


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
