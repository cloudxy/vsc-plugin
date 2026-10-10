#!/usr/bin/env python3
"""提交前获取 origin/main；需要合并时保存本地修改，合并并要求重新提交。行为说明见 docs/guide/maintenance.md。"""
import os
from pathlib import Path
import subprocess
import sys


def main():
    # git commit -a/--only 可能传入临时索引，不能用它来 stash 或合并。
    original_index = os.environ.get("GIT_INDEX_FILE")
    env = os.environ.copy()
    env.pop("GIT_INDEX_FILE", None)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_MERGE_AUTOEDIT"] = "no"

    def git(*args):
        return subprocess.run(["git", *args], env=env, text=True, capture_output=True)

    def value(*args):
        result = git(*args)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or "git " + " ".join(args))
        return result.stdout.strip()

    def fail(message, result=None):
        print("VSC pre-commit：" + message, file=sys.stderr)
        if result:
            print((result.stdout + result.stderr).strip(), file=sys.stderr)
        return 1

    def contains(commit, ancestor):
        result = git("merge-base", "--is-ancestor", ancestor, commit)
        if result.returncode not in (0, 1):
            raise RuntimeError(result.stderr.strip())
        return result.returncode == 0

    if git("symbolic-ref", "--quiet", "HEAD").returncode:
        return fail("请先切换到本地分支；不在 detached HEAD 上自动合并。")
    if git("rev-parse", "--verify", "HEAD").returncode:
        return fail("当前分支还没有提交，请先克隆已有仓库。")

    print("VSC pre-commit：获取 origin/main…", flush=True)
    fetched = git("fetch", "--no-tags", "--no-recurse-submodules", "origin",
                  "+refs/heads/main:refs/remotes/origin/main")
    if fetched.returncode:
        return fail("获取 origin/main 失败，本次提交已阻止。", fetched)
    remote = value("rev-parse", "--verify", "refs/remotes/origin/main^{commit}")
    if contains("HEAD", remote):
        return 0

    merge_head = Path(value("rev-parse", "--git-path", "MERGE_HEAD"))
    if merge_head.exists():
        # 自动合并有冲突时，允许用户解决后完成包含最新 main 的合并提交。
        if any(contains(parent, remote) for parent in merge_head.read_text().splitlines()):
            return 0
        return fail("正在进行的合并未包含最新 origin/main；请先完成或中止合并，再同步。")
    for state in ("CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply", "sequencer"):
        if Path(value("rev-parse", "--git-path", state)).exists():
            return fail("正在执行其他 Git 操作；请先完成或中止，再合并 origin/main。")

    index = Path(value("rev-parse", "--git-path", "index")).resolve()
    if original_index and Path(original_index).resolve() != index:
        return fail("main 有更新，但本次提交使用临时索引（如 -a/--only）。请先 git add，再用普通 git commit 同步。")

    stash = None
    if value("status", "--porcelain", "--untracked-files=all"):
        previous_stash = git("rev-parse", "--verify", "refs/stash").stdout.strip()
        saved = git("stash", "push", "--include-untracked", "--message", "VSC pre-commit: before merging origin/main")
        if saved.returncode:
            return fail("保存本地修改失败，未开始合并；请检查 git status 和 git stash list。", saved)
        stash = value("rev-parse", "refs/stash")
        if stash == previous_stash:
            return fail("工作区有无法保存的修改，未开始合并；请检查 git status（包括子模块）。")
        print("VSC pre-commit：本地修改已保存为 stash " + stash, flush=True)

    merged = git("merge", "--no-edit", "--no-stat", "--no-overwrite-ignore", remote)
    if merged.returncode:
        message = "合并 origin/main 失败，本次提交已阻止；请检查 git status，解决冲突或 git merge --abort。"
        if stash:
            message += " 原有修改保留在 stash，合并处理完后运行：git stash apply --index " + stash
        return fail(message, merged)

    if stash:
        restored = git("stash", "apply", "--index", stash)
        if restored.returncode:
            return fail("main 已合并，但恢复本地修改失败，本次提交已阻止。请检查 git status；备份仍在 stash "
                        + stash + "，不要重复 apply 未检查的修改。", restored)
        # 只删除本次创建且仍位于栈顶的 stash，不碰用户已有的 stash。
        if value("rev-parse", "refs/stash") == stash:
            dropped = git("stash", "drop", "stash@{0}")
            if dropped.returncode:
                print("VSC pre-commit：修改已恢复，stash 备份未删除：" + stash, file=sys.stderr)

    # 外层 git commit 已读取旧 HEAD；推进 HEAD 后不能让它继续创建提交。
    return fail("已合并最新 origin/main，本地修改及暂存状态已恢复。请检查 git diff --cached 后重新执行 git commit。")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, RuntimeError) as exc:
        print("VSC pre-commit：同步失败，提交已阻止：" + str(exc), file=sys.stderr)
        sys.exit(1)
