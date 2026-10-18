# xAI Grok Imagine 订阅路线（2026-10-17；能力面按官方文档 2026-10-17 核对）

用户账号以**订阅＋登录授权**使用 xAI Grok：在终端运行 `grok`（xAI 官方 CLI）完成浏览器登录后，`~/.grok/auth.json` 内按账号保存带时效的 `key`，VSC 用它作为 Bearer 调官方 REST 平台 `https://api.x.ai/v1`。该登录态由 grok CLI 在使用中自动刷新；VSC 只读本地文件，不联网验证、不刷新、不回显密钥值。

## 建模与授权边界

| 项 | 约定 |
|---|---|
| 供应商身份 | `supplier=xai`、`product=grok-imagine`、`plan=subscription`、`execution=api`；端点固定 `https://api.x.ai/v1`，`GROK_BASE_URL` 只能设为同一地址 |
| 凭证 | 只读 `~/.grok/auth.json`（嵌套账号条目的 `key`，取未过期且时效最新者）；`auth_ref` 留空，不使用环境变量。缺失提示在终端运行 `grok` 登录；过期提示重新登录刷新 |
| 与按量 API 分开 | 独立 `XAI_API_KEY`（按量计费）是另一条未接通路线，不与订阅混用，也不互相回退（401／403 不自动换凭证或重试） |
| 与宿主分开 | Grok Build 宿主的内置 `image_gen`／`image_edit` 等工具属于宿主授权（`host_tool` 语义），与本文 REST 订阅路线分开识别，不互相冒用 |

## 官方能力面与 VSC 实现（[Imagine 总览](https://docs.x.ai/developers/model-capabilities/imagine)、[参考生视频](https://docs.x.ai/developers/model-capabilities/video/reference-to-video)、[图生视频](https://docs.x.ai/developers/model-capabilities/video/image-to-video)）

模型：`grok-imagine-image-2.0`（生成＋编辑）、`grok-imagine-video-1.5`（全功能视频）、`grok-imagine-video`（旧版，功能子集）。

| 能力 | 官方规格 | VSC 实现 |
|---|---|---|
| 文生图 | `POST /v1/images/generations`；`model/prompt/n(1–10)/aspect_ratio/resolution(1k,2k)/response_format` | ✅ 脚本 `image`（无 `--ref`）与任务库图像适配器的默认模式 |
| 图像编辑／多图合成 | `POST /v1/images/edits`；单源图 `image:{url,type:image_url}`，多源图 `images`（**最多 5 张**：换装、风格迁移、多主体合成）；提示词只写要改的内容 | ✅ 脚本 `image --ref`（1–5 张）与图像适配器 `reference_media_ids`（用途 `image_edit`）；本地文件走 data URI，`aspect_ratio/resolution`显式进入共享请求编译器；batch每个逻辑候选一张 |
| 首帧图生视频 | `image:{url}` 单独出现即首帧锚定；时长 ≤15s（1.5）；1.5 支持原生 1080p | ✅ 脚本 `video --first-frame` 与视频适配器 `first_frame_media_id`；分辨率 480p/720p/1080p |
| 尾帧钉定 | `last_frame:{url}`；可单独使用（平台生成开场并落在该画面），也可与 `image` 组成首尾帧插值，或再叠加参考 | ✅ 脚本 `video --last-frame` 与适配器 `last_frame_media_id` |
| 参考生视频 | `reference_images:[{url},…]` **最多 14 张**（1.5）；可与 `image` 组合——`image` 成为钉定首帧，提示词占位符 `<IMAGE_0>` 归首帧、参考图从 `<IMAGE_1>` 起编号；无首帧时参考图从 `<IMAGE_0>` 起。提示词按位置指位（人物来自 `<IMAGE_1>`、商品来自 `<IMAGE_2>`）。参考模式分辨率上限 **720p** | ✅ 脚本 `video --ref-image`（1–14）与适配器 `reference_media_ids`；超过 14 张、或参考模式请求 1080p 在提交前拒绝 |
| 预置声音参考 | `reference_audios:[{voice_id},…]` 最多 3 个（1.5），只接平台预置 voice_id（如 `eve`）；自定义音频参考仅限受信伙伴 | ✅ 平台资源 id 存放在供应商注册表的模型默认参数 `reference_voice_ids`（`provider_models.default_params`，即数据库中的平台资源 id 字段），随模型配置进入任务库适配器；脚本用 `--voice-id`（≤3），提示词以 `<AUDIO_n>` 指位。VSC 的音频素材文件语义不同，仍不塞进该字段（负例在提交前拒绝） |
| 中段关键帧 | `keyframes:[{image:{url},timestamp_s},…]` 最多 4 个（1.5），时间戳须严格在片内并对齐 1/3 秒网格 | ✅ 供应商中立请求契约扩展 `VideoRequest.keyframes`（(媒体ID, 秒) 对），能力开关 `keyframes`；脚本 `--keyframe 文件@秒`（≤4）。片外时间戳、间隔不足 1/3 秒、经典模型使用均在提交前拒绝 |
| 视频编辑／续接 | `POST /v1/videos/edits`、`POST /v1/videos/extensions`，输入 `video`；编辑最长约8.7s；续接源片2–15s，`duration`为新增2–10s（默认6s）；输出跟随源片画幅/分辨率、最高720p | ✅ 脚本子命令 `edit`／`extend`（`--video`为可验证本地文件，`--prompt`均必填；续接支持`--duration`，编辑拒绝另设时长）。**线上探针已证**：编辑/续接由经典 `grok-imagine-video` 承担（1.5 返回 "Video editing is not supported"）；`extensions` 的 `prompt` 为平台必填（422 实证）。正式batch/run已接`grok_edit/grok_extend`；PG任务通过`operation=edit/extend`及固定`source_media_id/source_sha256/source_duration_ms`接通，成功任务登记media_operations输入输出血缘；实际源字节、时长、run批准与预算在提交前复核 |
| 无声视频 | `generate_audio:false` 请求无声输出 | ✅ 模型默认参数 `generate_audio`（布尔）与脚本 `--no-audio` |
| 画幅 | 视频可传 `aspect_ratio`；图生视频场景下强行另设会把源图拉伸 | 图生视频默认不传（跟随首帧）；参考／文生模式可用脚本 `--ratio`／模型默认参数 `ratio` 显式指定 |
| 结果时效 | 视频 URL 临时，须立即转存；官方未公布时效 | 成功后立即下载并登记 SHA，记录按保守 1 小时标注 `source_url_expires_at` |
| 计费口径 | 图像按张；编辑计输入＋输出张；视频按秒×分辨率 | 订阅额度内通常无边际费用；账本只记 `images`／`video_seconds` 原生用量，不做金额换算 |

