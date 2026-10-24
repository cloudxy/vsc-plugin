"""Real PG library versions, project isolation and original consumers."""
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import struct
import tempfile
import unittest
import uuid
import zlib
import wave
import json
import shutil
from types import SimpleNamespace
from threading import Barrier
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from support.fixtures.resource_store import ResourceStoreFixture

HAS_DB = all(importlib.util.find_spec(name) for name in ("sqlalchemy", "psycopg", "alembic"))
TEST_URL = os.environ.get("VSC_TEST_DATABASE_URL")


def png_bytes(color=b"\x28\x80\xb0"):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress((b"\x00" + color * 2) * 2)) + chunk(b"IEND", b"")


@unittest.skipUnless(TEST_URL and HAS_DB, "requires configured isolated PostgreSQL")
class SharedLibraryTest(ResourceStoreFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        from vsc.adapters.storage.local.store import LocalStorage
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.service.storage = LocalStorage(self.directory.name)
        self.library_key = "synthetic-library-" + uuid.uuid4().hex

    def actual_media(self, name="Synthetic image", color=b"\x28\x80\xb0", rights="owned", scope=None):
        staged = self.service.storage.stage_upload(io.BytesIO(png_bytes(color)), "fixture.png")
        value = self.write("register_media", {"name": name, "staged_upload": staged["staged_upload"], "rights": rights,
            "rights_scope": scope or {"purposes": ["*"]}, "source": {"kind": "synthetic-owned", "content": "Synthetic fixture evidence"}})
        self.write("record_media_check", {"media_id": value["id"], "checker": "ffprobe-fixture", "criteria_version": "1", "outcome": "pass"})
        return value["id"]

    def description(self):
        return {"library_key": self.library_key, "title": "Synthetic shared reference", "category": "image",
            "description": "A deliberately public synthetic description", "specification": {"style": "flat"},
            "allowed_purposes": ["first_frame", "composition"],
            "license": {"outcome": "owned", "allow_workspace_reuse": True, "evidence": "Synthetic original, no third-party content"}}

    def publish(self, media_id, **extra):
        return self.write("publish_library", dict(self.description(), members=[{"media_id": media_id, "member_key": "reference", "role": "first_frame"}], **extra))

    def target(self):
        project = self.service.create_project({"name": "Target synthetic project", "profile_snapshot": {"profile_id": "vsc.synthetic", "version": "1", "stages": []}}, actor="test-human")
        self.p, self.rev = project["id"], 0
        objects = self.hierarchy()
        self.artifact(objects=[objects["shot"]])
        self.artifact("state", "scene-state", [objects["scene"]], {"state_versions": [{"scene_id": objects["scene"]}]})
        return objects

    def use_payload(self, version, shot, **extra):
        return dict(library_version_id=version["library_version_id"], member_key="reference", target_object_id=shot, role="first_frame", select=True, **extra)

    def counts(self):
        from sqlalchemy import select, func
        from vsc.adapters.persistence.postgres import schema as S
        with self.engine.connect() as conn:
            return {name: conn.execute(select(func.count()).select_from(S.metadata.tables[name])).scalar_one()
                    for name in ("media_blobs", "media_items", "library_reuses", "binding_candidates", "generation_jobs", "job_events")}

    def test_real_two_project_fixed_blob_consumer_replay_update_and_recycle(self):
        a = self.hierarchy()
        self.artifact(objects=[a["shot"]])
        self.artifact("state", "scene-state", [a["scene"]], {"state_versions": [{"scene_id": a["scene"]}]})
        original = self.actual_media()
        source_choice = self.select(self.candidate(a["shot"], original))
        source_project, source_revision = self.p, self.rev
        version = self.publish(original)
        source_revision = self.rev
        public = self.service.get_library_version(version["library_version_id"])
        self.assertNotIn(source_project, str(public))
        self.assertNotIn("object_key", str(public))
        self.assertEqual(self.service.library_member_content(version["library_version_id"], "reference")[0].read_bytes(), png_bytes())
        b = self.target()
        payload = self.use_payload(version, b["shot"])
        before = self.counts()
        files = set(Path(self.directory.name).glob("blobs/*/*"))
        revision = self.rev
        with patch("httpx.Client.post") as provider_post:
            used = self.write("use_library", payload, idempotency_key="fixed-use")
            provider_post.assert_not_called()
        after = self.counts()
        self.assertEqual(after["media_blobs"], before["media_blobs"])
        self.assertEqual(after["generation_jobs"], before["generation_jobs"])
        self.assertEqual(after["job_events"], before["job_events"])
        self.assertEqual(set(Path(self.directory.name).glob("blobs/*/*")), files)
        self.assertEqual(used["revision"], revision + 1)
        self.assertNotEqual(used["media_id"], original)
        self.assertEqual(self.service.get_media(self.p, used["media_id"])["blob_id"], self.service.get_media(source_project, original)["blob_id"])
        context = self.service.compile_shot_context(self.p, b["shot"], "video_clip")
        self.assertTrue(context["ready"], context["gaps"])
        self.assertEqual(context["media"][0]["media_id"], used["media_id"])
        self.assertEqual(context["media"][0]["binding_decision_id"], used["decision_id"])
        replay = self.service.use_library(self.p, payload, expected_revision=revision,
            idempotency_key="fixed-use", actor="test-human")
        self.assertEqual(replay, used)
        self.assertEqual(self.counts(), after)
        target_project, target_revision = self.p, self.rev
        self.p, self.rev = source_project, source_revision
        v2 = self.publish(original, description="New public version", title="Synthetic updated shared reference")
        self.assertEqual(v2["version"], 2)
        self.write("retire_binding", {"slot_id": source_choice["slot_id"], "reason": "Source trash test"})
        result = self.write("recycle_media", {"media_ids": [original], "action": "trash", "reason": "Registration can be recovered"})
        self.assertEqual(result["items"][0]["status"], "trashed")
        self.p, self.rev = target_project, target_revision
        after_update = self.service.compile_shot_context(self.p, b["shot"], "video_clip")
        self.assertTrue(after_update["ready"], after_update["gaps"])
        self.assertEqual(after_update["sha256"], context["sha256"])
        self.assertEqual(self.service.get_library_version(version["library_version_id"])["description"], public["description"])
        self.assertEqual(self.service.get_library_version(version["library_version_id"])["title"], public["title"])
        latest = self.service.search_library("Synthetic updated shared reference")["items"]
        self.assertIn(v2["library_version_id"], [row["current_version_id"] for row in latest])

    def test_import_without_project_is_idempotent_and_uses_original_bytes(self):
        staged = self.service.storage.stage_upload(io.BytesIO(png_bytes()), "import.png")
        payload = dict(self.description(), import_key="external-" + uuid.uuid4().hex,
            members=[{"staged_upload": staged["staged_upload"], "member_key": "reference"}])
        before = self.counts()
        first = self.service.import_library(payload, actor="test-human")
        again = self.service.import_library(payload, actor="test-human")
        self.assertEqual(first, again)
        self.assertEqual(self.counts()["media_items"], before["media_items"])
        self.assertEqual(self.service.library_member_content(first["library_version_id"], "reference")[0].read_bytes(), png_bytes())
        from vsc.assets.resource_service import Conflict
        with self.assertRaises(Conflict):
            self.service.import_library(dict(payload, description="different"), actor="test-human")

    def test_two_images_and_sound_import_without_fake_project_and_original_render_consumer(self):
        from vsc.assets.resource_service import ResourceError
        sound = io.BytesIO()
        with wave.open(sound, "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(8000)
            output.writeframes(b"\x00\x00" * 8000)
        members = []
        for key, raw, filename in (("reference", png_bytes(), "one.png"),
                ("alternate", png_bytes(b"\x90\x80\x40"), "two.png"), ("sound", sound.getvalue(), "sound.wav")):
            staged = self.service.storage.stage_upload(io.BytesIO(raw), filename)
            members.append({"member_key": key, "staged_upload": staged["staged_upload"]})
        payload = dict(self.description(), allowed_purposes=["first_frame", "sfx"],
            import_key="multi-" + uuid.uuid4().hex, members=members)
        version = self.service.import_library(payload, actor="test-human")
        self.assertEqual([m["modality"] for m in self.service.get_library_version(version["library_version_id"])["members"]], ["image", "image", "audio"])
        b = self.target()
        chosen = self.write("use_library", dict(self.use_payload(version, b["shot"]), member_key="sound", role="sfx", track_key="sfx-1"))
        items = [{"shot_id": b["shot"], "track_key": "sfx-1", "offset_frame": 0, "duration_frames": 24,
            "media": [{"media_id": chosen["media_id"], "binding_decision_id": chosen["decision_id"], "role": "sfx", "source_out_frame": 24}]}]
        timeline_artifact = self.write("create_artifact", {"artifact_key": "timeline", "artifact_type": "edit-timeline", "document": {"items": items}})
        self.write("decide_artifact", {"artifact_id": timeline_artifact["id"], "reason": "Synthetic fixed edit"})
        timeline = self.write("freeze_timeline", {"artifact_id": timeline_artifact["id"], "episode_id": b["episode"], "items": items})
        render_spec = self.artifact("render", "render-spec")
        rendered = self.write("freeze_render", {"timeline_id": timeline["id"], "artifact_id": render_spec, "tool": "synthetic", "tool_version": "1"})
        self.assertEqual(self.service.get_media_usage(self.p, chosen["media_id"])["render_inputs"][0]["render_id"], rendered["id"])
        self.service.retire_library(version["entry_id"], {"outcome": "revoke_rights", "reason": "Current evidence changed", "idempotency_key": "rights-revoked"}, actor="test-human")
        with self.assertRaises(ResourceError):
            self.write("freeze_render", {"timeline_id": timeline["id"], "artifact_id": render_spec, "tool": "synthetic", "tool_version": "1"})
        # Historical fixed timelines and output provenance remain readable.
        self.assertEqual(self.service.get_timeline(self.p, timeline["id"])["id"], timeline["id"])
        self.assertEqual(self.service.library_member_content(version["library_version_id"], "sound")[0].read_bytes(), sound.getvalue())

    def test_http_global_read_preview_upload_import_and_confirmed_target_selection(self):
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        app = create_app({"projects_root": self.directory.name, "access_token": "synthetic-token",
            "human_identity": "test-human", "allowed_hosts": ["testserver"],
            "allowed_origins": ["http://testserver"]}, service=self.service)
        with TestClient(app) as client:
            self.assertEqual(client.get("/api/v1/library").status_code, 200)
            denied = client.post("/api/v1/library/uploads", content=png_bytes())
            self.assertEqual(denied.status_code, 403)
            headers = {"Origin": "http://testserver"}
            session = client.post("/api/v1/session", json={"token": "synthetic-token"}, headers=headers)
            headers["X-CSRF-Token"] = session.json()["csrf_token"]
            upload = client.post("/api/v1/library/uploads", content=png_bytes(), headers=dict(headers, **{"X-Filename": "fixture.png"}))
            self.assertEqual(upload.status_code, 200, upload.text)
            payload = dict(self.description(), import_key="http-" + uuid.uuid4().hex,
                members=[{"member_key": "reference", "staged_upload": upload.json()["staged_upload"]}])
            imported = client.post("/api/v1/library/import", json={"confirmed": True, "payload": payload}, headers=headers)
            self.assertEqual(imported.status_code, 200, imported.text)
            version = imported.json()
            detail = client.get("/api/v1/library/versions/" + version["library_version_id"]).json()
            self.assertEqual(client.get(detail["members"][0]["preview_url"]).content, png_bytes())
            b = self.target()
            base = "/api/v1/projects/" + self.p + "/library/"
            body = {"payload": self.use_payload(version, b["shot"]), "expected_revision": self.rev, "idempotency_key": "http-use"}
            preview = client.post(base + "preview-use", json=body)
            self.assertTrue(preview.json()["available"], preview.text)
            self.assertEqual(client.post(base + "use", json=body, headers=headers).status_code, 422)
            response = client.post(base + "use", json=dict(body, confirmed=True), headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertTrue(response.json()["selected"])
            self.assertEqual(client.post(base + "use", json=dict(body, confirmed=True)).status_code, 403)

    def test_candidate_only_and_atomic_rollback_on_original_adoption_failure(self):
        from vsc.assets.resource_service import ResourceError
        media = self.actual_media()
        version = self.publish(media)
        b = self.target()
        payload = self.use_payload(version, b["shot"])
        before = self.counts()
        # Preflight checks the same fixed specification. A second request with
        # an invalid actual review reason fails in the original review command,
        # after media/source/candidate/check were tentatively inserted.
        unapproved = self.write("create_artifact", {"artifact_key": "unapproved", "artifact_type": "asset-bible", "document": {"spec": "draft"}})
        with self.assertRaises(ResourceError):
            self.write("use_library", dict(payload, spec_version_id=unapproved["id"]))
        with self.assertRaises(ResourceError):
            self.write("use_library", dict(payload, reason=""))
        self.assertEqual(self.counts(), before)
        candidate = self.write("use_library", dict(payload, select=False))
        self.assertFalse(candidate["selected"])
        self.assertIsNone(candidate["decision_id"])
        with self.assertRaises(ResourceError):
            self.write("select_candidate", {"candidate_id": candidate["candidate_id"], "reason": "No human review was supplied"})

    def test_wrong_revision_project_modality_rights_missing_bytes_and_retirement(self):
        from vsc.assets.resource_service import Conflict, ResourceError
        media = self.actual_media()
        source_project = self.p
        source_object = self.hierarchy()["shot"]
        version = self.publish(media)
        source_revision = self.rev
        b = self.target()
        payload = self.use_payload(version, b["shot"])
        before = self.counts()
        with self.assertRaises(Conflict):
            self.service.use_library(self.p, payload, actor="test-human", expected_revision=0, idempotency_key="stale")
        with self.assertRaises(ResourceError):
            self.write("use_library", dict(payload, target_object_id=source_object))
        self.assertFalse(self.service.preview_library_use(self.p, dict(payload, role="reference_audio"))["available"])
        with self.assertRaises(ResourceError):
            self.write("use_library", dict(payload, role="reference_audio"))
        with self.assertRaises(ResourceError):
            self.service.use_library(self.p, payload, expected_revision=self.rev, idempotency_key="no-actor")
        path, _ = self.service.library_member_content(version["library_version_id"], "reference")
        saved = path.read_bytes()
        path.unlink()
        self.assertFalse(self.service.preview_library_use(self.p, payload)["available"])
        with self.assertRaises(ResourceError):
            self.write("use_library", payload)
        path.write_bytes(saved)
        self.assertEqual(self.counts(), before)
        selected = self.write("use_library", payload)
        self.service.retire_library(version["entry_id"], {"reason": "Stop new recommendation", "idempotency_key": "retire"}, actor="test-human")
        self.assertFalse(self.service.preview_library_use(self.p, payload)["available"])
        self.assertTrue(self.service.compile_shot_context(self.p, b["shot"], "video_clip")["ready"])
        target_project, target_revision = self.p, self.rev
        self.p, self.rev = source_project, source_revision
        self.write("decide_rights", {"media_id": media, "outcome": "revoked", "reason": "Updated source evidence"})
        self.p, self.rev = target_project, target_revision
        blocked = self.service.compile_shot_context(self.p, b["shot"], "video_clip")
        self.assertFalse(blocked["ready"])
        self.assertIn("library_source_rights_changed", str(blocked["gaps"]))
        self.assertEqual(self.service.get_media(self.p, selected["media_id"])["sha256"], hashlib.sha256(saved).hexdigest())

    def test_source_no_share_and_library_owner_permissions(self):
        from vsc.assets.resource_service import ResourceError
        media = self.actual_media(rights="licensed", scope={"purposes": ["first_frame"]})
        with self.assertRaises(ResourceError):
            self.publish(media)
        owned = self.actual_media("Second", color=b"\x90\x80\x40")
        version = self.publish(owned)
        with self.assertRaises(ResourceError):
            self.service.retire_library(version["entry_id"], {"reason": "No authority", "idempotency_key": "other"}, actor="other-human")

    def test_library_origin_cannot_be_republished_and_original_version_still_recovers(self):
        from sqlalchemy import insert
        from sqlalchemy.exc import IntegrityError
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.assets.resource_service import ResourceError
        source = self.actual_media("A original")
        version_a = self.publish(source, allowed_purposes=["*"])
        b = self.target()
        borrowed = self.write("use_library", self.use_payload(version_a, b["shot"]))
        before, revision_b = self.counts(), self.rev
        self.library_key = "republish-denied-" + uuid.uuid4().hex
        # B holds an otherwise valid licensed snapshot including library_share;
        # that snapshot cannot sever A's live library authority.
        payload = dict(self.description(), title="Republish must not exist", allowed_purposes=["*"],
            license={"outcome": "licensed", "allow_workspace_reuse": True, "evidence": "B's fixed A-library source"},
            members=[{"media_id": borrowed["media_id"], "member_key": "reference"}])
        with self.assertRaises(ResourceError) as rejected:
            self.write("publish_library", payload, idempotency_key="republish-blocked")
        self.assertEqual(rejected.exception.code, "library_republish_not_supported")
        self.assertEqual(rejected.exception.status_code, 409)
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.store.get_project(self.p)["revision"], revision_b)
        self.assertFalse(self.service.get_operation_receipt(self.p, "republish-blocked", actor="test-human")["found"])
        self.assertEqual(self.service.search_library("Republish must not exist")["items"], [])
        target_media = self.service.get_media(self.p, borrowed["media_id"])
        original_detail = self.service.get_library_version(version_a["library_version_id"])
        # An application DB INSERT cannot create the forbidden publish edge,
        # even though every original typed media/source/member FK is valid.
        with self.assertRaises(IntegrityError), self.engine.begin() as conn:
            conn.execute(insert(S.library_reuses).values(project_id=self.p, id=str(uuid.uuid4()),
                media_id=borrowed["media_id"], source_id=borrowed["source_id"],
                rights_decision_id=target_media["rights"]["id"], library_key=original_detail["library_key"],
                library_version="1", reuse_mode="publish", library_version_id=version_a["library_version_id"],
                member_key="reference", blob_id=target_media["blob_id"]))
        # Recovery uses the original fixed version directly, with C's own
        # choice. No extra library identity or rights chain is manufactured.
        c = self.target()
        self.write("use_library", self.use_payload(version_a, c["shot"]))
        self.assertTrue(self.service.compile_shot_context(self.p, c["shot"], "video_clip")["ready"])
        self.service.retire_library(version_a["entry_id"], {"outcome": "revoke_rights", "reason": "A evidence revoked",
            "idempotency_key": "origin-rights-revoked"}, actor="test-human")
        blocked = self.service.compile_shot_context(self.p, c["shot"], "video_clip")
        self.assertFalse(blocked["ready"])
        self.assertIn("library_rights_revoked", str(blocked["gaps"]))
        self.assertFalse(self.service.preview_library_use(self.p, self.use_payload(version_a, c["shot"]))["available"])

    def test_derived_library_origin_is_blocked_and_anomalous_existing_publish_fails_closed(self):
        from vsc.assets.resource_service import ResourceError
        source = self.actual_media("A reference")
        version_a = self.publish(source, allowed_purposes=["*"])
        b = self.target()
        independent = self.actual_media("B previously independent", color=b"\x90\x80\x40")
        self.library_key = "previously-independent-" + uuid.uuid4().hex
        version_b = self.publish(independent, allowed_purposes=["*"])
        project_b, revision_b = self.p, self.rev
        c = self.target()
        self.write("use_library", self.use_payload(version_b, c["shot"]))
        project_c = self.p
        self.p, self.rev = project_b, revision_b
        borrowed = self.write("use_library", self.use_payload(version_a, b["shot"]))
        # Appending real typed processing provenance makes this prior source a
        # library derivative. All new consumers fail closed; history is retained.
        self.write("create_media_operation", {"operation_type": "synthetic-composite", "recipe_version": "1",
            "tool": "fixture", "tool_version": "1", "inputs": [{"media_id": borrowed["media_id"]}],
            "outputs": [{"media_id": independent}]})
        self.library_key = "derived-republish-denied-" + uuid.uuid4().hex
        with self.assertRaises(ResourceError) as rejected:
            self.publish(independent, allowed_purposes=["*"])
        self.assertEqual(rejected.exception.code, "library_republish_not_supported")
        self.assertFalse(self.service.preview_library_use(project_c, self.use_payload(version_b, c["shot"]))["available"])
        context = self.service.compile_shot_context(project_c, c["shot"], "video_clip")
        self.assertFalse(context["ready"])
        self.assertIn("library_republish_not_supported", str(context["gaps"]))
        self.assertEqual(len(self.service.get_library_version(version_b["library_version_id"])["members"]), 1)

    def test_library_ancestor_predicate_is_scoped_and_original_cycle_guard_remains(self):
        from sqlalchemy import insert, text, update
        from sqlalchemy.exc import IntegrityError
        from vsc.adapters.persistence.postgres import schema as S
        origin = self.actual_media("Original")
        version = self.publish(origin, allowed_purposes=["*"])
        b = self.target()
        borrowed = self.write("use_library", self.use_payload(version, b["shot"]))
        first = self.actual_media("Cycle first", color=b"\x90\x80\x40")
        second = self.actual_media("Cycle second", color=b"\x30\x40\x50")
        with self.engine.begin() as conn:
            conn.execute(text("SET LOCAL statement_timeout = '2000ms'"))
            def connect(child, parents):
                operation = str(uuid.uuid4())
                conn.execute(insert(S.media_operations).values(project_id=self.p, id=operation, operation_type="invalid-cycle-fixture",
                    recipe_version="1", tool="fixture", tool_version="1", parameters={}, status="created", execution={}))
                conn.execute(insert(S.operation_outputs).values(project_id=self.p, id=str(uuid.uuid4()),
                    operation_id=operation, media_id=child, role="composite", ordinal=0))
                for ordinal, parent in enumerate(parents):
                    conn.execute(insert(S.operation_inputs).values(project_id=self.p, id=str(uuid.uuid4()),
                        operation_id=operation, media_id=parent, role="layer", layer_order=ordinal, transform={}, opacity=1))
                conn.execute(update(S.media_operations).where(S.media_operations.c.project_id == self.p,
                    S.media_operations.c.id == operation).values(status="succeeded"))
            connect(first, [second, borrowed["media_id"]])
            with self.assertRaises(IntegrityError), conn.begin_nested():
                connect(second, [first])
            self.assertTrue(conn.execute(text("SELECT vsc_library_has_imported_ancestor(CAST(:p AS uuid), CAST(:m AS uuid))"),
                {"p": self.p, "m": first}).scalar_one())
            # The same id never traverses a different project's graph.
            self.assertFalse(conn.execute(text("SELECT vsc_library_has_imported_ancestor(CAST(:p AS uuid), CAST(:m AS uuid))"),
                {"p": version["project_id"], "m": first}).scalar_one())

    def test_fixed_member_set_rejects_append_missing_members_and_zero_member_extension(self):
        from sqlalchemy import insert, select, update
        from sqlalchemy.exc import IntegrityError
        from vsc.adapters.persistence.postgres import schema as S
        media = self.actual_media()
        version = self.publish(media)
        detail = self.service.get_library_version(version["library_version_id"])
        with self.engine.connect() as conn:
            member = dict(conn.execute(select(S.library_version_media).where(
                S.library_version_media.c.library_version_id == version["library_version_id"])).mappings().one())
            fixed = dict(conn.execute(select(S.library_entry_versions).where(
                S.library_entry_versions.c.id == version["library_version_id"])).mappings().one())
        self.assertEqual(fixed["member_count"], 1)
        with self.assertRaises(IntegrityError), self.engine.begin() as conn:
            conn.execute(insert(S.library_version_media).values(dict(member, member_key="later-append", ordinal=1)))
        self.assertEqual(self.service.get_library_version(version["library_version_id"]), detail)
        with self.assertRaises(IntegrityError), self.engine.begin() as conn:
            conn.execute(update(S.library_entry_versions).where(S.library_entry_versions.c.id == version["library_version_id"])
                .values(member_count=2))
        # A declared complete set must exist at creating-transaction commit.
        with self.assertRaises(IntegrityError), self.engine.begin() as conn:
            conn.execute(insert(S.library_entry_versions).values(dict(fixed, id=str(uuid.uuid4()), version=2, member_count=2)))
        spec = self.service.import_library(dict(self.description(), library_key="spec-seal-" + uuid.uuid4().hex,
            import_key="spec-seal-" + uuid.uuid4().hex, specification={"font_size": 42}, members=[]), actor="test-human")
        with self.assertRaises(IntegrityError), self.engine.begin() as conn:
            conn.execute(insert(S.library_version_media).values(dict(member, library_version_id=spec["library_version_id"], ordinal=0)))
        self.assertEqual(self.service.get_library_version(spec["library_version_id"])["members"], [])

    def test_global_search_batch_queries_and_original_target_preflight(self):
        from sqlalchemy import event
        media = self.actual_media()
        for number in range(3):
            self.library_key = "batch-library-" + uuid.uuid4().hex
            version = self.publish(media, title="Bounded batch fixture " + str(number), allowed_purposes=["first_frame", "identity_face"])
        queries = []
        def capture(conn, cursor, statement, parameters, context, many):
            queries.append(statement)
        event.listen(self.engine, "before_cursor_execute", capture)
        try:
            one = self.service.search_library("Bounded batch fixture", limit=1)
            one_count = len(queries)
            queries.clear()
            three = self.service.search_library("Bounded batch fixture", limit=50)
            self.assertEqual(len(queries), one_count)
            self.assertLessEqual(len(queries), 6)
            self.assertEqual(len(three["items"]), 3)
            self.assertEqual(len(one["items"]), 1)
        finally:
            event.remove(self.engine, "before_cursor_execute", capture)
        b = self.target()
        preview = self.service.preview_library_use(self.p, dict(self.use_payload(version, b["shot"]), role="identity_face"))
        self.assertFalse(preview["available"])
        self.assertIn("missing_field", str(preview["gaps"]))

    def test_concurrent_same_key_and_conflicting_intent(self):
        from vsc.assets.resource_service import Conflict
        media = self.actual_media()
        version = self.publish(media)
        b = self.target()
        payload = self.use_payload(version, b["shot"])
        revision = self.rev
        before = self.counts()
        def use(_):
            return self.service.use_library(self.p, payload, actor="test-human", expected_revision=revision, idempotency_key="concurrent-use")
        with ThreadPoolExecutor(max_workers=2) as pool:
            values = list(pool.map(use, range(2)))
        self.assertEqual(values[0], values[1])
        self.assertEqual(self.counts()["media_items"], before["media_items"] + 1)
        self.assertEqual(self.counts()["library_reuses"], before["library_reuses"] + 1)
        with self.assertRaises(Conflict):
            self.service.use_library(self.p, dict(payload, select=False), actor="test-human", expected_revision=revision, idempotency_key="concurrent-use")

    def test_original_readonly_local_preview_consumes_library_and_rechecks_revocation(self):
        from sqlalchemy import insert
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.assets.resource_service import ResourceError
        original = self.actual_media()
        version = self.publish(original)
        objects = self.target()
        used = self.write("use_library", self.use_payload(version, objects["shot"]))
        provider, model = "offline_" + uuid.uuid4().hex, str(uuid.uuid4())
        with self.engine.begin() as conn:
            conn.execute(insert(S.providers).values(id=provider, name="Offline local preview fixture", modality="video",
                base_url="https://example.invalid", auth_ref="none", enabled=True, rate_limit={}))
            conn.execute(insert(S.provider_models).values(id=model, provider_id=provider, model_key="fixture", modality="video",
                model_version="1", capabilities={"purposes": ["video_clip"], "first_frame": True}, default_params={}, cost_rule={}, enabled=True))
        request = {"prompt": "Fixed local preview fixture", "first_frame_media_id": used["media_id"], "params": {"seed": 123}}
        run = self.production_run(objects["shot"], request)
        context = self.service.compile_shot_context(self.p, objects["shot"], purpose="video_clip")
        job = self.write("create_generation_job", {"run_version_id": run, "shot_id": objects["shot"], "purpose": "video_clip",
            "modality": "video", "model_id": model, "context_sha256": context["sha256"], "request_payload": request})
        self.write("update_generation_job", {"job_id": job["id"], "status": "failed"})
        before, revision = self.counts(), self.rev
        result = self.service.preview_local_production(self.p, {"action": "resample", "job_id": job["id"]})
        self.assertEqual(result["action"], "resample")
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.service.get_project(self.p)["revision"], revision)
        self.service.retire_library(version["entry_id"], {"outcome": "revoke_rights", "reason": "Changed fixed library rights",
            "idempotency_key": "readonly-revoke"}, actor="test-human")
        with self.assertRaises(ResourceError) as blocked:
            self.service.preview_local_production(self.p, {"action": "resample", "job_id": job["id"]})
        self.assertEqual(blocked.exception.code, "context_gaps")

    def test_reciprocal_projects_adopt_concurrently_without_lock_inversion(self):
        a = self.target()
        media_a = self.actual_media("A original")
        version_a = self.publish(media_a)
        project_a, revision_a = self.p, self.rev
        self.library_key = "reciprocal-b-" + uuid.uuid4().hex
        b = self.target()
        media_b = self.actual_media("B original", color=b"\x90\x80\x40")
        version_b = self.publish(media_b)
        project_b, revision_b = self.p, self.rev
        barrier = Barrier(2)
        def adopt(values):
            project, revision, version, shot = values
            barrier.wait(timeout=5)
            return self.service.use_library(project, self.use_payload(version, shot), actor="test-human",
                expected_revision=revision, idempotency_key="reciprocal-use")
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(adopt, values) for values in ((project_a, revision_a, version_b, a["shot"]),
                (project_b, revision_b, version_a, b["shot"]))]
            receipts = [future.result(timeout=10) for future in futures]
        self.assertTrue(all(row["selected"] for row in receipts))
        self.assertTrue(self.service.compile_shot_context(project_a, a["shot"], "video_clip")["ready"])
        self.assertTrue(self.service.compile_shot_context(project_b, b["shot"], "video_clip")["ready"])

    def test_database_keys_immutability_and_migration_roundtrip(self):
        from alembic import command
        from alembic.config import Config
        from alembic.autogenerate import compare_metadata
        from alembic.migration import MigrationContext
        from sqlalchemy import insert, update, text
        from sqlalchemy.exc import IntegrityError
        from vsc.adapters.persistence.postgres import schema as S
        from support.paths import ROOT
        from support.fixtures.postgres import isolated_postgres
        media = self.actual_media()
        version = self.publish(media)
        source = self.service.get_media(self.p, media)["sources"][0]["source_id"]
        with self.assertRaises(IntegrityError), self.engine.begin() as conn:
            conn.execute(insert(S.library_reuses).values(project_id=self.p, id=str(uuid.uuid4()), media_id=media,
                source_id=source, library_key=self.library_key, library_version="1", reuse_mode="reference", member_key="reference"))
        # Historical bare-key references remain valid; new partial fixed links
        # are rejected by the actual CHECK, not just Python or autogenerate.
        with self.engine.begin() as conn:
            conn.execute(insert(S.library_reuses).values(project_id=self.p, id=str(uuid.uuid4()), media_id=media,
                source_id=source, library_key="historical-key", library_version="old", reuse_mode="legacy"))
        with self.assertRaises(IntegrityError), self.engine.begin() as conn:
            conn.execute(update(S.library_entry_versions).where(S.library_entry_versions.c.id == version["library_version_id"]).values(description="mutate"))
        other = self.service.create_project({"name": "Other synthetic"}, actor="test-human")["id"]
        with self.assertRaises(IntegrityError), self.engine.begin() as conn:
            conn.execute(insert(S.library_reuses).values(project_id=other, id=str(uuid.uuid4()), media_id=media,
                source_id=str(uuid.uuid4()), library_key=self.library_key, library_version="1", reuse_mode="reference"))
        with isolated_postgres(TEST_URL) as engine:
            from vsc.adapters.persistence.postgres.resource_store import PostgresResourceStore
            from vsc.assets.resource_service import ResourceService
            prior = ResourceService(PostgresResourceStore(engine=engine), self.service.storage)
            prior_project = prior.create_project({"name": "Pre-migration fixed facts", "profile_snapshot": {
                "profile_id": "vsc.synthetic", "version": "1", "stages": []}}, actor="test-human")["id"]
            staged = prior.storage.stage_upload(io.BytesIO(png_bytes()), "prior.png")
            prior_media = prior.register_media(prior_project, {"staged_upload": staged["staged_upload"],
                "name": "Pre-migration bytes", "rights": "owned", "source": {"kind": "synthetic", "content": "Original fixed evidence"}},
                actor="test-human", expected_revision=0, idempotency_key="prior-media")
            prior_source = prior.get_media(prior_project, prior_media["id"])["sources"][0]["source_id"]
            with engine.begin() as conn:
                conn.execute(insert(S.library_reuses).values(project_id=prior_project, id=str(uuid.uuid4()),
                    media_id=prior_media["id"], source_id=prior_source, library_key="prior-legacy-key", library_version="v0", reuse_mode="legacy"))
            cfg = Config(str(ROOT / "migrations/postgres/alembic.ini"))
            with engine.begin() as conn:
                def old_facts():
                    return {name: [dict(row) for row in conn.execute(text("SELECT " + columns + " FROM " + name)).mappings()]
                        for name, columns in {"projects": "id,revision,decision_sequence", "media_blobs": "id,sha256,size_bytes",
                            "media_items": "project_id,id,blob_id", "source_versions": "project_id,id,sha256",
                            "rights_decisions": "project_id,id,media_id,source_id,outcome,scope",
                            "library_reuses": "project_id,id,media_id,source_id,library_key,library_version,reuse_mode"}.items()}
                before_facts = old_facts()
                self.assertEqual(compare_metadata(MigrationContext.configure(conn), S.metadata), [])
                cfg.attributes["connection"] = conn
                command.downgrade(cfg, "0012_assisted_workflow")
                self.assertEqual(old_facts(), before_facts)
                self.assertEqual(conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one(), "0012_assisted_workflow")
                command.upgrade(cfg, "head")
                self.assertEqual(old_facts(), before_facts)
                self.assertEqual(compare_metadata(MigrationContext.configure(conn), S.metadata), [])

    def test_legacy_json_preview_backup_resume_compare_cutover_and_original_consumer(self):
        from vsc.assets import library as legacy
        from vsc.assets.library_migration import LegacyLibraryMigration
        from vsc.assets.resource_service import Conflict, ResourceError
        root = Path(self.directory.name) / "legacy"
        folder = root / "prop" / "original-reference"
        folder.mkdir(parents=True)
        raw = png_bytes()
        (folder / "reference.png").write_bytes(raw)
        item = {"format": legacy.ITEM_FORMAT, "id": "original-reference", "kind": "prop", "name": "Original fixture",
            "summary": "Safe existing reference", "tags": [], "attributes": {}, "used_by": [],
            "files": [{"path": "reference.png", "sha256": hashlib.sha256(raw).hexdigest(), "role": "product"}],
            "rights": {"status": "owned", "source": "Synthetic original fixture", "allow_workspace_reuse": True,
                "allowed_purposes": ["first_frame"]}}
        (folder / "item.json").write_text(json.dumps(item), "utf-8")
        spec_folder = root / "subtitle_style" / "style-only"
        spec_folder.mkdir(parents=True)
        spec = dict(item, id="style-only", kind="subtitle_style", name="Fixed text style", files=[], attributes={"font_size": 42})
        (spec_folder / "item.json").write_text(json.dumps(spec), "utf-8")
        migration = LegacyLibraryMigration(self.service, root)
        files_before = sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_file())
        preview = migration.preview()
        self.assertEqual(preview["ready"], 2)
        self.assertEqual(preview["pending"], 0)
        self.assertEqual(files_before, sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()))
        imported = self.service.import_library
        calls = []
        def fail_after_commit(payload, actor=None):
            receipt = imported(payload, actor=actor)
            calls.append(receipt)
            if len(calls) == 2:
                raise ResourceError("Synthetic crash after commit", "synthetic_interruption")
            return receipt
        with patch.object(self.service, "import_library", side_effect=fail_after_commit):
            with self.assertRaises(ResourceError):
                migration.import_items(preview["inventory_sha256"], actor="test-human")
        count_after_commit = self.counts()
        result = migration.import_items(preview["inventory_sha256"], actor="test-human")
        self.assertTrue(result["passed"], result)
        self.assertTrue(result["can_cutover"])
        self.assertEqual(self.counts(), count_after_commit)
        self.assertTrue((Path(result["backup"]) / "prop/original-reference/reference.png").is_file())
        restored = Path(self.directory.name) / "restored-legacy"
        shutil.copytree(result["backup"], restored)
        self.assertEqual(len(legacy.load_items(restored)), 2)
        self.assertEqual(legacy.check(SimpleNamespace(library=str(restored)))[1], [])
        self.assertEqual((restored / "prop/original-reference/reference.png").read_bytes(), raw)
        style_receipt = result["receipts"]["style-only"]
        style = self.service.get_library_version(style_receipt["library_version_id"])
        self.assertEqual(style["members"], [])
        self.assertEqual(style["specification"]["attributes"]["font_size"], 42)
        backup_media = Path(result["backup"]) / "prop/original-reference/reference.png"
        backup_media.write_bytes(b"corrupted backup")
        self.assertFalse(migration.compare()["passed"])
        with self.assertRaises(Conflict):
            migration.cutover(actor="test-human")
        backup_media.write_bytes(raw)
        self.assertEqual(migration.cutover(actor="test-human")["status"], "cutover")
        with self.assertRaises(legacy.LibraryError), legacy.mutation_lock(root):
            self.fail("Old authority must reject writes after cutover")
        self.assertEqual(len(legacy.load_items(root)), 2)
        b = self.target()
        receipt = result["receipts"]["original-reference"]
        selected = self.write("use_library", dict(self.use_payload(receipt, b["shot"]), member_key="file-001"))
        context = self.service.compile_shot_context(self.p, b["shot"], "video_clip")
        self.assertTrue(context["ready"], context["gaps"])
        self.assertEqual(context["media"][0]["media_id"], selected["media_id"])
        self.assertEqual(context["media"][0]["sha256"], hashlib.sha256(raw).hexdigest())

    def test_legacy_missing_bytes_unknown_rights_source_change_and_pending_cutover(self):
        from vsc.assets import library as legacy
        from vsc.assets.library_migration import LegacyLibraryMigration
        from vsc.assets.resource_service import Conflict
        root = Path(self.directory.name) / "pending-legacy"
        folder = root / "prop" / "pending-reference"
        folder.mkdir(parents=True)
        item = {"format": legacy.ITEM_FORMAT, "id": "pending-reference", "kind": "prop", "name": "Pending",
            "summary": "Unverified existing reference", "files": [{"path": "missing.png", "sha256": "a" * 64}],
            "rights": {"status": "unknown"}}
        source = folder / "item.json"
        source.write_text(json.dumps(item), "utf-8")
        migration = LegacyLibraryMigration(self.service, root)
        preview = migration.preview()
        self.assertEqual(preview["pending"], 1)
        self.assertIn("legacy_missing_bytes", str(preview))
        self.assertIn("legacy_rights_unverified", str(preview))
        source.write_text(json.dumps(dict(item, summary="Source changed")), "utf-8")
        with self.assertRaises(Conflict):
            migration.import_items(preview["inventory_sha256"], actor="test-human")
        self.assertFalse(migration.marker.exists())
        preview = migration.preview()
        before = self.counts()
        result = migration.import_items(preview["inventory_sha256"], actor="test-human")
        self.assertEqual(self.counts(), before)
        self.assertEqual(len(result["pending"]), 1)
        with self.assertRaises(Conflict):
            migration.cutover(actor="test-human")
        retained = migration.cutover(actor="test-human", allow_pending=True)
        self.assertEqual(retained["status"], "cutover")
        self.assertEqual(len(retained["pending"]), 1)
