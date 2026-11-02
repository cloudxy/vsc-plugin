"""Gallery counts and fixed-source reuse through the original isolated PG paths."""
import io
import secrets
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone

import support.paths
from support.fixtures.resource_store import ResourceStoreFixture, HAS_DB_DEPS, TEST_URL
from support.fixtures.resources import png_bytes
from vsc.assets.resource_service import ResourceError


@unittest.skipUnless(TEST_URL and HAS_DB_DEPS, "requires isolated PostgreSQL")
class AssetCenterGalleryTests(ResourceStoreFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        from vsc.adapters.storage.local.store import LocalStorage
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.service.storage = LocalStorage(self.tmp.name)
        self.prefix = "gallery-" + uuid.uuid4().hex

    def shared(self, name, count=1, key=None):
        members = []
        for ordinal in range(count):
            staged = self.service.storage.stage_upload(io.BytesIO(png_bytes()), "synthetic.png")
            members.append({"member_key": "image-" + str(ordinal), "staged_upload": staged["staged_upload"]})
        return self.service.import_library({
            "library_key": key or self.prefix + "-" + name, "title": self.prefix + " " + name,
            "category": "image" if count else "production-spec", "description": "Owned synthetic test media",
            "specification": {"description": "No generated or third-party content"},
            "allowed_purposes": ["identity_face", "reference_image", "first_frame"],
            "license": {"outcome": "owned", "allow_workspace_reuse": True, "evidence": "Synthetic fixture"},
            "import_key": uuid.uuid4().hex, "members": members}, actor="test-human")

    def test_gallery_sql_counts_current_members_paging_and_legacy_filter(self):
        multi = self.shared("A", 2)
        self.shared("B")
        self.shared("C")
        self.shared("spec", 0)
        filters = {"query": self.prefix, "media_only": True}
        self.assertEqual(self.service.search_asset_center({"query": self.prefix}, "test-human")["total"], 4)
        self.assertEqual(self.service.search_asset_center(filters, "test-human")["total"], 3)
        pages = [self.service.search_asset_center(dict(filters, offset=i, limit=1), "test-human") for i in range(3)]
        self.assertEqual([page["next_offset"] for page in pages], [1, 2, None])
        self.assertEqual(len({page["items"][0]["id"] for page in pages}), 3)
        self.assertEqual(len(pages[0]["items"][0]["members"]), 2)  # Entries, not a multiplying join.
        self.service.edit_asset_catalog(dict(entry_id=multi["entry_id"], library_version_id=multi["version_id"],
            expected_revision=0, asset_kind="character", form_name="少年", workspace_id=None, review_status="draft",
            notes="", tags=[self.prefix + " 司机%"], command_key=uuid.uuid4().hex), "test-human")
        self.assertEqual(self.service.search_asset_center(dict(filters, asset_kind="character"), "test-human")["total"], 1)
        self.assertEqual(self.service.search_asset_center(dict(filters, asset_kind="other"), "test-human")["total"], 2)
        tagged = self.service.search_asset_center({"query": self.prefix + " 司机%", "media_only": True}, "test-human")
        self.assertEqual(tagged["total"], 1)
        # A historical media version must not turn a current specification into a gallery hit.
        self.shared("A", 0, key=self.prefix + "-A")
        self.assertEqual(self.service.search_asset_center(filters, "test-human")["total"], 2)
        self.assertEqual(self.service.search_asset_center({"query": self.prefix, "media_only": False}, "test-human")["total"], 4)
        with self.assertRaises(ResourceError):
            self.service.search_asset_center({"media_only": "false"}, "test-human")

    def test_fixed_single_import_and_reference_canvas_receipts_remain_independent(self):
        fixed = self.shared("reference")
        selection = self.service.change_asset_center_cart({"library_version_id": fixed["version_id"], "member_key": "image-0", "active": True}, "test-human")
        payload = {"cart_id": selection["id"], "asset_kind": "character", "role": "identity_face"}
        original_revision = self.rev
        result = self.write("import_asset_center_item", payload, idempotency_key="gallery-import")
        self.shared("reference", 0, key=self.prefix + "-reference")
        replay = self.service.import_asset_center_item(self.p, payload, actor="test-human", expected_revision=original_revision, idempotency_key="gallery-import")
        self.assertEqual(replay, result)
        again = self.write("import_asset_center_item", payload)
        self.assertEqual(again["media_id"], result["media_id"])
        card = self.service.get_asset_card(self.p, result["target_object_id"])
        self.assertEqual(card["forms"][0]["media_id"], result["media_id"])
        document = {"nodes": [{"id": "reference", "type": "image", "title": "合成参考", "media_id": result["media_id"], "x": 0, "y": 0},
                              {"id": "output", "type": "image", "title": "合成参考", "text": "", "x": 400, "y": 0}],
                    "edges": [{"id": "reference-edge", "source": "reference", "target": "output", "port": "reference"}]}
        canvas_payload = {"title": "合成参考", "episode_id": None, "document": document}
        revision = self.rev
        canvas = self.write("create_creative_canvas", canvas_payload, idempotency_key="gallery-canvas")
        self.assertEqual(canvas, self.service.create_creative_canvas(self.p, canvas_payload, actor="test-human", expected_revision=revision, idempotency_key="gallery-canvas"))
        from sqlalchemy import func, select
        from vsc.adapters.persistence.postgres import schema as S
        with self.engine.connect() as conn:
            reuse = conn.execute(select(S.library_reuses).where(S.library_reuses.c.project_id == self.p, S.library_reuses.c.media_id == result["media_id"])).mappings().one()
            self.assertEqual(reuse["library_version_id"], fixed["version_id"])
            self.assertEqual(conn.execute(select(func.count()).select_from(S.generation_jobs).where(S.generation_jobs.c.project_id == self.p)).scalar_one(), 0)
        self.service.retire_library(fixed["entry_id"], {"outcome": "revoke_rights", "reason": "Synthetic current source revoke", "idempotency_key": "gallery-revoke"}, actor="test-human")
        other = self.service.create_project({"name": "另一目标项目"}, actor="test-human")
        with self.assertRaises(ResourceError):
            self.service.import_asset_center_item(other["id"], payload, actor="test-human", expected_revision=0, idempotency_key="new-target-revoked")
        self.assertEqual(self.service.asset_center_cart("other-human")["items"], [])

    def test_http_media_filter_and_read_only_target_cannot_import(self):
        from fastapi.testclient import TestClient
        from vsc.assets.access_control import Principal, set_principal, reset_principal
        from vsc.interfaces.web.app import create_app
        fixed = self.shared("http")
        self.shared("spec", 0)
        owner = self.service.ensure_local_access("test-human")
        token = set_principal(Principal(**owner))
        self.addCleanup(reset_principal, token)
        def command(action, payload):
            return self.service.access_command(action, payload, expected_revision=self.service.access_snapshot()["access_revision"], idempotency_key=uuid.uuid4().hex, actor="test-human")
        preview = self.service.access_migration_preview(self.p, owner["workspace_id"])
        command("assign-project", {"project_id": self.p, "workspace_id": owner["workspace_id"], "preview_sha256": preview["sha256"]})
        secret, credential = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        command("invitation", {"scope": "project", "scope_id": self.p, "role": "viewer", "secret": secret, "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()})
        self.service.accept_access_invitation({"invitation_secret": secret, "credential_secret": credential, "display_name": "只读查看者"})
        app = create_app({"projects_root": self.tmp.name, "allowed_hosts": ["testserver"], "allowed_origins": ["http://testserver"], "access_token": "gallery-local", "human_identity": "test-human", "background_enabled": False}, service=self.service)
        with TestClient(app) as client:
            self.assertEqual(client.get('/api/v1/asset-center?media_only=true').status_code, 403)
            login = client.post('/api/v1/access/login', json={"secret": credential}, headers={"Origin": "http://testserver"})
            self.assertEqual(login.status_code, 200, login.text)
            headers = {"Origin": "http://testserver", "X-CSRF-Token": login.json()["csrf_token"]}
            filtered = client.get('/api/v1/asset-center', params={"query": self.prefix, "media_only": "true"}, headers=headers)
            self.assertEqual(filtered.status_code, 200, filtered.text)
            self.assertEqual(filtered.json()["total"], 1)
            self.assertEqual(client.get('/api/v1/asset-center', params={"query": self.prefix}, headers=headers).json()["total"], 2)
            self.assertEqual(client.get('/api/v1/asset-center?media_only=invalid', headers=headers).status_code, 422)
            cart = client.post('/api/v1/asset-center/cart', headers=headers, json={"payload": {"library_version_id": fixed["version_id"], "member_key": "image-0", "active": True}})
            self.assertEqual(cart.status_code, 200, cart.text)
            denied = client.post('/api/v1/projects/'+self.p+'/asset-center/import', headers=headers, json={"payload": {"cart_id": cart.json()["id"], "asset_kind": "character", "role": "identity_face"}, "expected_revision": self.rev, "idempotency_key": "viewer-import"})
            self.assertEqual(denied.status_code, 403, denied.text)
