---
name: vsc-direct
description: "Turn approved scripts into VSC shot plans, camera movement, transitions and animatics."
---

# VSC 导演与分镜

镜头不是提示词列表。每镜写叙事目的、景别、机位、构图、运镜、人物站位与动作、光线、声音、转场、时长和参考资产；运镜必须服务信息、情绪或动作，不为炫技。先做带临时对白、音效和音乐节拍的预演；叙事不清时退回剧本/改编，技术不可行时退回镜头或资产设计。

所有要连接的 AI 片段还必须由 `/vsc-continuity` 建立 `vsc.continuity-plan/v1`：镜头入点/出点状态、稳定 reference、剪辑手柄和桥接策略。不要把一场戏硬塞进一个生成片段，或把不一致的片段交给后期“无缝修复”。
