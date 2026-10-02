---
name: vsc-vendor
description: "Use when the user wants to assess, install, update, or schedule local third-party open-source skills/tools for VSC without committing them to Git."
---

# VSC Vendor 管理

第三方 Skill 和工具可作为本地 `vendor/` 缓存或完整组件管理；VSC 源码仓库只提交 `vendor/README.md`、`vendor/sources.lock.json`、安装指引与必要的 NOTICE 模板，绝不提交下载目录本身。VSC 核心保持 MIT，但可直接使用 MIT、Apache-2.0、AGPL-3.0 等其他许可证的开源工具与完整本地组件。根目录 MIT 只覆盖 VSC 自研部分，不能把上游代码、Skill 正文或模型资产伪装成 MIT。

## 先说清边界

“不上传 Git”只减少再次分发第三方代码的风险，**不是**商业使用的许可。不能因为 GitHub 上看得到、带有“open source”描述，或只在本地使用，就默认允许商用、SaaS、模型训练、声音克隆、再分发或修改。许可证不明时默认拒绝自动安装；涉及商业化、素材/人物/声音权利或复杂 copyleft 时要求责任人或专业意见。

## 审核—锁定—同步

1. 先收集来源 URL、完整 commit、LICENSE 原文/链接、SPDX 标识、用途、是否携带模型权重/素材、作者或组织、NOTICE 和上游依赖。
2. 说明许可证义务与不确定项；不要把 SPDX ID 当法律结论。没有明确许可证时按受版权保护处理。
3. 责任人批准后才写入 `vendor/sources.lock.json`。必须固定到 40 位 commit，并写 `usage.mode`（reference_only/external_tool/local_component/external_service/adapter_protocol）、接口、是否修改、`review.status=approved`、责任人和日期；`redistribution=local_only`。`local_component` 表示直接在本地使用完整上游项目，而不是仅作参考。
4. 先运行 `python3 scripts/vendor_sync.py --check` 与 `--plan`。它们不联网、不下载。
5. 只有管理员明确执行 `--sync`（或配置经批准的本机计划任务）才下载；更新 commit/许可证/用途后重新审核。

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
  "review": {"status": "approved", "by": "责任人", "at": "YYYY-MM-DD"}
}
```

AGPL 等强 copyleft 项目可以作为独立工具或 `local_component` 直接使用；如果修改后提供网络服务，必须记录网络源码提供义务的评估/入口，并由负责人或专业人士确认。若把上游代码融合进可发布的 VSC 模块，必须保留该模块的许可证边界与再分发义务，不能将其标为仅 MIT。不要替用户自动批准、下载许可证不明来源、配置全局 cron、保存凭据，或将 vendor 文件强制加入 Git。
