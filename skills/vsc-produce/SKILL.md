---
name: vsc-produce
description: "Plan and review provider-neutral image, image-to-video and audio take production from approved VSC specifications."
---

# VSC 制作

只根据已批准的 ShotPlan、AssetBible、声音方案和项目策略生产候选 take；图像、视频、音频候选都不是自动选中版本。

逐镜锚定，不用全片共用一段描述：生成前用 `python3 -B scripts/consistency.py anchors <镜头> --bible <资产库> --state <状态时间线> --text` 取该镜的身份与状态，再改写成供应商提示词，并优先喂入锚点包里的参考素材和上一镜出点帧。每个任务写一份 `vsc.generation-record/v1`（从 `templates/generation-record.json` 起步），用 `anchors_sha256` 绑定所用锚点包；参考图被平台拒绝时如实记录。生成后运行 `consistency.py check … --record <记录>`：锚点过期、参考素材不属于本镜、首帧不是取自上一镜都会报出，人物只靠文字锚定会提醒。供应商 API、密钥、收费、许可和平台策略由适配器及项目策略负责；本技能不假设任何一家模型存在。

按[上游 Skill 用法](../vsc-vendor/SKILL.md#下载后直接使用-skill)解析 `produce` 阶段；除运行环境外，项目授权也须就绪才调用生成工作流。未就绪时保留为可选能力，不伪造供应商调用或生成结果。
