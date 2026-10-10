# Vendor 候选更新与 Skill 生命周期

## 目标

VSC 要持续发现开源项目的新能力，但“上游最新”不能直接等同于“VSC 当前可安全、可用地采用”。因此更新分成两个状态：

```text
当前已批准 Vendor ──不被候选脚本覆盖──→ VSC 直接使用
             │
             └── 手动拉取 HEAD → 候选快照 → Skill 差异分析 → 人工决定 → 显式固定新 revision → 重新安装
```

这保留了可复现的当前版本，并让新增、变化和删除都可审计。

## 谁负责什么

| 模块 | 职责 |
| --- | --- |
| `vendor/sources.lock.json` | 来源、当前固定 revision、许可证和候选更新策略；schema 4。 |
| `scripts/vsc-vendor-maintenance.sh` | 用户按需运行的单次入口，透传退出码；不创建定时任务或常驻后台。`--plan` 不联网、不写入。 |
| `scripts/vendor_watch.py` | 下载固定基线和 HEAD 候选，保存完整 Skill 资源包及分析状态、校验完整性、按每来源 90 天/3 份清理。 |
| `scripts/vendor_bundle.py` | 共用资源包模块：Skill 子树、递归本地引用及根许可证/依赖声明；拒绝越界、符号链接与超限。 |
| `scripts/vendor_review.py` | 对比 Skill 资源包而非仅正文，输出机器 JSON 与人读 Markdown；不更新任何活跃内容。 |
| `vendor/.reviews/` | 本机报告目录，不进入 Git。 |
| 手动调用 `/vsc-vendor` | 根据用户指定报告与必要 diff，补充“可否继续引用/是否值得新增路由/删除处置”的语义评估；没有采用权限。 |
| 责任人 | 判断语义/兼容性、决定是否采用候选、是否新增路由、是否保留删除 Skill。 |

## 三种变化

| 变化 | 默认结论 | 必须的下一步 |
| --- | --- | --- |
| `changed_referenced_skill` | 阻止自动采用 | 检查方法、输入/输出、运行环境、权限和 VSC 契约；通过后才更新 revision。 |
| `new_skill` | `unrouted_pending_review` | 评估是否补足 VSC 能力；若采用，显式添加 Vendor 路由、运行环境与测试，运行 `vsc_kernel.py doctor`。 |
| `deleted_referenced_skill` | 保留当前活跃版本 | 在“保留最后批准快照 / 替换路由 / 退役”中作决定；不能让当前路由悄然变成缺失文件。 |

每条 Skill 变化同时列出具体资源变化。正文没变但 `rules.md`、脚本、参考、资产、LICENSE、NOTICE 或依赖声明变化时，也必须审查。报告格式升级为 `vsc.vendor-skill-analysis/v2`，原 `change_count`、变化分类与路由处置字段保留；`before_sha256`/`after_sha256` 现在是资源包散列，详细文件证据见 `resources`/`bundles`。

`vendor_review.py` 不会声称能仅凭文件散列判断创作方法是否合理。它准确报告结构变化和当前路由影响，并把语义判断留给负责审查的人或用户手动调用的 `/vsc-vendor`。脚本不自动启动模型。

## 资源包、失败恢复与保留边界

候选格式为 `vsc.vendor-skill-candidate/v2`，记录资源闭包算法版本。对于可用 Skill，保存目录内全部非忽略文件、递归显式本地引用、仓库根许可证/NOTICE/依赖声明，保留执行位，记录 SHA-256；不运行任何候选内容。URL 不下载，Markdown 围栏示例不解析成真实依赖；`/docs/...`、`/v1/...` 网站端点和 `/skill` 命令不当作本机路径。运行时配置及输出目录只记录外部前置条件，不读取／打包，也不声称已就绪。

真实正文相对引用缺失、绝对文件输入或越界、符号链接／特殊文件、单文件超过 8 MiB 时，报告逐 Skill 的 `unusable_skills` 并阻止采用；不会让一个坏 Skill 掩盖其他 Skill 的分析。被拒绝资源不读取或物化，只保留拒绝元信息以重现完整性诊断；这些候选**不具有该 Skill 的完整备份／就绪能力**。总量超过 64 MiB 或 5,000 文件仍使整个维护失败关闭。可用资源包能恢复 Skill 文件，**不是完整仓库、依赖运行环境或权重备份**；需要整仓恢复时仍按固定 commit 重新安装。

