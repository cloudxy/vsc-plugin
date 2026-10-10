#!/usr/bin/env python3
"""用本地 bare 远端与真实 git commit 验证提交前同步，不访问网络。"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent


class TestPreCommit(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.remote = self.base / "remote.git"
        self.upstream = self.base / "upstream"
        self.local = self.base / "local"
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        self.env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0")
        self.git(self.base, "init", "--bare", "-b", "main", str(self.remote))
        self.git(self.base, "clone", str(self.remote), str(self.upstream))
        self.configure(self.upstream)
        for relative in (".githooks/pre-commit", "scripts/vsc_pre_commit.py"):
            target = self.upstream / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, target)
        (self.upstream / ".githooks/pre-commit").chmod(0o755)
        (self.upstream / "work.txt").write_text("base\n")
        (self.upstream / ".gitignore").write_text("/ignored/\n")
        self.git(self.upstream, "add", ".")
        self.git(self.upstream, "commit", "-m", "base")
        self.git(self.upstream, "push", "origin", "main")
        self.git(self.base, "clone", str(self.remote), str(self.local))
        self.configure(self.local)
        self.git(self.local, "config", "core.hooksPath", ".githooks")

    def configure(self, root):
        self.git(root, "config", "user.name", "VSC hook test")
        self.git(root, "config", "user.email", "vsc-hook@example.invalid")
        self.git(root, "config", "commit.gpgSign", "false")
        self.git(root, "config", "merge.gpgSign", "false")

    def git(self, root, *args, check=True):
        result = subprocess.run(["git", "-C", str(root), *args], env=self.env,
                                capture_output=True, text=True, timeout=30)
        if check:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def value(self, *args):
        return self.git(self.local, *args).stdout.strip()

    def advance(self, name="remote.txt", contents="remote\n"):
        (self.upstream / name).write_text(contents)
        self.git(self.upstream, "add", name)
        self.git(self.upstream, "commit", "-m", "upstream update")
        self.git(self.upstream, "push", "origin", "main")
        return self.git(self.upstream, "rev-parse", "HEAD").stdout.strip()

    def edit(self):
        (self.local / "work.txt").write_text("staged\n")
        self.git(self.local, "add", "work.txt")
        (self.local / "work.txt").write_text("staged\nunstaged\n")
        (self.local / "untracked.txt").write_text("untracked\n")
        (self.local / "ignored").mkdir(exist_ok=True)
        (self.local / "ignored/data.txt").write_text("local only\n")

    def commit(self, *args):
        return self.git(self.local, "commit", "-m", "local change", *args, check=False)

    def assert_edits_preserved(self):
        self.assertEqual(self.value("show", ":work.txt"), "staged")
        self.assertEqual((self.local / "work.txt").read_text(), "staged\nunstaged\n")
        self.assertEqual((self.local / "untracked.txt").read_text(), "untracked\n")
        self.assertEqual((self.local / "ignored/data.txt").read_text(), "local only\n")

    def test_up_to_date_commit_preserves_unstaged_changes(self):
        self.edit()
        self.assertEqual(self.commit().returncode, 0)
        self.assertEqual(self.value("show", "HEAD:work.txt"), "staged")
        self.assertEqual((self.local / "work.txt").read_text(), "staged\nunstaged\n")

    def test_fast_forward_restores_index_and_requires_retry(self):
        self.edit()
        upstream = self.advance()
        result = self.commit()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("重新执行 git commit", result.stderr)
        self.assertEqual(self.value("rev-parse", "HEAD"), upstream)
        self.assert_edits_preserved()
        self.assertEqual(self.value("stash", "list"), "")
        self.assertEqual(self.commit().returncode, 0)
        self.assertEqual(self.value("rev-parse", "HEAD^"), upstream)

    def test_diverged_feature_branch_merges_main_before_retry(self):
        self.git(self.local, "switch", "-c", "feature")
        (self.local / "feature.txt").write_text("feature\n")
        self.git(self.local, "add", "feature.txt")
        self.assertEqual(self.commit().returncode, 0)
        feature_head = self.value("rev-parse", "HEAD")
        upstream = self.advance()
        self.edit()
        self.assertNotEqual(self.commit().returncode, 0)
        self.assertEqual(self.value("rev-parse", "HEAD^1"), feature_head)
        self.assertEqual(self.value("rev-parse", "HEAD^2"), upstream)
        self.assertEqual(self.value("branch", "--show-current"), "feature")
        self.assert_edits_preserved()
        self.assertEqual(self.commit().returncode, 0)

    def test_fetch_failure_blocks_commit_without_touching_edits(self):
        self.edit()
        head = self.value("rev-parse", "HEAD")
        self.git(self.local, "remote", "set-url", "origin", str(self.base / "missing.git"))
        self.assertNotEqual(self.commit().returncode, 0)
        self.assertEqual(self.value("rev-parse", "HEAD"), head)
        self.assert_edits_preserved()
        self.assertEqual(self.value("stash", "list"), "")

    def test_missing_remote_main_does_not_use_stale_tracking_ref(self):
        self.git(self.remote, "symbolic-ref", "HEAD", "refs/heads/other")
        self.git(self.remote, "update-ref", "-d", "refs/heads/main")
        self.edit()
        self.assertNotEqual(self.commit().returncode, 0)
        self.assert_edits_preserved()

    def test_existing_stash_is_preserved(self):
        (self.local / "saved.txt").write_text("saved\n")
        self.git(self.local, "stash", "push", "-u", "-m", "user stash")
        original_stash = self.value("rev-parse", "refs/stash")
        self.advance()
        self.edit()
        self.assertNotEqual(self.commit().returncode, 0)
        self.assertEqual(self.value("rev-parse", "refs/stash"), original_stash)
        self.assert_edits_preserved()

    def test_merge_conflict_keeps_saved_edits_and_can_be_resolved(self):
        (self.local / "work.txt").write_text("local committed\n")
        self.git(self.local, "add", "work.txt")
        self.assertEqual(self.commit().returncode, 0)
        upstream = self.advance("work.txt", "remote committed\n")
        (self.local / "extra.txt").write_text("saved staged\n")
        self.git(self.local, "add", "extra.txt")
        result = self.commit()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("git stash apply --index", result.stderr)
        self.assertEqual(self.value("rev-parse", "MERGE_HEAD"), upstream)
        saved = self.value("rev-parse", "refs/stash")
        self.assertFalse((self.local / "extra.txt").exists())
        (self.local / "work.txt").write_text("resolved\n")
        self.git(self.local, "add", "work.txt")
        self.assertEqual(self.commit().returncode, 0)
        self.git(self.local, "stash", "apply", "--index", saved)
        self.assertEqual(self.value("show", ":extra.txt"), "saved staged")

    def test_restore_conflict_keeps_stash_after_main_is_merged(self):
        self.edit()
        upstream = self.advance("work.txt", "remote overlapping\n")
        result = self.commit()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("恢复本地修改失败", result.stderr)
        self.assertEqual(self.value("rev-parse", "HEAD"), upstream)
        saved = self.value("rev-parse", "refs/stash")
        self.assertEqual(self.value("show", saved + "^2:work.txt"), "staged")
        self.assertEqual(self.value("show", saved + ":work.txt"), "staged\nunstaged")

    def test_partial_commit_blocks_sync_without_changing_head_or_index(self):
        self.edit()
        self.advance()
        head = self.value("rev-parse", "HEAD")
        result = self.commit("--only", "work.txt")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("临时索引", result.stderr)
        self.assertEqual(self.value("rev-parse", "HEAD"), head)
        self.assert_edits_preserved()
        self.assertEqual(self.value("stash", "list"), "")

    def test_detached_head_is_rejected(self):
        self.git(self.local, "checkout", "--detach")
        self.edit()
        result = self.commit()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("detached HEAD", result.stderr)

    def test_remote_cannot_overwrite_ignored_local_data(self):
        self.edit()
        head = self.value("rev-parse", "HEAD")
        (self.upstream / "ignored").mkdir()
        (self.upstream / "ignored/data.txt").write_text("remote data\n")
        self.git(self.upstream, "add", "-f", "ignored/data.txt")
        self.git(self.upstream, "commit", "-m", "track previously ignored path")
        self.git(self.upstream, "push", "origin", "main")
        self.assertNotEqual(self.commit().returncode, 0)
        self.assertEqual(self.value("rev-parse", "HEAD"), head)
        self.assertEqual((self.local / "ignored/data.txt").read_text(), "local only\n")
        self.assertTrue(self.value("stash", "list"))

    def test_clean_worktree_can_merge_before_empty_commit(self):
        upstream = self.advance()
        self.assertNotEqual(self.commit("--allow-empty").returncode, 0)
        self.assertEqual(self.value("rev-parse", "HEAD"), upstream)
        self.assertEqual(self.value("stash", "list"), "")
        self.assertEqual(self.commit("--allow-empty").returncode, 0)

    def test_resolved_merge_is_blocked_if_main_advanced_again(self):
        (self.local / "work.txt").write_text("local committed\n")
        self.git(self.local, "add", "work.txt")
        self.assertEqual(self.commit().returncode, 0)
        self.advance("work.txt", "remote committed\n")
        self.assertNotEqual(self.commit("--allow-empty").returncode, 0)
        (self.local / "work.txt").write_text("resolved\n")
        self.git(self.local, "add", "work.txt")
        self.advance("another.txt", "main advanced again\n")
        result = self.commit()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("未包含最新 origin/main", result.stderr)


if __name__ == "__main__":
    unittest.main()
