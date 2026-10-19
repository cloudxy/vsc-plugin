# 维护与本地验证

维护流程见 [vsc-architecture](../../skills/vsc-architecture/SKILL.md)；本地 CI 的检查项见 [`scripts/maintenance/local_ci.py`](../../scripts/maintenance/local_ci.py) 的说明。本页说明本机钩子与常用命令。

检查入口自动使用工作区已初始化的 `.venv` Python，数据库连接从项目 `config/.env` 读取，无需先激活虚拟环境或加载 shell 配置。跟踪文件门禁会拒绝真实 `config/.env`，只允许 `config/.env.example`。

## 启用与常用命令

```bash
git config core.hooksPath .githooks                      # 每个克隆一次：提交前同步 origin/main，推送时按改动范围验证
python3 -B tests/run.py --files src/vsc/post/subtitles.py --list  # 先查看变更影响范围
python3 -B tests/run.py --test post.unit.test_subtitles   # 修改期间只跑受影响的测试（示例）
python3 -B scripts/maintenance/local_ci.py                       # 跨模块或影响不明且未启用钩子时，最终推送前手动运行一次
```

测试分组、公共夹具、影响配置、耗时报告和新增测试要求见[测试工程](../../tests/README.md)。统一入口保留 `unittest`，最终本地 CI 通过 `--all` 检查测试配置并递归运行全部测试。

## 提交前同步钩子

每次普通 `git commit` 前，钩子都会获取 `origin/main`。当前分支已包含最新 main 时直接提交；需要更新时，先保存暂存、未暂存及未跟踪文件，合并 main，再恢复修改及暂存状态。忽略的作品、vendor 源码与本机配置不进入 stash，也不允许被合并覆盖。由于合并会推进 HEAD，本次提交会中止；检查 `git diff --cached` 并重跑受影响的测试后重新执行 `git commit`，最终检查范围按改动类型决定。有更新时不自动处理 `git commit -a/--only` 等临时索引提交，请先 `git add` 再普通提交。

获取失败、合并冲突或恢复修改失败都会阻止提交。合并失败时，原有修改保留在钩子输出的 stash 中：先解决或中止合并，再按提示 `git stash apply --index <stash-id>` 恢复。若恢复时发生冲突，先检查 `git status`，不要直接重复 apply。不要用 `--no-verify` 或关闭 hooks 绕过同步。纯文案只做内容、链接和格式检查；指定功能点位的小修改只跑相关测试，推送不要求全量。跨模块、契约、关系模型或影响不明的改动才运行一次全量。工作区须已提交，未启用钩子时手动执行同等范围检查。


## 按范围检查

pre-push 使用 Git 提供的远程旧版本与本次提交计算差异。仅 `docs/`、README 或术语文档变更时自动执行跟踪文件与链接检查，不运行代码测试。其他改动默认全量；新远程引用没有比较基线时也默认全量。

用户明确指定的小修改使用定向模式：

```bash
VSC_CI_SCOPE=targeted git push origin main
# 非代码规则等共享输入会扩大自动影响选择；范围明确时指定实际相关模块或方法
VSC_CI_SCOPE=targeted VSC_CI_TESTS="maintenance.integration.test_vsc_local_ci" git push origin main
```

定向模式仍执行内核、相关测试、跟踪文件和链接检查，失败会阻止推送；不是跳过钩子。显式 `VSC_CI_SCOPE=full` 或手动运行 `scripts/maintenance/local_ci.py` 保留全量方式。不要把范围明确的小修改扩大为全仓库测试，也不要用定向模式掩盖影响不明的改动。

临时审计与探索稿放 `tmp`；需要执行、持续维护的方案放本机 `docs/plans/`。该目录受 Git 忽略，计划与索引不提交、不打包；公开文档不链接其中的文件。
