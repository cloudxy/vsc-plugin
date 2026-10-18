"""The real AI suggestion consumer: durable invocation, frozen input and atomic proposals."""
import subprocess
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import support.paths  # noqa
from support.fixtures.resource_store import HAS_DB_DEPS, TEST_URL, ResourceStoreFixture
from vsc.assets.resource_service import ResourceError
from vsc.assets.script_ai import GrokBuildSuggestions


class Backend:
    name = "offline-host"
    def __init__(self, callback):
        self.callback, self.calls = callback, 0
    def available(self): return True
    def generate(self, document, goal):
        self.calls += 1
        return self.callback(document, goal)


@unittest.skipUnless(HAS_DB_DEPS and TEST_URL, "requires explicit PostgreSQL test URL")
class ScriptAIFlow(ResourceStoreFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.document = {"scenes": [{"id": "SC1", "actions": [{"id": "A1", "text": "停下"}],
            "dialogue": [{"id": "L1", "speaker": "C1", "text": "你好"},
                         {"id": "L2", "speaker": "C1", "text": "明天见"}], "silence": []}]}
        self.service.save_script_draft(self.p, {"content": self.document}, actor="test-editor")
        self.addCleanup(setattr, self.service, "script_suggester", None)

    def request(self):
        draft = self.service.get_script_draft(self.p)
        return {"base_draft_revision": draft["draft_revision"], "base_content_sha256": draft["content_sha256"],
                "goal": "Improve performability", "scope_key": ""}

    def proposals(self, *_):
        return [dict(scene_id="SC1", line_id=key, kind=kind, field="text", after_value=after, reason="local improvement")
            for key, kind, after in [("A1", "action", "停下脚步"), ("L1", "dialogue", "你来了"), ("L2", "dialogue", "明天还在这里见")]]

    def test_generation_three_proposals_accept_one_and_undo_keeps_other_lines(self):
        backend = self.service.script_suggester = Backend(self.proposals)
        payload, key = self.request(), uuid.uuid4().hex
        result = self.write("generate_script_suggestions", payload, idempotency_key=key)
        self.assertEqual((result["status"], backend.calls), ("completed", 1))
        replay = self.service.generate_script_suggestions(self.p, payload, actor="test-human",
            expected_revision=0, idempotency_key=key)
        self.assertTrue(replay["reused"]); self.assertEqual(backend.calls, 1)
        before = self.service.get_script_draft(self.p)
        self.assertEqual(before["content"], self.document)
        suggestions = before["suggestions"]
        chosen = next(r for r in suggestions if r["line_id"] == "L1")
        self.write("decide_script_suggestion", {"suggestion_id": chosen["id"], "outcome": "accept", "reason": "test choice"})
        changed = self.service.get_script_draft(self.p)["content"]
        self.assertEqual(changed["scenes"][0]["dialogue"][0]["text"], "你来了")
        self.assertEqual(changed["scenes"][0]["actions"], self.document["scenes"][0]["actions"])
        self.assertEqual(changed["scenes"][0]["dialogue"][1], self.document["scenes"][0]["dialogue"][1])
        self.write("decide_script_suggestion", {"suggestion_id": chosen["id"], "outcome": "undo_accept", "reason": "test undo"})
        self.assertEqual(self.service.get_script_draft(self.p)["content"], self.document)

    def test_concurrent_edit_isolates_result_and_invalid_target_batch_is_atomic(self):
        def concurrent(document, goal):
            self.service.save_script_draft(self.p, {"base_draft_revision": 1,
                "content": dict(self.document, body="newer local draft")}, actor="other-editor")
            return self.proposals()
        self.service.script_suggester = Backend(concurrent)
        result = self.write("generate_script_suggestions", self.request())
        self.assertEqual(result["status"], "stale")
        self.assertEqual(self.service.get_script_draft(self.p)["suggestions"], [])
        self.service.script_suggester = Backend(lambda *_: self.proposals() + [dict(self.proposals()[0], line_id="missing")])
        result = self.write("generate_script_suggestions", self.request())
        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.service.get_script_draft(self.p)["suggestions"], [])

    def test_unknown_invocation_is_not_automatically_repeated_and_bad_sha_has_zero_calls(self):
        def timeout(*_): raise ResourceError("unknown", "suggestion_submission_unknown")
        backend = self.service.script_suggester = Backend(timeout)
        payload, key = self.request(), uuid.uuid4().hex
        with self.assertRaises(ResourceError):
            self.write("generate_script_suggestions", dict(payload, base_content_sha256="0" * 64))
        self.assertEqual(backend.calls, 0)
        result = self.write("generate_script_suggestions", payload, idempotency_key=key)
        self.assertEqual(result["status"], "submission_unknown")
        self.service.generate_script_suggestions(self.p, payload, actor="test-human", expected_revision=0, idempotency_key=key)
        self.assertEqual(backend.calls, 1)
        self.write("generate_script_suggestions", payload)
        self.assertEqual(backend.calls, 1, "a refreshed page with a new command key must recover the same input")
        self.write("generate_script_suggestions", dict(payload, new_attempt=True))
        self.assertEqual(backend.calls, 2, "an explicit new round is a separate bounded invocation")
        other = self.service.create_project({"name": "other synthetic project"}, actor="test-human")
        with self.assertRaises(ResourceError):
            self.store.get_script_suggestion_run(other["id"], result["id"])

    def test_independent_batch_accepts_and_undoes_locally_but_autosave_blocks_rebase(self):
        self.service.script_suggester = Backend(self.proposals)
        self.write("generate_script_suggestions", self.request())
        suggestions = self.service.get_script_draft(self.p)["suggestions"]
        first = next(row for row in suggestions if row["line_id"] == "A1")
        second = next(row for row in suggestions if row["line_id"] == "L1")
        for row in [first, second]:
            self.write("decide_script_suggestion", {"suggestion_id": row["id"], "outcome": "accept", "reason": "explicit choice"})
        self.write("decide_script_suggestion", {"suggestion_id": first["id"], "outcome": "undo_accept", "reason": "undo only action"})
        draft = self.service.get_script_draft(self.p)
        self.assertEqual(draft["content"]["scenes"][0]["actions"][0]["text"], "停下")
        self.assertEqual(draft["content"]["scenes"][0]["dialogue"][0]["text"], "你来了")
        self.service.save_script_draft(self.p, {"base_draft_revision": draft["draft_revision"], "content": draft["content"]}, actor="other")
        third = next(row for row in suggestions if row["line_id"] == "L2")
        with self.assertRaises(ResourceError):
            self.write("decide_script_suggestion", {"suggestion_id": third["id"], "outcome": "accept", "reason": "stale"})

    def test_malformed_before_is_failed_not_stuck_and_completed_receipt_needs_no_host(self):
        import copy
        invalid = copy.deepcopy(self.document);invalid["scenes"][0]["actions"][0]["text"] = {"bad": "value"}
        self.service.save_script_draft(self.p, {"base_draft_revision": 1, "content": invalid}, actor="editor")
        backend = self.service.script_suggester = Backend(self.proposals)
        payload, key = self.request(), uuid.uuid4().hex
        result = self.write("generate_script_suggestions", payload, idempotency_key=key)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["result"]["error_code"], "invalid_suggestions")
        backend.available = lambda: False
        replay = self.service.generate_script_suggestions(self.p, payload, actor="test-human", expected_revision=0, idempotency_key=key)
        self.assertEqual(replay["status"], "failed");self.assertEqual(backend.calls, 1)

    def test_host_result_survives_registration_conflicts_and_resumes_without_another_call(self):
        from vsc.assets.resource_service import Conflict
        backend = self.service.script_suggester = Backend(self.proposals)
        payload, key = self.request(), uuid.uuid4().hex
        with patch.object(self.store, "finish_script_suggestion_run", side_effect=Conflict()):
            with self.assertRaises(Conflict):
                self.write("generate_script_suggestions", payload, idempotency_key=key)
        self.rev = self.service.get_project(self.p)["revision"]
        backend.available = lambda: False
        result = self.write("generate_script_suggestions", payload, idempotency_key=key)
        self.assertEqual(result["status"], "completed");self.assertEqual(backend.calls, 1)
        self.assertEqual(len(self.service.get_script_draft(self.p)["suggestions"]), 3)

    def test_malformed_scene_members_end_as_failed_with_recoverable_host_evidence(self):
        import copy
        invalid = copy.deepcopy(self.document);invalid["scenes"].insert(0, None)
        self.service.save_script_draft(self.p, {"base_draft_revision": 1, "content": invalid}, actor="editor")
        backend = self.service.script_suggester = Backend(self.proposals)
        result = self.write("generate_script_suggestions", self.request())
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["result"]["error_code"], "invalid_suggestions")
        self.assertTrue(result["result"]["host_suggestions"])
        self.assertEqual(backend.calls, 1)


