# VSC 文档

文档按读者分组。工作流的事实来源是 [`workflow/`](../workflow/README.md)；文档解释它，不另立规则。

## plans · 审查与改进方案

| 文档 | 内容 |
|---|---|
| [2026-10-11 短剧／短视频工作流深度审查](plans/2026-10-11-vsc-workflow-review.md) | 16 类问题、离线复现证据、7 个实施工作包与真实制作验收；工程改造见实施记录 |
| [2026-10-12 实施记录](plans/2026-10-12-vsc-workflow-implementation.md) | 工作包、回归证据与真实制作验收边界 |
| [项目浏览器方案](plans/2026-10-14-project-browser.md) | VSC 内置只读网页、旧项目与系列数据库兼容、文案和素材可视化；尚未实现 |

## guide · 使用与维护

| 文档 | 内容 |
|---|---|
| [AI 客户端接入](guide/workspace-setup.md) | Codex、Claude Code、Grok Build、Kimi Code、ZCode 的入口与验证 |
| [命令行使用](guide/cli.md) | 新建项目、登记与批准、契约校验、记忆与学习、Profile、外部交接 |
| [素材复用与检索](guide/reuse-and-search.md) | 跨作品素材库、公开创作方法、内容查找与集／场衔接 |
| [制作规格包](guide/asset-recipes.md) | 20 类可复用规格，区分文本规格与实际媒体 |
| [制作交接 v2](guide/production-v2.md) | 固定输入、共享预算、获选媒体与可迁移交付 |
| [批量生产](guide/production-batch.md) | 图像／视频依赖、规模预算、预检与安全续接 |
| [本地 Vendor](../vendor/README.md) | 第三方 Skill/工具的声明、安装与锁定字段 |
| [维护与本地验证](guide/maintenance.md) | 本地 CI、提交与推送钩子、宿主入口同步、测试 |

## design · 创作方法

| 文档 | 内容 |
|---|---|
| [创作体系](design/creative-production.md) | 从改编到镜头、资产、生成、后期和交付 |
| [工程化制作](design/engineering-production.md) | 从工程化 Profile、素材复用到豆包生产、章节接续和后期 |
| [连续性与声音](design/continuity-and-sound.md) | 剧本化、跨 AI 片段状态契约、BGM/环境声与时间线策略 |
| [记忆与学习](design/memory-and-learning.md) | 角色身份、任务上下文、素材观察、能力卡、评测与安全边界 |
| [Profile 与验证](design/profiles-and-validation.md) | 业务定制、纸面样例和验证路线 |
| [Remotion](design/remotion.md) | VSC 时间线到可编辑预演和确定性渲染的本机接口 |

## architecture · 架构

| 文档 | 内容 |
|---|---|
| [通用架构](architecture/reference-architecture.md) | 产物、活动、决策、策略、版本、事件与可扩展内核 |
| [生成适配器边界](architecture/generation-adapters.md) | 供应商中立的生成接缝、每次生成需记录的字段与已实现的媒体检查适配器 |
| [豆包固定音色语音](architecture/doubao-speech.md) | TTS 请求绑定、流式记录、媒体检查与权限边界 |
| [豆包 Seed-Audio](architecture/doubao-audio.md) | MediaKit 音频任务、恢复与实际验证状态 |
| [内核重构](architecture/kernel-refactor.md) | v0.6 从分散声明到可验证内核：结构问题与扩展规则 |
| [工作流内核](../workflow/README.md) | 单一事实来源、稳定查询/校验接口与扩展方式 |
| [ADR](adr/README.md) | 影响长期结构的可追溯决定 |

## governance · 治理与证据

| 文档 | 内容 |
|---|---|
| [Vendor 治理](governance/vendor-governance.md) | 本地开源 Skill/工具的审核、锁定和同步 |
| [Vendor 候选更新](governance/vendor-updates.md) | 手动候选脚本、Skill 分析、采用与快照保留 |
| [专业制作证据](governance/production-evidence.md) | 媒体范围、真实成片检查与人工审片 |

## research · 研究依据

| 文档 | 内容 |
|---|---|
| [思想基础与跨行业研究](research/foundations.md) | 哲学、设计、影视、软件和系统工程的共性与边界 |
| [来源与证据边界](research/sources.md) | 公开研究资料与项目推论的边界 |

## releases · 版本记录

| 文档 | 内容 |
|---|---|
| [v0.17.1](releases/v0.17.1.md) | 缺少火山 key 时只提示配置火山方舟 Agent 版本 API Key |
| [v0.17.2](releases/v0.17.2.md) | Agent Plan 个人版专属地址与视频档位离线预检，明确 AFP 和语音能力边界 |
| [v0.17.0](releases/v0.17.0.md) | 火山凭证统一为方舟 Agent Plan 专属 key，旧变量提示已更换 |
| [v0.16.0](releases/v0.16.0.md) | 系列选片清单编译，与素材库权属及已批准选片一致 |
| [v0.15.0](releases/v0.15.0.md) | 批准 run 不因单镜选片失效、批量续查、生成记录导出、关系查询与静帧运镜 |
| [v0.14.0](releases/v0.14.0.md) | 系列正式运行、统一执行入口、媒体转存与权属决定 |
| [v0.13.1](releases/v0.13.1.md) | 火山图像／视频 Provider 实现与离线契约检查 |
| [v0.13.0](releases/v0.13.0.md) | 数据库连续短剧 Profile、按镜上下文与离线任务接口 |
| [v0.12.0](releases/v0.12.0.md) | 制作交接、正式运行与交付验证 |
| [v0.11.1](releases/v0.11.1.md) | 缺钥时提醒配置位置与加载方式 |
| [v0.11](releases/v0.11.md) | 工程化 Profile、批量生产、20 类规格与声音接口 |
| [v0.9](releases/v0.9.md) | 创作目标、批准版本、依赖与范围验收、试用评测和真实媒体证据 |
| [v0.10](releases/v0.10.md) | 豆包适配器、素材复用、创作方法检索和集／场衔接 |
| [v0.2](releases/v0.2.md) | 架构如何落为插件骨架 |
