# 12 · Vendor 候选更新与 Skill 生命周期

## 目标

VSC 要持续发现开源项目的新能力，但“上游最新”不能直接等同于“VSC 当前可安全、可用地采用”。因此更新分成两个状态：

```text
当前已批准 Vendor ──不被定时任务覆盖──→ VSC 直接使用
             │
             └── 每日拉取 HEAD → 候选快照 → Skill 差异分析 → 人工决定 → 显式固定新 revision → 重新安装
```

这保留了可复现的当前版本，并让新增、变化和删除都可审计。

## 谁负责什么

| 模块 | 职责 |
| --- | --- |
| `vendor/sources.lock.json` | 来源、当前固定 revision、许可证和候选更新策略；schema 4。 |
| ZCode `plugin-updater` | 每日下载候选、保存快照、调用分析、写日志与按每来源 90 天/3 份清理。 |
| `scripts/vendor_review.py` | 对比当前 Vendor 与候选中所有 `SKILL.md`，输出机器 JSON 与人读 Markdown；不更新任何活跃内容。 |
| `vendor/.reviews/` | 本机报告目录，不进入 Git。 |
| ZCode 审查任务 | 仅在出现候选时阅读结构报告与必要 diff，补充“可否继续引用/是否值得新增路由/删除处置”的语义评估；没有采用权限。 |
| 责任人 | 判断语义/兼容性、决定是否采用候选、是否新增路由、是否保留删除 Skill。 |

## 三种变化

| 变化 | 默认结论 | 必须的下一步 |
| --- | --- | --- |
| `changed_referenced_skill` | 阻止自动采用 | 检查方法、输入/输出、运行环境、权限和 VSC 契约；通过后才更新 revision。 |
| `new_skill` | `unrouted_pending_review` | 评估是否补足 VSC 能力；若采用，显式添加 Vendor 路由、运行环境与测试，运行 `vsc_kernel.py doctor`。 |
| `deleted_referenced_skill` | 保留当前活跃版本 | 在“保留最后批准快照 / 替换路由 / 退役”中作决定；不能让当前路由悄然变成缺失文件。 |

`vendor_review.py` 不会声称能仅凭文件散列判断创作方法是否合理。它准确报告结构变化和当前路由影响，并把语义判断留给负责审查的人或受控的 ZCode 分析任务。

## ZCode 每日任务

在 ZCode 自动化中创建一个名为“VSC Vendor 候选审查”的每日任务，cron 为 `45 9 * * *`（避开 09:30 的插件同步）。工作目录为 VSC 插件根目录，任务先且只先执行：

```bash
/bin/bash /Users/xuyun/.zcode/plugin-updater/scripts/vsc-vendor-maintenance.sh
```

执行后仅在输出含 `CANDIDATE` 时，读取本次生成的 `vendor/.reviews/<source>-<revision>.md`、对应 JSON 和候选/基线快照中必要的原始 `SKILL.md`。将语义评估写为同名 `.assessment.md`：已路由 Skill 是否仍可引用、每个新增 Skill 是否值得路由及理由、每个已删除引用应保留/替换/退役的建议、所需运行环境与测试。它不得编辑 `vendor/<source>`、`sources.lock.json`、VSC 路由、角色或命令，也不得执行候选中的脚本。

这让自动化完成“发现和分析”，但不越权完成“采用”。若 ZCode 当前没有电脑使用权限，可先手动执行该入口；任务配置内容和入口不依赖系统 crontab。

## 采用流程

1. 阅读 `vendor/.reviews/<source>-<candidate>.md` 和必要的原始 `SKILL.md` diff。
2. 记录兼容性、权属、运行环境、路由和删除处置结论。
3. 明确将 `sources.lock.json` 中该来源的 40 位 `revision` 改为已批准候选。
4. 执行 `python3 scripts/vendor_sync.py --install <source>`，使 active Vendor 与固定 revision 一致。
5. 执行 `python3 scripts/vendor_sync.py --write-declaration`、`python3 scripts/vsc_kernel.py doctor` 和相关测试；再决定是否提交 VSC 配置变更。

任何候选分析失败、下载失败或未完成审查时，当前 active Vendor 保持不变。

## 架构 Skill 的直接使用

`mattpocock-skills` 是 MIT 来源，VSC 稀疏安装四个互相配合的原始 Skill：`improve-codebase-architecture`、`codebase-design`、`grilling` 与 `domain-modeling`。使用 `/vsc-architecture` 时，先解析本机 Vendor 路由，再按上游方法读取它们；VSC 的 `GLOSSARY.md` 和 ADR 仍是本项目的领域真相。

```bash
python3 scripts/vendor_sync.py --install mattpocock-skills
python3 scripts/vendor_skills.py --resolve architecture
```
