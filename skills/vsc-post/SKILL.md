---
name: vsc-post
description: "Edit VSC takes into a timeline with sound, music, subtitles, review and delivery artifacts."
---

# VSC 后期

切点、反应或声音连接需要实例时，按[固定读取](../vsc/references/method-practice.md)选[声画节奏练习](references/sound-picture-rhythm.md)，同素材一次改一个接点并正常速度听看；有意硬切可保留，确定性剪辑不先重生成。

修改意见按[说明与真实预览的同题对比](references/sound-picture-rhythm.md#edit-result)返回可播放结果及变化位置，检查真实用料、保留项和非目标副作用；有工程需求时交可打开的实际工程。只有计划、脚手架或完成说明时保持待制作，合格候选、用户采用和最终交付按[原成果口径](../vsc/references/review-and-feedback.md#effective-result)分别记录。

按[可用区间与定向复核](../vsc/references/creative-production.md)滚动完成局部粗剪，优先检查动作／反应覆盖、节奏和声音接点。局部缺陷先比较保留区间、裁切、合成、替换、调整剪辑与重生；用 `scripts/production/quality.py check` 汇总区间并集及分单位成本、主动工时与等待。未知审美不得写通过；审查复用仍需现行批准与依赖检查。

在时间线中表达真正的剪切、转场、对白、音效、BGM、字幕、调色与混音，而不是把多个片段伪装成一条连续镜头。审片分开检查：叙事理解、人物/空间/声音连续性、技术交付和素材用途。问题优先退回造成问题的最早阶段；交付清单必须列明选中的版本、规格、授权范围与责任人的最终决定。

按[上游 Skill 用法](../vsc-vendor/SKILL.md#下载后直接使用-skill)解析 `post` 阶段；所有上游命令仍以 VSC 已批准的时间线、文件路径和输出规格为准。

BGM 和环境底按场景/情绪段落跨镜铺设，不按每个生成视频重启。与 `/vsc-sound` 共同维护 `vsc.sound-cue-sheet/v1`，为每个边界写 J/L cut、crossfade、声音桥或刻意静音，并在导出前运行 `sound validate`。

后期工具（用法与边界见各自的 `--help`）：

- 剪辑师要在剪映中精剪：`scripts/post/jianying.py` 把 `vsc.remotion-render-plan/v1` 写成剪映多轨草稿，并列出无法迁移的项。
- 出带字幕的版本：`scripts/post/subtitle_burn.py` 把已批准的 SRT 烧进视频；加 `--bible` 使用资产库的全片字幕样式。对白字幕先按真实语音停顿定时，一屏至多两行；超长对白拆成多个有实测时码的 Cue。烧录后抽查最长 Cue、含标点 Cue 和换镜前后的画面，确认标点位置、断行及遮挡，再登记候选成片。不要另写项目内的固定字数断行和临时字体烧录脚本。
- 交付前核对响度：`scripts/media/qa.py check` 的 `--loudness-target` 按发布平台规范填写。

需要把已批准时间线做成可编辑预演或确定性成片时，交给 `/vsc-remotion`。它直接复用本机 Remotion 官方 Skill，并将 VSC 时间线编译为可校验的 `vsc.remotion-render-plan/v1`；不要在本技能中绕过预览与人工导出决定。

## 制作交接 v2

新规则时间线绑定获选媒体 SHA、用途与声音 Cue，混音交付独立索引。正式 QA 完整解码并复检音频区间与固定响度目标；完整结构化审片绑定 render SHA 和 delivery ID。交付包迁移后重新检查媒体，不能借旧本机路径报告过关。

规则见 [制作协议](../../workflow/production-v2.md)，操作见 [v2 指南](../../docs/guide/production-v2.md)。
