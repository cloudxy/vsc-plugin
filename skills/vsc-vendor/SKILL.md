---
name: vsc-vendor
description: "Use when the user wants to assess, install, manually check updates, or review local third-party open-source skills/tools for VSC without committing them to Git."
---

# VSC Vendor 管理

第三方 Skill 和工具只装在本机 `vendor/`，不进 Git。操作命令与锁定字段见 [vendor/README.md](../../vendor/README.md)，`usage.mode` 与许可证原则见 [Vendor 治理](../../docs/governance/vendor-governance.md)，各来源的用途与须知见 [THIRD_PARTY.md](../../vendor/THIRD_PARTY.md)。

## 智能体须遵守

- 许可证不明时默认拒绝安装；涉及商业化、素材/人物/声音权利或复杂 copyleft 时，要求责任人或专业意见。不能因为 GitHub 上看得到、标着 open source 或只在本地使用，就推定允许商用、SaaS、训练、声音克隆、再分发或修改。
- 审核新来源时先收集来源 URL、完整 commit、LICENSE 原文/链接、SPDX 标识、用途、是否携带模型权重/素材、作者或组织、NOTICE 和上游依赖，说明许可证义务与不确定项，再按 vendor/README.md 声明与安装。
- 只有用户明确要求才执行 `--install`；不要替用户配置全局 cron、保存凭据，或把 vendor 文件强制加入 Git。

## 下载后直接使用 Skill

下载不是终点。安装完成后运行 `python3 scripts/vendor_skills.py --scan`，在本机生成 `vendor/skill-catalog.json`。当用户进入某个创作或维护阶段，运行 `python3 scripts/vendor_skills.py --resolve adapt|script|direct|assets|produce|sound|post|architecture`：

1. 对 `guide` 条目，读取输出路径对应的**上游原始** `SKILL.md`，并直接采用其方法；不复制到 VSC 核心。
2. 对 `runtime: ...` 条目，先检查所列 CLI、MCP、密钥或依赖；就绪后才调用它的原生能力。
3. 将结果映射回 VSC 的改编、剧本、ShotPlan、资产、Cue、时间线等产物，不让上游 Skill 绕过 VSC 的批准、连续性或权属边界。

## 审查候选更新

候选更新的机制与采用流程见 [Vendor 候选更新](../../docs/governance/vendor-updates.md)。用户要求语义审查时，阅读指定报告与必要的资源 diff，写同名 `.assessment.md`：已引用 Skill 是否兼容、新增 Skill 是否值得路由、删除引用的处置建议，以及环境与测试要求。审查没有采用权限：不改 `vendor/<source>`、`sources.lock.json`、路由，也不执行候选内容。不要把“上游有新提交”当作“已批准升级”。
