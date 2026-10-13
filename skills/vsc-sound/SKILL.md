---
name: vsc-sound
description: "Use when VSC needs scene-aware BGM, ambience, dialogue space, sound bridges, J/L cuts, cue sheets, or audio continuity across generated clips."
---

# VSC 音乐与声音叙事

设计前检索素材库的 voice、ambience、sfx、music，复用既有声线与声场；需要声音桥方法时查询 `scripts/vsc_craft.py search <需求> --stage sound`。操作见[素材复用与检索](../../docs/guide/reuse-and-search.md)。

先写声音提示表，再找/生成音乐。每个场景按“观众此刻应感到什么、角色不知道什么、信息何时转向”建立情绪曲线；每个 Cue 要有叙事功能、情绪、强度 0–5、音色/节奏方向、进出方式、可控 stem/混音层、环境底、对白避让和使用权。

按[上游 Skill 用法](../vsc-vendor/SKILL.md#下载后直接使用-skill)解析 `sound` 阶段；其输出必须回填本技能的声音提示表与使用权字段。

不要按 6–8 秒视频片段重启 BGM。把 BGM 和环境底按场景/段落做成连续音轨，在剪辑时间线中跨镜铺设；边界按需要使用：

- `J_cut`：下一场的声音先出现，制造预期或引入地点；
- `L_cut`：上一场的脚步、雨声、呼吸或台词尾音延续，维持情绪；
- `crossfade`：用于相近声场/音乐层的平滑交接；
- `sound_bridge`：用雨声、门响、车流、电话震动、音乐 stinger 等把画面切换变成叙事动作；
- `intentional_silence`：明确写出留白的目的，而不是误把漏音当成设计。

将计划保存为 `vsc.sound-cue-sheet/v1`，运行：

```bash
python3 scripts/vsc_kernel.py contract validate vsc.sound-cue-sheet/v1 ./07-后期/声音提示表.json
```

预演需要临时对白时，用 `scripts/temp_voice.py` 为已批准剧本的台词生成临时配音与字幕；输入格式、输出位置和用途限制见其 `--help`。台词用 `speaker` 指向资产库人物并加 `--bible`，同一人物全片使用同一音色。正式对白须使用有授权的配音或演员录音。

已有可选声音入口：`scripts/doubao_speech.py synthesize`（默认走统一 Agent Plan key 的 `--service agent-plan` 路由） 按供应商 speaker 生成对白／声音参考并支持情绪 context，可用 `--entity/--bible` 核对人物绑定；`scripts/doubao_audio.py generate` 经 MediaKit 生成 music/ambience/sfx 候选。两者默认 dry run，显式 `--execute` 才可能付费，须给出 `--max-chars`；Seed-Audio 的 `--max-polls` 只限制本轮查询次数，“约十秒”等提示词不能保证实际时长，不提供自动分轨或人声分离。

制作前运行 `python3 -B scripts/vsc_toolchain.py --project <作品目录> --json`，分别核对实现、凭证配置与当前作品候选证据。诊断不探测网络权限、不进行审听或批准。TTS 与 Seed-Audio 默认读 `ARK_AGENT_PLAN_API_KEY`（找不到时提示配置火山方舟 Agent 版本的 API Key）；可用 `--key-env <环境变量名>` 显式选择其他 key，不能由方舟图像／视频可用推定声音权限。2026-10-11 当前语音音色列表探测为 HTTP 401，MediaKit key 未配置，尚无成功豆包声音实测。

离线声音可用 `scripts/procedural_audio.py --preset wind|rain|cloth|footsteps|ceramic|bell|music_pad`，固定 seed 和参数可复现。它不使用豆包模型或外部采样，输出仍需按 Cue 的叙事功能、对白空间和声音接点试听。所有声音候选写 `kind=audio`、`purpose=asset` 的生成记录，人工确认后用 `vsc_library.py promote/use` 复用并保留来源与授权。使用说明见[生成适配器边界](../../docs/architecture/generation-adapters.md)、[豆包语音](../../docs/architecture/doubao-speech.md)和[Seed-Audio](../../docs/architecture/doubao-audio.md)。

图像／视频可用[批量生产队列](../../docs/guide/production-batch.md)按 plan hash 执行，但当前队列不包含声音任务；声音按场景／段落生产后由剪辑阶段放入独立音轨。

音频生成或延长不应承担对白真伪、音乐版权或场景连续性的全部责任。将对白、BGM、环境声和 SFX 分轨保存；每个音频资产都写使用权、版本、时码和最终选择人。

## 制作交接 v2

新规则对白 Cue 回指固定剧本行 ID、表演及口型用途；候选记录实测时长。mix 对照 timeline 检查实际 Cue 覆盖和 J/L cut。原生音画须具名人工审听/口型复核，不用 AI 推断替代。

规则见 [制作协议](../../workflow/production-v2.md)，操作见 [v2 指南](../../docs/guide/production-v2.md)。
