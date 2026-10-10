#!/usr/bin/env python3
"""vendor_review.py 自测。运行：python3 tests/test_vendor_review.py"""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _paths import SCRIPTS
SPEC = importlib.util.spec_from_file_location("vendor_review", SCRIPTS / "vendor_review.py")
REVIEW = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REVIEW)


def write(root, relative, content):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, "utf-8")


class TestVendorReview(unittest.TestCase):
    def test_changed_deleted_and_new_skills_are_classified_without_auto_adoption(self):
        with tempfile.TemporaryDirectory() as temp:
            current, candidate = Path(temp) / "current", Path(temp) / "candidate"
            referenced = "packages/core/skills/inkos-script-writing/SKILL.md"
            deleted = "packages/core/skills/inkos-story-review/SKILL.md"
            write(current, referenced, "old")
            write(current, deleted, "old review")
            write(candidate, referenced, "new")
            write(candidate, "skills/new/SKILL.md", "new skill")
            report = REVIEW.analyze("inkos", current, candidate, "oldrev", "newrev")
            actions = {change["path"]: change for change in report["changes"]}
            self.assertEqual(actions[referenced]["kind"], "changed_referenced_skill")
            self.assertEqual(actions[deleted]["required_action"], "retain_last_approved_snapshot_or_replace_route")
            self.assertEqual(actions["skills/new/SKILL.md"]["kind"], "new_skill")
            self.assertEqual(report["summary"]["adoption"], "blocked_pending_review")

    def test_report_writes_machine_and_human_views(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            current, candidate = root / "current", root / "candidate"
            write(current, "SKILL.md", "before")
            write(candidate, "SKILL.md", "after")
            report = REVIEW.analyze("unknown", current, candidate, candidate_revision="abcdef123456")
            json_path, markdown_path = REVIEW.write_report(report, root / "reports")
            self.assertEqual(json.loads(json_path.read_text("utf-8"))["format"], REVIEW.FORMAT)
            self.assertIn("待填写", markdown_path.read_text("utf-8"))

    def test_unchanged_skill_supporting_resources_and_license_changes_are_detected(self):
        with tempfile.TemporaryDirectory() as temp:
            current, candidate = Path(temp) / "current", Path(temp) / "candidate"
            skill = "skills/engineering/improve-codebase-architecture/SKILL.md"
            rule = "skills/engineering/improve-codebase-architecture/HTML-REPORT.md"
            for root in (current, candidate):
                write(root, skill, "Read [report](HTML-REPORT.md).")
                write(root, rule, "old")
                write(root, "LICENSE", "MIT old")
            write(candidate, rule, "new")
            write(candidate, "LICENSE", "MIT new")
            report = REVIEW.analyze("mattpocock-skills", current, candidate)
            self.assertEqual(report["summary"]["change_count"], 1)
            self.assertEqual(report["changes"][0]["kind"], "changed_referenced_skill")
            self.assertEqual({item["path"] for item in report["changes"][0]["resources"]}, {rule, "LICENSE"})

    def test_references_outside_skill_directory_are_recursive(self):
        with tempfile.TemporaryDirectory() as temp:
            current, candidate = Path(temp) / "current", Path(temp) / "candidate"
            for root in (current, candidate):
                write(root, "skills/a/SKILL.md", "Read [shared](../../shared/read.md).")
                write(root, "shared/read.md", "Run [tool](tool.py).")
                write(root, "shared/tool.py", "print('old')")
            write(candidate, "shared/tool.py", "print('new')")
            report = REVIEW.analyze("unknown", current, candidate)
            self.assertEqual(report["changes"][0]["resources"][0]["path"], "shared/tool.py")

    def test_executable_mode_change_is_detected(self):
        with tempfile.TemporaryDirectory() as temp:
            current, candidate = Path(temp) / "current", Path(temp) / "candidate"
            for root in (current, candidate):
                write(root, "skills/a/SKILL.md", "method")
                write(root, "skills/a/run.py", "pass")
            (current / "skills/a/run.py").chmod(0o644)
            (candidate / "skills/a/run.py").chmod(0o755)
            self.assertEqual(REVIEW.analyze("unknown", current, candidate)["summary"]["change_count"], 1)

    def test_missing_links_and_traversal_fail_closed(self):
        for text in ("[missing](missing.md)", "[escape](../../../secret.md)"):
            with self.subTest(text=text), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                write(root, "skills/a/SKILL.md", text)
                with self.assertRaises(REVIEW.vendor_bundle.BundleError):
                    REVIEW.skill_files(root)

    def test_symlink_resources_and_limits_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write(root, "skills/a/SKILL.md", "method")
            (root / "skills/a/unsafe").symlink_to("/etc/passwd")
            with self.assertRaises(REVIEW.vendor_bundle.BundleError):
                REVIEW.skill_files(root)
            (root / "skills/a/unsafe").unlink()
            with mock.patch.object(REVIEW.vendor_bundle, "MAX_FILE_BYTES", 2):
                with self.assertRaises(REVIEW.vendor_bundle.BundleError):
                    REVIEW.skill_files(root)
            with mock.patch.object(REVIEW.vendor_bundle, "MAX_FILES", 0):
                with self.assertRaises(REVIEW.vendor_bundle.BundleError):
                    REVIEW.skill_files(root)

    def test_old_skill_only_candidate_is_not_a_complete_bundle(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write(root, "skills/a/SKILL.md", "method")
            write(root, ".vsc-candidate.json", json.dumps({"format": "vsc.vendor-skill-candidate/v1"}))
            with self.assertRaises(REVIEW.vendor_bundle.BundleError):
                REVIEW.skill_files(root)

    def test_unsafe_report_name_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write(root, "SKILL.md", "method")
            report = REVIEW.analyze("../../escape", root, root)
            with self.assertRaises(REVIEW.vendor_bundle.BundleError):
                REVIEW.write_report(report, root / "reports")

    def test_license_is_preserved_and_reviewed_even_without_skills(self):
        with tempfile.TemporaryDirectory() as temp:
            current, candidate = Path(temp) / "current", Path(temp) / "candidate"
            write(current, "LICENSE", "old")
            write(candidate, "LICENSE", "new")
            report = REVIEW.analyze("unknown", current, candidate)
            self.assertEqual(report["summary"]["source_metadata_change_count"], 1)
            self.assertEqual(report["summary"]["adoption"], "blocked_pending_review")
            self.assertNotIn("没有发现", REVIEW.markdown(report))

    def test_fenced_examples_and_root_relative_site_urls_are_not_local_dependencies(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write(root, "skills/a/SKILL.md", """# Actual guide
[effect docs](/docs/effects/api)
[video endpoint](/v1/video.webm)
Use `/v1/video.webm`, `GET /v1/convai/llm/list` and `/export` as endpoint/command examples.
JSX closure: `<Options id="..." />`.
Runtime configuration: `~/.claude/mcp.json`; output directory `/tmp`.
```markdown
[example glossary](./src/ordering/GLOSSARY.md)
python /etc/example.py
```
~~~markdown
[another example](not-a-resource.md)
~~~
Read [actual](rules.md).
""")
            write(root, "skills/a/rules.md", "actual rule")
            report = REVIEW.analyze("unknown", root, root)
            self.assertEqual(report["summary"]["candidate_unusable_skill_count"], 0)
            self.assertEqual(set(report["bundles"]["candidate"]["skills/a/SKILL.md"]["files"]),
                             {"skills/a/SKILL.md", "skills/a/rules.md"})
            self.assertEqual(report["summary"]["candidate_external_runtime_reference_count"], 2)

    def test_genuine_absolute_files_and_commands_remain_rejected(self):
        for text in ("[local](/etc/passwd)", "[local](file:///Users/user/private.md)",
                     "`/etc/passwd`", "`python /private/tmp/run.py`", "`cat ~/private.txt`",
                     "[escape](../../../private.md)"):
            with self.subTest(text=text), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                write(root, "skills/a/SKILL.md", text)
                with self.assertRaises(REVIEW.vendor_bundle.BundleError):
                    REVIEW.skill_files(root)
                report = REVIEW.analyze("unknown", root, root)
                self.assertEqual(report["summary"]["candidate_unusable_skill_count"], 1)
                self.assertEqual(report["summary"]["adoption"], "blocked_pending_review")

    def test_missing_real_prose_resource_marks_only_affected_skill_unusable(self):
        with tempfile.TemporaryDirectory() as temp:
            current, candidate = Path(temp) / "current", Path(temp) / "candidate"
            for root in (current, candidate):
                write(root, "skills/good/SKILL.md", "good")
                write(root, "skills/bad/SKILL.md", "Read [required](missing-rules.md).")
            report = REVIEW.analyze("unknown", current, candidate)
            self.assertEqual(report["summary"]["candidate_skill_count"], 2)
            self.assertEqual(report["summary"]["candidate_unusable_skill_count"], 1)
            self.assertEqual(report["summary"]["adoption"], "blocked_pending_review")
            self.assertEqual(report["unusable_skills"]["candidate"][0]["path"], "skills/bad/SKILL.md")
            self.assertIn("missing-rules.md", REVIEW.markdown(report))

    def test_symlink_descendant_is_not_reported_as_upstream_file_deletion(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write(root, "skills/a/SKILL.md", "[rule](alias/rule.md)")
            write(root, "shared/rule.md", "not followed")
            (root / "skills/a/alias").symlink_to(root / "shared")
            report = REVIEW.analyze("unknown", root, root)
            problems = report["unusable_skills"]["candidate"][0]["problems"]
            self.assertFalse(any(problem["kind"] == "missing_local_reference" for problem in problems))
            self.assertTrue(any("符号链接" in problem.get("reason", "") for problem in problems))


if __name__ == "__main__":
    unittest.main()
