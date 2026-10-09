---
name: vsc-vendor
description: "Use when the user wants to assess, install, manually check updates, or review local third-party open-source skills/tools for VSC without committing them to Git."
---

# VSC Vendor 管理

第三方 Skill 和工具可作为本地 `vendor/` 缓存或完整组件管理；VSC 源码仓库只提交 `vendor/README.md`、机器可读的 `vendor/sources.lock.json` 及从它生成的 `vendor/THIRD_PARTY.md`，绝不提交下载目录本身。VSC 核心保持 MIT，但可直接使用 MIT、Apache-2.0、AGPL-3.0 等其他许可证的开源工具与完整本地组件。根目录 MIT 只覆盖 VSC 自研部分，不能把上游代码、Skill 正文或模型资产伪装成 MIT。

## 先说清边界

“不上传 Git”只减少再次分发第三方代码的风险，**不是**商业使用的许可。不能因为 GitHub 上看得到、带有“open source”描述，或只在本地使用，就默认允许商用、SaaS、模型训练、声音克隆、再分发或修改。许可证不明时默认拒绝自动安装；涉及商业化、素材/人物/声音权利或复杂 copyleft 时要求责任人或专业意见。

## 审核—锁定—同步

1. 先收集来源 URL、完整 commit、LICENSE 原文/链接、SPDX 标识、用途、是否携带模型权重/素材、作者或组织、NOTICE 和上游依赖。
2. 说明许可证义务与不确定项；不要把 SPDX ID 当法律结论。没有明确许可证时按受版权保护处理。
3. 在 `vendor/sources.lock.json` 声明来源。必须固定到 40 位 commit，并写 `usage.mode`（reference_only/external_tool/local_component/external_service/adapter_protocol）、接口、是否修改、责任人和 `redistribution=local_only`。`local_component` 表示直接在本地使用完整上游项目，而不是仅作参考。再运行 `python3 scripts/vendor_sync.py --write-declaration` 生成供人阅读的 `vendor/THIRD_PARTY.md`。
4. 先运行 `python3 scripts/vendor_sync.py --check` 与 `--plan`。它们不联网、不下载。
5. 只有用户明确执行 `python3 scripts/vendor_sync.py --install [来源 id]`（或兼容的 `--sync`）才下载；脚本不会自动安装或配置全局 cron。

## 下载后直接使用 Skill

下载不是终点。安装完成后运行 `python3 scripts/vendor_skills.py --scan`，在本机生成 `vendor/skill-catalog.json`。当用户进入某个创作或维护阶段，运行 `python3 scripts/vendor_skills.py --resolve adapt|script|direct|assets|produce|sound|post|architecture`：

1. 对 `guide` 条目，读取输出路径对应的**上游原始** `SKILL.md`，并直接采用其方法；不复制到 VSC 核心。
2. 对 `runtime: ...` 条目，先检查所列 CLI、MCP、密钥或依赖；就绪后才调用它的原生能力。
3. 将结果映射回 VSC 的改编、剧本、ShotPlan、资产、Cue、时间线等产物，不让上游 Skill 绕过 VSC 的批准、连续性或权属边界。

## 手动候选更新：先分析，后采用

用户按需运行 `scripts/vsc-vendor-maintenance.sh`，不依赖 ZCode 定时任务。`--plan` 只预览，不联网或写入；不加此参数则执行一次并退出。项目 `vendor_watch.py` 保存各来源的完整 **Skill 资源包候选**并调用 `vendor_review.py`，把 JSON 与 Markdown 报告写入本机 `vendor/.reviews/`。资源包包含 Skill 子目录、递归显式本地引用、根 LICENSE/NOTICE 与依赖声明。脚本不自动调用模型；用户要求语义审查时，由本 Skill 阅读指定报告与必要资源 diff，写同名 `.assessment.md`，说明已引用 Skill 是否兼容、新增 Skill 是否值得路由、删除引用的处置建议以及环境与测试要求。评估没有采用权限；不覆盖已批准的 `vendor/<source>`，不改写 `sources.lock.json`，不新增路由或执行候选内容。

- 已路由 Skill 的正文或支持资源、许可证、依赖声明有变化：报告标为 `changed_referenced_skill`，必须判断其方法、输入/输出、运行环境、权限与 VSC 契约是否仍兼容。不要只读 `SKILL.md` diff。
- 新增 Skill：报告标为 `new_skill`，默认 `unrouted_pending_review`；只有人工显式把它接到 VSC 阶段并通过 `vsc_kernel.py doctor`，才能直接使用。
- 已路由 Skill 被删除：报告要求“保留最后批准快照、替换路由或退役”三选一；候选维护不会静默删除当前活跃版本。
- 每次执行时按每来源 90 天、最多 3 份清理候选资源包（基线也计入）；不运行脚本就不后台清理，过期文件在下次运行时处理。它们用于恢复 Skill 文件，不等于完整仓库或已安装运行环境备份，不进入 VSC Git。
- 下载状态与分析状态独立；`failed`、未完成或报告丢失必须重试。正文相对引用缺失、绝对文件输入、符号链接／特殊文件或单文件超限时，逐 Skill 报告不可用，被拒资源不读取／物化；不能把此类候选说成完整可执行备份。资源总量超限或完整性不一致时任务失败关闭，不自动降级成只比较正文。
- 代码围栏示例、站点根相对 URL 和 `/skill` 命令不当作源资源；运行时配置／输出目录仅记录前置条件，未读取、未打包、未验证就绪。不要把真实缺失的正文资源当成例子忽略，也不要跟随链接补下载。

本机调用：`bash scripts/vsc-vendor-maintenance.sh [--plan] [--source ID] [--maintenance-root /path/to/data]`。默认数据在 `vendor/.maintenance/`，`--updater-root` 是旧参数兼容别名。核对本次退出码及报告，失败不得报告成功。仅变更项目文件不会删除已存在的宿主任务；不创建或恢复定时任务。旧缓存复用及手动审查流程见 `docs/12-vendor-candidate-updates.md`。

需把通过审查的候选投入使用时，先由责任人更新相应来源的固定 revision，再执行 `vendor_sync.py --install <来源>`；随后重新生成声明并运行 `vsc_kernel.py doctor`。不要把“上游有新提交”当作“已批准升级”。

## 锁定记录范例

```json
{
  "id": "example-skill",
  "type": "git",
  "url": "https://host.example/org/example-skill.git",
  "revision": "40位完整commit",
  "license_spdx": "MIT",
  "license_evidence": "https://host.example/org/example-skill/blob/<commit>/LICENSE",
  "purpose": "仅本地辅助分镜草稿，不进入交付物",
  "owner": "项目责任人",
  "redistribution": "local_only",
  "usage": {"mode": "local_component", "interface": "cli", "modified": false}
}
```

AGPL 等强 copyleft 项目可以作为独立工具或 `local_component` 直接使用；如果修改后提供网络服务或把上游代码融合进可发布的 VSC 模块，必须处理相应许可证义务，不能将其标为仅 MIT。不要替用户自动下载许可证不明来源、配置全局 cron、保存凭据，或将 vendor 文件强制加入 Git。
