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
| ZCode `plugin-updater` | 每日薄调用项目维护入口并保留日志；不再独立维护另一份生命周期实现。 |
| `scripts/vendor_watch.py` | 下载固定基线和 HEAD 候选，保存完整 Skill 资源包及分析状态、校验完整性、按每来源 90 天/3 份清理。 |
| `scripts/vendor_bundle.py` | 共用资源包模块：Skill 子树、递归本地引用及根许可证/依赖声明；拒绝越界、符号链接与超限。 |
| `scripts/vendor_review.py` | 对比 Skill 资源包而非仅正文，输出机器 JSON 与人读 Markdown；不更新任何活跃内容。 |
| `vendor/.reviews/` | 本机报告目录，不进入 Git。 |
| ZCode 审查任务 | 仅在出现候选时阅读结构报告与必要 diff，补充“可否继续引用/是否值得新增路由/删除处置”的语义评估；没有采用权限。 |
| 责任人 | 判断语义/兼容性、决定是否采用候选、是否新增路由、是否保留删除 Skill。 |

## 三种变化

| 变化 | 默认结论 | 必须的下一步 |
| --- | --- | --- |
| `changed_referenced_skill` | 阻止自动采用 | 检查方法、输入/输出、运行环境、权限和 VSC 契约；通过后才更新 revision。 |
| `new_skill` | `unrouted_pending_review` | 评估是否补足 VSC 能力；若采用，显式添加 Vendor 路由、运行环境与测试，运行 `vsc_kernel.py doctor`。 |
| `deleted_referenced_skill` | 保留当前活跃版本 | 在“保留最后批准快照 / 替换路由 / 退役”中作决定；不能让当前路由悄然变成缺失文件。 |

每条 Skill 变化同时列出具体资源变化。正文没变但 `rules.md`、脚本、参考、资产、LICENSE、NOTICE 或依赖声明变化时，也必须审查。报告格式升级为 `vsc.vendor-skill-analysis/v2`，原 `change_count`、变化分类与路由处置字段保留；`before_sha256`/`after_sha256` 现在是资源包散列，详细文件证据见 `resources`/`bundles`。

`vendor_review.py` 不会声称能仅凭文件散列判断创作方法是否合理。它准确报告结构变化和当前路由影响，并把语义判断留给负责审查的人或受控的 ZCode 分析任务。

## 资源包、失败恢复与保留边界

候选格式为 `vsc.vendor-skill-candidate/v2`，记录资源闭包算法版本。对于可用 Skill，保存目录内全部非忽略文件、递归显式本地引用、仓库根许可证/NOTICE/依赖声明，保留执行位，记录 SHA-256；不运行任何候选内容。URL 不下载，Markdown 围栏示例不解析成真实依赖；`/docs/...`、`/v1/...` 网站端点和 `/skill` 命令不当作本机路径。运行时配置及输出目录只记录外部前置条件，不读取／打包，也不声称已就绪。

真实正文相对引用缺失、绝对文件输入或越界、符号链接／特殊文件、单文件超过 8 MiB 时，报告逐 Skill 的 `unusable_skills` 并阻止采用；不会让一个坏 Skill 掩盖其他 Skill 的分析。被拒绝资源不读取或物化，只保留拒绝元信息以重现完整性诊断；这些候选**不具有该 Skill 的完整备份／就绪能力**。总量超过 64 MiB 或 5,000 文件仍使整个维护失败关闭。可用资源包能恢复 Skill 文件，**不是完整仓库、依赖运行环境或权重备份**；需要整仓恢复时仍按固定 commit 重新安装。

下载资源包与分析分别存储：`.vsc-candidate.json` 表示已保存，`.analysis.json` 表示 `pending` / `failed` / `completed`。分析失败或报告被删除后，再次执行会复用完整候选并重试；只有报告存在且分析格式、当前基线匹配时，才输出 `UNCHANGED-CANDIDATE`。资源被篡改会拒绝复用。旧 v1 单正文快照不用于分析，维护时重建 v2。

