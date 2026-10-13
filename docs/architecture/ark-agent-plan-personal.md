# 火山方舟 Agent Plan 个人版与 VSC 工作流对照（2026-10-13）

适用范围是用户给出的[个人版套餐概览](https://docs.volcengine.com/docs/ark/agent-plan-personal-plan-overview?lang=zh)。该概览页在当前只读抓取环境仅返回 JavaScript 外壳；下列可核实规则分别依据官方[个人版实践指南](https://docs.volcengine.com/docs/ark/agent-plan-personal-practice-education?lang=zh)、[语音接入](https://docs.volcengine.com/docs/ark/agent-plan-personal-voice-model?lang=zh)、[AFP 抵扣规则](https://docs.volcengine.com/docs/ark/agent-plan-personal-afp-credits-billing-rules?lang=zh)与[模型更新](https://docs.volcengine.com/docs/ark/agent-plan-personal-feature-release?lang=zh)。不从企业版推出个人版权益。

| 能力或限制 | 官方个人版规则 | VSC 当前实现与边界 |
|---|---|---|
| 图像／视频接口 | 专属 API Key 与 `https://ark.cn-beijing.volces.com/api/plan/v3`；其他方舟 key 不可混用 | `volc_ark.py` 和系列适配器已统一 key 与地址。新任务提交前拒绝标准 `/api/v3`，Provider 登记也拒绝该地址。没有线上成功响应证据。 |
| 视频档位 | Small、Medium 不支持生视频；Large、Max 可申请使用套餐支持的视频模型 | 新提交须本机声明 `ARK_AGENT_PLAN_TIER=large` 或 `max`，旧 CLI 和系列调度器均在付费提交前拦截其他值。声明只代表操作员配置，不能证明订阅有效、模型在当前账号可用或 AFP 充足。 |
| 模型范围 | 支持模型随套餐和更新变化；Seedance 2.5、2.0 mini 的 Large/Max 限制见官方更新 | `provider_models` 保存能力、模型版本与用途。登记时应以当前账号控制台模型清单核实，再填精确 model key；不因同名系列或普通方舟模型可用就推断套餐可用。没有自动线上模型发现。 |
| AFP 用量 | 图像按成功张数及模型系数；视频按消耗 token/10000 乘系数；TTS 按文本字符数/10000 乘系数。模型、分辨率、输入视频与活动可改变系数 | 现有 `production_run` 预算是 `images`、`video_seconds`、`speech_chars` 等**本地原生上限**，不是 AFP 额度。`cost_rule` 仅供登记，目前没有逐任务 AFP 预测、平台余额查询或额度占用；不能把秒数直接换成 AFP。结果用量与账单需要之后对账。 |
| 语音 | 官方个人版包含 Seed TTS 2.0 与 ASR 2.0，TTS 用专属语音路由和 `seed-tts-2.0` 资源 ID | `doubao_speech.py` 有供应商专用 TTS CLI，但在线认证曾失败；系列统一 `AudioProvider` 仍未映射语音服务。ASR、角色声线一致性自动比对、声音复刻都未接通。相同 speaker ID 仍须人工审听。 |
| 音乐／音效 | 个人版官方已核实列表没有证明 MediaKit Seed-Audio 1.0 纳入 Agent Plan 权益 | `doubao_audio.py` 是独立 MediaKit 适配，不得把共享的环境变量名称当成套餐可用证明；在账号权限和计费模式核实前，不把它排入系列套餐批量任务。 |
| 文本／向量 | 套餐 key 的文本与向量模型不能直接用于普通业务 API | `volc_ark.py` 对相应路径拒绝；`inspect` 不发起新请求。AI 素材索引以本地关系库的批准绑定和 SHA 为准，语义检索只作候选发现。 |

## 对 60 集、每集约 3 分钟制作的影响

每次开始批量生成前，先核对当前订阅档位、可用模型及 AFP 余额，并明确是否开通超额后付费。工作流仍按已批准镜头和资产版本计划候选，不用一次性把 60 集全部提交。先以重复人物与地点的一集做图像、视频、配音、剪辑和人工审片试点，记录真实 AFP 与返工原因，再决定批次和候选数。角色、场景、声音一致性靠母版／变体、镜头上下文、引用权利、固定版本和选片审核；套餐只提供生成能力，不保证一次成片。

现有 `resume-pending` 会续查已知外部视频任务并转存结果，但没有账号级 AFP 余额查询、模型资格在线核验、语音统一调度或真实账号成功验收。本次仅做离线契约与拦截验证；首次线上调用由用户提供脚本后进行。查询个人版 AFP 的官方控制面接口[GetAFPUsage](https://docs.volcengine.com/docs/ark/get-afp-usage-api?lang=zh)使用 **Access Key 鉴权**，不能拿 Agent Plan API Key 直接请求，后续若接入须另设只读凭证和授权流程。