## VSC 实现位置

- 独立脚本：`scripts/providers/xai/grok.py`（`src/vsc/adapters/providers/xai_grok/api.py`）——图像（文生图／编辑合成）、视频（首帧／尾帧／参考／文生）各写一份 `vsc.generation-record/v1`（`engine.provider=xai_grok`）、任务文件 `vsc.grok-task/v1`、提交意图先行、断点续查不重提、共享预算 `images`／`video_seconds`；参考图按出现顺序做语义摘要（data URI → 内容 SHA）。
- 任务库适配器：`src/vsc/adapters/providers/xai_grok/provider.py` 实现 `ImageProvider`／`VideoProvider`；模式由冻结请求字段决定（首帧/尾帧/参考图/纯文本），非法组合（参考模式 1080p、>14 参考图、音频素材冒充 voice_id）在传输前拒绝。`resource_factory.py` 供 PostgreSQL worker，`worker_factory.py` 按登记供应商分发。
- 正式批次：`grok_image/grok_video/grok_edit/grok_extend`经同一编译器、预算与CLI运行；完成后核原始记录、稳定账号和完整媒体。unknown仅恢复；已核验本地结果可离线复用。
- series 栈：`jobs.py` 的 `xai_grok` Provider 登记（登录态授权、固定端点）与适配器分支；`dispatch.py` 提交前核对登录态。
- 资源面板：预设 `Grok Imagine 图像（订阅登录）`（用途 `identity_ref/image_edit/first_frame/last_frame`，参考媒体 ≤5）、`Grok Imagine 图生视频（订阅登录）`（用途 `image_to_video`，首尾帧＋参考媒体 ≤14，最长 15s）默认停用；按项目启用并绑定用途默认。
- 就绪诊断：`scripts/media/toolchain.py` 的 `grok_image`／`grok_video` 行按登录态文件报 `present`／`pending`。

## 验证边界

离线验证已完成（2026-10-17，FakeTransport 与离线 CLI，无付费调用）：全部模式的请求组装与负例（编辑 >5 源图、参考 >14 张、参考模式 1080p、音频素材冒充声音参考、关键帧片外/间隔/超量、经典模型越权特性、预置声音 >3）、占位符语义摘要、生成记录契约、提交续查不重提、worker 分发、series 登记。线上只读探针已核对端点行为：`/v1/videos/edits` 接受 `grok-imagine-video`＋prompt 并返回 request_id；`/v1/videos/extensions` 存在且 prompt 必填；1.5 模型明确拒绝视频编辑。**真实媒体的成功生成仍待小批量试产**（重点：参考模式身份一致性、`<IMAGE_n>`／`<AUDIO_n>` 指位遵守、编辑未改区域稳定性、续接的运动连贯），实测前不得把该路线报告为“已可用于生产”。

2026-10-18工程复验：四模式正式run使用离线transport与真实合成媒体完成预算、一次POST、恢复及候选登记；PG普通生成覆盖成功响应先持久化与失败转存恢复。账号以稳定身份摘要绑定，同账号token刷新可恢复，跨账号在网络前拒绝。媒体验证完整解码；这些结果不代表订阅账号线上权限或专业效果通过。续接参数已重新核对[官方说明](https://docs.x.ai/developers/model-capabilities/video/extension)。

v0.35.0补齐PG加工：正式任务和worker的离线有效媒体回归覆盖固定源、原生用量、实际端点、成功响应持久化、转存/登记崩溃与加工血缘。不据此宣称PG各模式线上或专业效果通过。
