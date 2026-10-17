# xAI Grok Imagine 订阅路线（2026-10-17）

用户账号以**订阅＋登录授权**使用 xAI Grok：在终端运行 `grok`（xAI 官方 CLI）完成浏览器登录后，`~/.grok/auth.json` 内按账号保存带时效的 `key`，VSC 用它作为 Bearer 调官方 REST 平台 `https://api.x.ai/v1` 的图像与视频接口。该登录态由 grok CLI 在使用中自动刷新；VSC 只读本地文件，不联网验证、不刷新、不回显密钥值。

## 建模与授权边界

| 项 | 约定 |
|---|---|
| 供应商身份 | `supplier=xai`、`product=grok-imagine`、`plan=subscription`、`execution=api`；端点固定 `https://api.x.ai/v1`，`GROK_BASE_URL` 只能设为同一地址 |
| 凭证 | 只读 `~/.grok/auth.json`（嵌套账号条目的 `key`，取未过期且时效最新者）；`auth_ref` 留空，不使用环境变量。缺失提示在终端运行 `grok` 登录；过期提示重新登录刷新 |
| 与按量 API 分开 | 独立 `XAI_API_KEY`（按量计费）是另一条未接通路线，不与订阅混用，也不互相回退（401／403 不自动换凭证或重试） |
| 与宿主分开 | Grok Build 宿主的内置 `image_gen`／`image_edit` 等工具属于宿主授权（`host_tool` 语义），与本文 REST 订阅路线分开识别，不互相冒用 |

## 能力与限制（按 2026-10 核实的接口）

| 能力 | 说明 |
|---|---|
| 文生图 | `POST /v1/images/generations`；`model`（`grok-imagine-image-2.0`／`grok-imagine-image-quality` 等）、`prompt`、`n`（1–10）、`aspect_ratio`（默认 `9:16`）、`resolution`（`1k`／`2k`，默认 `2k`）。同步返回 `data[].url`（临时链接，须立即转存）。多图编辑端点 `/v1/images/edits` 未接 |
| 图生视频 | `POST /v1/videos/generations` 提交（返回 `request_id`），`GET /v1/videos/{request_id}` 轮询；`status` 为 `pending`／`done`／`failed`／`expired`。默认模型 `grok-imagine-video-1.5`，`image` 为首帧（本地图走 data URI），`duration` 1–15 整秒（默认 6），`resolution` `480p`（默认）／`720p`／`1080p`；**不传 `aspect_ratio`**（画幅跟随源图，强行另设会拉伸）。完成后读 `video.url`／`video.duration`，视频自带音轨。不支持尾帧锁定、参考图与参考音频混用；纯文生视频不作为默认路线 |
| 请求标头 | 必须带浏览器 `User-Agent`，否则平台网关（Cloudflare）回 403／1010；适配器统一注入 |
| 时效 | 结果 URL 是临时的，成功后立即下载并登记 SHA；官方未公布 URL 有效期，记录按保守 1 小时标注 `source_url_expires_at`，仅作元数据 |

## VSC 实现位置

- 独立脚本：`scripts/providers/xai/grok.py`（`src/vsc/adapters/providers/xai_grok/api.py`）——图像／视频各写一份 `vsc.generation-record/v1`（`engine.provider=xai_grok`）、任务文件 `vsc.grok-task/v1`、提交意图先行、断点续查不重提、共享预算 `images`／`video_seconds`。
- 任务库适配器：`src/vsc/adapters/providers/xai_grok/provider.py` 实现 `ImageProvider`／`VideoProvider`；`resource_factory.py` 供 PostgreSQL worker，`src/vsc/adapters/providers/worker_factory.py` 按任务登记的供应商分发（方舟与 Grok）。
- series 栈：`jobs.py` 的 `xai_grok` Provider 登记（登录态授权、固定端点）与适配器分支；`dispatch.py` 提交前核对登录态，缺失时在预留预算前失败。
- 资源面板：预设 `Grok Imagine 图像（订阅登录）`／`Grok Imagine 图生视频（订阅登录）` 默认停用；启用须声明用途与模型版本，图像用途默认 `ratio_map`（尺寸→画幅）加 `resolution`，视频须 `480p`／`720p`／`1080p`。按项目把用途默认绑定到 Grok 后，新任务才走该路线。
- 就绪诊断：`scripts/media/toolchain.py` 的 `grok_image`／`grok_video` 行按登录态文件报 `present`／`pending`，不读环境变量。

## 验证边界

离线验证已完成：凭证读取与缺失提示、请求映射（画幅／分辨率／时长／首帧 data URI）、视频提交→轮询→终态、失败与过期状态、续查不重提、生成记录契约、worker 分发、series 登记不变量（2026-10-17，全部经 FakeTransport，无付费调用）。**真实订阅账号的线上生成尚未实测**：接入后先在单个真实作品小批量试产，核对画质、身份一致性、额度与到账口径，再绑定用途默认；未实测前不得把该路线报告为“已可用于生产”。

计费口径：订阅额度内通常无边际费用，但额度、限速（图像约 6 rps、视频约 10 rps）与订阅档位以账号实际为准；预算账本只记 `images`／`video_seconds` 原生用量，不做金额换算。
