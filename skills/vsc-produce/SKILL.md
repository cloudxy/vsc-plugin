---
name: vsc-produce
description: "Plan and review provider-neutral image, image-to-video and audio take production from approved VSC specifications."
---

# VSC 制作

只根据已批准的 ShotPlan、AssetBible、声音方案和项目策略生产候选 take。每个任务记录输入版本、参考资产、适配器、参数摘要、预算、输出路径和连续性检查；图像、视频、音频候选都不是自动选中版本。供应商 API、密钥、收费、许可和平台策略由适配器及项目策略负责；本技能不假设任何一家模型存在。

按[上游 Skill 用法](../vsc-vendor/SKILL.md#下载后直接使用-skill)解析 `produce` 阶段；除运行环境外，项目授权也须就绪才调用生成工作流。未就绪时保留为可选能力，不伪造供应商调用或生成结果。
