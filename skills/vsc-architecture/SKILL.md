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

审查前先读 `GLOSSARY.md`、相关 `docs/adr/` 与 `workflow/`。用模块、接口、实现、深度、接缝、适配器、杠杆和局部性描述问题；区分“已有实现”“候选方案”“尚未实现”。把审计 HTML 写入系统临时目录，不把它冒充为 VSC 交付物。

上游 Skill 的更新必须先经过 `vendor/.reviews/` 中的分析。新增 Skill 在显式路由前不能使用；被删除的已路由 Skill 不得静默消失，须在报告中决定保留已批准快照、替换路由或退役。

## 案例驱动维护与提交

VSC 通过本机作品（`projects/`）发现问题，再改进 VSC 本身。vendor 与作品只在本机，因此验证只在本地进行，不使用线上 CI。

1. 定位：写明作品、阶段、产物 ID 与现象，以及负责的规则、Skill、契约或脚本。修复退回最早的责任环节，不在作品里绕过规则。
2. 修改：直接在 `main` 上修改，不建分支或 PR。只改工作流源码（`skills/`、`agents/`、`commands/`、`workflow/`、`profiles/`、`adapters/`、`templates/`、`scripts/`、`docs/` 等）；作品、vendor 源码与本机配置不进仓库。行为变化须补测试。
3. 验证：运行 `python3 -B scripts/vsc_local_ci.py`，doctor、全部测试、vendor 版本与路由、作品可读性、跟踪文件须全部通过。再用暴露问题的作品重跑对应阶段，确认问题消失；无法重跑时如实说明。
4. 提交：启用 `.githooks` 后，`pre-commit` 每次获取 `origin/main`；需要更新时保存本地修改、合并并恢复暂存状态，然后中止本次提交，检查后重新执行 CI 与提交。获取、合并或恢复失败时不得绕过钩子。提交说明沿用 `feat:`/`fix:`/`refactor:`/`docs:`/`chore:`，正文写现象、根因与验证。仓库公开：提交说明和文件中不写作品原文、人物、素材或其他受限内容，按 `capability export` 的去项目化标准描述。
5. 推送：`git push origin main`。已启用 `.githooks/pre-push` 时推送会再跑一次本地 CI，失败即中止。行为、契约或 schema 变化时同步更新 README 版本与升级说明。
