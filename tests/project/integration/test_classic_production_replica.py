"""End-to-end PostgreSQL + FastAPI integration tests for Slice A4 (06A-06F & 15D /fcp/:locale)."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import importlib.util
import io
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile
import unittest
import uuid
import zipfile

from support.fixtures.resource_store import ResourceStoreFixture, HAS_DB_DEPS
from vsc.assets.access_control import Principal, set_principal, reset_principal
from vsc.assets.resource_service import ResourceError

HAS_WEB_DEPS = all(importlib.util.find_spec(n) for n in ("fastapi", "httpx", "PIL"))


@unittest.skipUnless(os.environ.get("VSC_TEST_DATABASE_URL") and HAS_DB_DEPS and HAS_WEB_DEPS, "requires isolated PostgreSQL and web deps")
class ClassicProductionReplicaTests(ResourceStoreFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        from fastapi.testclient import TestClient
        from vsc.adapters.storage.local.store import LocalStorage
        from vsc.interfaces.web.app import create_app

        self.temp = tempfile.TemporaryDirectory(prefix="vsc-classic-replica-")
        self.addCleanup(self.temp.cleanup)
        self.previous_storage = self.service.storage
        self.service.storage = LocalStorage(Path(self.temp.name) / "storage")
        self.addCleanup(setattr, self.service, "storage", self.previous_storage)
        self.app = create_app(
            {
                "projects_root": self.temp.name + "/projects",
                "media_root": self.temp.name,
                "allowed_hosts": ["testserver"],
                "allowed_origins": ["http://testserver"],
                "human_identity": "test-human",
                "access_token": "test-token",
                "background_enabled": False,
            },
            service=self.service,
        )
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        session = self.client.post(
            "/api/v1/session",
            headers={"Origin": "http://testserver"},
            json={"token": "test-token"},
        ).json()
        self.headers = {"Origin": "http://testserver", "X-CSRF-Token": session["csrf_token"]}
        self.base = "/api/v1/projects/" + self.p

    def post_cmd(self, path, payload, expected=None, key=None):
        res = self.client.post(
            self.base + path,
            headers=self.headers,
            json={
                "payload": payload,
                "expected_revision": self.rev if expected is None else expected,
                "idempotency_key": key or uuid.uuid4().hex,
            },
        )
        if res.status_code == 200 and isinstance(res.json(), dict) and "revision" in res.json():
            self.rev = res.json()["revision"]
        return res

    def register_png(self, name="frame.png", color="red", size=(64, 64), project_id=None, rev=None):
        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", size, color).save(buf, format="PNG")
        buf.seek(0)
        staged = self.service.storage.stage_upload(buf, name)
        pid = project_id or self.p
        expected = self.rev if project_id is None else rev
        row = self.service.register_media(
            pid,
            {
                "staged_upload": staged["staged_upload"],
                "name": name,
                "rights": "owned",
                "source": {"kind": "synthetic", "content": "local test png"},
            },
            expected_revision=expected,
            idempotency_key=uuid.uuid4().hex,
            actor="test-human",
        )
        if project_id is None:
            self.rev = row["revision"]
        return row

    def test_prompt_recommendations_batch_upload_check_kling_gif_omni_and_shot_delete(self):
        objects = self.hierarchy()

        rec = self.client.get(self.base + "/classic-production/prompt-recommendations", headers=self.headers)
        self.assertEqual(rec.status_code, 200, rec.text)
        categories = rec.json()["categories"]
        self.assertGreaterEqual(len(categories), 5)

        bad_batch = self.client.post(
            self.base + "/classic-production/batch-upload-check",
            headers=self.headers,
            json={"payload": {"filenames": ["2.jpg", "cover.png", "1.png"]}},
        )
        self.assertEqual(bad_batch.status_code, 422, bad_batch.text)
        self.assertIn("文件名格式不正确：cover.png", bad_batch.json()["message"])

        ok_batch = self.client.post(
            self.base + "/classic-production/batch-upload-check",
            headers=self.headers,
            json={"payload": {"filenames": ["10.JPEG", "2.jpg", "1.png"]}},
        )
        self.assertEqual(ok_batch.status_code, 200, ok_batch.text)
        self.assertEqual([item["number"] for item in ok_batch.json()["items"]], [1, 2, 10])
        self.assertEqual([item["filename"] for item in ok_batch.json()["items"]], ["1.png", "2.jpg", "10.JPEG"])

        base_doc = {
            "shot_id": objects["shot"],
            "mode": "text",
            "model_id": "",
            "purpose": "",
            "prompt": "中" * 11000,
            "duration_ms": 5000,
            "width": 1080,
            "height": 1920,
            "count": 1,
            "params": {},
            "references": [],
        }
        saved_draft = self.write("save_classic_draft", {"document": base_doc, "base_draft_id": None})
        with self.assertRaises(ResourceError):
            self.write("save_classic_draft", {"document": dict(base_doc, prompt="中" * 11001), "base_draft_id": saved_draft["id"]})
        saved_draft2 = self.write("save_classic_draft", {"document": dict(base_doc, prompt="a" * 26000), "base_draft_id": saved_draft["id"]})
        with self.assertRaises(ResourceError):
            self.write("save_classic_draft", {"document": dict(base_doc, prompt="a" * 26001), "base_draft_id": saved_draft2["id"]})

        gif_doc = dict(
            base_doc,
            mode="image",
            prompt="分镜动态预览",
            params={"output_format": "gif", "frame_count": 8, "frame_duration_ms": 120},
        )
        self.write("save_classic_draft", {"document": gif_doc, "base_draft_id": None})
        with self.assertRaises(ResourceError):
            self.write(
                "save_classic_draft",
                {"document": dict(gif_doc, params={"output_format": "gif", "transparent_background": True}), "base_draft_id": None},
            )

        import wave

        wav_buf = io.BytesIO()
        with wave.open(wav_buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(8000)
            wf.writeframes(b"\x00\x00" * 1600)
        wav_buf.seek(0)
        staged_wav = self.service.storage.stage_upload(wav_buf, "line.wav")
        audio_row = self.write(
            "register_media",
            {
                "staged_upload": staged_wav["staged_upload"],
                "name": "对白音轨.wav",
                "rights": "owned",
                "source": {"kind": "synthetic", "content": "local test wav"},
            },
        )
        audio_id = audio_row["id"]
        omni_draft = self.write(
            "save_classic_draft",
            {
                "document": dict(
                    base_doc,
                    mode="omni",
                    purpose="reference_to_video",
                    prompt="音频校验",
                    references=[{"role": "reference_audio", "media_id": audio_id}],
                ),
                "base_draft_id": None,
            },
        )
        preview = self.service.preview_workbench_generation(
            self.p,
            {
                "draft_version_id": omni_draft["id"],
                "execution_policy": {
                    "version": "bounded-v1",
                    "max_attempts_per_purpose": 4,
                    "max_repair_rounds": 1,
                    "first_draft_due_at": "2030-01-01T00:00:00Z",
                    "stop_submitting_at": "2030-01-02T00:00:00Z",
                },
            },
        )
        self.assertFalse(preview["ready"])
        self.assertTrue(any(g["code"] == "omni_visual_required" and "全能参考不能仅使用音频" in g["message"] for g in preview["gaps"]))

        # Shot delete: cannot delete last shot; can delete when >= 2 shots exist
        del_last = self.post_cmd("/classic-production/shots", {"action": "delete", "shot_id": objects["shot"]})
        self.assertGreaterEqual(del_last.status_code, 400)
        created_shot = self.post_cmd(
            "/classic-production/shots",
            {"action": "create", "parent_id": objects["sequence"], "title": "镜头2"},
        )
        self.assertEqual(created_shot.status_code, 200, created_shot.text)
        shot2_id = created_shot.json()["id"]
        deleted = self.post_cmd("/classic-production/shots", {"action": "delete", "shot_id": objects["shot"]})
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(deleted.json()["next_shot_id"], shot2_id)
        self.assertEqual(self.service.list_generation_jobs(self.p)["total"], 0)

    def test_cross_project_storyboard_references_and_eraser_mask_pixel_editing(self):
        from PIL import Image

        objects = self.hierarchy()
        other = self.service.create_project({"name": "源分镜项目"}, actor="test-human")
        other_id, other_rev = other["id"], other["revision"]
        wk = self.service.create_object(
            other_id,
            {"kind": "work", "title": "源作品", "display_code": "WK-1", "parent_id": None, "ordinal": 0},
            expected_revision=other_rev,
            idempotency_key=uuid.uuid4().hex,
            actor="test-human",
        )
        ep = self.service.create_object(
            other_id,
            {"kind": "episode", "parent_id": wk["id"], "title": "第1集", "display_code": "EP-1", "ordinal": 1},
            expected_revision=wk["revision"],
            idempotency_key=uuid.uuid4().hex,
            actor="test-human",
        )
        sc = self.service.create_object(
            other_id,
            {"kind": "scene", "parent_id": ep["id"], "title": "场1", "display_code": "SC-1", "ordinal": 1},
            expected_revision=ep["revision"],
            idempotency_key=uuid.uuid4().hex,
            actor="test-human",
        )
        sq = self.service.create_object(
            other_id,
            {"kind": "sequence", "parent_id": sc["id"], "title": "组1", "display_code": "SQ-1", "ordinal": 1},
            expected_revision=sc["revision"],
            idempotency_key=uuid.uuid4().hex,
            actor="test-human",
        )
        sh = self.service.create_object(
            other_id,
            {"kind": "shot", "parent_id": sq["id"], "title": "源分镜镜头", "display_code": "SH-1", "ordinal": 1},
            expected_revision=sq["revision"],
            idempotency_key=uuid.uuid4().hex,
            actor="test-human",
        )
        src_img = self.register_png("src-storyboard.png", color="green", project_id=other_id, rev=sh["revision"])
        cand_resp = self.client.post(
            "/api/v1/projects/" + other_id + "/binding-candidates",
            headers=self.headers,
            json={
                "payload": {"target_object_id": sh["id"], "media_id": src_img["id"], "role": "first_frame", "slot_key": "workbench"},
                "expected_revision": src_img["revision"],
                "idempotency_key": uuid.uuid4().hex,
            },
        )
        self.assertEqual(cand_resp.status_code, 200, cand_resp.text)
        cand = cand_resp.json()
        sel_resp = self.client.post(
            "/api/v1/projects/" + other_id + "/working-selections",
            headers=self.headers,
            json={
                "payload": {
                    "shot_id": sh["id"],
                    "output_kind": "image",
                    "candidate_id": cand.get("candidate_id") or cand["id"],
                    "base_version_id": None,
                },
                "expected_revision": cand["revision"],
                "idempotency_key": uuid.uuid4().hex,
            },
        )
        self.assertEqual(sel_resp.status_code, 200, sel_resp.text)

        refs = self.client.get("/api/v1/projects/" + other_id + "/classic-production/storyboard-references", headers=self.headers)
        self.assertEqual(refs.status_code, 200, refs.text)
        self.assertEqual(len(refs.json()["items"]), 1)
        self.assertEqual(refs.json()["items"][0]["selected_media_id"], src_img["id"])
        self.assertEqual(refs.json()["items"][0]["images"][0]["media_id"], src_img["id"])

        imported = self.post_cmd(
            "/classic-production/frame-media",
            {
                "shot_id": objects["shot"],
                "role": "first_frame",
                "source_project_id": other_id,
                "source": {"kind": "storyboard", "shot_id": sh["id"], "media_id": src_img["id"]},
            },
        )
        self.assertEqual(imported.status_code, 200, imported.text)
        self.assertEqual(imported.json()["sha256"], src_img["sha256"])

        # Eraser tool clears mask & overlay pixels
        local_img = self.register_png("repaint-base.png", color="blue", size=(64, 64))
        edit_doc = {
            "format": "vsc.reference-edit/v1",
            "id": uuid.uuid4().hex,
            "source_media_id": local_img["id"],
            "source_sha256": local_img["sha256"],
            "source_modality": "image",
            "time_ms": 0,
            "width": 64,
            "height": 64,
            "description": "局部擦除测试",
            "brightness": 1,
            "saturation": 1,
            "operations": [
                {"id": "m1", "tool": "mask", "points": [[0.5, 0.5], [0.5, 0.5]], "color": "#ffffff", "width": 0.10},
                {"id": "e1", "tool": "eraser", "points": [[0.5, 0.5], [0.5, 0.5]], "color": "#ffffff", "width": 0.14},
                {"id": "m2", "tool": "mask", "points": [[0.15, 0.15], [0.25, 0.25]], "color": "#ffffff", "width": 0.10},
            ],
        }
        saved_edit = self.write(
            "save_classic_reference_edit",
            {"shot_id": objects["shot"], "mode": "image", "document": edit_doc, "base_edit_id": None},
        )
        exported = self.write("export_classic_reference_edit", {"edit_version_id": saved_edit["id"]})
        by_role = {r["role"]: r for r in exported["outputs"]}
        mask_row = self.service.get_media(self.p, by_role["mask"]["media_id"])
        mask_img = Image.open(self.service.storage.verify(mask_row["locations"][0]["object_key"], mask_row["sha256"]))
        self.assertEqual(mask_img.getpixel((32, 32)), 0)

        # Optional reference_image slot in image_inpaint mode
        ref_extra = self.register_png("repaint-ref.png", color="red", size=(64, 64))
        inpaint_draft = self.write(
            "save_classic_draft",
            {
                "document": {
                    "shot_id": objects["shot"],
                    "mode": "image_inpaint",
                    "model_id": "",
                    "purpose": "image_edit",
                    "prompt": "参考红衣细节局部重绘",
                    "duration_ms": 5000,
                    "width": 64,
                    "height": 64,
                    "count": 1,
                    "params": {},
                    "tool_settings": {
                        "mask_media_id": by_role["inpaint-mask"]["media_id"],
                        "mask_sha256": by_role["inpaint-mask"]["sha256"],
                        "mask_export_id": exported["id"],
                    },
                    "references": [
                        {"role": "operation_source", "media_id": local_img["id"], "sha256": local_img["sha256"]},
                        {"role": "operation_mask", "media_id": by_role["inpaint-mask"]["media_id"], "sha256": by_role["inpaint-mask"]["sha256"]},
                        {"role": "reference_image", "media_id": ref_extra["id"], "sha256": ref_extra["sha256"]},
                    ],
                },
                "base_draft_id": None,
            },
        )
        inpaint_preview = self.service.preview_workbench_generation(
            self.p,
            {
                "draft_version_id": inpaint_draft["id"],
                "execution_policy": {
                    "version": "bounded-v1",
                    "max_attempts_per_purpose": 4,
                    "max_repair_rounds": 1,
                    "first_draft_due_at": "2030-01-01T00:00:00Z",
                    "stop_submitting_at": "2030-01-02T00:00:00Z",
                },
            },
        )
        self.assertEqual(
            [g for g in inpaint_preview["gaps"] if g["code"] not in {"classic_model_unavailable", "model_capability_mismatch"}],
            [],
        )

    def test_video_review_zip_download_and_combine(self):
        if not shutil.which("ffmpeg"):
            self.skipTest("requires ffmpeg for synthetic mp4")
        objects = self.hierarchy()
        mp4_path = Path(self.temp.name) / "clip1.mp4"
        res = subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=navy:s=64x64:r=12:d=1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(mp4_path)],
            capture_output=True,
            timeout=20,
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        with mp4_path.open("rb") as f:
            staged = self.service.storage.stage_upload(f, "clip1.mp4")
        vid = self.write(
            "register_media",
            {"staged_upload": staged["staged_upload"], "name": "镜头1视频.mp4", "rights": "owned", "source": {"kind": "synthetic", "content": "local clip"}},
        )
        cand = self.candidate(objects["shot"], vid["id"], role="video_take")
        sel_vid = self.post_cmd(
            "/working-selections",
            {"shot_id": objects["shot"], "output_kind": "video", "candidate_id": cand["candidate_id"], "base_version_id": None},
        )
        self.assertEqual(sel_vid.status_code, 200, sel_vid.text)

        review = self.client.get(
            self.base + "/classic-production/video-review",
            params={"episode_id": objects["episode"]},
            headers=self.headers,
        )
        self.assertEqual(review.status_code, 200, review.text)
        self.assertEqual(len(review.json()["clips"]), 1)
        self.assertEqual(review.json()["clips"][0]["media_id"], vid["id"])

        empty_fav = self.client.get(
            self.base + "/classic-production/video-download",
            params={"scope": "favorites", "episode_id": objects["episode"]},
            headers=self.headers,
        )
        self.assertGreaterEqual(empty_fav.status_code, 400)
        self.assertIn("当前没有收藏视频，请先收藏", empty_fav.text)

        zip_all = self.client.get(
            self.base + "/classic-production/video-download",
            params={"scope": "all", "episode_id": objects["episode"]},
            headers=self.headers,
        )
        self.assertEqual(zip_all.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(zip_all.content)) as zf:
            self.assertEqual(len(zf.namelist()), 1)

        combined = self.post_cmd("/classic-production/video-combine", {"episode_id": objects["episode"]})
        self.assertEqual(combined.status_code, 200, combined.text)
        self.assertEqual(combined.json()["clip_count"], 1)

    def test_spatial_director_stage_catalog_auto_frame_occlusion_batch_views_and_panorama(self):
        sky = self.register_png("sky-pano.png", color="skyblue", size=(128, 64))
        listing = self.client.get(self.base + "/spatial-scene-options", headers=self.headers)
        self.assertEqual(listing.status_code, 200, listing.text)
        meta = listing.json()
        self.assertGreaterEqual(len(meta["pose_catalog"]), 20)
        self.assertGreaterEqual(len(meta["body_presets"]), 8)
        self.assertGreaterEqual(len(meta["camera_presets"]), 14)
        self.assertGreaterEqual(len(meta["joint_groups"]), 7)

        doc = {
            "width": 320,
            "height": 180,
            "duration": 2,
            "background": "#10131d",
            "panorama_media_id": sky["id"],
            "sphere_radius": 80,
            "objects": [
                {
                    "id": "hero",
                    "name": "主角",
                    "kind": "actor",
                    "position": [0, 0, 0],
                    "rotation": [0, 0, 0],
                    "scale": [1, 1, 1],
                    "body_preset": "male_basic",
                    "pose": "combat",
                    "joints": {"head_nod": 5},
                },
                {
                    "id": "wall",
                    "name": "四面遮挡笼",
                    "kind": "box",
                    "position": [0, 1.0, 0],
                    "rotation": [0, 0, 0],
                    "scale": [3.6, 3.6, 3.6],
                },
            ],
            "cameras": [
                {
                    "id": "cam-1",
                    "name": "主机位",
                    "position": [0, 1.4, 5.0],
                    "target": [0, 1.0, 0],
                    "fov": 45,
                    "roll": 12,
                }
            ],
        }
        created = self.post_cmd("/spatial-scenes", {"title": "3D导演台测试", "document": doc})
        self.assertEqual(created.status_code, 200, created.text)
        scene_id = created.json()["id"]

        auto = self.client.post(
            self.base + "/spatial-auto-frame",
            headers=self.headers,
            json={"document": doc, "camera_id": "cam-1", "target_object_id": "hero"},
        )
        self.assertEqual(auto.status_code, 200, auto.text)
        self.assertTrue(auto.json()["occluded"])
        self.assertEqual(auto.json()["warning"], "核心对象仍有遮挡，请检查场景或手动调整机位")

        shot_id = self.hierarchy()["shot"]
        media_before_stale = len(self.service.classic_production_options(self.p, shot_id)["media"])
        stale_views = self.client.post(
            f"{self.base}/spatial-scenes/{scene_id}/batch-views",
            headers=self.headers,
            json={
                "payload": {"count": 4, "camera_id": "cam-1", "time": 0},
                "expected_revision": self.rev - 1,
                "idempotency_key": uuid.uuid4().hex,
            },
        )
        self.assertEqual(stale_views.status_code, 409, stale_views.text)
        self.assertEqual(len(self.service.classic_production_options(self.p, shot_id)["media"]), media_before_stale)

        for count in (4, 12):
            views = self.post_cmd(
                f"/spatial-scenes/{scene_id}/batch-views",
                {"count": count, "camera_id": "cam-1", "time": 0},
            )
            self.assertEqual(views.status_code, 200, views.text)
            self.assertEqual(views.json()["count"], count)
            self.assertEqual(len(views.json()["items"]), count)
            self.assertTrue(views.json()["items"][0]["media_id"])
        self.assertEqual(self.service.list_generation_jobs(self.p)["total"], 0)

    def test_team_review_first_frame_batch_commit_duplicate_pass_guard_and_mark_read(self):
        owner = self.service.ensure_local_access("test-human")
        token = set_principal(Principal(**owner))
        self.addCleanup(reset_principal, token)

        preview = self.service.access_migration_preview(self.p, owner["workspace_id"])
        acc_rev = self.service.access_snapshot()["access_revision"]
        self.service.access_command(
            "assign-project",
            {"project_id": self.p, "workspace_id": owner["workspace_id"], "preview_sha256": preview["sha256"]},
            expected_revision=acc_rev,
            idempotency_key=uuid.uuid4().hex,
            actor=owner["actor"],
        )
        acc_rev = self.service.access_snapshot()["access_revision"]
        self.service.access_command(
            "review-policy",
            {"project_id": self.p, "lanes": ["storyboard"]},
            expected_revision=acc_rev,
            idempotency_key=uuid.uuid4().hex,
            actor=owner["actor"],
        )

        objects = self.hierarchy()
        shot2 = self.write("create_object", {"kind": "shot", "parent_id": objects["sequence"], "title": "镜头2", "display_code": "SH-2", "ordinal": 2})
        m1 = self.register_png("ff1.png", color="orange")["id"]
        m2 = self.register_png("ff2.png", color="purple")["id"]
        c1 = self.candidate(objects["shot"], m1, role="first_frame")["candidate_id"]
        c2 = self.candidate(shot2["id"], m2, role="first_frame")["candidate_id"]

        queue = self.service.team_review_queue(self.p, "storyboard")
        self.assertEqual(queue["total"], 2)

        sub1 = self.write("submit_team_review", {"candidate_id": c1, "lane": "storyboard"})
        sub2 = self.write("submit_team_review", {"candidate_id": c2, "lane": "storyboard"})

        from vsc.assets.resource_service import Conflict, ResourceError

        c_unreviewed = self.write(
            "propose_binding",
            {"target_object_id": objects["shot"], "media_id": m1, "role": "last_frame", "slot_key": "unreviewed"},
        )["candidate_id"]
        with self.assertRaises(ResourceError) as missing_verdict:
            self.write("mark_team_review_read", {"candidate_id": c_unreviewed})
        self.assertEqual(missing_verdict.exception.code, "review_missing_for_read_ack")

        secret, cred = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        acc_rev = self.service.access_snapshot()["access_revision"]
        self.service.access_command(
            "invitation",
            {"scope": "project", "scope_id": self.p, "role": "reviewer", "secret": secret, "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()},
            expected_revision=acc_rev,
            idempotency_key=uuid.uuid4().hex,
            actor=owner["actor"],
        )
        reviewer = self.service.accept_access_invitation({"invitation_secret": secret, "credential_secret": cred, "display_name": "审核员"})

        @contextmanager
        def as_reviewer():
            tok = set_principal(Principal(**reviewer))
            try:
                yield
            finally:
                reset_principal(tok)

        with as_reviewer():
            batch = self.service.batch_commit_team_review(
                self.p,
                {"submission_ids": [sub1["submission_id"], sub2["submission_id"]], "outcome": "pass", "reason": "批量审核通过"},
                expected_revision=self.rev,
                idempotency_key=uuid.uuid4().hex,
                actor=reviewer["actor"],
            )
            self.rev = batch["revision"]
            self.assertEqual(batch["count"], 2)

        with self.assertRaises(Conflict) as dup_err:
            self.write("submit_team_review", {"candidate_id": c1, "lane": "storyboard"})
        self.assertIn("无需重复提审", str(dup_err.exception))

        marked = self.write("mark_team_review_read", {"candidate_id": c1, "shot_id": objects["shot"]})
        self.assertTrue(marked["read_ack"])
        queue_after = self.service.team_review_queue(self.p, "storyboard")
        c1_item = next(item for item in queue_after["candidates"] if item["id"] == c1)
        self.assertEqual(len(c1_item["review_history"]), 2)
        self.assertTrue(c1_item["review_history"][0]["read_ack"])

    def test_clean_spa_routes_and_fcp_embed_csp(self):
        for route in ("/storyboard", "/storyboard/repaint", "/video", "/video/review", "/video/multi-clip", "/fcp/en", "/fcp/zh-CN"):
            res = self.client.get(route)
            self.assertEqual(res.status_code, 200, f"{route}: {res.status_code}")
            self.assertIn("classic-subpage-view", res.text)

        embed_en = self.client.get("/api/v1/fcp-embed/en")
        self.assertEqual(embed_en.status_code, 200)
        self.assertIn("frame-ancestors 'self'", embed_en.headers.get("content-security-policy", ""))
        self.assertIn("/static/fcp-embed.js", embed_en.text)

        embed_zh = self.client.get("/api/v1/fcp-embed/zh-cn")
        self.assertEqual(embed_zh.status_code, 404)
