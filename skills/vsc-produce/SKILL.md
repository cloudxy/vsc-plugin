---
name: vsc-produce
description: "Plan and review provider-neutral image, image-to-video and audio take production from approved VSC specifications."
---

# VSC 制作

只根据已批准的 ShotPlan、AssetBible、声音方案和项目策略生产候选 take；图像、视频、音频候选都不是自动选中版本。

按[专业制作与返工控制](../vsc/references/creative-production.md)固定必要条件、容差和停止条件；用 `scripts/production/quality.py check <检查包.json> --root <证据目录>` 核对要求到实际输入字段的覆盖，并按逻辑镜头／用途跨新任务累计缺陷。用 `scripts/production/run.py plan --quality-plan` 将检查包固定到 run，批准、执行和付费提交复核会实际阻断缺项、漂移与停止阈值。预演前本地有限试片使用 `--phase trial --trial-spec`，复用已有 pilot 上下文、script Gate、上游批准与共享预算；试片不是正式采用，细则见同一方法文档。数据库项目使用原权威入口。达到约定阈值先比较局部修复或换方法；报告未知不能视为质量通过。

同一个人物或物件独立从文字重建容易发生身份漂移。先固定必要参考资产，再按镜头功能、连续性计划和已验证的供应商能力，选择首帧、首尾帧或多参考生成；需要的关键帧属于这个输入方案，不默认每镜制作两帧。

先用 `scripts/assets/library.py search` 查已有素材，确认变体与权属后 `use` 绑定本项目；确需新建才生成。操作见[素材复用与检索](../../docs/guide/reuse-and-search.md)。

1. **资产图**：每个人物、地点和关键道具先建立满足具体用途的必要规范图（生成记录 `purpose: asset`，不属于任何镜头），复用已确认身份；新增角度或状态按用途补充，不重复独立创造身份。人工确认后登记为资产库中对应实体的参考素材，此后有关画面以它为参考。
2. **关键帧与参考输入**：按状态时间线确定必须约束入点、出点还是身份／空间。首帧模式准备必要入点；首尾帧模式在供应商确实支持且末态有明确要求时补出点；多参考模式固定每张图的身份、地点、构图等用途。输入结合 `python3 -B scripts/story/consistency.py anchors <镜头> --bible <资产库> --state <状态时间线> --text --moment entry|exit` 给出的状态；所生成关键帧记录 `shot_id` 和 `inputs.moment`。
   - 只有同一连续动作且机位、构图与动作接点兼容，并采用相应连续性策略时，上一镜出点帧才作为下一镜入点复用。换机位、反应镜、时间／空间跳转等按批准桥接策略设计，不强迫相邻镜头共享像素。
   - 需要局部改变时可比较以上一关键帧编辑或重建的成本与副作用；实际编辑记 `inputs.base_frame`（`use: edit`），仅参考记 `use: reference`。编辑后复核变化及未改区域。
   - 所用关键帧或参考经适用的检查后进入视频。人数、道具与位置问题应先处理，不把错误输入交给视频阶段修复。
3. **视频**：使用本镜选定且适配器已支持的输入模式，文字表达动作、表演、运镜、声音及必要限制，避免与参考身份矛盾。实际传入首／尾帧时，记录对应 `first_frame`／`last_frame` 的 SHA；参考图用途如实登记，未传入的帧不能伪造记录。
   - 返回实际尾帧时登记为 `outputs[].role=last_frame`，先核对状态与接点兼容性，再决定是否供下一镜使用。多参考中的“从图片1开始”是意图要求，须核对实际首帧，不能视为硬控制。
   - 若固定 Profile／契约要求的输入或连续性能力当前模式不支持，先换已支持路线、调整镜头或提出正式规格变更；不删必填字段或跳过校验。参数可提交不代表实际精度已验证。

每个生成任务写一份 `vsc.generation-record/v1`（从 `templates/generation-record.json` 起步），用 `anchors_sha256` 绑定所用锚点包；参考图被平台拒绝时如实记录。生成后，把资产图、关键帧和视频的全部记录一起交给 `scripts/story/consistency.py check … --record <记录> …`。它会报告以下问题：

- 锚点已过期；
- 参考素材不属于本镜；
- 声明的首帧来源与实际记录不符；
- 传入的视频首尾帧与对应入点／出点记录不符；
- 要求像素匹配的桥接中，交界帧不一致。

