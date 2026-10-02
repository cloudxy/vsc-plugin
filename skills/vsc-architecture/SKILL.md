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
