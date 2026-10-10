---
name: vsc-post
description: "Edit VSC takes into a timeline with sound, music, subtitles, review and delivery artifacts."
---

# VSC 后期

在时间线中表达真正的剪切、转场、对白、音效、BGM、字幕、调色与混音，而不是把多个片段伪装成一条连续镜头。审片分开检查：叙事理解、人物/空间/声音连续性、技术交付和素材用途。问题优先退回造成问题的最早阶段；交付清单必须列明选中的版本、规格、授权范围与责任人的最终决定。

按[上游 Skill 用法](../vsc-vendor/SKILL.md#下载后直接使用-skill)解析 `post` 阶段；所有上游命令仍以 VSC 已批准的时间线、文件路径和输出规格为准。

BGM 和环境底按场景/情绪段落跨镜铺设，不按每个生成视频重启。与 `/vsc-sound` 共同维护 `vsc.sound-cue-sheet/v1`，为每个边界写 J/L cut、crossfade、声音桥或刻意静音，并在导出前运行 `sound validate`。

后期工具（用法与边界见各自的 `--help`）：

- 剪辑师要在剪映中精剪：`scripts/jianying_export.py` 把 `vsc.remotion-render-plan/v1` 写成剪映多轨草稿，并列出无法迁移的项。
- 出带字幕的版本：`scripts/subtitle_burn.py` 把已批准的 SRT 烧进视频，默认字体 Noto Sans SC。
- 交付前核对响度：`scripts/media_qa.py check` 的 `--loudness-target` 按发布平台规范填写。

需要把已批准时间线做成可编辑预演或确定性成片时，交给 `/vsc-remotion`。它直接复用本机 Remotion 官方 Skill，并将 VSC 时间线编译为可校验的 `vsc.remotion-render-plan/v1`；不要在本技能中绕过预览与人工导出决定。