它还会提醒三种情况：资产图没有登记进资产库；帧追溯不到关键帧记录；人物既没用参考素材，也没用由资产图生成的关键帧。

可选豆包工具 `scripts/providers/volcengine/ark.py` 已提供图像、视频与视觉检查；先 dry run 核对视频请求，再在已有预算范围内提交。视觉提醒写 `vsc.visual-check/v1`，不能取代人工选择。供应商 API、密钥、收费、许可和平台策略由适配器及项目策略负责；配置、实测与限制见[生成适配器边界](../../docs/architecture/generation-adapters.md)。

制作前运行 `python3 -B scripts/media/toolchain.py --project <作品目录> --json`。实现存在、默认凭证变量存在、当前作品有有效候选与人工已审阅分别看；该诊断不联网核验权限，`configured=true` 不能当作供应商可用或批准。

声音按已批准声音方案另行制作：`scripts/providers/volcengine/speech.py synthesize` 提供固定 speaker 和情绪 context，`scripts/providers/volcengine/audio.py generate` 经 MediaKit 生成音乐／环境／音效候选。语音默认 `--service agent-plan`（统一的方舟 Agent Plan key），普通语音须显式 `--service speech`；两者不能因鉴权失败自动互换。两个声音脚本默认 dry run，`--execute` 才提交，`--max-chars` 必填；火山图片、视频与两个声音脚本统一读 `ARK_AGENT_PLAN_API_KEY`，找不到时提示配置火山方舟 Agent 版本的 API Key；可通过 `--key-env <环境变量名>` 显式选择其他变量并单独核验权限。该 key 不得直接调用文本生成模型，视觉检查不能新提交。2026-10-11 普通语音探测／合成及显式 Agent Plan 合成均未通过认证（401／45000010），MediaKit key 未配置；接口离线验证通过，尚无成功云端声音，不能声称已生成可用豆包声音。无远程声源时可用 `scripts/media/procedural_audio.py` 离线合成原创环境底、拟音与简约配乐，须如实标记为程序合成。

声音资产记录写 `kind=audio`、`purpose=asset`，不属于镜头画面。人工试听后通过 `scripts/assets/library.py promote/use` 复用 voice/music/ambience/sfx；相同音色 ID、音轨存在或工具成功都不代替声线、表演、权属与人工选择。具体参数见[豆包语音](../../docs/architecture/doubao-speech.md)、[Seed-Audio](../../docs/architecture/doubao-audio.md)。

需要批量图像／视频时，按[批量生产](../../docs/guide/production-batch.md)准备 `templates/production-batch.json`，先用 `scripts/production/plan.py validate/plan` 只读预检并审阅任务依赖、输入 SHA 和规模预算，再 `run --execute --plan-hash <hash>`。队列当前只支持方舟 image/video，不接管声音任务；计划 hash 不等于人工批准，未知提交不重提，失败停止下游。

按[上游 Skill 用法](../vsc-vendor/SKILL.md#下载后直接使用-skill)解析 `produce` 阶段；除运行环境外，项目授权也须就绪才调用生成工作流。未就绪时保留为可选能力，不伪造供应商调用或生成结果。

## 制作交接 v2

PostgreSQL 项目通过 `scripts/assets/resources.py context` 和 `create_generation_job` 固定输入，已批准 run 逐项授权请求；明确 `worker` 提交、`worker --poll` 查询、`worker --resume` 恢复转存。候选输出经面板检查、人审和用途选择后才供下游消费。不得绕过任务库直接运行低层供应商脚本，PG 失败时不得回退旧权威。见[资源面板指南](../../docs/guide/resource-panel.md)。

PG 预演前有限试片、固定质量包的构造顺序及 `trial_adoption` 正式采用字段，见 [PostgreSQL 试片与质量包](../vsc/references/creative-production.md#postgresql-试片与质量包)。首版每份 trial run 限定单镜头，质量证据从本项目固定已批准 artifact 字节读取；PG 正式风险评测的自动复用尚未接入，不将独立 `pass` 字段当作授权。

新规则付费制作必须走已批准 production-run、相应 Gate 和项目共享预算；批次 plan hash 不是人工批准。成功先导入 draft，关键候选真实审阅后下游才续跑；最终选择另交 selected-takes。

规则见 [制作协议](../../workflow/production-v2.md)，操作见 [v2 指南](../../docs/guide/production-v2.md)。
