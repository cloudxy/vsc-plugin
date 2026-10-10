---
name: vsc-produce
description: "Plan and review provider-neutral image, image-to-video and audio take production from approved VSC specifications."
---

# VSC 制作

只根据已批准的 ShotPlan、AssetBible、声音方案和项目策略生产候选 take。每个任务记录输入版本、参考资产、适配器、参数摘要、预算、输出路径和连续性检查；图像、视频、音频候选都不是自动选中版本。供应商 API、密钥、收费、许可和平台策略由适配器及项目策略负责；本技能不假设任何一家模型存在。

先运行 `python3 scripts/vendor_skills.py --resolve produce`。已安装的 OpenMontage 生成/视频理解 Skill 会被直接列出；只有其声明的 MCP、CLI、凭据和项目授权均已就绪，才读取原始 `SKILL.md` 并调用原生工作流。未就绪时保留为可选能力，不伪造供应商调用或生成结果。

## 一键成片模式：由用户选择

用户想“一句话直接出片”时，说明两种模式，由用户决定：

1. **VSC 受控模式（默认）**：经过创作委托、剧本、镜头、资产与人工批准，产物可追溯、可进入交付。
2. **MoneyPrinterTurbo 一键成片**：由主题自动写稿、找素材、配音、加字幕与 BGM，直接出片；不经过 VSC 的任何关卡，成片只能作为候选或参考，不能直接登记为已批准交付物。

用户选择第 2 种后：先运行 `python3 -B scripts/mpt_adapter.py prepare`，再阅读 `vendor/moneyprinterturbo/docs/skill/SKILL.md` 并运行其辅助脚本，必须加 `--root <工作流根目录>/vendor/moneyprinterturbo`，使用 VSC 固定版本，而不是另行下载上游 main。该 Skill 要求“不征求确认”；在 VSC 中，用户选择此模式即为确认，但开始前仍要让用户决定字体与 BGM：默认字体是 Noto Sans SC；带 `assets-` 前缀的字体与 BGM 先请用户阅读 `vendor/THIRD_PARTY.md` 中的须知再决定。付费素材源的 `--confirm-*-charge` 只能在用户明确同意后添加。
