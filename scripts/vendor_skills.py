#!/usr/bin/env python3
"""发现并路由已安装在 vendor/ 的上游 Skill。

此脚本不下载、不复制上游 Skill。--scan 生成仅存本机的 vendor/skill-catalog.json；
--resolve 为 VSC 创作阶段列出可直接阅读和使用的 Skill 原文，以及需要额外运行环境的 Skill。
"""
import argparse
import json
from pathlib import Path

from vsc_kernel import vendor_skill_stages

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor"
CATALOG = VENDOR / "skill-catalog.json"
# 创作阶段名称由 workflow/kernel.json 定义；Vendor 只维护各阶段的上游 Skill 映射。
STAGES = vendor_skill_stages()

# This is a small, explicit route table. It references upstream files in vendor/, never copies them.
ROUTES = {
    "adapt": (
        ("inkos", "packages/core/skills/inkos-script-writing/SKILL.md", "guide", "将小说叙述外化为可演动作、冲突与转折。"),
        ("inkos", "packages/core/skills/inkos-story-review/SKILL.md", "guide", "检查故事因果、人物动机和改编问题。"),
        ("openwrite", "presets/openwrite/skills/novel-reviewer/SKILL.md", "runtime: openwrite-bridge", "调用 OpenWrite 原生小说评审工具。"),
    ),
    "script": (
        ("inkos", "packages/core/skills/inkos-script-writing/SKILL.md", "guide", "编写可表演、可拍摄的短剧场次。"),
        ("openwrite", "presets/openwrite/skills/dialoguequality/SKILL.md", "guide", "分析角色对白指纹与 AI 味问题。"),
        ("openwrite", "presets/openwrite/skills/novel-creator/SKILL.md", "runtime: openwrite-bridge", "调用 OpenWrite 原生章节创作工作流。"),
    ),
    "direct": (
        ("inkos", "packages/core/skills/inkos-storyboard/SKILL.md", "guide", "把叙事节拍拆成可拍、可画、可生图的分镜。"),
        ("inkos", "packages/core/skills/inkos-interactive-film/SKILL.md", "guide", "为互动/分支叙事提供镜头组织方法。"),
    ),
    "assets": (
        ("inkos", "packages/core/skills/inkos-play-illustration/SKILL.md", "guide", "建立戏剧插画、角色与场景的视觉表达。"),
        ("openmontage", ".agents/skills/character-animation-qa/SKILL.md", "guide", "检查角色动画和动作表现。"),
    ),
    "produce": (
        ("openmontage", ".agents/skills/create-video/SKILL.md", "runtime: HeyGen MCP or HEYGEN_API_KEY", "调用文本到视频的上游生成工作流。"),
        ("openmontage", ".agents/skills/kling-official/SKILL.md", "runtime: Kling credentials/tools", "调用 Kling 相关视频生成工作流。"),
        ("openmontage", ".agents/skills/video-understand/SKILL.md", "runtime: provider credentials/tools", "分析生成候选与素材视频。"),
        ("moneyprinterturbo", "docs/skill/SKILL.md", "runtime: uv; user-selected quick mode", "用户显式选择的一键成片模式：由主题直接出片，跳过 VSC 批准链，成片只作候选或参考。"),
    ),
    "sound": (
        ("openmontage", ".agents/skills/music-to-video/SKILL.md", "runtime: HyperFrames, Python audio dependencies", "按音乐节拍组织画面与剪辑。"),
        ("openmontage", ".agents/skills/text-to-speech/SKILL.md", "runtime: configured TTS provider", "生成或组织对白语音。"),
        ("openmontage", ".agents/skills/music/SKILL.md", "runtime: configured music provider", "生成或组织 BGM。"),
    ),
    "post": (
        ("openmontage", ".agents/skills/video-edit/SKILL.md", "runtime: ffmpeg", "剪切、拼接、转码、替换音轨与导出。"),
        ("openmontage", ".agents/skills/ffmpeg/SKILL.md", "runtime: ffmpeg", "使用 ffmpeg/ffprobe 做媒体检查和处理。"),
        ("openmontage", ".agents/skills/video-understand/SKILL.md", "runtime: provider credentials/tools", "复核候选片段与成片。"),
        ("remotion", "packages/skills/skills/remotion-best-practices/SKILL.md", "guide", "路由 Composition、预览、渲染与字幕的 Remotion 官方方法。"),
        ("remotion", "packages/skills/skills/remotion-markup/SKILL.md", "guide", "以帧驱动的 React 时间线、媒体、动画和可编辑场景。"),
        ("remotion", "packages/skills/skills/remotion-captions/SKILL.md", "guide", "字幕 JSON、转写、显示与导出。"),
        ("remotion", "packages/skills/skills/remotion-studio/SKILL.md", "runtime: Node.js, npm dependencies", "启动 Remotion Studio 预览并允许人工调整。"),
        ("remotion", "packages/skills/skills/remotion-render/SKILL.md", "runtime: Node.js, npm dependencies", "将已批准 Composition 导出为视频或静帧。"),
    ),
    "architecture": (
        ("mattpocock-skills", "skills/engineering/improve-codebase-architecture/SKILL.md", "guide", "发现模块深度、接缝、可测试性与 AI 可导航性的架构摩擦。"),
        ("mattpocock-skills", "skills/engineering/codebase-design/SKILL.md", "guide", "提供模块、接口、深度、接缝、适配器、杠杆和局部性的共享词汇。"),
        ("mattpocock-skills", "skills/productivity/grilling/SKILL.md", "guide", "在选定架构候选后澄清约束和设计取舍。"),
        ("mattpocock-skills", "skills/engineering/domain-modeling/SKILL.md", "guide", "维护 VSC 术语表和 ADR，使架构决定可追溯。"),
    ),
}


