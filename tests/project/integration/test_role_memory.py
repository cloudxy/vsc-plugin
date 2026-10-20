"""Real PostgreSQL role/dispatch/memory lifecycle, including human session seam."""
import copy
import hashlib
import json
import os
import tempfile
import uuid
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from support.fixtures.resource_store import ResourceStoreFixture, HAS_DB_DEPS, TEST_URL
from vsc.project.role_runtime import bind_packet, digest, policy_errors, validate_packet


@unittest.skipUnless(HAS_DB_DEPS and TEST_URL, "explicit PostgreSQL test database required")
class RoleMemoryTests(ResourceStoreFixture, unittest.TestCase):
    def packet(self, role="director", inputs=None, mode=None, **extra):
        from vsc.kernel.catalog import role_cards
        card = role_cards()[role]
        packet = dict(format="vsc.role-context/v2", context_id="CT-" + uuid.uuid4().hex,
            project={"project_id": self.p}, revision=self.rev, scope="project", role=card, task="镜头证据检查",
            inputs=[{"id": a, "sha256": self.service.get_artifact_version(self.p, a)["sha256"]} for a in inputs or []],
            source_refs=[], approved_memories=[], approved_capabilities=[], pilot_capabilities=[], rules=["固定输入"])
        packet.update(extra)
        if packet["approved_memories"]:
            packet["retrieval"] = {"budget_chars": 10000, "used_chars": sum(len(json.dumps(m, ensure_ascii=False, sort_keys=True)) for m in packet["approved_memories"])}
        return bind_packet(packet, host="test-host", actor="agent:" + role + ":" + uuid.uuid4().hex, review_mode=mode)

    def dispatch(self, role="director", inputs=None, mode=None, **extra):
        packet = self.packet(role, inputs, mode, **extra)
        self.write("create_role_dispatch", {"packet": packet})
        return packet

    @staticmethod
    def identity(packet):
        d = packet["dispatch"]
        return {"dispatch_id": d["id"], "instance_id": d["instance_id"], "role_id": d["role_id"],
            "context_sha256": packet["context_sha256"]}

    def consume(self, packet):
        return self.write("consume_role_dispatch", dict(self.identity(packet), packet=packet), actor=packet["dispatch"]["actor"])

    @staticmethod
    def result(packet, proposals=None, **extra):
        result = dict(role_id=packet["role"]["id"], role_sha256=packet["dispatch"]["role_sha256"], context_id=packet["context_id"],
            context_sha256=packet["context_sha256"], dispatch_id=packet["dispatch"]["id"], instance_id=packet["dispatch"]["instance_id"],
            result_refs=[], memory_proposals=proposals or [])
        return dict(result, **extra)

    @staticmethod
    def delivery(kind="synthetic-result"):
        return {"format": "vsc.role-delivery/v1", "purpose": "固定剧本交镜头设计",
            "artifact_type": kind, "consumer": "director", "validation": "读取实际动作与对白，核固定输入关系",
            "preserve": ["原人物及场景范围"]}

    def proposal(self, source, content="镜头检查必须核对证据", **extra):
        return dict(kind="lesson", content=content, sources=[{"kind": "artifact", "id": source,
            "sha256": self.service.get_artifact_version(self.p, source)["sha256"]}], association_complete=True, **extra)

    def return_packet(self, packet, proposals=None, key="return-1", **extra):
        payload = dict(self.identity(packet), result=self.result(packet, proposals, **extra), return_key=key)
        return self.write("return_role_dispatch", payload, actor=packet["dispatch"]["actor"])

    def approve(self, version_id, outcome="approved"):
        from vsc.assets.role_memory import verified_memory_decision
        item = next(r for r in self.service.list_role_memories(self.p)["items"] if r["version_id"] == version_id)
        return self.write("decide_role_memory", {"version_id": version_id, "content_sha256": item["content_sha256"],
            "outcome": outcome, "reason": "隔离测试的真实人工会话决定"}, human_decision=verified_memory_decision("test-human"))

    def test_all_roles_dispatch_consumption_returns_and_retrieval(self):
        from vsc.kernel.catalog import role_cards
        source = self.artifact()
        for role, card in role_cards().items():
            with self.subTest(role=role):
                self.assertEqual(policy_errors(card), [])
                packet = self.dispatch(role, [source])
                self.assertEqual(validate_packet(packet, role, card), [])
                self.consume(packet)
                returned = self.return_packet(packet, [self.proposal(source)])
                proposal = returned["memory_proposals"][0]
                self.assertEqual(proposal["status"], "draft")
                self.approve(proposal["version_id"])
                mode = "followup" if role == "post-reviewer" else "design" if role == "continuity-supervisor" else "work"
                query = self.service.retrieve_role_memories(self.p, role=role, task="镜头检查证据", mode=mode)
                self.assertEqual([m["role"] for m in query["items"]], [role])
                self.assertTrue(query["items"][0]["decision_id"])
                restored = self.packet(role, [source], mode, approved_memories=query["items"])
                restored["dispatch"]["host"] = "second-host"
                restored["context_sha256"] = digest({k: v for k, v in restored.items() if k != "context_sha256"})
                self.write("create_role_dispatch", {"packet": restored})
                self.consume(restored)

    def test_unverified_cli_label_cannot_approve_and_web_session_can(self):
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        from vsc.assets.resource_service import ResourceError
        source = self.artifact()
        packet = self.dispatch(inputs=[source]); self.consume(packet)
        item = self.return_packet(packet, [self.proposal(source)])["memory_proposals"][0]
        row = self.service.list_role_memories(self.p)["items"][0]
        payload = {"version_id": item["version_id"], "content_sha256": row["content_sha256"], "outcome": "approved", "reason": "阅读固定证据后批准"}
        with self.assertRaises(ResourceError) as error:
            self.write("decide_role_memory", payload, actor="human:someone")
        self.assertEqual(error.exception.code, "human_confirmation_required")
        with tempfile.TemporaryDirectory() as root:
            app = create_app({"projects_root": root, "access_token": "synthetic-token", "human_identity": "verified-user"}, service=self.service)
            with TestClient(app, base_url="http://127.0.0.1") as client:
                origin = {"Origin": "http://127.0.0.1:8765"}
                endpoint = "/api/v1/projects/" + self.p + "/role-memory-decisions"
                body = {"payload": payload, "confirmed": True, "expected_revision": self.rev, "idempotency_key": "web-decision"}
                self.assertEqual(client.post(endpoint, json=body, headers=origin).status_code, 403)
                login = client.post("/api/v1/session", json={"token": "synthetic-token"}, headers=origin).json()
                headers = dict(origin, **{"X-CSRF-Token": login["csrf_token"]})
                self.assertEqual(client.post(endpoint, json=dict(body, confirmed=False), headers=headers).status_code, 422)
                bad = copy.deepcopy(body); bad["payload"]["actor"] = "intruder"
                self.assertEqual(client.post(endpoint, json=bad, headers=headers).status_code, 422)
                response = client.post(endpoint, json=body, headers=headers)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["status"], "approved")
                replay = client.post(endpoint, json=body, headers=headers)
                self.assertEqual(replay.json(), response.json())

    def test_identity_tamper_self_approval_and_return_idempotency(self):
        from vsc.assets.resource_service import ResourceError
        source = self.artifact()
        packet = self.dispatch(inputs=[source])
        identity = self.identity(packet)
        with self.assertRaises(ResourceError):
            self.write("consume_role_dispatch", dict(identity, role_id="editor", packet=packet), actor=packet["dispatch"]["actor"])
        bad = copy.deepcopy(packet); bad["task"] = "污染包"
        with self.assertRaises(ResourceError):
            self.write("consume_role_dispatch", dict(identity, packet=bad), actor=packet["dispatch"]["actor"])
        with self.assertRaises(ResourceError):
            self.return_packet(packet)
        self.consume(packet)
        with self.assertRaises(ResourceError):
            self.return_packet(packet, [dict(self.proposal(source), role="editor")])
        returned = self.return_packet(packet, [self.proposal(source)])
        repeated = self.return_packet(packet, [self.proposal(source)])
        self.assertEqual(returned["return_id"], repeated["return_id"])
        self.assertEqual(len(self.service.list_role_memories(self.p)["items"]), 1)
        forged = dict(self.identity(packet), role_id="editor", context_sha256="a"*64,
            result=self.result(packet, [self.proposal(source)]), return_key="return-1")
        with self.assertRaises(ResourceError):
            self.write("return_role_dispatch", forged, actor=packet["dispatch"]["actor"])
        with self.assertRaises(ResourceError):
            self.return_packet(packet, [self.proposal(source, "另一个结论")])

    def test_fresh_review_isolation_and_followup_explicit_judgment(self):
        source = self.artifact("method")
        target = self.artifact("current")
        ids = {}
        for role, kind, reference in [("post-reviewer", "check_method", source), ("post-reviewer", "lesson", target),
                                      ("post-reviewer", "judgment", source), ("director", "lesson", source)]:
            packet = self.dispatch(role, [reference], "followup" if role == "post-reviewer" else "work")
            self.consume(packet)
            proposal = dict(self.proposal(reference), kind=kind)
            item = self.return_packet(packet, [proposal])["memory_proposals"][0]
            self.approve(item["version_id"]); ids[(role, kind, reference)] = item["id"]
        fresh = self.service.retrieve_role_memories(self.p, role="post-reviewer", task="镜头检查证据", mode="fresh", target_artifact_ids=[target])
        self.assertEqual([m["kind"] for m in fresh["items"]], ["check_method"])
        from vsc.assets.resource_service import ResourceError
        judgment = ids[("post-reviewer", "judgment", source)]
        with self.assertRaises(ResourceError):
            self.service.retrieve_role_memories(self.p, role="post-reviewer", task="镜头检查", mode="fresh", forced=[judgment], target_artifact_ids=[target])
        follow = self.service.retrieve_role_memories(self.p, role="post-reviewer", task="镜头检查", mode="followup", forced=[judgment], budget_chars=10000)
        self.assertIn(judgment, [m["id"] for m in follow["items"]])
        with self.assertRaises(ValueError):
            self.packet("post-reviewer", [target], "fresh", parent_brief={"content": "已通过，无需复核"})

    def test_source_invalidation_and_frozen_history(self):
        from vsc.assets.resource_service import ResourceError
        source = self.artifact()
        packet = self.dispatch(inputs=[source]); self.consume(packet)
        item = self.return_packet(packet, [self.proposal(source)])["memory_proposals"][0]; self.approve(item["version_id"])
        knowledge = self.service.retrieve_role_memories(self.p, role="director", task="镜头检查证据")
        frozen = self.dispatch(inputs=[source], approved_memories=knowledge["items"])
        self.artifact()  # same logical artifact key, new immutable source version
        query = self.service.retrieve_role_memories(self.p, role="director", task="镜头检查证据")
        self.assertEqual(query["items"], [])
        self.assertTrue(query["retrieval"]["excluded"])
        with self.assertRaises(ResourceError):
            self.consume(frozen)
        self.assertEqual(self.service.get_role_dispatch(self.p, frozen["dispatch"]["id"])["packet"], frozen)

    def test_concurrent_instances_keep_both_proposals_and_revision_conflict(self):
        from vsc.assets.resource_service import ResourceError
        source = self.artifact()
        packets = [self.dispatch(inputs=[source]) for _ in range(2)]
        for p in packets: self.consume(p)
        revision = self.rev
        def send(index):
            packet = packets[index]
            payload = dict(self.identity(packet), result=self.result(packet, [self.proposal(source, "检查证据 " + str(index))]), return_key="stable")
            try:
                return self.service.return_role_dispatch(self.p, payload, expected_revision=revision,
                    idempotency_key=uuid.uuid4().hex, actor=packet["dispatch"]["actor"])
            except ResourceError as error:
                self.assertEqual(error.code, "revision_conflict")
                return self.service.return_role_dispatch(self.p, payload, expected_revision=self.service.get_project(self.p)["revision"],
                    idempotency_key=uuid.uuid4().hex, actor=packet["dispatch"]["actor"])
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(send, range(2)))
        self.rev = self.service.get_project(self.p)["revision"]
        self.assertEqual(len(self.service.list_role_memories(self.p)["items"]), 2)
        self.assertNotEqual(results[0]["memory_proposals"][0]["id"], results[1]["memory_proposals"][0]["id"])

    def test_cross_project_fk_immutable_records_and_scope_budget(self):
        from sqlalchemy import insert, update
        from sqlalchemy.exc import IntegrityError
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.assets.resource_service import ResourceError
        source = self.artifact(); packet = self.dispatch(inputs=[source]); self.consume(packet)
        item = self.return_packet(packet, [self.proposal(source)])["memory_proposals"][0]; self.approve(item["version_id"])
        other = self.service.create_project({"name": "另一个项目", "profile_snapshot": {"profile_id": "vsc.synthetic", "version": "1", "stages": []}}, actor="test-human")
        with self.assertRaises(IntegrityError):
            with self.engine.begin() as conn:
                conn.execute(insert(S.role_memory_artifacts).values(project_id=other["id"], memory_version_id=item["version_id"], artifact_id=source, source_sha256="a"*64))
        with self.assertRaises(IntegrityError):
            with self.engine.begin() as conn:
                conn.execute(update(S.role_memory_versions).where(S.role_memory_versions.c.project_id == self.p).values(content="伪造覆盖"))
        with self.assertRaises(ResourceError):
            self.service.retrieve_role_memories(self.p, role="director", task="检查", forced=[item["id"]], budget_chars=10)
        self.assertEqual(self.service.retrieve_role_memories(other["id"], role="director", task="检查")["items"], [])

    def test_resume_expiry_close_and_source_invalidation(self):
        from unittest.mock import patch
        from vsc.assets.resource_service import ResourceError
        source = self.artifact()
        packet = self.dispatch(inputs=[source]); self.consume(packet)
        payload = dict(self.identity(packet), result=self.result(packet, session_summary="待补镜头证据"), return_key="partial", closed=False)
        self.write("return_role_dispatch", payload, actor=packet["dispatch"]["actor"])
        summary = self.service.resume_role_summary(self.p, packet["dispatch"]["id"], "director")
        self.assertEqual(summary["content"], "待补镜头证据")
        self.assertEqual(self.service.list_role_memories(self.p)["items"], [])
        with patch("vsc.adapters.persistence.postgres.memory_store.datetime") as clock:
            clock.now.return_value = datetime.now(timezone.utc) + timedelta(days=2)
            with self.assertRaises(ResourceError) as error:
                self.service.resume_role_summary(self.p, packet["dispatch"]["id"], "director")
            self.assertEqual(error.exception.code, "summary_expired")
        with self.assertRaises(ResourceError):
            self.service.resume_role_summary(self.p, packet["dispatch"]["id"], "editor")
        self.return_packet(packet, key="closed")
        with self.assertRaises(ResourceError):
            self.service.resume_role_summary(self.p, packet["dispatch"]["id"], "director")
        other = self.dispatch(inputs=[source]); self.consume(other)
        self.write("return_role_dispatch", dict(self.identity(other), result=self.result(other, session_summary="有界摘要"), return_key="open", closed=False), actor=other["dispatch"]["actor"])
        self.artifact()
        with self.assertRaises(ResourceError) as error:
            self.service.resume_role_summary(self.p, other["dispatch"]["id"], "director")
        self.assertEqual(error.exception.code, "resume_source_invalid")

    def test_memory_revision_retirement_and_ten_task_reference_budget(self):
        from sqlalchemy import func, select
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.assets.resource_service import ResourceError
        source = self.artifact(); packet = self.dispatch(inputs=[source]); self.consume(packet)
        item = self.return_packet(packet, [self.proposal(source)])["memory_proposals"][0]; self.approve(item["version_id"])
        sizes = []
        for index in range(10):
            query = self.service.retrieve_role_memories(self.p, role="director", task="镜头检查证据")
            current = self.dispatch(inputs=[source], approved_memories=query["items"], retrieval=query["retrieval"])
            self.consume(current); self.return_packet(current)
            sizes.append(query["retrieval"]["used_chars"])
        self.assertEqual(len(set(sizes)), 1)
        self.assertLessEqual(sizes[0], 2200)
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(select(func.count()).select_from(S.role_memories).where(S.role_memories.c.project_id == self.p)).scalar_one(), 1)
            self.assertEqual(conn.execute(select(func.count()).select_from(S.dispatch_memory_refs).where(S.dispatch_memory_refs.c.project_id == self.p)).scalar_one(), 10)
        pending = self.dispatch(inputs=[source], approved_memories=query["items"], retrieval=query["retrieval"])
        self.approve(item["version_id"], "retired")
        with self.assertRaises(ResourceError):
            self.consume(pending)
        proposal = dict(self.proposal(source), memory_id=item["id"], expected_memory_revision=1, role="director", proposal_key="revision-2")
        revised = self.write("propose_role_memory", proposal)
        self.assertEqual(revised["version"], 2)
        with self.assertRaises(ResourceError) as error:
            self.write("propose_role_memory", dict(proposal, content="并发旧版本修订"))
        self.assertEqual(error.exception.code, "memory_revision_conflict")
        self.assertEqual(self.service.retrieve_role_memories(self.p, role="director", task="检查")["items"], [])

    def test_migration_roundtrip_metadata_and_known_history_read_only(self):
        from alembic import command
        from alembic.config import Config
        from alembic.autogenerate import compare_metadata
        from alembic.migration import MigrationContext
        from sqlalchemy import text
        from support.paths import ROOT
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.assets.resource_service import ResourceError
        config = Config(str(ROOT / "migrations/postgres/alembic.ini"))
        with self.engine.begin() as conn:
            self.assertEqual(compare_metadata(MigrationContext.configure(conn), S.metadata), [])
            config.attributes["connection"] = conn
            command.downgrade(config, "0008_script_note_baselines")
        try:
            for revision in ("0008_script_note_baselines", "0007_script_suggestions"):
                if revision.startswith("0007"):
                    with self.engine.begin() as conn:
                        config.attributes["connection"] = conn; command.downgrade(config, revision)
                self.assertEqual(self.store.check_schema(read_only=True)["migration"], revision)
                self.assertEqual(self.service.get_project_tree(self.p)["project"]["id"], self.p)
                with self.assertRaises(ResourceError): self.store.check_schema()
            with self.engine.begin() as conn:
                conn.execute(text("UPDATE alembic_version SET version_num='unknown_schema'"))
            with self.assertRaises(ResourceError): self.store.check_schema(read_only=True)
            with self.engine.begin() as conn:
                conn.execute(text("UPDATE alembic_version SET version_num='0007_script_suggestions'"))
        finally:
            with self.engine.begin() as conn:
                config.attributes["connection"] = conn; command.upgrade(config, "head")
                self.assertEqual(compare_metadata(MigrationContext.configure(conn), S.metadata), [])

    def test_typed_media_inputs_and_result_artifact_references(self):
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.assets.resource_service import ResourceError
        objects = self.hierarchy(); source = self.artifact(objects=[objects["shot"]])
        media_id = self.media(); candidate = self.candidate(objects["shot"], media_id)
        selected = self.select(candidate)
        media = self.service.get_media(self.p, media_id)
        resource = {"media_id": media_id, "sha256": media["sha256"], "role": "first_frame", "binding_decision_id": selected["decision_id"]}
        packet = self.dispatch(inputs=[source], scope=objects["shot"], resources=[resource]); self.consume(packet)
        output = self.write("create_artifact", {"artifact_key": "role-result", "artifact_type": "synthetic-result", "document": "尚未批准的专业交付草稿"})
        sha = self.service.get_artifact_version(self.p, output["id"])["sha256"]
        result = self.result(packet); result["result_refs"] = [{"kind": "artifact", "id": output["id"], "sha256": sha}]
        returned = self.write("return_role_dispatch", dict(self.identity(packet), result=result, return_key="fixed-output"), actor=packet["dispatch"]["actor"])
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(select(S.dispatch_result_artifacts.c.artifact_id).where(S.dispatch_result_artifacts.c.project_id == self.p,
                S.dispatch_result_artifacts.c.return_id == returned["return_id"])).scalar_one(), output["id"])
        waiting = self.dispatch(inputs=[source], scope=objects["shot"], resources=[resource])
        self.write("retire_binding", {"slot_id": candidate["slot_id"], "reason": "素材用途变更"})
        with self.assertRaises(ResourceError): self.consume(waiting)

    def test_minimal_director_producer_reviewer_handoff(self):
        """Synthetic fixed artifacts prove protocol handoff, not media quality."""
        brief = self.artifact("brief")
        previous = brief
        for role, key in [("director", "shot-plan"), ("generation-producer", "candidate"), ("post-reviewer", "review")]:
            packet = self.dispatch(role, [previous])
            self.assertEqual([a["id"] for a in packet["inputs"]], [previous])
            self.assertNotIn("conversation", packet)
            self.consume(packet)
            outcome = "fail" if role == "post-reviewer" else "pass"
            output = self.write("create_artifact", {"artifact_key": key, "artifact_type": "synthetic-handoff",
                "document": {"method": "synthetic_protocol_probe", "outcome": outcome, "input_id": previous},
                "dependency_ids": [previous]})
            result = self.result(packet); result["result_refs"] = [{"kind": "artifact", "id": output["id"],
                "sha256": self.service.get_artifact_version(self.p, output["id"])["sha256"]}]
            self.write("return_role_dispatch", dict(self.identity(packet), result=result, return_key="handoff"), actor=packet["dispatch"]["actor"])
            self.assertFalse(self.service.get_artifact_version(self.p, output["id"])["approved"])
            if role != "post-reviewer":
                self.write("decide_artifact", {"artifact_id": output["id"], "reason": "隔离测试操作者确认下一步固定输入"})
            previous = output["id"]
        review = self.service.get_artifact_version(self.p, previous)
        self.assertEqual(json.loads(review["document"])["outcome"], "fail")

    def test_retired_memory_invalidates_existing_summary_resume(self):
        from vsc.assets.resource_service import ResourceError
        source = self.artifact(); initial = self.dispatch(inputs=[source]); self.consume(initial)
        memory = self.return_packet(initial, [self.proposal(source)])["memory_proposals"][0]; self.approve(memory["version_id"])
        knowledge = self.service.retrieve_role_memories(self.p, role="director", task="镜头检查证据")
        packet = self.dispatch(inputs=[source], approved_memories=knowledge["items"], retrieval=knowledge["retrieval"]); self.consume(packet)
        self.write("return_role_dispatch", dict(self.identity(packet), result=self.result(packet, session_summary="旧通过结论"), return_key="partial", closed=False), actor=packet["dispatch"]["actor"])
        self.approve(memory["version_id"], "retired")
        with self.assertRaises(ResourceError): self.service.resume_role_summary(self.p, packet["dispatch"]["id"], "director")
        with self.assertRaises(ResourceError): self.consume(packet)

    def test_source_refs_latest_version_invalidates_consumption_and_resume(self):
        from vsc.assets.resource_service import ResourceError
        source_key = uuid.uuid4().hex
        def register(number):
            source_id = str(uuid.uuid4()); content = "source-" + str(number)
            sha = hashlib.sha256(content.encode()).hexdigest()
            self.write("register_media", {"name": content, "modality": "text", "mime_type": "text/plain", "sha256": sha,
                "size_bytes": len(content), "storage": "local", "object_key": sha, "rights": "unknown",
                "source": {"id": source_id, "source_key": source_key, "version": number, "kind": "original", "content": content}})
            return {"id": source_id, "sha256": sha}
        source = register(1)
        packet = self.dispatch("story-analyst", source_refs=[source]); self.consume(packet)
        self.write("return_role_dispatch", dict(self.identity(packet), result=self.result(packet, session_summary="v1摘要"), return_key="partial", closed=False), actor=packet["dispatch"]["actor"])
        register(2)
        with self.assertRaises(ResourceError): self.consume(packet)
        with self.assertRaises(ResourceError): self.service.resume_role_summary(self.p, packet["dispatch"]["id"], "story-analyst")

    def test_fresh_excludes_memory_with_dependency_on_reviewed_object(self):
        from vsc.assets.resource_service import ResourceError
        target = self.artifact("review-target")
        derived = self.write("create_artifact", {"artifact_key": "prior-judgment", "artifact_type": "synthetic-method",
            "document": "该对象旧通过结论", "dependency_ids": [target]})
        self.write("decide_artifact", {"artifact_id": derived["id"], "reason": "隔离的旧审查证据"})
        packet = self.dispatch("post-reviewer", [derived["id"]], "followup"); self.consume(packet)
        item = self.return_packet(packet, [self.proposal(derived["id"])])["memory_proposals"][0]; self.approve(item["version_id"])
        query = self.service.retrieve_role_memories(self.p, role="post-reviewer", task="镜头检查证据", mode="fresh", target_artifact_ids=[target])
        self.assertEqual(query["items"], [])
        with self.assertRaises(ResourceError):
            self.service.retrieve_role_memories(self.p, role="post-reviewer", task="镜头检查", mode="fresh", target_artifact_ids=[target], forced=[item["id"]])

    def test_dispatch_expiry_is_fixed_by_server_role_policy(self):
        from vsc.assets.resource_service import ResourceError
        for expiry in ("2100-01-01T00:00:00+00:00", "2100-01-01T00:00:00", "not-a-date", "2000-01-01T00:00:00+00:00"):
            with self.subTest(expiry=expiry):
                packet = self.packet(); packet["dispatch"]["expires_at"] = expiry
                packet["context_sha256"] = digest({k: v for k, v in packet.items() if k != "context_sha256"})
                with self.assertRaises(ResourceError): self.write("create_role_dispatch", {"packet": packet})
        packet = self.packet()
        packet["dispatch"]["created_at"] = "2100-01-01T00:00:00+00:00"
        packet["dispatch"]["expires_at"] = "2100-01-02T00:00:00+00:00"
        packet["context_sha256"] = digest({k: v for k, v in packet.items() if k != "context_sha256"})
        with self.assertRaises(ResourceError): self.write("create_role_dispatch", {"packet": packet})

    def test_delivery_rejects_false_completion_and_recovers_unapproved_result(self):
        from vsc.assets.resource_service import ResourceError
        source = self.artifact()
        packet = self.dispatch(inputs=[source], delivery=self.delivery())
        self.consume(packet)
        with self.assertRaises(ResourceError) as caught:
            self.return_packet(packet, session_summary="已全部完成，检查通过")
        self.assertEqual(caught.exception.code, "invalid_dispatch_return")
        identity = self.identity(packet)
        blocked = self.result(packet, session_summary="尚缺可读镜头正文，完成后重新登记并返回")
        self.write("return_role_dispatch", dict(identity, result=blocked, return_key="blocked", closed=False),
            actor=packet["dispatch"]["actor"])
        restored = self.service.resume_role_summary(self.p, packet["dispatch"]["id"], "director")
        self.assertEqual(restored["delivery"], self.delivery())
        self.assertEqual(restored["result_refs"], [])
        foreign_project = self.service.create_project({"name": "独立项目", "profile_snapshot": {
            "profile_id": "vsc.synthetic", "version": "1", "stages": []}}, actor="test-human")
        foreign = self.service.create_artifact(foreign_project["id"], {"artifact_key": "foreign-result",
            "artifact_type": "synthetic-result", "document": "其他项目正文"}, expected_revision=0,
            idempotency_key=uuid.uuid4().hex, actor="test-human")
        with self.assertRaises(ResourceError):
            self.return_packet(packet, result_refs=[{"kind": "artifact", "id": foreign["id"], "sha256": foreign["sha256"]}])
        for values in (
            {"artifact_type": "synthetic-report", "dependency_ids": [source]},
            {"artifact_type": "synthetic-result", "dependency_ids": []},
        ):
            output = self.write("create_artifact", dict(artifact_key=uuid.uuid4().hex,
                document="已登记但不符合本任务要求的正文", **values))
            with self.assertRaises(ResourceError) as caught:
                self.return_packet(packet, result_refs=[{"kind": "artifact", "id": output["id"], "sha256": output["sha256"]}])
            self.assertEqual(caught.exception.code, "return_delivery_mismatch")
        output = self.write("create_artifact", {"artifact_key": "actual-result", "artifact_type": "synthetic-result",
            "document": "近景：角色手指压住门把，停顿一拍再放开。", "dependency_ids": [source]})
        refs = [{"kind": "artifact", "id": output["id"], "sha256": output["sha256"]}]
        with self.assertRaises(ResourceError):
            self.return_packet(packet, result_refs=[dict(refs[0], sha256="0" * 64)])
        self.return_packet(packet, key="finished", result_refs=refs)
        replay = self.return_packet(packet, key="finished", result_refs=refs)
        self.assertTrue(replay["reused"])
        self.assertFalse(self.service.get_artifact_version(self.p, output["id"])["approved"])
        with self.assertRaises(ResourceError):
            self.service.resume_role_summary(self.p, packet["dispatch"]["id"], "director")

    def test_delivery_validates_real_contract_scope_and_fixed_input(self):
        from vsc.assets.resource_service import ResourceError
        objects = self.hierarchy()
        source = self.artifact(objects=[objects["scene"]])
        for metadata in ({"type": "false-type"}, {"version": 999}):
            bad = self.packet(inputs=[source], delivery=self.delivery())
            bad["inputs"][0].update(metadata)
            bad["context_sha256"] = digest({k: v for k, v in bad.items() if k != "context_sha256"})
            with self.assertRaises(ResourceError) as caught:
                self.write("create_role_dispatch", {"packet": bad})
            self.assertEqual(caught.exception.code, "context_input_invalid")
        packet = self.dispatch(inputs=[source], scope=objects["scene"], delivery=self.delivery())
        self.consume(packet)
        wrong_scope = self.write("create_artifact", {"artifact_key": "wide-result", "artifact_type": "synthetic-result",
            "document": "扩大为整个项目的结果", "dependency_ids": [source]})
        with self.assertRaises(ResourceError) as caught:
            self.return_packet(packet, result_refs=[{"kind": "artifact", "id": wrong_scope["id"], "sha256": wrong_scope["sha256"]}])
        self.assertEqual(caught.exception.code, "return_delivery_mismatch")
        with self.assertRaises(ResourceError):
            self.write("create_artifact", {"artifact_key": "blank", "artifact_type": "synthetic-result", "document": "   "})
        for content in ("{}", "[]"):
            empty = self.write("create_artifact", {"artifact_key": uuid.uuid4().hex, "artifact_type": "synthetic-result",
                "document": content, "dependency_ids": [source], "object_ids": [objects["scene"]]})
            with self.assertRaises(ResourceError) as caught:
                self.return_packet(packet, result_refs=[{"kind": "artifact", "id": empty["id"], "sha256": empty["sha256"]}])
            self.assertEqual(caught.exception.code, "return_artifact_invalid")
        output = self.write("create_artifact", {"artifact_key": "scoped-result", "artifact_type": "synthetic-result",
            "document": "本场景中的近景设计", "dependency_ids": [source], "object_ids": [objects["shot"]]})
        refs = [{"kind": "artifact", "id": output["id"], "sha256": output["sha256"]}]
        self.return_packet(packet, result_refs=refs)
        # The repository return also rejects an invalid canonical document
        # imported below the public registration validator.
        invalid = self.store.create_artifact(self.p, {"artifact_key": "invalid-brief", "artifact_type": "vsc.creative_brief",
            "document": {"format": "vsc.creative-brief/v1", "audience": "待填写"}},
            expected_revision=self.rev, idempotency_key=uuid.uuid4().hex, actor="test-human")
        self.rev = invalid["revision"]
        new_packet = self.dispatch(delivery=self.delivery("vsc.creative_brief"))
        self.consume(new_packet)
        with self.assertRaises(ResourceError) as caught:
            self.return_packet(new_packet, result_refs=[{"kind": "artifact", "id": invalid["id"], "sha256": invalid["sha256"]}])
        self.assertEqual(caught.exception.code, "return_artifact_invalid")

    def test_pg_context_cli_build_consume_return_and_resume_delivery(self):
        import contextlib
        import io
        from types import SimpleNamespace
        from vsc.interfaces.cli.pg_state import execute
        from vsc.assets.resource_service import ResourceError
        source = self.artifact()
        with tempfile.TemporaryDirectory() as root:
            definition = Path(root) / "delivery.json"
            definition.write_text(json.dumps(self.delivery()), encoding="utf-8")
            options = dict(command="context", action="build", project=root, role="director", task="产生可读镜头设计",
                scope="project", source=None, artifact=[source], capability=None, pilot=None, memory=None,
                parent_brief=None, budget_chars=2200, review_mode=None, include_restricted=False,
                host="cli-test", actor="agent:cli", instance_id="cli-test", owns=None, resume_dispatch=None,
                delivery=str(definition))
            def run(**updates):
                with contextlib.redirect_stdout(io.StringIO()):
                    execute(self.service, self.p, SimpleNamespace(**dict(options, **updates)))
                self.rev = self.service.get_project(self.p)["revision"]
            run()
            path = next(Path(root).glob("10-记忆/上下文/*.json"))
            packet = json.loads(path.read_text())
            self.assertEqual(packet["delivery"], self.delivery())
            run(action="consume", file=str(path))
            result = self.result(packet, session_summary="尚缺镜头正文，接续继续完成")
            returned = Path(root) / "result.json"; returned.write_text(json.dumps(result), encoding="utf-8")
            run(action="return", file=str(path), result=str(returned), return_key="partial", keep_open=True)
            run(delivery=None, resume_dispatch=packet["dispatch"]["id"], instance_id="resumed")
            restored = [json.loads(p.read_text()) for p in Path(root).glob("10-记忆/上下文/*.json")
                if p != path][0]
            self.assertEqual(restored["delivery"], packet["delivery"])
            self.assertEqual(restored["parent_brief"]["result_refs"], [])
            definition.write_text(json.dumps(self.delivery("different-type")), encoding="utf-8")
            with self.assertRaises(ResourceError):
                run(resume_dispatch=packet["dispatch"]["id"], instance_id="changed")
