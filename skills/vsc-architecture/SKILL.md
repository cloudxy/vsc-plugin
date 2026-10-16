---
name: vsc-architecture
description: "Use when a VSC user wants to review or improve VSC, a Profile, an adapter, or a business extension without confusing an architecture proposal with an implemented capability."
---

# VSC 架构维护

这是 VSC 的维护入口，不是短剧创作阶段。先运行：

```bash
python3 scripts/vsc_kernel.py doctor
python3 scripts/vendor_skills.py --resolve architecture
```

若 `mattpocock-skills` 已安装，直接阅读其中的 `improve-codebase-architecture`，以及其要求的 `codebase-design`、`grilling` 和 `domain-modeling` 原始 Skill。它们为 VSC 的架构审查提供方法，不会覆盖 VSC 的术语、ADR、权属、人工批准或 Vendor 生命周期规则。

审查前先读 `GLOSSARY.md`、相关 `docs/adr/` 与 `workflow/`。用模块、接口、实现、深度、接缝、适配器、杠杆和局部性描述问题；区分“已有实现”“候选方案”“尚未实现”。临时审计、探索稿与中间产物写入系统临时目录；形成需要执行或持续维护的方案后，保存到本机 `docs/plans/`，明确候选／已实施状态；该目录受 Git 忽略，计划及其索引不提交、不打包、不写入公开文档索引。只有用户明确要求发布的规范或使用说明才单独整理到公开文档；维护方案不冒充作品交付物。

上游 Skill 更新在切换前自动生成 `vendor/.reviews/` 中的分析；资源配置页的一次“更新”决定即为采用授权，不额外增加人工审核轮次。新增 Skill 在显式路由前不能使用；被删除的已路由 Skill 不得静默消失，须在报告中决定保留已批准快照、替换路由或退役。

## 案例驱动维护与提交

VSC 通过本机作品（`projects/`）发现问题，再改进 VSC 本身。本机钩子与命令见 [维护与本地验证](../../docs/guide/maintenance.md)。

1. 定位：写明作品、阶段、产物 ID 与现象，以及负责的规则、Skill、契约或脚本。修复退回最早的责任环节，不在作品里绕过规则。
2. 修改：直接在 `main` 上修改，不建分支或 PR。只改工作流源码（`skills/`、`agents/`、`workflow/`、`profiles/`、`templates/`、`scripts/`、`tests/`、`docs/` 等）；作品、vendor 源码与本机配置不进仓库。`workflow/hosts.json` 声明的宿主入口不手改，改动来源后运行 `python3 -B scripts/vsc_hosts.py sync`。行为变化须补测试。
3. 验证：纯文案只检查内容、链接与格式；用户指定功能点位的小修改只运行相关测试和必要检查，提交／推送不要求全量。小修改使用 `VSC_CI_SCOPE=targeted`，必要时用 `VSC_CI_TESTS` 指定模块／方法；未指定时按推送差异选择受影响测试。跨模块、契约、关系模型或影响不明的改动才在最终推送阶段执行一次全量。启用钩子时由 pre-push 完成，不提前重复；未启用时手动执行同等范围的检查。无法验证的部分如实说明。
4. 提交：钩子失败时按维护指南处理，不得绕过。提交说明沿用 `feat:`/`fix:`/`refactor:`/`docs:`/`chore:`，正文写现象、根因与验证。仓库公开：提交说明和文件中不写作品原文、人物、素材或其他受限内容，按 `capability export` 的去项目化标准描述。
5. 推送：`git push origin main`。行为、契约或 schema 变化时，更新 `.zcode-plugin/plugin.json` 的版本号，并在 `docs/releases/` 写明变化。

## 制作交接 v2

修改关系模型、资源用途、生成输入或数据库迁移时，先读取维护子路由 [vsc-schema-review](../vsc-schema-review/SKILL.md)，执行结构检查与相关真实数据库测试。资源面板属于内建应用，Skill 只定义维护 SOP。

production-v2 的规范、显式迁移和验证入口见新增内核协议。维护时保留旧 Profile 快照和真实批准；新 DAG 验证缓存仅单次操作有效，不跨命令掩盖 SHA 漂移。

规则见 [制作协议](../../workflow/production-v2.md)，操作见 [v2 指南](../../docs/guide/production-v2.md)。
