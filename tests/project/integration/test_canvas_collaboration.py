"""Real PostgreSQL + WebSocket sync_protocol=2 collaboration, OE permissions, locks and 11103/11105 recovery."""
from contextlib import contextmanager
import secrets
import tempfile
import unittest
import uuid

from sqlalchemy import delete, insert, select, update

import support.paths
from support.fixtures.resource_store import ResourceStoreFixture, HAS_DB_DEPS, TEST_URL
from vsc.adapters.persistence.postgres import schema as S
from vsc.assets.access_control import Principal, current_principal, reset_principal, set_principal
from vsc.assets.resource_service import Conflict, ResourceError


@unittest.skipUnless(TEST_URL and HAS_DB_DEPS, "requires isolated PostgreSQL")
class CanvasCollaborationTests(ResourceStoreFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        from vsc.adapters.storage.local.store import LocalStorage

        self.temp = tempfile.TemporaryDirectory(prefix="vsc-canvas-collab-")
        self.addCleanup(self.temp.cleanup)
        self.service.storage = LocalStorage(self.temp.name)
        self.owner = self.service.ensure_local_access("test-human")
        self.token = set_principal(Principal(**self.owner))
        self.addCleanup(reset_principal, self.token)
        self.bind(self.p, self.owner["workspace_id"])

    def bind(self, project_id, workspace_id):
        preview = self.service.access_migration_preview(project_id, workspace_id)
        self.service.access_command(
            "assign-project",
            dict(project_id=project_id, workspace_id=workspace_id, preview_sha256=preview["sha256"]),
            actor="test-human",
            expected_revision=self.service.access_snapshot()["access_revision"],
            idempotency_key=uuid.uuid4().hex,
        )

    def make_studio_workspace_and_bind(self, project_id):
        ws_id = str(uuid.uuid4())
        with self.engine.begin() as conn:
            conn.execute(
                insert(S.access_workspaces).values(
                    id=ws_id,
                    kind="studio",
                    name="Studio Team",
                    parent_id=None,
                    created_by=self.owner["identity_id"],
                )
            )
            conn.execute(
                insert(S.access_workspace_members).values(
                    workspace_id=ws_id,
                    identity_id=self.owner["identity_id"],
                    role="owner",
                    active=True,
                )
            )
            conn.execute(
                update(S.access_projects)
                .where(S.access_projects.c.project_id == project_id)
                .values(workspace_id=ws_id)
            )
        return ws_id

    def make_member(self, role, *, name="Collaborator", workspace_id=None, ws_role=None):
        ident_id = str(uuid.uuid4())
        actor = "member:" + ident_id
        with self.engine.begin() as conn:
            conn.execute(
                insert(S.access_identities).values(
                    id=ident_id,
                    subject_key="remote:" + ident_id,
                    actor=actor,
                    display_name=name,
                    preferences={},
                    active=True,
                )
            )
            conn.execute(
                insert(S.access_project_members).values(
                    project_id=self.p,
                    identity_id=ident_id,
                    role=role,
                    active=True,
                )
            )
            if workspace_id and ws_role:
                conn.execute(
                    insert(S.access_workspace_members).values(
                        workspace_id=workspace_id,
                        identity_id=ident_id,
                        role=ws_role,
                        active=True,
                    )
                )
        return dict(identity_id=ident_id, actor=actor, workspace_id=workspace_id)

    @contextmanager
    def as_principal(self, info):
        token = set_principal(Principal(**info))
        try:
            yield
        finally:
            reset_principal(token)

    def create_canvas(self, title="Collab Canvas", nodes=None, edges=None, **extra):
        payload = dict(
            title=title,
            document={"nodes": nodes or [], "edges": edges or []},
            **extra,
        )
        res = self.service.create_creative_canvas(
            self.p,
            payload,
            actor=current_principal().actor,
            expected_revision=self.service.get_project(self.p)["revision"],
            idempotency_key=uuid.uuid4().hex,
        )
        self.rev = res["revision"]
        return res

    def test_user_preferences_and_asymmetric_studio_admin_oe_permission(self):
        prefs = self.service.get_user_preferences()
        self.assertEqual(prefs["preferences"]["collaboration"]["enabled_on_new_canvas"], False)
        updated = self.service.update_user_preferences(
            {"collaboration": {"enabled_on_new_canvas": True}}
        )
        self.assertEqual(updated["preferences"]["collaboration"]["enabled_on_new_canvas"], True)
        auto_collab = self.create_canvas("Auto Collab")
        self.assertIs(auto_collab["collaboration_enabled"], True)
        self.service.update_user_preferences({"collaboration": {"enabled_on_new_canvas": False}})

        # Personal workspace marks is_personal_workspace=True
        personal_detail = self.service.get_creative_canvas(self.p, auto_collab["id"])
        self.assertIs(personal_detail["permission"]["is_personal_workspace"], True)

        # Convert project to Studio workspace and create a private canvas authored by an editor
        studio_ws = self.make_studio_workspace_and_bind(self.p)
        author = self.make_member("editor", name="Canvas Author", workspace_id=studio_ws, ws_role="editor")
        studio_admin = self.make_member("owner", name="Studio Admin", workspace_id=studio_ws, ws_role="owner")

        with self.as_principal(author):
            private_canvas = self.create_canvas(
                "Author Private",
                nodes=[{"id": "n1", "type": "text", "title": "Draft", "text": "hello", "x": 100, "y": 100}],
                collaboration_enabled=False,
            )

        # Studio Admin is NOT owner: while collaboration_enabled=False, can_manage_collaboration=True BUT can_edit=False!
        with self.as_principal(studio_admin):
            detail = self.service.get_creative_canvas(self.p, private_canvas["id"])
            perm = detail["permission"]
            self.assertEqual(perm["mode"], "manage")
            self.assertIs(perm["is_owner"], False)
            self.assertIs(perm["is_studio_admin"], True)
            self.assertIs(perm["can_manage_collaboration"], True)
            self.assertIs(perm["can_edit"], False)
            self.assertIs(perm["is_personal_workspace"], False)

            with self.assertRaises(ResourceError) as denied_edit:
                self.service.save_creative_canvas(
                    self.p,
                    dict(canvas_id=private_canvas["id"], canvas_revision=1, title="Illegal Admin Edit", document=detail["document"]),
                    actor=studio_admin["actor"],
                    expected_revision=self.service.get_project(self.p)["revision"],
                    idempotency_key=uuid.uuid4().hex,
                )
            self.assertEqual(denied_edit.exception.code, "canvas_edit_denied")

            # Studio Admin CAN enable collaboration via set_canvas_collaboration, gaining edit permission!
            toggled = self.service.set_canvas_collaboration(
                self.p,
                dict(canvas_id=private_canvas["id"], collaboration_enabled=True),
                actor=studio_admin["actor"],
                expected_revision=self.service.get_project(self.p)["revision"],
                idempotency_key=uuid.uuid4().hex,
            )
            self.assertIs(toggled["collaboration_enabled"], True)
            self.assertIs(toggled["permission"]["can_edit"], True)

            saved = self.service.save_creative_canvas(
                self.p,
                dict(canvas_id=private_canvas["id"], canvas_revision=1, title="Admin Collaborative Edit", document=detail["document"]),
                actor=studio_admin["actor"],
                expected_revision=self.service.get_project(self.p)["revision"],
                idempotency_key=uuid.uuid4().hex,
            )
            self.assertEqual(saved["canvas_revision"], 2)

    def test_recovery_batch_clean_merge_11103_conflict_lock_guard_and_11105_invalid_edge(self):
        studio_ws = self.make_studio_workspace_and_bind(self.p)
        editor = self.make_member("editor", name="Editor Two", workspace_id=studio_ws, ws_role="editor")
        canvas = self.create_canvas(
            "Recovery Canvas",
            nodes=[
                {"id": "n-a", "type": "text", "title": "Node A", "text": "v1-a", "x": 100, "y": 100},
                {"id": "n-b", "type": "text", "title": "Node B", "text": "v1-b", "x": 400, "y": 100},
            ],
            collaboration_enabled=True,
        )

        # Owner advances v1 -> v2 by editing only n-a
        v1_doc = self.service.get_creative_canvas(self.p, canvas["id"])["document"]
        v2_doc = {
            "viewport": v1_doc["viewport"],
            "nodes": [
                dict(v1_doc["nodes"][0], text="v2-a-remote"),
                dict(v1_doc["nodes"][1]),
            ],
            "edges": [],
        }
        self.service.save_creative_canvas(
            self.p,
            dict(canvas_id=canvas["id"], canvas_revision=1, title="Recovery Canvas", document=v2_doc),
            actor="test-human",
            expected_revision=self.service.get_project(self.p)["revision"],
            idempotency_key=uuid.uuid4().hex,
        )

        # Editor recovers against base_version=1 touching ONLY disjoint node n-b -> clean merge to v3!
        with self.as_principal(editor):
            merged = self.service.recover_canvas_batch(
                self.p,
                dict(
                    protocol_version=1,
                    canvas_id=canvas["id"],
                    base_version=1,
                    operations=[{"op": "upsert_node", "node": {"id": "n-b", "type": "text", "title": "Node B", "text": "v3-b-local", "x": 420, "y": 100}}],
                ),
                actor=editor["actor"],
                expected_revision=self.service.get_project(self.p)["revision"],
                idempotency_key=uuid.uuid4().hex,
            )
            self.assertEqual(merged["version"], 3)
            by_id = {n["id"]: n for n in merged["document"]["nodes"]}
            self.assertEqual(by_id["n-a"]["text"], "v2-a-remote")
            self.assertEqual(by_id["n-b"]["text"], "v3-b-local")

            # Editor submits stale base_version=1 touching overlapping n-a -> 11103 conflict!
            with self.assertRaises(Conflict) as conflict_ctx:
                self.service.recover_canvas_batch(
                    self.p,
                    dict(
                        protocol_version=1,
                        canvas_id=canvas["id"],
                        base_version=1,
                        operations=[{"op": "upsert_node", "node": {"id": "n-a", "type": "text", "title": "Node A", "text": "stale-overwrite", "x": 120, "y": 100}}],
                    ),
                    actor=editor["actor"],
                    expected_revision=self.service.get_project(self.p)["revision"],
                    idempotency_key=uuid.uuid4().hex,
                )
            self.assertEqual(conflict_ctx.exception.details["error_code"], 11103)
            self.assertEqual(conflict_ctx.exception.details["conflicts"][0]["node_id"], "n-a")

            # Invalid edge port returns 11105
            with self.assertRaises(ResourceError) as bad_edge:
                self.service.recover_canvas_batch(
                    self.p,
                    dict(
                        protocol_version=1,
                        canvas_id=canvas["id"],
                        base_version=3,
                        operations=[{"op": "upsert_edge", "edge": {"id": "bad-e", "source": "n-a", "target": "n-b", "port": "prompt"}}],
                    ),
                    actor=editor["actor"],
                    expected_revision=self.service.get_project(self.p)["revision"],
                    idempotency_key=uuid.uuid4().hex,
                )
            self.assertEqual(bad_edge.exception.details["error_code"], 11105)

    def test_websocket_sync_protocol_2_locks_takeover_4009_and_live_permission_downgrade(self):
        from fastapi.testclient import TestClient
        from starlette.websockets import WebSocketDisconnect
        from vsc.interfaces.web.app import create_app
        from vsc.project.resource_catalog import ResourceCatalog

        studio_ws = self.make_studio_workspace_and_bind(self.p)
        collab_secret = secrets.token_urlsafe(32)
        editor = self.make_member("editor", name="Live Editor", workspace_id=studio_ws, ws_role="editor")
        with self.as_principal(self.owner):
            from hashlib import sha256
            editor_personal_ws = str(uuid.uuid4())
            with self.engine.begin() as conn:
                conn.execute(
                    insert(S.access_workspaces).values(
                        id=editor_personal_ws,
                        name="Live Editor个人空间",
                        kind="personal",
                        parent_id=None,
                        created_by=editor["identity_id"],
                    )
                )
                conn.execute(
                    insert(S.access_workspace_members).values(
                        workspace_id=editor_personal_ws,
                        identity_id=editor["identity_id"],
                        role="owner",
                        active=True,
                    )
                )
                conn.execute(
                    insert(S.access_credentials).values(
                        id=str(uuid.uuid4()),
                        identity_id=editor["identity_id"],
                        secret_sha256=sha256(collab_secret.encode("utf-8")).hexdigest(),
                        revoked=False,
                    )
                )
            canvas = self.create_canvas(
                "Realtime Canvas",
                nodes=[
                    {"id": "node-2", "type": "text", "title": "Second", "text": "two", "x": 360, "y": 100},
                    {"id": "node-1", "type": "text", "title": "First", "text": "one", "x": 100, "y": 100},
                ],
                collaboration_enabled=True,
            )

        app = create_app(
            dict(
                allowed_hosts=["testserver"],
                allowed_origins=["http://testserver"],
                access_token="owner-token",
                human_identity="test-human",
                background_enabled=False,
            ),
            catalog=ResourceCatalog(self.temp.name, self.service, media_root=self.temp.name),
            service=self.service,
        )
        origin_headers = {"Origin": "http://testserver"}
        with TestClient(app) as owner_client, TestClient(app) as editor_client:
            owner_login = owner_client.post("/api/v1/session", json={"token": "owner-token"}, headers=origin_headers)
            self.assertEqual(owner_login.status_code, 200, owner_login.text)
            owner_headers = {"Origin": "http://testserver", "X-CSRF-Token": owner_login.json()["csrf_token"]}
            editor_login = editor_client.post("/api/v1/access/login", json={"secret": collab_secret}, headers=origin_headers)
            self.assertEqual(editor_login.status_code, 200, editor_login.text)
            editor_headers = {"Origin": "http://testserver", "X-CSRF-Token": editor_login.json()["csrf_token"]}

            base_url = f"/api/v1/projects/{self.p}/creative-canvases/{canvas['id']}"
            t1 = owner_client.post(f"{base_url}/collab/ticket", json={"payload": {"mode": "edit", "page_session_id": "ps_owner_1"}}, headers=owner_headers)
            self.assertEqual(t1.status_code, 200, t1.text)
            ticket_str = t1.json()["ticket"]

            ws_path_1 = f"{base_url}/collab/ws?project_id={self.p}&canvas_id={canvas['id']}&mode=edit&sync_protocol=2&ticket={ticket_str}&client_last_seq=1"
            with owner_client.websocket_connect(ws_path_1) as ws1:
                ready = ws1.receive_json()
                self.assertEqual(ready["type"], "session.ready")
                snap = ws1.receive_json()
                self.assertEqual(snap["type"], "canvas.sync.snapshot")
                self.assertEqual(snap["payload"]["protocol_version"], 2)

                # Replay of the consumed one-time ticket must be rejected (4003)
                with self.assertRaises(WebSocketDisconnect) as replay_err:
                    with owner_client.websocket_connect(ws_path_1):
                        pass
                self.assertEqual(replay_err.exception.code, 4003)

                # Same-user takeover from second tab kicks ws1 with session.kicked + 4009!
                t1b = owner_client.post(f"{base_url}/collab/ticket", json={"payload": {"mode": "edit", "page_session_id": "ps_owner_2"}}, headers=owner_headers).json()
                ws_path_1b = f"{base_url}/collab/ws?project_id={self.p}&canvas_id={canvas['id']}&mode=edit&sync_protocol=2&ticket={t1b['ticket']}&client_last_seq=1"
                with owner_client.websocket_connect(ws_path_1b) as ws_owner:
                    self.assertEqual(ws_owner.receive_json()["type"], "session.ready")
                    self.assertEqual(ws_owner.receive_json()["type"], "canvas.sync.snapshot")
                    kicked_msg = ws1.receive_json()
                    self.assertEqual(kicked_msg["type"], "session.kicked")
                    self.assertEqual(kicked_msg["payload"]["reason"], "same_user_takeover")

                    # Editor connects concurrently
                    te = editor_client.post(f"{base_url}/collab/ticket", json={"payload": {"mode": "edit", "page_session_id": "ps_editor_1"}}, headers=editor_headers).json()
                    ws_path_e = f"{base_url}/collab/ws?project_id={self.p}&canvas_id={canvas['id']}&mode=edit&sync_protocol=2&ticket={te['ticket']}&client_last_seq=1"
                    with editor_client.websocket_connect(ws_path_e) as ws_editor:
                        self.assertEqual(ws_editor.receive_json()["type"], "session.ready")
                        self.assertEqual(ws_editor.receive_json()["type"], "canvas.sync.snapshot")
                        joined = ws_owner.receive_json()
                        self.assertEqual(joined["type"], "member.joined")
                        self.assertEqual(ws_owner.receive_json()["type"], "members.snapshot")

                        # Unsorted multi-node lock request is strictly rejected (deadlock guard)
                        ws_editor.send_json({
                            "type": "node.lock.acquire",
                            "event_id": "evt_unsorted",
                            "request_id": "req_lock_unsorted",
                            "payload": {"node_keys": ["node-2", "node-1"], "intent": "edit"},
                        })
                        unsorted_rej = ws_editor.receive_json()
                        self.assertEqual(unsorted_rej["type"], "node.lock.rejected")
                        self.assertEqual(unsorted_rej["payload"]["reason"], "unsorted_lock_keys")

                        # Sorted multi-node lock request is granted with fencing_token
                        ws_editor.send_json({
                            "type": "node.lock.acquire",
                            "event_id": "evt_1",
                            "request_id": "req_lock_1",
                            "payload": {"node_keys": ["node-1", "node-2"], "intent": "edit"},
                        })
                        editor_locked = ws_editor.receive_json()
                        self.assertEqual(editor_locked["type"], "node.locked")
                        self.assertEqual([l["node_key"] for l in editor_locked["payload"]["locks"]], ["node-1", "node-2"])
                        self.assertEqual(ws_editor.receive_json()["type"], "members.snapshot")
                        owner_saw_lock = ws_owner.receive_json()
                        self.assertEqual(owner_saw_lock["type"], "node.locked")
                        self.assertEqual(ws_owner.receive_json()["type"], "members.snapshot")

                        # Owner attempting to acquire node-1 is rejected
                        ws_owner.send_json({
                            "type": "node.lock.acquire",
                            "event_id": "evt_2",
                            "request_id": "req_lock_2",
                            "payload": {"node_keys": ["node-1"], "intent": "move"},
                        })
                        rejected = ws_owner.receive_json()
                        self.assertEqual(rejected["type"], "node.lock.rejected")
                        self.assertEqual(rejected["payload"]["reason"], "locked_by_other")

                        # Owner toggles collaboration OFF -> Editor immediately receives permission.changed (can_edit=False) & locks purged!
                        proj_rev = owner_client.get(base_url).json()["revision"]
                        off = owner_client.post(
                            f"{base_url}/collaboration",
                            json={
                                "payload": {"collaboration_enabled": False},
                                "expected_revision": proj_rev,
                                "idempotency_key": uuid.uuid4().hex,
                            },
                            headers=owner_headers,
                        )
                        self.assertEqual(off.status_code, 200, off.text)

                        editor_frames = [ws_editor.receive_json(), ws_editor.receive_json(), ws_editor.receive_json()]
                        frame_types = {f["type"] for f in editor_frames}
                        self.assertIn("node.unlocked", frame_types)
                        self.assertIn("permission.changed", frame_types)
                        self.assertIn("members.snapshot", frame_types)
                        perm_frame = next(f for f in editor_frames if f["type"] == "permission.changed")
                        self.assertIs(perm_frame["payload"]["permission"]["can_edit"], False)

    def test_immutability_triggers_protect_decisions_ops_and_canvas_identity(self):
        canvas = self.create_canvas("Immutable Canvas", collaboration_enabled=False)
        self.service.set_canvas_collaboration(
            self.p,
            dict(canvas_id=canvas["id"], collaboration_enabled=True),
            actor="test-human",
            expected_revision=self.service.get_project(self.p)["revision"],
            idempotency_key=uuid.uuid4().hex,
        )
        from sqlalchemy.exc import IntegrityError

        for table in (S.canvas_collaboration_decisions, S.canvas_collab_ops):
            with self.assertRaises(IntegrityError):
                with self.engine.begin() as conn:
                    conn.execute(delete(table).where(table.c.project_id == self.p))
        with self.assertRaises(IntegrityError):
            with self.engine.begin() as conn:
                conn.execute(
                    update(S.creative_canvases)
                    .where(S.creative_canvases.c.project_id == self.p, S.creative_canvases.c.id == canvas["id"])
                    .values(created_by="tampered-actor")
                )

    def test_ws_authority_fencing_conflict_11103_revocation_share_and_bounded_collaborators(self):
        from hashlib import sha256
        from sqlalchemy import event
        from vsc.interfaces.web.creative_canvas import parse_request_host

        # P2-1: IPv6 host header parsing parity
        self.assertEqual(parse_request_host("[::1]:8765"), "[::1]")
        self.assertEqual(parse_request_host("[::1]"), "[::1]")
        self.assertEqual(parse_request_host("127.0.0.1:8765"), "127.0.0.1")

        studio_ws = self.make_studio_workspace_and_bind(self.p)
        editor = self.make_member("editor", name="Editor Two", workspace_id=studio_ws, ws_role="editor")
        outsider_id = str(uuid.uuid4())
        outsider = {"identity_id": outsider_id, "actor": f"outsider:{outsider_id}"}
        cred_id = str(uuid.uuid4())
        with self.engine.begin() as conn:
            conn.execute(
                insert(S.access_identities).values(
                    id=outsider_id,
                    subject_key="remote:" + outsider_id,
                    actor=outsider["actor"],
                    display_name="Outsider User",
                    preferences={},
                    active=True,
                )
            )
            conn.execute(
                insert(S.access_credentials).values(
                    id=cred_id,
                    identity_id=editor["identity_id"],
                    secret_sha256=sha256(b"editor2-secret").hexdigest(),
                    revoked=False,
                )
            )
        with self.as_principal(self.owner):
            canvas = self.create_canvas(
                "Hardened Collab Canvas",
                nodes=[
                    {"id": "n-1", "type": "text", "title": "Node One", "text": "v1", "x": 100, "y": 100},
                    {"id": "n-2", "type": "text", "title": "Node Two", "text": "v1", "x": 360, "y": 100},
                ],
                collaboration_enabled=True,
            )

        # P1-4: _project_collaborators must execute in O(1) SQL statements regardless of unrelated active users!
        def measure_get_canvas_sql():
            cnt = 0

            def count_sql(_conn, _cursor, _stmt, _params, _ctx, _many):
                nonlocal cnt
                cnt += 1

            event.listen(self.engine, "before_cursor_execute", count_sql)
            try:
                with self.as_principal(self.owner):
                    fetched = self.service.get_creative_canvas(self.p, canvas["id"])
                    self.assertEqual(len(fetched["collaborators"]), 2)
            finally:
                event.remove(self.engine, "before_cursor_execute", count_sql)
            return cnt

        sql_before = measure_get_canvas_sql()
        with self.engine.begin() as conn:
            for idx in range(40):
                uid = str(uuid.uuid4())
                conn.execute(
                    insert(S.access_identities).values(
                        id=uid,
                        subject_key=f"unrelated:{idx}:{uid}",
                        actor=f"unrelated-{idx}",
                        display_name=f"无关成员{idx}",
                        preferences={},
                        active=True,
                    )
                )
        sql_after = measure_get_canvas_sql()
        self.assertEqual(sql_after, sql_before, f"expected O(1) SQL statements ({sql_before}), got {sql_after}")

        # P0-1 & P1-5: Share-link + logged-in non-member can read/edit via share, but CANNOT issue WS collab ticket!
        share_id = str(uuid.uuid4())
        from datetime import datetime, timedelta, timezone
        with self.engine.begin() as conn:
            conn.execute(
                insert(S.access_shares).values(
                    id=share_id,
                    project_id=self.p,
                    canvas_id=canvas["id"],
                    canvas_version_id=canvas["version_id"],
                    mode="edit",
                    secret_sha256=sha256(b"share-secret").hexdigest(),
                    revoked=False,
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
                    created_by=self.owner["identity_id"],
                )
            )
        outsider_with_share = Principal(
            identity_id=outsider["identity_id"],
            actor=outsider["actor"],
            share_id=share_id,
            local=False,
        )
        from vsc.assets.access_control import set_principal, reset_principal
        tok = set_principal(outsider_with_share)
        try:
            shared_detail = self.service.get_creative_canvas(self.p, canvas["id"])
            self.assertIs(shared_detail["permission"]["can_edit"], True)
            with self.assertRaises(ResourceError):
                self.service.issue_canvas_collab_ticket(
                    self.p,
                    canvas["id"],
                    {"mode": "edit", "page_session_id": "ps_share"},
                    actor=outsider["actor"],
                )
        finally:
            reset_principal(tok)

        # P0-2: WebSocket ops submit enforces fencing_token & 11103 conflict detection
        with self.as_principal(editor):
            t_ed = self.service.issue_canvas_collab_ticket(
                self.p, canvas["id"], {"mode": "edit", "page_session_id": "ps_ed"}, actor=editor["actor"]
            )
        consumed = self.store.consume_canvas_collab_ticket(self.p, canvas["id"], t_ed["ticket"], client_last_seq=1)
        ed_sid = consumed["session"]["id"]

        lock_res = self.store.acquire_canvas_node_locks(self.p, canvas["id"], ed_sid, ["n-1"], intent="edit")
        self.assertIs(lock_res["accepted"], True)
        ftok = lock_res["fencing_token"]

        # Missing or non-int fencing_token on locked node must fail without TypeError
        bad_tok_res = self.store.submit_canvas_collab_ops(
            self.p,
            canvas["id"],
            ed_sid,
            {
                "base_version": 1,
                "ops": [{"op": "upsert_node", "node": {"id": "n-1", "type": "text", "title": "Node One", "text": "no-tok", "x": 100, "y": 100}}],
                "lock_credentials": {"n-1": "not-an-int"},
            },
        )
        self.assertIs(bad_tok_res["accepted"], False)
        self.assertEqual(bad_tok_res["reason"], "node_locked")

        # Valid fencing_token advances version 1 -> 2 on n-1
        ok_ops = self.store.submit_canvas_collab_ops(
            self.p,
            canvas["id"],
            ed_sid,
            {
                "base_version": 1,
                "client_op_id": "op-ed-1",
                "ops": [{"op": "upsert_node", "node": {"id": "n-1", "type": "text", "title": "Node One", "text": "ed-v2", "x": 100, "y": 100}}],
                "lock_credentials": {"n-1": ftok},
            },
        )
        self.assertIs(ok_ops["accepted"], True)
        self.assertEqual(ok_ops["version"], 2)
        self.store.release_canvas_node_locks(self.p, canvas["id"], ed_sid, [{"node_key": "n-1", "fencing_token": ftok}])

        # Owner session submits concurrent edit on n-1 with stale base_seq=1 (without explicit base_version) -> must hit 11103!
        with self.as_principal(self.owner):
            t_ow = self.service.issue_canvas_collab_ticket(
                self.p, canvas["id"], {"mode": "edit", "page_session_id": "ps_ow"}, actor=self.owner["actor"]
            )
        ow_sid = self.store.consume_canvas_collab_ticket(self.p, canvas["id"], t_ow["ticket"], client_last_seq=1)["session"]["id"]
        conflict_ops = self.store.submit_canvas_collab_ops(
            self.p,
            canvas["id"],
            ow_sid,
            {
                "base_seq": 1,
                "client_op_id": "op-ow-conflict",
                "ops": [{"op": "upsert_node", "node": {"id": "n-1", "type": "text", "title": "Node One", "text": "ow-stale", "x": 100, "y": 100}}],
            },
        )
        self.assertIs(conflict_ops["accepted"], False)
        self.assertEqual(conflict_ops["error_code"], 11103)
        self.assertEqual(conflict_ops["conflicts"][0]["node_id"], "n-1")

        # P0-1 & P1-5: Revoking editor's credential blocks sync_canvas_collab_ops and deactivating user does not crash room_state!
        with self.engine.begin() as conn:
            conn.execute(update(S.access_credentials).where(S.access_credentials.c.id == cred_id).values(revoked=True))
        with self.assertRaises(ResourceError):
            self.store.sync_canvas_collab_ops(self.p, canvas["id"], ed_sid, 1)

        with self.engine.begin() as conn:
            conn.execute(update(S.access_identities).where(S.access_identities.c.id == editor["identity_id"]).values(active=False))
        room_state = self.store.canvas_collab_room_state(self.p, canvas["id"])
        self.assertIsNotNone(room_state)
