---
name: vsc-post
description: "Edit VSC takes into a timeline with sound, music, subtitles, review and delivery artifacts."
---

# VSC 后期

在时间线中表达真正的剪切、转场、对白、音效、BGM、字幕、调色与混音，而不是把多个片段伪装成一条连续镜头。审片分开检查：叙事理解、人物/空间/声音连续性、技术交付和素材用途。问题优先退回造成问题的最早阶段；交付清单必须列明选中的版本、规格、授权范围与责任人的最终决定。

先运行 `python3 scripts/vendor_skills.py --resolve post`。若本机具备 `ffmpeg`，直接读取并执行已安装的 OpenMontage `video-edit`/`ffmpeg` Skill；视频理解 Skill 仅在其供应商环境就绪后调用。所有上游命令仍以 VSC 已批准的时间线、文件路径和输出规格为准。

BGM 和环境底按场景/情绪段落跨镜铺设，不按每个生成视频重启。与 `/vsc-sound` 共同维护 `vsc.sound-cue-sheet/v1`，为每个边界写 J/L cut、crossfade、声音桥或刻意静音，并在导出前运行 `sound validate`。