下载资源包与分析分别存储：`.vsc-candidate.json` 表示已保存，`.analysis.json` 表示 `pending` / `failed` / `completed`。分析失败或报告被删除后，再次执行会复用完整候选并重试；只有报告存在且分析格式、当前基线匹配时，才输出 `UNCHANGED-CANDIDATE`。资源被篡改会拒绝复用。旧 v1 单正文快照不用于分析，维护时重建 v2。

每次维护运行时执行 90 天与最多 3 份两个清理条件，按来源计算，基线也计入；过期或超额快照清理不影响活跃 `vendor/<source>`。不运行脚本时没有后台清理，文件可能超过 90 天，下一次运行时才处理。保留策略不允许设置超过此上限。被上游删除的已路由 Skill 仍留在活跃批准版本中，不因候选清理而退役。

## 手动执行脚本

策略为 `scheduler: manual`。不创建 ZCode 自动化、cron 或 launchd 任务。在 VSC 插件根目录执行：

```bash
# 只验证配置并预览来源、数据目录和保留策略；不联网、不写入、不清理
bash scripts/vsc-vendor-maintenance.sh --plan
# 一次检查全部来源，或只检查一个来源
bash scripts/vsc-vendor-maintenance.sh
bash scripts/vsc-vendor-maintenance.sh --source mattpocock-skills
# 复用原中央维护目录中的已有缓存与候选；不会启动调度
bash scripts/vsc-vendor-maintenance.sh --maintenance-root /absolute/path/to/plugin-updater
```

执行后检查退出码与本次输出；退出码非零时记录失败，不报告成功。结构报告在 `vendor/.reviews/<source>-<revision>.md` 和对应 JSON 中。需要语义评估时手动调用 `/vsc-vendor 审查候选报告 <报告路径>`，读取报告及候选/基线中必要的原始 Skill 与支持资源，将评估写为同名 `.assessment.md`：已路由 Skill 是否仍可引用、每个新增 Skill 是否值得路由及理由、每个已删除引用应保留/替换/退役的建议、所需运行环境与测试。它不得编辑 `vendor/<source>`、`sources.lock.json`、VSC 路由、角色或命令，也不得执行候选中的脚本。

脚本完成“发现和结构分析”，但不越权完成“采用”。`UNCHANGED-CANDIDATE` 仅表示结构报告无需重建，不表示已有人完成语义评估；用户仍可指定已有报告审查。无 `--maintenance-root` 时使用本机 `vendor/.maintenance/`；旧参数 `--updater-root` 为兼容别名，`--source ID` 可重复指定来源。脚本路径不依赖当前工作目录，也可用绝对路径从任意目录执行。

## 旧中央入口与任务迁移

项目不再提供中央定时入口部署器。已有的 `~/.zcode/plugin-updater/scripts/vsc-vendor-maintenance.sh` 与 `vsc-vendor-watch.py` 若是转发项目脚本的薄入口，可保留为手动兼容命令；文件存在不代表有定时任务。推荐直接调用项目入口。

改项目代码不能替代删除宿主任务。已有安装应在用户授权下移除 ZCode 中指向 VSC 工作区或 VSC 维护入口的任务；核对系统 crontab／launchd 是否存在同类任务，不动其他插件任务。保留历史运行记录、审查报告、已安装 Vendor 和可复用缓存；无需为这次模式切换重新下载来源。候选快照恢复与显式采用仍遵守上述完整性与审批边界。

## 采用流程

1. 阅读 `vendor/.reviews/<source>-<candidate>.md` 和必要的原始 `SKILL.md` diff。
2. 记录兼容性、权属、运行环境、路由和删除处置结论。
3. 明确将 `sources.lock.json` 中该来源的 40 位 `revision` 改为已批准候选。
4. 执行 `python3 scripts/vendor_sync.py --install <source>`，使 active Vendor 与固定 revision 一致。
5. 执行 `python3 scripts/vendor_sync.py --write-declaration`、`python3 scripts/vsc_kernel.py doctor` 和相关测试；再决定是否提交 VSC 配置变更。

任何候选分析失败、下载失败或未完成审查时，当前 active Vendor 保持不变。
