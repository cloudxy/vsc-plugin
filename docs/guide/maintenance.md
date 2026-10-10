# 维护与本地验证

维护流程见 [vsc-architecture](../../skills/vsc-architecture/SKILL.md)；本地 CI 的检查项见 [`scripts/vsc_local_ci.py`](../../scripts/vsc_local_ci.py) 的说明。本页说明本机钩子与常用命令。

## 启用与常用命令

```bash
git config core.hooksPath .githooks                      # 每个克隆一次：提交前同步 origin/main，推送前运行本地 CI
python3 -B scripts/vsc_local_ci.py                       # 手动运行本地 CI
python3 -B -m unittest discover -s tests -p 'test_*.py'  # 只跑测试；单个文件可直接运行
```

## 提交前同步钩子

每次普通 `git commit` 前，钩子都会获取 `origin/main`。当前分支已包含最新 main 时直接提交；需要更新时，先保存暂存、未暂存及未跟踪文件，合并 main，再恢复修改及暂存状态。忽略的作品、vendor 源码与本机配置不进入 stash，也不允许被合并覆盖。由于合并会推进 HEAD，本次提交会中止；检查 `git diff --cached` 并重跑本地 CI 后重新执行 `git commit`。有更新时不自动处理 `git commit -a/--only` 等临时索引提交，请先 `git add` 再普通提交。

获取失败、合并冲突或恢复修改失败都会阻止提交。合并失败时，原有修改保留在钩子输出的 stash 中：先解决或中止合并，再按提示 `git stash apply --index <stash-id>` 恢复。若恢复时发生冲突，先检查 `git status`，不要直接重复 apply。不要用 `--no-verify` 或关闭 hooks 绕过同步。推送前仍运行本地 CI，且工作区须已提交。
