"""Explicit AI delegation, real bytes and immutable relational audit in PostgreSQL."""
import hashlib
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone

from support.paths import ROOT

TEST_URL = os.environ.get("VSC_TEST_DATABASE_URL")
HAS_DB_DEPS = all(importlib.util.find_spec(name) for name in ("sqlalchemy", "psycopg", "alembic"))


@unittest.skipUnless(TEST_URL and HAS_DB_DEPS, "requires explicit VSC_TEST_DATABASE_URL and postgres dependencies")
class ReviewDelegationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from support.fixtures.postgres import isolated_postgres
        from vsc.adapters.persistence.postgres.resource_store import PostgresResourceStore
        cls.db = isolated_postgres(TEST_URL)
        cls.engine = cls.db.__enter__()
        cls.store = PostgresResourceStore(engine=cls.engine)

    @classmethod
    def tearDownClass(cls):
        cls.db.__exit__(None, None, None)

    def write(self, method, payload, actor="codex"):
        row = getattr(self.service, method)(self.p, payload, actor=actor, expected_revision=self.rev,
                                          idempotency_key=uuid.uuid4().hex)
        self.rev = row["revision"]
        return row

    def setUp(self):
        from vsc.assets.resource_service import ResourceService
        from vsc.adapters.storage.local.store import LocalStorage
        self.temp = tempfile.TemporaryDirectory(prefix="vsc-delegation-test-")
        self.addCleanup(self.temp.cleanup)
        self.storage = LocalStorage(self.temp.name)
        self.service = ResourceService(self.store, self.storage)
        self.p = self.service.create_project({"name": "委托选择", "profile_snapshot": {
            "profile_id": "vsc.synthetic", "version": "1", "stages": []}}, actor="test-human")["id"]
        self.rev = 0
        self.asset = self.write("create_object", {"kind": "asset", "asset_kind": "character", "display_code": "CHAR"})["id"]
        self.other = self.write("create_object", {"kind": "asset", "asset_kind": "character", "display_code": "OTHER"})["id"]
        raw = self.media_bytes = b"controlled synthetic bytes"
        sha = hashlib.sha256(raw).hexdigest()
        self.object_key = sha + ".bin"
        self.storage.resolve(self.object_key).write_bytes(raw)
        self.media = self.write("register_media", {"name": "测试素材", "modality": "image", "sha256": sha,
            "size_bytes": len(raw), "mime_type": "image/png", "storage": "local", "object_key": self.object_key,
            "rights": "owned", "source": {"kind": "test", "content": "explicit synthetic rights evidence"}})["id"]
        self.write("record_media_check", {"media_id": self.media, "checker": "test", "criteria_version": "1", "outcome": "pass"})
        self.candidate = self.write("propose_binding", {"target_object_id": self.asset, "media_id": self.media,
            "role": "identity_face", "context_sha256": "a" * 64})
        self.review = self.ai_review()

    def ai_review(self, **changes):
        return self.write("record_review", dict(candidate_id=self.candidate["id"], reviewer_type="ai", outcome="pass",
            reason="AI复核建议；无人工观看声明", context_sha256="a" * 64, **changes))

    def policy(self, scopes=None, approve=True, **changes):
        doc = {"format": "vsc.review-delegation/v1", "project_id": self.p, "grantor_actor": "test-human",
            "delegate_actor": "codex", "allowed_roles": ["identity_face"],
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "action": "select_candidate", "final_release_authorized": False}
        doc.update(changes)
        row = self.write("create_artifact", {"artifact_key": "delegation-" + uuid.uuid4().hex,
            "artifact_type": "vsc.review_delegation", "document": doc, "object_ids": scopes if scopes is not None else [self.asset]})
        if approve:
            self.write("decide_artifact", {"artifact_id": row["id"], "reason": "明确委托本范围素材选择，未声明已经观看"}, actor="test-human")
        return row

    def choose(self, policy, review=None, actor="codex"):
        return self.write("select_candidate", {"candidate_id": self.candidate["id"], "delegation_artifact_id": policy["id"],
            "review_id": (review or self.review)["id"], "reason": "按已批准委托选择；保留AI审查身份"}, actor=actor)

    def assert_blocked(self, code, action):
        from vsc.assets.resource_service import ResourceError
        with self.assertRaises(ResourceError) as caught:
            action()
        self.assertEqual(caught.exception.code, code)

    def test_approved_delegation_links_ai_review_policy_and_human_grant(self):
        from sqlalchemy import select, update
        from sqlalchemy.exc import IntegrityError
        from vsc.adapters.persistence.postgres import schema as S
        policy = self.policy()
        decision = self.choose(policy)
        usage = self.service.get_media_usage(self.p, self.media)
        self.assertEqual(usage["totals"]["selection_delegations"], 1)
        self.assertEqual(usage["selection_delegations"][0]["reviewer_type"], "ai")
        with self.engine.connect() as conn:
            link = conn.execute(select(S.binding_selection_delegations).where(
                S.binding_selection_delegations.c.project_id == self.p)).mappings().one()
            self.assertEqual(link["decision_id"], decision["id"])
            self.assertEqual(link["review_id"], self.review["id"])
            self.assertEqual(link["delegation_artifact_id"], policy["id"])
            review = conn.execute(select(S.media_reviews).where(S.media_reviews.c.project_id == self.p,
                S.media_reviews.c.id == self.review["id"])).mappings().one()
            self.assertEqual((review["reviewer_type"], review["reviewer"]), ("ai", "codex"))
            approval = conn.execute(select(S.artifact_decisions).where(S.artifact_decisions.c.project_id == self.p,
                S.artifact_decisions.c.id == link["approval_decision_id"])).mappings().one()
            self.assertEqual(approval["actor"], "test-human")
        with self.assertRaises(IntegrityError), self.engine.begin() as conn:
            conn.execute(update(S.binding_selection_delegations).where(S.binding_selection_delegations.c.project_id == self.p)
                .values(review_id=self.review["id"]))

    def test_default_still_requires_human_and_delegate_cannot_approve_policy(self):
        self.assert_blocked("human_review_required", lambda: self.write("select_candidate", {
            "candidate_id": self.candidate["id"], "reason": "无委托"}))
        policy = self.policy(approve=False)
        self.assert_blocked("delegation_grantor_required", lambda: self.write("decide_artifact", {
            "artifact_id": policy["id"], "reason": "AI不能自批"}))
        self.assert_blocked("delegation_unapproved", lambda: self.choose(policy))

    def test_scope_actor_expiry_role_and_revocation_are_enforced(self):
        cases = [("scope", {"scopes": [self.other]}, "delegation_scope_mismatch"),
                 ("role", {"allowed_roles": ["prop"]}, "delegation_scope_mismatch"),
                 ("expiry", {"expires_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()}, "delegation_expired")]
        for name, changes, code in cases:
            with self.subTest(name=name):
                policy = self.policy(**changes)
                self.assert_blocked(code, lambda: self.choose(policy))
        policy = self.policy()
        self.assert_blocked("delegation_actor_mismatch", lambda: self.choose(policy, actor="other-ai"))
        self.write("decide_artifact", {"artifact_id": policy["id"], "outcome": "revoke", "reason": "委托人撤销"}, actor="test-human")
        self.assert_blocked("delegation_unapproved", lambda: self.choose(policy))

    def test_human_veto_and_latest_ai_review_cannot_be_overridden(self):
        policy = self.policy()
        self.ai_review_changes(outcome="fail")
        self.assert_blocked("delegation_review_mismatch", lambda: self.choose(policy))
        self.review = self.ai_review()
        self.write("record_review", {"candidate_id": self.candidate["id"], "reviewer_type": "human",
            "outcome": "fail", "reason": "人工明确拒绝"}, actor="test-human")
        self.assert_blocked("human_review_veto", lambda: self.choose(policy))

    def ai_review_changes(self, **changes):
        payload = {"candidate_id": self.candidate["id"], "reviewer_type": "ai", "outcome": "pass",
                   "reason": "新的AI复核", "context_sha256": "a" * 64}
        payload.update(changes)
        return self.write("record_review", payload)

    def test_real_bytes_rights_and_checks_remain_required(self):
        from vsc.assets.resource_service import ResourceService
        policy = self.policy()
        self.service = ResourceService(self.store)
        self.assert_blocked("delegation_storage_required", lambda: self.choose(policy))
        self.service = ResourceService(self.store, self.storage)
        self.storage.resolve(self.object_key).write_bytes(b"tampered")
        self.assert_blocked("media_unavailable", lambda: self.choose(policy))
        self.storage.resolve(self.object_key).write_bytes(self.media_bytes)
        self.write("record_media_check", {"media_id": self.media, "checker": "test", "criteria_version": "1", "outcome": "fail"})
        self.assert_blocked("unusable_media", lambda: self.choose(policy))
        self.write("record_media_check", {"media_id": self.media, "checker": "test", "criteria_version": "1", "outcome": "pass"})
        self.write("decide_rights", {"media_id": self.media, "outcome": "restricted", "reason": "测试权限限制"})
        self.assert_blocked("unusable_media", lambda: self.choose(policy))

    def test_invalid_contract_and_project_wide_policy_are_rejected(self):
        for changes in ({"final_release_authorized": True}, {"action": "publish"}, {"expires_at": "2026-10-16T10:00:00"}):
            with self.subTest(changes=changes):
                self.assert_blocked("invalid_contract", lambda: self.policy(**changes))
        self.assert_blocked("invalid_delegation", lambda: self.policy(scopes=[]))

    def test_database_rejects_self_approval_outside_application(self):
        from sqlalchemy import insert
        from sqlalchemy.exc import IntegrityError
        from vsc.adapters.persistence.postgres import schema as S
        policy = self.policy(approve=False)
        with self.assertRaises(IntegrityError), self.engine.begin() as conn:
            conn.execute(insert(S.artifact_decisions).values(project_id=self.p, id=str(uuid.uuid4()),
                artifact_id=policy["id"], outcome="approve", decision_sequence=100000,
                actor="codex", reason="direct forbidden", based_on_revision=self.rev))

    def test_database_rejects_review_for_different_selected_candidate(self):
        from sqlalchemy import insert, select
        from sqlalchemy.exc import IntegrityError
        from vsc.adapters.persistence.postgres import schema as S
        policy = self.policy()
        other_candidate = self.write("propose_binding", {"target_object_id": self.asset, "media_id": self.media,
            "role": "identity_face", "context_sha256": "a" * 64})
        decision_id = str(uuid.uuid4())
        with self.assertRaises(IntegrityError) as caught:
            with self.engine.begin() as conn:
                approval_id = conn.execute(select(S.artifact_decisions.c.id).where(
                    S.artifact_decisions.c.project_id == self.p, S.artifact_decisions.c.artifact_id == policy["id"])).scalar_one()
                conn.execute(insert(S.binding_decisions).values(project_id=self.p, id=decision_id,
                    slot_id=self.candidate["slot_id"], candidate_id=other_candidate["id"], outcome="select",
                    actor="codex", reason="synthetic forged association", decision_sequence=100000, based_on_revision=self.rev))
                conn.execute(insert(S.binding_selection_delegations).values(project_id=self.p, decision_id=decision_id,
                    slot_id=self.candidate["slot_id"], candidate_id=self.candidate["id"], review_id=self.review["id"],
                    delegation_artifact_id=policy["id"], approval_decision_id=approval_id))
        self.assertEqual(caught.exception.orig.sqlstate, "23503")
