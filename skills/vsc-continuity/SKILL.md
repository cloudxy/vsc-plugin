---
name: vsc-continuity
description: "Use when VSC needs to preserve character, scene, action, camera, lighting or audio continuity across short AI-generated video clips, or diagnose a broken cut."
---

# VSC 连续性

不要把两个 AI 视频文件直接相连。先为每个镜头写**入点状态**和**出点状态**：场次、地点、时间/天气、人物身份/服装/道具/姿势/视线、屏幕方向、景别/机位/运镜、光线、环境声。每镜还要绑定稳定角色/场景参考资产，并预留 head/tail 手柄。

在每个边界选一种有叙事理由的策略：

- `match_action`／`match_frame`：出入点明确保持的状态字段必须相等；
- `cutaway`／`reaction_hold`：用信息性插镜或反应镜跨越生成差异；
- `occlusion`／`whip_pan`：以遮挡或快速运动隐藏边界，仍需保留方向和声音；
- `hard_cut`／`scene_cut`：只在信息、时间或空间确实发生跳变时使用，并写清目的。

对 6–8 秒片段，优先生成一个动作/信息单元，而非硬把完整场景塞进一段。下一镜的入点应以当前出点的末帧、参考资产和同一状态契约为依据；若无法稳定接上，先增加反应镜、手部/道具特写、环境插镜或声音桥，而不是反复要求模型“无缝”。

同场各镜的状态不要逐镜手写：每场戏写一份基线，每个镜头只写本镜内发生的变化，保存为 `vsc.scene-state/v1`（模板 `templates/scene-state.json`）。连续性计划的人物键使用资产库 ID、`costume_id` 使用变体名，再用 `python3 -B scripts/consistency.py check --bible <资产库> --state <状态时间线> --continuity <连续性计划>` 核对三者一致。

将 JSON 计划保存为 `vsc.continuity-plan/v1`，运行：

```bash
python3 scripts/vsc_kernel.py contract validate vsc.continuity-plan/v1 ./05-预演/连续性计划.json
```

结构通过不代表画面已通过。必须人工核对：人物身份、服装/道具、左右方向、动作接点、镜头运动、空间地理、天气/光色、帧率/画幅、环境底与对白进出；失败应退回角色资产、场景资产、ShotPlan 或生成 take 的最早根因。
