---
name: vsc-produce
description: "Plan and review provider-neutral image, image-to-video and audio take production from approved VSC specifications."
---

# VSC 制作

只根据已批准的 ShotPlan、AssetBible、声音方案和项目策略生产候选 take；图像、视频、音频候选都不是自动选中版本。

同一个人物或物件，从文字生成两次就会长得不一样。所以画面按“资产图 → 关键帧 → 视频”三段生产，文字只在第一段描述外观：

先用 `scripts/vsc_library.py search` 查已有素材，确认变体与权属后 `use` 绑定本项目；确需新建才生成。操作见[素材复用与检索](../../docs/guide/reuse-and-search.md)。

1. **资产图**：每个人物、地点和关键道具只生成一次规范图（生成记录 `purpose: asset`，不属于任何镜头）。人工确认后登记为资产库中对应实体的参考素材，此后所有画面都以它为参考。
2. **关键帧**：按状态时间线，为每镜生成入点帧和出点帧。输入是在场实体的资产图，加上 `python3 -B scripts/consistency.py anchors <镜头> --bible <资产库> --state <状态时间线> --text --moment entry|exit` 给出的那一时刻的状态。图像记录写 `shot_id` 和 `inputs.moment`。
   - 相邻镜头共用交界帧：上一镜的出点帧就是下一镜的入点帧，不另外生成。
   - 镜内状态有变化时，以上一张关键帧为底图编辑，只改变化的部分，记作 `inputs.base_frame`（`use: edit`）；只作参考时记 `use: reference`。
   - 关键帧经人工或视觉检查后才能进入视频。人数、道具数量和位置的错误会原样带进视频。
3. **视频**：首尾帧加文字生成。文字只写动作、台词和声音，外观以首尾帧为准。视频记录的 `first_frame` 和 `last_frame` 写入两帧的 SHA。
   - 供应商返回实际尾帧时登记为 `outputs[].role=last_frame`，可原样用于下一镜。参考模式中“从图片1开始”是文字要求，须核对实际首帧，不能等同于硬约束。

每个生成任务写一份 `vsc.generation-record/v1`（从 `templates/generation-record.json` 起步），用 `anchors_sha256` 绑定所用锚点包；参考图被平台拒绝时如实记录。生成后，把资产图、关键帧和视频的全部记录一起交给 `consistency.py check … --record <记录> …`。它会报告以下问题：

- 锚点已过期；
- 参考素材不属于本镜；
- 首帧不是取自上一镜；
- 视频首尾帧不是本镜的入点帧或出点帧；
- 相邻两镜的视频交界帧不是同一张图。

它还会提醒三种情况：资产图没有登记进资产库；帧追溯不到关键帧记录；人物既没用参考素材，也没用由资产图生成的关键帧。

可选豆包工具 `scripts/volc_ark.py` 已提供图像、视频与视觉检查；先 dry run 核对视频请求，再在已有预算范围内提交。视觉提醒写 `vsc.visual-check/v1`，不能取代人工选择。供应商 API、密钥、收费、许可和平台策略由适配器及项目策略负责；配置、实测与限制见[生成适配器边界](../../docs/architecture/generation-adapters.md)。

制作前运行 `python3 -B scripts/vsc_toolchain.py --project <作品目录> --json`。实现存在、默认凭证变量存在、当前作品有有效候选与人工已审阅分别看；该诊断不联网核验权限，`configured=true` 不能当作供应商可用或批准。

声音按已批准声音方案另行制作：`scripts/doubao_speech.py synthesize` 提供固定 speaker 和情绪 context，`scripts/doubao_audio.py generate` 经 MediaKit 生成音乐／环境／音效候选。语音专属套餐 key 须显式 `--service agent-plan`，普通语音默认 `--service speech`；两者不能因鉴权失败自动互换。两个声音脚本默认 dry run，`--execute` 才提交，`--max-chars` 必填；默认分别读 `DOUBAO_SPEECH_API_KEY`、`DOUBAO_MEDIAKIT_API_KEY`，不自动回退到方舟 key，可通过 `--key-env <环境变量名>` 显式选择并单独核验权限。2026-10-11 普通语音探测／合成及显式 Agent Plan 合成均未通过认证（401／45000010），MediaKit key 未配置；接口离线验证通过，尚无成功云端声音，不能声称已生成可用豆包声音。无远程声源时可用 `scripts/procedural_audio.py` 离线合成原创环境底、拟音与简约配乐，须如实标记为程序合成。

声音资产记录写 `kind=audio`、`purpose=asset`，不属于镜头画面。人工试听后通过 `vsc_library.py promote/use` 复用 voice/music/ambience/sfx；相同音色 ID、音轨存在或工具成功都不代替声线、表演、权属与人工选择。具体参数见[豆包语音](../../docs/architecture/doubao-speech.md)、[Seed-Audio](../../docs/architecture/doubao-audio.md)。

需要批量图像／视频时，按[批量生产](../../docs/guide/production-batch.md)准备 `templates/production-batch.json`，先用 `scripts/vsc_production.py validate/plan` 只读预检并审阅任务依赖、输入 SHA 和规模预算，再 `run --execute --plan-hash <hash>`。队列当前只支持方舟 image/video，不接管声音任务；计划 hash 不等于人工批准，未知提交不重提，失败停止下游。

按[上游 Skill 用法](../vsc-vendor/SKILL.md#下载后直接使用-skill)解析 `produce` 阶段；除运行环境外，项目授权也须就绪才调用生成工作流。未就绪时保留为可选能力，不伪造供应商调用或生成结果。

## 制作交接 v2

新规则付费制作必须走已批准 production-run、相应 Gate 和项目共享预算；批次 plan hash 不是人工批准。成功先导入 draft，关键候选真实审阅后下游才续跑；最终选择另交 selected-takes。

规则见 [制作协议](../../workflow/production-v2.md)，操作见 [v2 指南](../../docs/guide/production-v2.md)。
