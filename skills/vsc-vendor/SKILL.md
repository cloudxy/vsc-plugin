---
name: vsc-vendor
description: "Use when the user wants to assess, install, manually check updates, or review local third-party open-source skills/tools for VSC without committing them to Git."
---

# VSC Vendor 管理

第三方 Skill 和工具只装在本机 `vendor/`，不进 Git。操作命令与锁定字段见 [vendor/README.md](../../vendor/README.md)，`usage.mode` 与许可证原则见 [Vendor 治理](../../docs/governance/vendor-governance.md)，各来源的用途与须知见 [THIRD_PARTY.md](../../vendor/THIRD_PARTY.md)。

评估字幕、声音、表演与提示词候选时，先查[固定来源及拒绝范围](../../docs/governance/vendor-governance.md#candidate-assessments)和[分发边界](../../docs/governance/vendor-governance.md#distribution-boundary)；供应商接入与独立负向字段按[适配器评估](../../docs/architecture/generation-adapters.md#provider-assessment)。只读评估、已安装、已路由、离线编译和线上可用分别报告，不将同名来源或未映射参数当可用。

## 智能体须遵守

- 许可证不明时默认拒绝安装；涉及商业化、素材/人物/声音权利或复杂 copyleft 时，要求责任人或专业意见。不能因为 GitHub 上看得到、标着 open source 或只在本地使用，就推定允许商用、SaaS、训练、声音克隆、再分发或修改。
- 审核新来源时先收集来源 URL、完整 commit、LICENSE 原文/链接、SPDX 标识、用途、是否携带模型权重/素材、作者或组织、NOTICE 和上游依赖，说明许可证义务与不确定项，再按 vendor/README.md 声明与安装。
- 只有用户明确要求才执行 `--install`；不要替用户配置全局 cron、保存凭据，或把 vendor 文件强制加入 Git。

## 下载后直接使用 Skill

下载不是终点。安装完成后运行 `python3 scripts/maintenance/vendor_skills.py --scan`，在本机生成 `vendor/skill-catalog.json`。当用户进入某个创作或维护阶段，运行 `python3 scripts/maintenance/vendor_skills.py --resolve adapt|script|direct|assets|produce|sound|post|architecture`：

1. 对 `guide` 条目，读取输出路径对应的**上游原始** Skill、指南或角色方法文件，并直接采用适用方法；不复制到 VSC 核心，不替换 VSC 角色身份与权限。已路由的非 `SKILL.md` 原文同样进入候选资源包及变化/删除检查。
2. 对 `runtime: ...` 条目，先检查所列 CLI、MCP、密钥或依赖；就绪后才调用它的原生能力。
3. 将结果映射回 VSC 的改编、剧本、ShotPlan、资产、Cue、时间线等产物，不让上游 Skill 绕过 VSC 的批准、连续性或权属边界。

## 审查候选更新

资源配置页的工具更新使用简化入口 `python3 scripts/maintenance/provider_sync.py check`。
显示当前／最新固定版本后，用户点击“更新”或运行
`python3 scripts/maintenance/provider_sync.py update --tool <ID> --revision <检查所得固定版本> --actor <操作人>`
即为本次采用授权；后台下载、分析、校验和切换，不再要求第二轮人工确认。
“不更新”保持原状，无需执行命令。当前支持官方 Ark CLI 的 Git Skill 源码及已安装的登记 Git 来源；
后者单独标明来源身份，不能冒称模型供应商官方包。另支持 `volcengine-ark-cli-release` 官方 npm 分发包的
SHA-512／平台 SHA-256 校验下载及原子指针切换；保留旧版本，不运行 postinstall／bootstrap／CLI，不加入 PATH。
官方包的来源与字节校验不等于签名验证或封闭代码审计，CLI 保持交互／方法参考，不能冒称自动生产执行器。
受控生产的 `official_sdk` 使用固定且已离线核验的官方 Python SDK，独立于 Skill／CLI 更新，沿既有任务与预算执行。
宿主内置工具由宿主管理；独立 Skill 站点与其他未登记分发格式明确返回尚不支持。
下载／结构兼容检查失败保留旧版；已引用 Skill 被删除时本次更新失败并保留旧版，不再添加人工审批队列。
更新不执行候选代码、不调用生成模型、不更改凭证与套餐；在途任务或提交未知时等待结束后重试。
检查依赖网络但不调用模型鉴权，模型列表刷新与工具版本更新分别报告。

候选更新的机制与采用流程见 [Vendor 候选更新](../../docs/governance/vendor-updates.md)。用户只要求语义审查时，阅读指定报告与必要的资源 diff，写同名 `.assessment.md`：已引用 Skill 是否兼容、新增 Skill 是否值得路由、删除引用的处置建议，以及环境与测试要求。仅审查没有采用权限：不改 `vendor/<source>`、`sources.lock.json`、路由，也不执行候选内容。用户已点击更新时沿用上面的单次采用授权，不再要求额外批准。
