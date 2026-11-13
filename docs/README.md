# VSC 文档

文档按读者分组。工作流的事实来源是 [`workflow/`](../workflow/README.md)；文档解释它，不另立规则。

## guide · 使用与维护

| 文档 | 内容 |
|---|---|
| [AI 客户端接入](guide/workspace-setup.md) | Codex、Claude Code、Grok Build、Kimi Code、ZCode 的入口与验证 |
| [资源配置与画布](guide/resource-settings.md) | 全局模型配置、默认用途、官方更新与素材关系 |
| [创作工作台](guide/creative-workbench.md) | 场镜资料、资产使用实例、跨镜声音、专业动作与关系查阅 |
| [命令行使用](guide/cli.md) | 新建项目、登记与批准、契约校验、记忆与学习、Profile、外部交接 |
| [素材复用与检索](guide/reuse-and-search.md) | 跨作品素材库、公开创作方法、内容查找与集／场衔接 |
| [制作规格包](guide/asset-recipes.md) | 20 类可复用规格，区分文本规格与实际媒体 |
| [制作交接 v2](guide/production-v2.md) | 固定输入、共享预算、获选媒体与可迁移交付 |
| [批量生产](guide/production-batch.md) | 图像／视频依赖、规模预算、预检与安全续接 |
| [本地 Vendor](../vendor/README.md) | 第三方 Skill/工具的声明、安装与锁定字段 |
| [维护与本地验证](guide/maintenance.md) | 本地 CI、提交与推送钩子、宿主入口同步、测试 |
| [代码结构与目录职责](guide/code-structure.md) | 命令分组、领域实现、工程维护、规范与文件归属 |
| [测试工程](../tests/README.md) | 领域／层级目录、unittest 配置、公共夹具、受影响选择与最终门禁 |

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
| [工作流内核](../workflow/README.md) | 单一事实来源、稳定查询/校验接口与扩展方式 |

## governance · 治理与证据

| 文档 | 内容 |
|---|---|
| [Vendor 治理](governance/vendor-governance.md) | 本地开源 Skill/工具的审核、锁定和同步 |
| [Vendor 候选更新](governance/vendor-updates.md) | 手动候选脚本、Skill 分析、采用与快照保留 |
| [专业制作证据](governance/production-evidence.md) | 媒体范围、真实成片检查与人工审片 |