90 天与最多 3 份两个条件同时执行，按来源计算，基线也计入；过期或超额快照清理不影响活跃 `vendor/<source>`。保留策略不允许设置超过此上限。被上游删除的已路由 Skill 仍留在活跃批准版本中，不因候选清理而退役。

## ZCode 每日任务

在 ZCode 自动化中创建一个名为“VSC Vendor 候选审查”的每日任务，cron 为 `45 9 * * *`（避开 09:30 的插件同步）。工作目录为 VSC 插件根目录，任务先且只先执行：

```bash
/bin/bash /absolute/path/to/vsc-workflow/scripts/vsc-vendor-maintenance.sh --updater-root /absolute/path/to/plugin-updater
```

执行后检查退出码与本次输出/日志段落；退出码非零时记录失败，不报告成功。仅在本次含 `CANDIDATE` 时，读取本次生成的 `vendor/.reviews/<source>-<revision>.md`、对应 JSON 和候选/基线快照中必要的原始 Skill 与支持资源。将语义评估写为同名 `.assessment.md`：已路由 Skill 是否仍可引用、每个新增 Skill 是否值得路由及理由、每个已删除引用应保留/替换/退役的建议、所需运行环境与测试。它不得编辑 `vendor/<source>`、`sources.lock.json`、VSC 路由、角色或命令，也不得执行候选中的脚本。

这让自动化完成“发现和分析”，但不越权完成“采用”。项目不自动创建或修改 ZCode 任务。无 `--updater-root` 时使用本机 `vendor/.maintenance/`；`--source ID` 可只检查一个来源。

## 旧中央入口迁移（显式部署）

项目代码已升级，不等于 `~/.zcode/plugin-updater/scripts/` 中旧副本已升级。旧 worker 只保留 `SKILL.md`，旧 shell 还会丢失失败退出码；两者都不应继续承担生命周期实现。先备份中央入口，再让它们薄调用项目脚本（或把 ZCode 任务入口改为上述项目路径），不要复制第三方 Skill 内容到核心。

项目提供只处理这两个现有中央文件的显式部署器：

```bash
# 默认列计划，不写入；--check 表示需要部署时以非零退出。
python3 -B scripts/install_vendor_scheduler.py --updater-root /absolute/path/to/plugin-updater
python3 -B scripts/install_vendor_scheduler.py --check --updater-root /absolute/path/to/plugin-updater
# 仅经用户授权后运行：先备份两个原入口及散列/权限，语法检查后原子替换。
python3 -B scripts/install_vendor_scheduler.py --apply --updater-root /absolute/path/to/plugin-updater
```

它保留中央日志库及 `logs/vsc-vendor-maintenance-YYYYMMDD.log` 路径，返回真实退出码；不修改 ZCode 任务数据库、添加 cron 或执行候选更新。备份在 `backups/vsc-vendor-entrypoints/<timestamp>/`，`manifest.json` 指明两个原目标、SHA-256 与权限；恢复时经授权将这两个原文件放回记录的目标即可。无变更的重复 `--apply` 不产生额外备份。部署目录必须是现有绝对路径且名为 `plugin-updater`，拒绝符号链接与非普通目标文件。

中央 shell 如需要保留现有日志库，应把业务命令改为：

```bash
if /bin/bash "$PLUGIN/scripts/vsc-vendor-maintenance.sh" --plugin "$PLUGIN" --updater-root "$BASE" "$@" >> "$LOG" 2>&1; then
    log "VSC Vendor 候选维护成功"
    exit 0
else
    vsc_exit_status=$?
    log "VSC Vendor 候选维护失败 exit=$vsc_exit_status"
    exit "$vsc_exit_status"
fi
```

不能在 `fi` 后再读取 `$?`。中央 worker 若需要兼容现有参数，只负责将 `--plugin`、`--updater-root`、`--source` 转交项目 `scripts/vendor_watch.py`，并原样返回进程退出码。修改中央文件或任务属于本机配置变更，需显式授权；项目测试只使用临时本地 Git，不进行真实下载或外部部署。

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
