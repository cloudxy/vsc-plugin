# 维护与本地验证

维护 VSC 时直接提交并推送 `main`。vendor 与作品只在本机，验证也只在本地：推送前运行本地 CI，依次检查 doctor、全部测试、vendor 版本与路由、`projects/` 中作品可读性、Git 跟踪文件不含作品、vendor 源码或本机配置，以及文档相对链接有效。流程见 [vsc-architecture](../../skills/vsc-architecture/SKILL.md)。

## 本地 CI 与提交钩子

```bash
python3 -B scripts/vsc_local_ci.py

# 每个克隆启用一次：启用提交前同步与推送前本地 CI
git config core.hooksPath .githooks
```

每次普通 `git commit` 前，钩子都会获取 `origin/main`。当前分支已包含最新 main 时直接提交；需要更新时，先保存暂存、未暂存及未跟踪文件，合并 main，再恢复修改及暂存状态。忽略的作品、vendor 源码与本机配置不进入 stash，也不允许被合并覆盖。由于合并会推进 HEAD，本次提交会中止；检查 `git diff --cached` 并重跑本地 CI 后重新执行 `git commit`。有更新时不自动处理 `git commit -a/--only` 等临时索引提交，请先 `git add` 再普通提交。

获取失败、合并冲突或恢复修改失败都会阻止提交。合并失败时，原有修改保留在钩子输出的 stash 中：先解决或中止合并，再按提示 `git stash apply --index <stash-id>` 恢复。若恢复时发生冲突，先检查 `git status`，不要直接重复 apply。不要用 `--no-verify` 或关闭 hooks 绕过同步。推送前仍运行本地 CI，且工作区须已提交。

## 宿主入口

修改技能、角色卡的 name/description 或 `workflow/kernel.json` 的阶段入口后，运行 `python3 -B scripts/vsc_hosts.py sync` 重新生成各客户端入口；未同步时 doctor 失败。见 [AI 客户端接入](workspace-setup.md)。

## 单独运行测试

```bash
python3 -B tests/test_vsc_state.py
python3 -B tests/test_vsc_kernel.py
python3 -B tests/test_vendor_sync.py
python3 -B tests/test_vendor_skills.py
python3 -B tests/test_vendor_review.py
python3 -B tests/test_remotion_plan.py
python3 -B tests/test_vsc_integrity.py
python3 -B tests/test_vsc_learning.py
python3 -B tests/test_media_qa.py
python3 -B tests/test_vendor_watch.py
python3 -B tests/test_vsc_local_ci.py
python3 -B tests/test_vsc_hosts.py
python3 -B tests/test_vsc_pre_commit.py
python3 -B tests/test_mpt_adapter.py
python3 -B tests/test_jianying_export.py

# 或一次运行全部本地测试
python3 -B -m unittest discover -s tests -p 'test_*.py'
```