def frontmatter(path):
    """Read the small YAML front matter we need without adding a YAML dependency."""
    try:
        lines = path.read_text("utf-8").splitlines()
    except UnicodeDecodeError:
        return {}
    if not lines or lines[0].strip() != "---":
        return {}
    values = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" not in line or line.startswith((" ", "\t")):
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def safe_skill_path(source_id, relative_path, vendor_root=VENDOR):
    vendor_root = vendor_root.resolve()
    source_root = (vendor_root / source_id).resolve()
    candidate = (source_root / relative_path).resolve()
    if source_root not in candidate.parents:
        raise ValueError(f"非法 Skill 路径：{source_id}/{relative_path}")
    return candidate


def discover(vendor_root=VENDOR):
    vendor_root = vendor_root.resolve()
    records = []
    if not vendor_root.is_dir():
        return records
    for source_root in sorted(path for path in vendor_root.iterdir() if path.is_dir() and not path.name.startswith(".")):
        for skill_path in sorted(source_root.rglob("SKILL.md")):
            if ".git" in skill_path.parts:
                continue
            meta = frontmatter(skill_path)
            records.append({
                "source_id": source_root.name,
                "name": meta.get("name", skill_path.parent.name),
                "description": meta.get("description", ""),
                "relative_path": skill_path.relative_to(vendor_root).as_posix(),
            })
    return records


def resolve(stage, vendor_root=VENDOR):
    vendor_root = vendor_root.resolve()
    if stage not in ROUTES:
        raise ValueError("未知阶段：" + stage)
    records = []
    for source_id, relative_path, readiness, purpose in ROUTES[stage]:
        skill_path = safe_skill_path(source_id, relative_path, vendor_root)
        meta = frontmatter(skill_path) if skill_path.is_file() else {}
        records.append({
            "stage": stage,
            "source_id": source_id,
            "name": meta.get("name", Path(relative_path).parent.name),
            "description": meta.get("description", ""),
            "relative_path": skill_path.relative_to(vendor_root).as_posix() if skill_path.is_file() else f"{source_id}/{relative_path}",
            "readiness": readiness if skill_path.is_file() else "missing: install source",
            "purpose": purpose,
        })
    return records


def print_records(records):
    for record in records:
        print(f"{record['readiness'].upper():<48} {record['source_id']}/{record['name']}")
        print(f"  {record['relative_path']}")
        if record.get("purpose"):
            print(f"  {record['purpose']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--scan", action="store_true", help="扫描 vendor/ 中全部 SKILL.md 并写入本机目录")
    mode.add_argument("--resolve", choices=STAGES, metavar="STAGE", help="列出某 VSC 阶段应直接使用的上游 Skill")
    mode.add_argument("--list", action="store_true", help="列出已发现的全部上游 Skill")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出（--scan 仍会写本机目录）")
    args = parser.parse_args()

    if args.scan:
        records = discover()
        CATALOG.write_text(json.dumps({"schema_version": 1, "skills": records}, ensure_ascii=False, indent=2) + "\n", "utf-8")
        result = {"catalog": CATALOG.relative_to(ROOT).as_posix(), "count": len(records), "skills": records}
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"SCANNED {len(records)} 个 Skill → {result['catalog']}")
        return

    records = resolve(args.resolve) if args.resolve else discover()
    if args.json:
        print(json.dumps(records, ensure_ascii=False, indent=2))
    else:
        print_records(records)


if __name__ == "__main__":
    main()