class GrokSuggestionAdapter(unittest.TestCase):
    def test_bounded_tool_free_host_command_and_structured_result(self):
        seen = []
        def run(command, **kwargs):
            from pathlib import Path
            seen.append(command)
            import json
            prompt = json.loads(Path(command[command.index("--prompt-file") + 1]).read_text())
            self.assertEqual(prompt[0]["type"], "text")
            self.assertIn('"goal": "test"', prompt[0]["text"])
            self.assertEqual(kwargs["timeout"], 120)
            self.assertNotIn("shell", kwargs)
            return SimpleNamespace(returncode=0, stdout='{"structuredOutput":{"suggestions":[]},"text":"host wrapper"}')
        with patch("vsc.assets.script_ai.shutil.which", return_value="/test/grok"):
            self.assertEqual(GrokBuildSuggestions(runner=run).generate({}, "test"), [])
        command = seen[0]
        self.assertEqual(command[command.index("--tools") + 1], "")
        self.assertIn("--no-subagents", command); self.assertIn("--disable-web-search", command)
        self.assertNotIn("--always-approve", command)

    def test_timeout_and_cli_errors_never_expose_transcripts(self):
        with patch("vsc.assets.script_ai.shutil.which", return_value="/test/grok"):
            with self.assertRaises(ResourceError) as caught:
                GrokBuildSuggestions(runner=lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired("grok", 1))).generate({}, "test")
            self.assertEqual(caught.exception.code, "suggestion_submission_unknown")
            with self.assertRaises(ResourceError) as caught:
                GrokBuildSuggestions(runner=lambda *a, **k: SimpleNamespace(returncode=1, stderr="sensitive", stdout="sensitive")).generate({}, "test")
            self.assertNotIn("sensitive", str(caught.exception))
