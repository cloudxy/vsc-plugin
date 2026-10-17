# 火山方舟 Agent Plan 个人版与 VSC 工作流对照（2026-10-13）

适用范围是用户给出的[个人版套餐概览](https://docs.volcengine.com/docs/ark/agent-plan-personal-plan-overview?lang=zh)。该概览页在当前只读抓取环境仅返回 JavaScript 外壳；下列可核实规则分别依据官方[个人版实践指南](https://docs.volcengine.com/docs/ark/agent-plan-personal-practice-education?lang=zh)、[语音接入](https://docs.volcengine.com/docs/ark/agent-plan-personal-voice-model?lang=zh)、[AFP 抵扣规则](https://docs.volcengine.com/docs/ark/agent-plan-personal-afp-credits-billing-rules?lang=zh)与[模型更新](https://docs.volcengine.com/docs/ark/agent-plan-personal-feature-release?lang=zh)。不从企业版推出个人版权益。

| 能力或限制 | 官方个人版规则 | VSC 当前实现与边界 |
|---|---|---|
| 图像／视频接口 | 专属 API Key 与 `https://ark.cn-beijing.volces.com/api/plan/v3`；其他方舟 key 不可混用 | `volc_ark.py` 和系列适配器已统一 key 与地址。新任务提交前拒绝标准 `/api/v3`，Provider 登记也拒绝该地址。没有线上成功响应证据。 |
| 模型范围 | 支持模型随套餐和更新变化；Seedance 2.5、2.0 mini 的 Large/Max 限制见官方更新 | `provider_models` 保存能力、模型版本与用途。登记时应以当前账号控制台模型清单核实，再填精确 model key；不因同名系列或普通方舟模型可用就推断套餐可用。没有自动线上模型发现。 |
| AFP 用量 | 图像按成功张数及模型系数；视频按消耗 token/10000 乘系数；TTS 按文本字符数/10000 乘系数。模型、分辨率、输入视频与活动可改变系数 | 现有 `production_run` 预算是 `images`、`video_seconds`、`speech_chars` 等**本地原生上限**，不是 AFP 额度。`cost_rule` 仅供登记，目前没有逐任务 AFP 预测、平台余额查询或额度占用；不能把秒数直接换成 AFP。结果用量与账单需要之后对账。 |
| 语音 | 官方个人版包含 Seed TTS 2.0 与 ASR 2.0，TTS 用专属语音路由和 `seed-tts-2.0` 资源 ID | 系列统一 `AudioProvider` 已离线接入预置音色 TTS：已批准台词行、覆盖镜头、人物音色和发音提示固定在任务中；同步响应经解码和 SHA 校验入库。`doubao_speech.py` 的独立 CLI 仍在。系列线上认证尚未验证；ASR、角色声线自动比对、声音复刻未接通。相同 speaker ID 仍须人工审听。 |
| 音乐／音效 | 个人版官方已核实列表没有证明 MediaKit Seed-Audio 1.0 纳入 Agent Plan 权益 | `doubao_audio.py` 是独立 MediaKit 适配，不得把共享的环境变量名称当成套餐可用证明；在账号权限和计费模式核实前，不把它排入系列套餐批量任务。 |
| 文本／向量 | 套餐 key 的文本与向量模型不能直接用于普通业务 API | `volc_ark.py` 对相应路径拒绝；`inspect` 不发起新请求。AI 素材索引以本地关系库的批准绑定和 SHA 为准，语义检索只作候选发现。 |

## 对 60 集、每集约 3 分钟制作的影响

每次开始批量生成前，先核对当前订阅档位、可用模型及 AFP 余额，并明确是否开通超额后付费。工作流仍按已批准镜头和资产版本计划候选，不用一次性把 60 集全部提交。先以重复人物与地点的一集做图像、视频、配音、剪辑和人工审片试点，记录真实 AFP 与返工原因，再决定批次和候选数。角色、场景、声音一致性靠母版／变体、镜头上下文、引用权利、固定版本和选片审核；套餐只提供生成能力，不保证一次成片。

现有 `resume-pending` 会续查已知外部视频任务并转存结果；同步语音也进入统一任务、预算和素材库。模型资格、语音线上认证与真实账号成功验收尚无证据。本次仅做离线契约与拦截验证；首次线上调用由用户提供脚本后进行。查询个人版 AFP 的官方控制面接口[GetAFPUsage](https://docs.volcengine.com/docs/ark/get-afp-usage-api?lang=zh)使用 **Access Key 鉴权**，不能拿 Agent Plan API Key 直接请求，后续若接入须另设只读凭证和授权流程。

## 2026-10-16：官方工具与受控 SDK 执行

重新核对用户的[个人版套餐概览](https://console.volcengine.com/ark/region:cn-beijing/docs/agent-plan-personal-plan-overview)和[专属 API Key 文档](https://console.volcengine.com/ark/region:cn-beijing/docs/api-key)，可读内容更新至 2026-10-15：Small／Medium 不含视频能力，Large／Max 才能使用相应视频服务；超额后付费是否开启需核对实际账号，配置名称不能证明权益。VSC 只核对 `ARK_AGENT_PLAN_API_KEY` 是否加载，不用文本 hello、向量请求或新生成请求验证凭证。

官方[视觉模型接入页](https://docs.volcengine.com/docs/ark/agent-plan-personal-visual-models?lang=zh)提供 Skill、ArkCLI 和 API 路线。其链接的 `skills.volces.com/skills/volcengine/agentplan` 在本次公开抓取返回不可取得；没有把未取得的独立 Skill 标成已审计。实际读取的 [ArkCLI 官方仓库](https://github.com/volcengine/ark-cli)固定源码 `fb5b7bef87fe10792b6581cef30549f4046dea36` 包含 Skills／说明，官方 npm `@volcengine/ark-cli` 1.0.39 包含启动脚本与平台二进制清单。CLI 文档能说明参数和异步 task ID，但封闭二进制不能提供内部重试／提示词改写的源码证据，因此仍是交互／方法参考，不进入自动生成 worker。

VSC 的 `official_sdk` 路线实际采用官方独立 [Ark Runtime Python SDK](https://github.com/volcengine/ark-runtime-python)，官方[迁移文档](https://console.volcengine.com/ark/region:cn-beijing/docs/migrate-ark-runtime-sdk)说明其从旧 SDK 导入路径迁移。可选依赖固定为 PyPI 已发布的 `arkruntime==0.13.0`（官方仓库 main 的 0.14.0 版本声明不是已发布包）。配置保存时由服务端读取实际 SDK、递归依赖版本与代码摘要、VSC 适配器代码摘要、Python 版本及平台，固定在该模型版本的 `sdk_runtime` 中；界面无需填写指纹。缺包或版本不符只能保存停用草稿，不能启用。检查按钮比对完整运行指纹；缺包、字节变化或版本变化都会在提交前拒绝执行，旧任务也不能静默改用新环境。

执行通过既有 `volc_ark_factory` 和 `ResourceWorker`：批准的输入与模型、原生预算占用、提交意图、未知结果、外部 task ID、续查与转存都使用原有 PostgreSQL 权威。图像调用真实 `Ark.images.generate`，视频调用真实 `Ark.content_generation.tasks.create/get`；`max_retries=0`，HTTP 不跟随重定向，不继承代理环境，发送前核对实际 method／URL／JSON 与固定请求一致。精确提示词和引用映射保持不变，文本／向量端点不在允许集合中。语音继续使用已登记 API 路线，未宣称该 SDK 音频已接通。

任务响应留存 `vsc_execution`：VSC 宿主、服务供应商、产品／套餐／区域、配置与凭证引用、精确模型、SDK 版本／发布者／来源／环境摘要、请求摘要及返回用量。配置 ID 是本机连接引用，`account_identity_verified=false` 明确没有通过网络验证真实账号归属；不会把环境变量名冒充已认证账号 ID。生成媒体经任务输出关系可追溯固定输入和执行证据，仍需人工审核选择。

验证边界：真实 SDK + HTTP MockTransport 已验证图像请求精确性、视频 POST→task ID→GET、401／403／429／500／307／超时单次请求、固定环境变化拦截。真实隔离 PostgreSQL 测试已验证 SDK 路线经过 worker，图像落盘成为固定首帧，视频任务提交后即使配置停用仍可续查、转存真实合成 MP4，反查输入／输出归属；超时保留 `submission_unknown` 且不能自动重发。这些是离线工程证据，没有对真实账号做新付费调用，也没有验证生成效果、额度余额或线上权限。
