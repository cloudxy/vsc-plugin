---
name: vsc-direct
description: "Turn approved scripts into VSC shot plans, camera movement, transitions and animatics."
---

# VSC 导演与分镜

需要运镜、构图、视觉或表演方法时，用 `scripts/knowledge/craft.py search <需求> --stage direct` 找依据，再用 `show` 阅读步骤、限制与来源。将选择落入本片镜头规格；用法见[素材复用与检索](../../docs/guide/reuse-and-search.md)。

镜头不是提示词列表。每镜写叙事目的、景别、机位、构图、运镜、人物站位与动作、光线、声音、转场、时长和参考资产；运镜必须服务信息、情绪或动作，不为炫技。先做带临时对白、音效和音乐节拍的预演；叙事不清时退回剧本/改编，技术不可行时退回镜头或资产设计。

依[专业拆解与返工控制](../vsc/references/creative-production.md)区分相机运动、主体运动与剪辑变化；落实站位、路径、遮挡、轴线、视线、道具交接与接触反馈。剧情、意象、纪实分别按表达功能设计覆盖，提前写采用区间与剪辑手柄。节奏预演与代表性生成试片证明不同问题，未实测的控制精度保持未知。

按[上游 Skill 用法](../vsc-vendor/SKILL.md#下载后直接使用-skill)解析 `direct` 阶段，把镜头方法落为 VSC ShotPlan；不要只复制提示词或让上游 Skill 取代 VSC 的连续性契约。

所有要连接的 AI 片段还必须由 `/vsc-continuity` 建立 `vsc.continuity-plan/v1`：镜头入点/出点状态、稳定 reference、剪辑手柄和桥接策略。不要把一场戏硬塞进一个生成片段，或把不一致的片段交给后期“无缝修复”。

## 制作交接 v2

新规则在 design 提交覆盖计划，逐场枚举 sequence、镜头、剧本单元及声音计划固定版本；遗漏绑定真实 omission 决定。animatic 必须可播放，临时声音与未决项明确列出。

规则见 [制作协议](../../workflow/production-v2.md)，操作见 [v2 指南](../../docs/guide/production-v2.md)。

## 设计与生成追溯

按[分镜与资源工作区](../../docs/guide/source-resource-workspace.md)区分设计单元、有序面板、镜头和生成尝试。固定产物中的 `design_units` 明确镜头、用途和主用／备选关系；需要的剧本行必须引用同项目的固定行和依赖版本。设计修订追加版本，生成沿现有任务／候选／选择流程，不以最新分镜替换历史任务的固定输入。
