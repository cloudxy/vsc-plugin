---
name: vsc-architecture
description: "Audit, plan or implement VSC workflow/software improvements, or consolidate reusable maintenance methods. Preserve the requested mode and distinguish proposed capabilities from verified implementation."
---

# VSC 架构维护

这是 VSC 的维护入口，不是短剧创作阶段。**每次进入本技能，先读正文和[执行检查](references/execution-checks.md)，据当前请求与会话已确认范围选择模式，再操作。** 不依赖上一轮聊天记忆恢复规则；参考文件打不开时明确报告，不能声称已完成该检查。

## 任务模式与范围

| 模式 | 典型要求 | 本次交付与操作边界 |
| --- | --- | --- |
| 审查 | 检查完成度、找问题、解释原因 | 读当前实现与证据，必要时在隔离数据做获准范围的验证；交付发现、依据与建议，不据此启动修复 |
| 规划 | 制定／完善执行方案 | 更新私有计划，写清办法、步骤、依赖和验收；计划中的代码、迁移与生产动作仍是将来任务 |
| 实施 | 修复、实现、把规则写入技能等实际变更请求 | 按用户已授权范围修改、验证与交付；实现某项不自动授权整套计划 |

“继续／continue”沿用已有模式和范围，不自动把审查或规划升级为实施。用户已明确要求实施时直接执行，不重复索要同一授权；范围确有无法消除的歧义时，先完成独立的只读工作，仅澄清影响下一步操作的部分。混合请求按子任务分别应用模式。

开始 VSC 维护工作时执行：

```bash
python3 -B scripts/kernel/catalog.py doctor
python3 -B scripts/kernel/catalog.py route architecture
python3 -B scripts/maintenance/vendor_skills.py --resolve architecture
```

架构探索时，若 `mattpocock-skills` 已安装，阅读其中的 `improve-codebase-architecture`，以及其要求的 `codebase-design`、`grilling` 和 `domain-modeling` 原始 Skill；按当前问题采用其方法，不把候选讨论、ADR 修改或实施步骤当作超出本次范围的授权。明确的小范围规则更新不必另起整仓架构探索。VSC 术语、ADR、权属、人工批准与 Vendor 规则继续适用。

涉及面板、阅读、导航、交互或视觉体验时，读取[产品与体验维护](references/product-experience.md)，按任务需要路由 `product-manager` 的问题/验收职责与 `product-designer` 的信息/交互/视觉职责；影视美术继续走 `asset-director`。两者使用相同的角色上下文与记忆协议，不新增创作阶段。上游产品与设计方法从 architecture Vendor 解析结果按需读取。

软件体验维护开始前，按该参考中的[角色方法与能力](references/product-experience.md#角色方法与能力)选择相关职责、输入、交付和退出证据；交付前选用[代表性验收场景](references/product-experience.md#代表性验收场景)检查实际行为。复盘与经验沉淀沿[经验与证据的存放](references/product-experience.md#经验与证据的存放)执行，不将更新方法当作重新实施产品或自动批准项目记忆的授权。

涉及成果展示、接续或存储时，架构责任读取[成果的权威与真实引用](references/product-experience.md#result-authority)，将创作工具的顺序和就近操作落到原领域消费者；实际引用、检查、采用与消费分别核验，文档和卡片数量不能代替成果。

先读 `GLOSSARY.md`、相关 `docs/adr/` 与 `workflow/`，核对当前 HEAD、工作区差异、相关提交和证据适用范围。旧审计不能直接代表新实现；已有提交先核消费者与验收缺口，不重复建设。用模块、接口、实现、深度、接缝、适配器、杠杆和局部性描述问题。

临时审计、探索稿与中间产物放系统 tmp；需要执行或持续维护的方案存入本机 `docs/plans/`，沿已有主题入口按职责组织，当前状态只维护一处。该目录受 Git 忽略，不提交、不打包、不进入公开文档索引。公开 Skill 只保存通用方法，不链接私有计划或复制作品证据。

交付前按[执行检查](references/execution-checks.md)核对任务可执行性、跨计划责任、条件依赖和证据分层；“已有实现／工程已验证／线上已验证／专业效果已验证”分别说明。计划整理不能写成实现交付，测试或发布成功不能替代真实用户批准。

上游 Skill 更新在切换前自动生成 `vendor/.reviews/` 中的分析；资源配置页的一次“更新”决定即为采用授权，不额外增加人工审核轮次。新增 Skill 在显式路由前不能使用；被删除的已路由 Skill 不得静默消失，须在报告中决定保留已批准快照、替换路由或退役。

## 案例驱动维护与提交

**以下修改、提交、推送步骤仅适用于已授权实施的子任务。** 审查和规划在其约定交付完成后结束，不自动进入此流程。

VSC 通过本机作品（`projects/`）发现问题，再改进 VSC 本身；结束的作品不自动承担修片、迁移或试产。工作流或计划自身的问题直接定位相应模块，不伪造作品案例。本机钩子与命令见 [维护与本地验证](../../docs/guide/maintenance.md)。

1. 定位：写明作品、阶段、产物 ID 与现象，以及负责的规则、Skill、契约或脚本。修复退回最早的责任环节，不在作品里绕过规则。
2. 修改：直接在 `main` 上修改，不建分支或 PR。只改工作流源码（`skills/`、`agents/`、`workflow/`、`profiles/`、`templates/`、`scripts/`、`tests/`、`docs/` 等）；作品、vendor 源码与本机配置不进仓库。`workflow/hosts.json` 声明的宿主入口不手改，改动来源后运行 `python3 -B scripts/kernel/hosts.py sync`。行为变化须补测试。
3. 验证：纯文案只检查内容、链接与格式；用户指定功能点位的小修改只运行相关测试和必要检查，提交／推送不要求全量。小修改使用 `VSC_CI_SCOPE=targeted`，必要时用 `VSC_CI_TESTS` 指定模块／方法；未指定时按推送差异选择受影响测试。跨模块、契约、关系模型或影响不明的改动才在最终推送阶段执行一次全量。启用钩子时由 pre-push 完成，不提前重复；未启用时手动执行同等范围的检查。无法验证的部分如实说明。
4. 提交：钩子失败时按维护指南处理，不得绕过。提交说明沿用 `feat:`/`fix:`/`refactor:`/`docs:`/`chore:`，正文写现象、根因与验证。仓库公开：提交说明和文件中不写作品原文、人物、素材或其他受限内容，按 `capability export` 的去项目化标准描述。
5. 推送：`git push origin main`。行为、契约或 schema 变化时，更新 `.zcode-plugin/plugin.json` 的版本号，并在 `docs/releases/` 写明变化。

## 制作交接 v2

修改关系模型、资源用途、生成输入或数据库迁移时，先读取维护子路由 [vsc-schema-review](../vsc-schema-review/SKILL.md)，执行结构检查与相关真实数据库测试。资源面板属于内建应用，Skill 只定义维护 SOP。

production-v2 的规范、显式迁移和验证入口见新增内核协议。维护时保留旧 Profile 快照和真实批准；新 DAG 验证缓存仅单次操作有效，不跨命令掩盖 SHA 漂移。

规则见 [制作协议](../../workflow/production-v2.md)，操作见 [v2 指南](../../docs/guide/production-v2.md)。
