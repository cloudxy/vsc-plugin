"""Legacy JSON and SQLite use the same verified memory decision/return policy."""
import contextlib
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from support.paths import SCRIPTS
from vsc.project import state as ST
from vsc.project.role_runtime import digest, validate_packet


class LegacyRoleMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def cli(self, *args, expected=0):
        result = subprocess.run([sys.executable, "-B", str(SCRIPTS / "project/state.py"), *map(str, args)], capture_output=True, text=True)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result.stdout + result.stderr

    def project(self, profile="vsc.light-short"):
        path = self.root / uuid.uuid4().hex
        self.cli("init", path, "--title", "隔离记忆测试", "--profile", profile)
        document = self.root / "evidence.md"; document.write_text("固定来源依据", "utf-8")
        artifact_id = self.cli("artifact", "add", path, "--stage", "brief", "--type", "vsc.synthetic", "--file", document).split()[1]
        self.cli("artifact", "decide", path, artifact_id, "--status", "approved", "--by", "测试操作者")
        return path, artifact_id

    def packet(self, project, source, role="director", **kw):
        flags = [value for name, value in kw.items() for value in ("--" + name.replace("_", "-"), str(value))]
        context_id = self.cli("context", "build", project, "--role", role, "--task", "镜头检查证据", "--artifact", source,
            "--host", "host-one", "--actor", "agent:one", "--instance-id", uuid.uuid4().hex, *flags).split()[1]
        path = project / "10-记忆/上下文" / (context_id + ".json")
        return path, json.loads(path.read_text())

    @staticmethod
    def result(packet, proposals):
        return {"role_id": packet["role"]["id"], "role_sha256": packet["dispatch"]["role_sha256"],
            "context_id": packet["context_id"], "context_sha256": packet["context_sha256"], "dispatch_id": packet["dispatch"]["id"],
            "instance_id": packet["dispatch"]["instance_id"], "result_refs": [], "memory_proposals": proposals}

    def consume(self, project, path, packet, **kw):
        return self.cli("context", "consume", project, "--file", path, "--role", packet["role"]["id"],
            "--instance-id", packet["dispatch"]["instance_id"], "--actor", "agent:one", **kw)

    def return_packet(self, project, path, packet, proposals, keep_open=False, expected=0,
                      return_key="stable-return", **extra):
        result = self.result(packet, proposals); result.update(extra)
        result_path = self.root / "return.json"; result_path.write_text(json.dumps(result, ensure_ascii=False))
        return self.cli("context", "return", project, "--file", path, "--result", result_path, "--role", packet["role"]["id"],
            "--instance-id", packet["dispatch"]["instance_id"], "--actor", "agent:one", "--return-key", return_key,
            *(["--keep-open"] if keep_open else []), expected=expected)

    def test_json_and_sqlite_proposal_human_web_decision_retrieval_and_return(self):
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        for profile in ("vsc.light-short", "vsc.series-db"):
            with self.subTest(profile=profile):
                project, source = self.project(profile)
                path, packet = self.packet(project, source)
                self.assertEqual(validate_packet(packet), [])
                self.consume(project, path, packet)
                self.consume(project, path, packet)
                self.assertEqual(len(ST.project_state(project)["contexts"][-1]["consumptions"]), 1)
                source_row = ST.artifact_by_id(ST.project_state(project), source)
                sha = source_row["sha256"]
                proposals = [{"kind": "lesson", "content": "镜头证据需要检查", "association_complete": True,
                    "sources": [{"kind": "artifact", "id": source, "sha256": sha}]}]
                self.return_packet(project, path, packet, proposals)
                self.return_packet(project, path, packet, proposals)
                state = ST.project_state(project)
                self.assertEqual(len(state["memories"]), 1)
                self.assertEqual(state["memories"][0]["origin"], "agent_proposed")
                item = state["memories"][0]
                self.cli("memory", "decide", project, item["id"], "--status", "approved", "--by", "human", expected=1)
                app = create_app({"projects_root": str(self.root), "access_token": "test", "human_identity": "human"})
                with TestClient(app, base_url="http://127.0.0.1") as client:
                    headers = {"Origin": "http://127.0.0.1:8765"}
                    login = client.post("/api/v1/session", headers=headers, json={"token": "test"}).json()
                    headers["X-CSRF-Token"] = login["csrf_token"]
                    url = "/api/v1/projects/" + state["project_id"] + "/role-memory-decisions"
                    body = {"confirmed": True, "expected_revision": state["revision"], "idempotency_key": "approve-memory",
                        "payload": {"version_id": item["id"], "content_sha256": hashlib.sha256(item["content"].encode()).hexdigest(),
                            "outcome": "approved", "reason": "确认此固定来源和结论"}}
                    response = client.post(url, headers=headers, json=body)
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(client.post(url, headers=headers, json=body).json(), response.json())
                    self.assertEqual(client.get("/api/v1/projects/" + state["project_id"] + "/role-memories").json()["items"][0]["status"], "approved")
                path2, packet2 = self.packet(project, source, host="host-two")
                self.assertEqual([m["id"] for m in packet2["approved_memories"]], [item["id"]])
                self.consume(project, path2, packet2)
                if profile == "vsc.series-db":
                    from vsc.adapters.persistence.sqlite.series import load_state
                    self.assertEqual(load_state(project), ST.project_state(project))

    def test_every_role_can_propose_and_read_private_memory(self):
        from support.fixtures.human_memory import decide_legacy_memory
        from vsc.kernel.catalog import role_cards
        project, source = self.project()
        source_row = ST.artifact_by_id(ST.project_state(project), source)
        for role in role_cards():
            with self.subTest(role=role):
                mode = "followup" if role == "post-reviewer" else "design" if role == "continuity-supervisor" else "work"
                path, packet = self.packet(project, source, role=role, review_mode=mode)
                self.consume(project, path, packet)
                proposal = {"kind": "lesson", "content": "镜头检查证据 " + role, "association_complete": True,
                    "sources": [{"kind": "artifact", "id": source, "sha256": source_row["sha256"]}]}
                self.return_packet(project, path, packet, [proposal])
                item = ST.project_state(project)["memories"][-1]
                decide_legacy_memory(project, item["id"])
                _, next_packet = self.packet(project, source, role=role, review_mode=mode)
                self.assertEqual([m["role"] for m in next_packet["approved_memories"]], [role])

    def test_tamper_wrong_role_source_change_and_summary_lifecycle(self):
        from vsc.project.role_runtime_legacy import resume_summary
        from vsc.assets.resource_service import ResourceError
        project, source = self.project()
        path, packet = self.packet(project, source)
        bad = json.loads(path.read_text()); bad["task"] = "篡改"
        path.write_text(json.dumps(bad, ensure_ascii=False)); self.consume(project, path, packet, expected=1)
        ST.write_json(path, packet); self.consume(project, path, packet)
        self.return_packet(project, path, packet, [], keep_open=True, session_summary="尚缺镜头证据")
        state = ST.project_state(project)
        summary = resume_summary(project, state, packet["dispatch"]["id"], "director")
        self.assertEqual(summary["content"], "尚缺镜头证据")
        _, resumed = self.packet(project, source, resume_dispatch=packet["dispatch"]["id"])
        self.assertEqual(resumed["parent_brief"]["persistence"], "temporary_resume_only")
        with self.assertRaises(ResourceError):
            resume_summary(project, state, packet["dispatch"]["id"], "editor")
        state = ST.project_state(project)
        state["contexts"][0]["returns"][-1]["expires_at"] = "2000-01-01T00:00:00+00:00"
        ST.save(project, state)
        with self.assertRaises(ResourceError):
            resume_summary(project, ST.project_state(project), packet["dispatch"]["id"], "director")

    def test_retired_memory_invalidates_json_and_sqlite_summary(self):
        from support.fixtures.human_memory import decide_legacy_memory
        from vsc.project.role_runtime_legacy import resume_summary
        from vsc.assets.resource_service import ResourceError
        for profile in ("vsc.light-short", "vsc.series-db"):
            with self.subTest(profile=profile):
                project, source = self.project(profile)
                memory = self.cli("memory", "add", project, "--scope", "role", "--role", "director", "--kind", "lesson",
                    "--source", source, "--content", "镜头证据检查").split()[1]
                decide_legacy_memory(project, memory)
                path, packet = self.packet(project, source); self.consume(project, path, packet)
                self.return_packet(project, path, packet, [], keep_open=True, session_summary="旧通过结论")
                decide_legacy_memory(project, memory, outcome="retired")
                with self.assertRaises(ResourceError): resume_summary(project, ST.project_state(project), packet["dispatch"]["id"], "director")
                self.consume(project, path, packet, expected=1)

    def test_fresh_dependency_closure_and_cli_association_metadata(self):
        from support.fixtures.human_memory import decide_legacy_memory
        project, target = self.project()
        document = self.root / "prior.md"; document.write_text("镜头证据检查", "utf-8")
        derived = self.cli("artifact", "add", project, "--stage", "brief", "--type", "vsc.synthetic",
            "--file", document, "--depends", target).split()[1]
        self.cli("artifact", "decide", project, derived, "--status", "approved", "--by", "测试")
        memory = self.cli("memory", "add", project, "--scope", "role", "--role", "post-reviewer", "--kind", "lesson",
            "--source", derived, "--association-complete", "--content", "镜头证据检查").split()[1]
        self.assertTrue(ST.project_state(project)["memories"][-1]["association_complete"])
        decide_legacy_memory(project, memory)
        _, packet = self.packet(project, target, role="post-reviewer", review_mode="fresh")
        self.assertEqual(packet["approved_memories"], [])

    def test_delivery_json_sqlite_real_results_blocked_resume_and_file_damage(self):
        from vsc.assets.resource_service import ResourceError
        from vsc.project.role_runtime_legacy import resume_summary
        delivery = {"format": "vsc.role-delivery/v1", "purpose": "固定剧本交镜头设计",
            "artifact_type": "vsc.synthetic_result", "consumer": "director",
            "validation": "读取实际镜头动作并核版本", "preserve": ["原人物和场景"]}
        definition = self.root / "delivery.json"
        definition.write_text(json.dumps(delivery), encoding="utf-8")
        for profile in ("vsc.light-short", "vsc.series-db"):
            with self.subTest(profile=profile):
                project, source = self.project(profile)
                path, packet = self.packet(project, source, delivery=definition)
                self.assertEqual(packet["delivery"], delivery)
                self.consume(project, path, packet)
                self.return_packet(project, path, packet, [], session_summary="已完成", expected=1)
                self.return_packet(project, path, packet, [], keep_open=True, return_key="blocked",
                    session_summary="还缺实际镜头正文；补齐后返回")
                _, resumed = self.packet(project, source, resume_dispatch=packet["dispatch"]["id"])
                self.assertEqual(resumed["delivery"], delivery)
                self.assertEqual(resumed["parent_brief"]["result_refs"], [])
                document = self.root / "result.md"
                document.write_text("近景：手指按下门把，停一拍后松开。", encoding="utf-8")
                def register(kind="vsc.synthetic_result", depends=True):
                    identifier = self.cli("artifact", "add", project, "--stage", "brief", "--type", kind,
                        "--file", document, *(["--depends", source] if depends else [])).split()[1]
                    return ST.artifact_by_id(ST.project_state(project), identifier)
                for wrong in (register("vsc.synthetic_report"), register(depends=False)):
                    self.return_packet(project, path, packet, [], expected=1,
                        result_refs=[{"kind": "artifact", "id": wrong["id"], "sha256": wrong["sha256"]}])
                output = register()
                refs = [{"kind": "artifact", "id": output["id"], "sha256": output["sha256"]}]
                self.return_packet(project, path, packet, [], expected=1,
                    result_refs=[dict(refs[0], sha256="0" * 64)])
                self.return_packet(project, path, packet, [], expected=1,
                    result_refs=[{"kind": "artifact", "id": "/tmp/unregistered.md", "sha256": output["sha256"]}])
                fixed = project / output["path"]
                original = fixed.read_bytes()
                fixed.unlink()
                self.return_packet(project, path, packet, [], expected=1, result_refs=refs)
                fixed.write_bytes(original + b"\nchanged")
                self.return_packet(project, path, packet, [], expected=1, result_refs=refs)
                fixed.write_bytes(original)
                self.return_packet(project, path, packet, [], keep_open=True, return_key="draft",
                    result_refs=refs, session_summary="已有可读草稿，待专业阅读")
                restored = resume_summary(project, ST.project_state(project), packet["dispatch"]["id"], "director")
                self.assertEqual(restored["result_refs"], refs)
                self.assertEqual(ST.artifact_by_id(ST.project_state(project), output["id"])["status"], "draft")
                fixed.write_bytes(original + b"\nchanged")
                with self.assertRaises(ResourceError):
                    resume_summary(project, ST.project_state(project), packet["dispatch"]["id"], "director")
                fixed.write_bytes(original)
                self.return_packet(project, path, packet, [], result_refs=refs)
                self.return_packet(project, path, packet, [], result_refs=refs)
                self.assertEqual(len(ST.project_state(project)["contexts"][0]["returns"]), 3)

    def test_delivery_scope_and_template_contract_remain_enforced(self):
        delivery = {"format": "vsc.role-delivery/v1", "purpose": "制作本集设计",
            "artifact_type": "vsc.synthetic_result", "consumer": "director",
            "validation": "阅读固定正文", "preserve": []}
        definition = self.root / "scope-delivery.json"; definition.write_text(json.dumps(delivery), encoding="utf-8")
        for profile in ("vsc.light-short", "vsc.series-db"):
            with self.subTest(profile=profile):
                project, source = self.project(profile)
                self.cli("object", "add", project, "--kind", "episode", "--id", "EP-001", "--label", "合成范围")
                path, packet = self.packet(project, source, delivery=definition, scope="EP-001")
                self.consume(project, path, packet)
                document = self.root / "scoped.md"; document.write_text("本集明确动作设计", encoding="utf-8")
                for scope, expected in (("project", 1), ("EP-001", 0)):
                    identifier = self.cli("artifact", "add", project, "--stage", "brief", "--type", "vsc.synthetic_result",
                        "--file", document, "--depends", source, "--scope", scope).split()[1]
                    row = ST.artifact_by_id(ST.project_state(project), identifier)
                    self.return_packet(project, path, packet, [], expected=expected,
                        result_refs=[{"kind": "artifact", "id": row["id"], "sha256": row["sha256"]}])
                # Draft registration preserves incomplete work; a template shell
                # must still fail when returned as the task's deliverable.
                template = self.root / "empty-brief.json"
                template.write_text(json.dumps({"format": "vsc.creative-brief/v1", "audience": "待填写"}), encoding="utf-8")
                identifier = self.cli("artifact", "add", project, "--stage", "brief", "--type", "vsc.creative_brief",
                    "--file", template, "--depends", source).split()[1]
                row = ST.artifact_by_id(ST.project_state(project), identifier)
                definition.write_text(json.dumps(dict(delivery, artifact_type="vsc.creative_brief")), encoding="utf-8")
                brief_path, brief_packet = self.packet(project, source, delivery=definition)
                self.consume(project, brief_path, brief_packet)
                message = self.return_packet(project, brief_path, brief_packet, [], expected=1,
                    result_refs=[{"kind": "artifact", "id": row["id"], "sha256": row["sha256"]}])
                self.assertIn("返回产物不可用", message)
                definition.write_text(json.dumps(delivery), encoding="utf-8")
