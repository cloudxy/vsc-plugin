---
name: vsc-sound
description: "Use when VSC needs scene-aware BGM, ambience, dialogue space, sound bridges, J/L cuts, cue sheets, or audio continuity across generated clips."
---

# VSC 音乐与声音叙事

先写声音提示表，再找/生成音乐。每个场景按“观众此刻应感到什么、角色不知道什么、信息何时转向”建立情绪曲线；每个 Cue 要有叙事功能、情绪、强度 0–5、音色/节奏方向、进出方式、可控 stem/混音层、环境底、对白避让和使用权。

先运行 `python3 scripts/vendor_skills.py --resolve sound`。已安装的 OpenMontage 音乐到视频、TTS、音乐原始 Skill 可直接复用；先确认其 HyperFrames、音频依赖或供应商环境，再按原始 Skill 的工作流执行。其输出必须回填本技能的声音提示表与使用权字段。

不要按 6–8 秒视频片段重启 BGM。把 BGM 和环境底按场景/段落做成连续音轨，在剪辑时间线中跨镜铺设；边界按需要使用：

- `J_cut`：下一场的声音先出现，制造预期或引入地点；
- `L_cut`：上一场的脚步、雨声、呼吸或台词尾音延续，维持情绪；
- `crossfade`：用于相近声场/音乐层的平滑交接；
- `sound_bridge`：用雨声、门响、车流、电话震动、音乐 stinger 等把画面切换变成叙事动作；
- `intentional_silence`：明确写出留白的目的，而不是误把漏音当成设计。

将计划保存为 `vsc.sound-cue-sheet/v1`，运行：

```bash
python3 scripts/vsc_state.py sound validate ./07-后期/声音提示表.json
```

音频生成或延长不应承担对白真伪、音乐版权或场景连续性的全部责任。将对白、BGM、环境声和 SFX 分轨保存；每个音频资产都写使用权、版本、时码和最终选择人。
