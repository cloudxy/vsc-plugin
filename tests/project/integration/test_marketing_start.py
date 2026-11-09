"""One marketing start uses the original PG turn/session/dispatch and receipt."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import io
import secrets
import shutil
import tempfile
from threading import Event, get_ident
import unittest
import uuid
from unittest.mock import patch

from support.fixtures.resource_store import ResourceStoreFixture, HAS_DB_DEPS, TEST_URL
from vsc.assets.marketing_studio import marketing_methods, marketing_start_key, marketing_start_request
from vsc.assets.resource_service import ResourceError


class MarketingStartContractTests(unittest.TestCase):
    def test_start_key_fixed_vector_and_strict_intent(self):
        from vsc.assets.access_control import action_capability
        root = "00000000-0000-4000-8000-000000000000"
        self.assertEqual(marketing_start_key(root), "marketing-start:db8055e0e0307d5a016bec4dc338d69875eb0fb7e614a8b125b08fb082095d98")
        self.assertEqual(len(marketing_start_key("x" * 200)), 80)
        self.assertEqual(action_capability("start_marketing_canvas"), "execute")
        good = dict(canvas_id=str(uuid.uuid4()), prepare_key=root, canvas_revision=1, canvas_sha256="a" * 64,
            model_ids=[str(uuid.uuid4()), str(uuid.uuid4())], mode="manual", execution_settings={})
        self.assertEqual(marketing_start_request(good), good)
        uppercase = dict(good, model_ids=[item.upper() for item in good["model_ids"]])
        self.assertEqual(marketing_start_request(uppercase), good)
        bad = [dict(good, mode={}), dict(good, model_ids=[good["model_ids"][0]] * 2),
            dict(good, canvas_revision=True), dict(good, canvas_sha256="bad"), dict(good, model_ids="wrong"),
            dict(good, execution_settings={"auto_media": {"max_credits": None}}), dict(good, message="spoof"),
            dict(good, skill_id="vsc-script"), dict(good, node_ids=[]), dict(good, session_id=str(uuid.uuid4())),
            dict(good, execution_settings={"actor": "spoof"})]
        for value in bad:
            with self.subTest(value=value):
                with self.assertRaises(ResourceError):
                    marketing_start_request(value)
        for root in ("", " ", "x" * 201, None):
            with self.subTest(root=root):
                with self.assertRaises(ResourceError):
                    marketing_start_key(root)


class PlanBackend:
    name = "synthetic-marketing-plan-only"
    def __init__(self, unknown=False):
        self.calls, self.unknown = 0, unknown
    def available(self):
        return True
    def generate(self, packet, turn, skill):
        self.calls += 1
        if self.unknown:
            raise ResourceError("synthetic uncertain planning response", "canvas_agent_submission_unknown")
        return dict(message="请补充商品事实", questions=["请提供商品事实。"],
            action=dict(kind="none", title="", text="", source_node_id=""))


@unittest.skipUnless(TEST_URL and HAS_DB_DEPS and shutil.which("ffmpeg"), "requires isolated PostgreSQL, web dependencies and ffmpeg")
class MarketingStartTests(ResourceStoreFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        from fastapi.testclient import TestClient
        from vsc.adapters.storage.local.store import LocalStorage
        from vsc.interfaces.web.app import create_app
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        previous = self.service.storage
        self.addCleanup(setattr, self.service, "storage", previous)
        self.service.storage = LocalStorage(self.directory.name)
        self.client = TestClient(create_app(dict(projects_root=self.directory.name + "/projects", media_root=self.directory.name,
            allowed_hosts=["testserver"], allowed_origins=["http://testserver"], human_identity="test-human",
            access_token="test-token", background_enabled=False), service=self.service))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        session = self.client.post("/api/v1/session", headers={"Origin": "http://testserver"}, json={"token": "test-token"}).json()
        self.headers = {"Origin": "http://testserver", "X-CSRF-Token": session["csrf_token"]}
        self.base = "/api/v1/projects/" + self.p
        previous_backend = getattr(self.service, "canvas_agent_backend", None)
        self.addCleanup(setattr, self.service, "canvas_agent_backend", previous_backend)

    def prepare(self, method=None, media_ids=None, episode_id=None, prompt=" \n仅补问，不生成媒体。🛍\n "):
        root = str(uuid.uuid4())
        payload = dict(prompt=prompt, media_ids=media_ids or [], episode_id=episode_id)
        if method:
            payload.update(method_id=method["id"], method_version=method["version"], method_sha256=method["sha256"])
        prepared = self.write("create_marketing_canvas", payload, idempotency_key=root)
        return prepared, root

    def body(self, prepared, root, **extra):
        payload = dict(prepare_key=root, canvas_revision=prepared["canvas_revision"], canvas_sha256=prepared["sha256"],
            model_ids=[], mode="manual", execution_settings={})
        payload.update(extra)
        return dict(payload=payload, expected_revision=self.rev, idempotency_key=marketing_start_key(root))

    def post(self, prepared, body):
        response = self.client.post(self.base + "/marketing-canvases/" + prepared["id"] + "/start", headers=self.headers, json=body)
        if response.status_code == 200:
            self.rev = response.json()["revision"]
        return response

    def start_direct(self, prepared, body, actor="test-human", project_id=None):
        return self.service.start_marketing_canvas(project_id or self.p, dict(body["payload"], canvas_id=prepared["id"]),
            actor=actor, expected_revision=body["expected_revision"], idempotency_key=body["idempotency_key"])

    def counts(self):
        from sqlalchemy import func, select
        from vsc.adapters.persistence.postgres import schema as S
        with self.engine.connect() as conn:
            return {table.name: conn.scalar(select(func.count()).select_from(table).where(table.c.project_id == self.p))
                for table in (S.canvas_agent_sessions, S.canvas_agent_turns, S.role_dispatches, S.dispatch_consumptions,
                              S.canvas_agent_refs, S.generation_jobs, S.artifact_decisions)}

    def actual_image(self, name="product"):
        from support.fixtures.media import production_media
        staged = self.service.storage.stage_upload(io.BytesIO(production_media()["png"]), name + ".png")
        return self.write("register_media", dict(staged_upload=staged["staged_upload"], name=name,
            rights="owned", source=dict(kind="test-owned", content="Synthetic marketing image")))["id"]

    def models(self):
        from sqlalchemy import insert
        from vsc.adapters.persistence.postgres import schema as S
        provider, models = "synthetic-" + uuid.uuid4().hex, [str(uuid.uuid4()), str(uuid.uuid4())]
        with self.engine.begin() as conn:
            conn.execute(insert(S.providers).values(id=provider, name="No execution fixture", modality="image",
                base_url="https://example.invalid", auth_ref="none", enabled=True, rate_limit={}))
            for number, model in enumerate(models):
                conn.execute(insert(S.provider_models).values(id=model, provider_id=provider, model_key="synthetic-" + str(number),
                    modality="image", model_version="1", capabilities={}, default_params={}, cost_rule={}, enabled=True))
        return models

    def test_http_all_eight_methods_and_no_method_derive_the_first_turn(self):
        episode = self.hierarchy()["episode"]
        models = self.models()
        with patch.object(self.service, "execute_canvas_agent_turn", side_effect=AssertionError("start must not execute host")):
            for method in [*marketing_methods(), None]:
                with self.subTest(method=method["id"] if method else "general"):
                    prepared, root = self.prepare(method, episode_id=episode)
                    body = self.body(prepared, root, model_ids=models[::-1])
                    before = self.rev
                    response = self.post(prepared, body)
                    self.assertEqual(response.status_code, 200, response.text)
                    result = response.json()
                    self.assertEqual(result["revision"], before + 1)
                    self.assertEqual(result["turn_status_at_commit"], "queued")
                    self.assertFalse(result["provider_submitted"])
                    read = self.client.get(self.base + "/creative-canvas-agent-turns/" + result["turn_id"])
                    self.assertEqual(read.status_code, 200, read.text)
                    turn = read.json()
                    self.assertEqual((turn["project_id"], turn["canvas_id"], turn["episode_id"], turn["session_id"]),
                        (self.p, prepared["id"], episode, result["session_id"]))
                    self.assertEqual(turn["message"], prepared["agent_handoff"]["message"])
                    self.assertEqual(turn["skill_id"], prepared["agent_handoff"]["skill_id"])
                    self.assertEqual(turn["model_ids"], models[::-1])
                    self.assertIsNone(turn["parent_turn_id"])
                    self.assertEqual(turn["attachments"], [])
                    if method:
                        self.assertEqual(next(node for node in turn["referenced_nodes"] if node["id"] == "marketing-method")["text"], method["text"])
                    receipt = self.service.get_operation_receipt(self.p, body["idempotency_key"], actor="test-human")
                    self.assertEqual(receipt["response"], result)
        counts = self.counts()
        for table in ("canvas_agent_sessions", "canvas_agent_turns", "role_dispatches", "dispatch_consumptions"):
            self.assertEqual(counts[table], 9)
        self.assertEqual(counts["generation_jobs"], 0)
        self.assertEqual(counts["artifact_decisions"], 0)

    def test_fifteen_images_seventeen_refs_full_method_and_catalog_upgrade(self):
        import hashlib
        images = [self.actual_image("product-" + str(i)) for i in range(15)]
        methods = marketing_methods()
        method = methods[0]
        method["text"] += "\n固定完整方法正文" * 800
        method["sha256"] = hashlib.sha256(method["text"].encode()).hexdigest()
        with patch("vsc.assets.marketing_studio.marketing_methods", return_value=methods):
            prepared, root = self.prepare(method, images)
        body = self.body(prepared, root)
        with patch("vsc.assets.marketing_studio.marketing_methods", side_effect=AssertionError("start must use pinned method")):
            response = self.post(prepared, body)
        self.assertEqual(response.status_code, 200, response.text)
        turn = self.service.get_canvas_agent_turn(self.p, response.json()["turn_id"])
        self.assertEqual(len(turn["referenced_nodes"]), 17)
        self.assertEqual(turn["attachment_count"], 0)
        self.assertEqual([node["media_id"] for node in turn["referenced_nodes"] if node["type"] == "image"], images)
        fixed_method = next(node for node in turn["referenced_nodes"] if node["id"] == "marketing-method")
        self.assertGreater(len(fixed_method["text"]), 6000)
        self.assertEqual(fixed_method["text"], method["text"])
        self.assertFalse(fixed_method["text_excerpt"])
        media = self.service.get_media(self.p, images[0])
        self.service.storage.resolve(media["locations"][0]["object_key"]).unlink()
        replay = self.post(prepared, body)
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.json(), response.json())

    def test_same_start_concurrent_lost_response_and_changed_intent(self):
        prepared, root = self.prepare()
        models = self.models()
        body = self.body(prepared, root, model_ids=models)
        before = self.rev
        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = [future.result() for future in [pool.submit(self.start_direct, prepared, body), pool.submit(self.start_direct, prepared, body)]]
        self.assertEqual(a, b)
        self.assertEqual(a["revision"], before + 1)
        replay = self.post(prepared, body)
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.json(), a)
        for change in (dict(model_ids=models[::-1]), dict(mode="auto_drafts"), dict(execution_settings={"duration_ms": 5000}),
                       dict(canvas_revision=2), dict(canvas_sha256="0" * 64)):
            with self.subTest(change=change):
                rejected = self.post(prepared, dict(body, payload=dict(body["payload"], **change)))
                self.assertEqual(rejected.status_code, 409, rejected.text)
                self.assertEqual(rejected.json()["error"], "idempotency_conflict")
        wrong_key = self.post(prepared, dict(body, idempotency_key="different-key"))
        self.assertEqual(wrong_key.status_code, 409, wrong_key.text)
        self.assertEqual(self.counts()["canvas_agent_turns"], 1)
        self.assertEqual(self.counts()["canvas_agent_sessions"], 1)
        self.assertEqual(self.counts()["role_dispatches"], 1)

    def test_receipt_committed_after_precheck_miss_wins_over_later_media_failure(self):
        for number, changed in enumerate(("same", "payload", "actor"), 1):
            with self.subTest(changed=changed):
                image = self.actual_image("receipt-race-" + changed)
                prepared, root = self.prepare(media_ids=[image])
                body = self.body(prepared, root)
                follower_body = dict(body, payload=dict(body["payload"], mode="auto_drafts")) if changed == "payload" else body
                follower_actor = "other-actor" if changed == "actor" else "test-human"
                miss, release, media_failure = Event(), Event(), Event()
                follower_thread = {}
                original_receipt, original_verify = self.service.get_operation_receipt, self.service._verify_media

                def receipt(project_id, key, actor=None):
                    result = original_receipt(project_id, key, actor=actor)
                    if get_ident() == follower_thread.get("id") and key == body["idempotency_key"] and not result["found"]:
                        miss.set()
                        if not release.wait(10):
                            raise RuntimeError("timed out waiting for the competing start commit")
                    return result

                def verify(*args, **kwargs):
                    try:
                        return original_verify(*args, **kwargs)
                    except ResourceError:
                        if get_ident() == follower_thread.get("id"):
                            media_failure.set()
                        raise

                def follower():
                    follower_thread["id"] = get_ident()
                    return self.start_direct(prepared, follower_body, actor=follower_actor)

                with patch.object(self.service, "get_operation_receipt", side_effect=receipt), \
                        patch.object(self.service, "_verify_media", side_effect=verify), ThreadPoolExecutor(max_workers=1) as pool:
                    pending = pool.submit(follower)
                    try:
                        self.assertTrue(miss.wait(10), "follower must observe an actual missing PG receipt")
                        winner = self.start_direct(prepared, body)
                        self.rev = winner["revision"]
                        media = self.service.get_media(self.p, image)
                        self.service.storage.resolve(media["locations"][0]["object_key"]).unlink()
                    finally:
                        release.set()
                    if changed == "same":
                        self.assertEqual(pending.result(timeout=10), winner)
                    else:
                        with self.assertRaises(ResourceError) as conflict:
                            pending.result(timeout=10)
                        self.assertEqual(conflict.exception.code, "idempotency_conflict")
                self.assertTrue(media_failure.is_set(), "the follower must encounter the real missing bytes")
                self.assertEqual(original_receipt(self.p, body["idempotency_key"], actor="test-human")["response"], winner)
                self.assertEqual(self.service.get_project(self.p)["revision"], body["expected_revision"] + 1)
                counts = self.counts()
                for table in ("canvas_agent_sessions", "canvas_agent_turns", "role_dispatches", "dispatch_consumptions"):
                    self.assertEqual(counts[table], number)
        # With no competing S, the same arbitration must retain the preflight
        # failure and never create a queued turn, session, dispatch or receipt.
        image = self.actual_image("uncommitted-bad-media")
        prepared, root = self.prepare(media_ids=[image])
        body = self.body(prepared, root)
        media = self.service.get_media(self.p, image)
        self.service.storage.resolve(media["locations"][0]["object_key"]).unlink()
        with self.assertRaises(ResourceError) as missing_media:
            self.start_direct(prepared, body)
        self.assertEqual(missing_media.exception.code, "media_unavailable")
        self.assertFalse(self.service.get_operation_receipt(self.p, body["idempotency_key"], actor="test-human")["found"])
        self.assertEqual(self.service.get_project(self.p)["revision"], body["expected_revision"])
        self.assertEqual(self.counts()["canvas_agent_turns"], 3)

    def test_invalid_first_start_scope_actor_version_receipt_and_body(self):
        prepared, root = self.prepare()
        body = self.body(prepared, root)
        for spoof in ("message", "skill_id", "node_ids", "episode_id", "session_id", "parent_turn_id", "actor", "canvas_id"):
            with self.subTest(spoof=spoof):
                response = self.post(prepared, dict(body, payload=dict(body["payload"], **{spoof: "spoof"})))
                self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.post(prepared, dict(body, actor="spoof")).status_code, 422)
        no_csrf = self.client.post(self.base + "/marketing-canvases/" + prepared["id"] + "/start", json=body)
        self.assertEqual(no_csrf.status_code, 403)
        with self.assertRaises(ResourceError) as actor:
            self.start_direct(prepared, body, actor="different-actor")
        self.assertEqual(actor.exception.code, "marketing_prepare_receipt_missing")
        other = self.service.create_project(dict(name="foreign start target"), actor="test-human")
        with self.assertRaises(ResourceError):
            self.start_direct(prepared, dict(body, expected_revision=0), project_id=other["id"])
        wrong_root = str(uuid.uuid4())
        missing = self.post(prepared, dict(body, payload=dict(body["payload"], prepare_key=wrong_root), idempotency_key=marketing_start_key(wrong_root)))
        self.assertEqual(missing.status_code, 409, missing.text)
        bad_hash = self.post(prepared, dict(body, payload=dict(body["payload"], canvas_sha256="0" * 64)))
        self.assertEqual(bad_hash.status_code, 409, bad_hash.text)
        current = self.service.get_creative_canvas(self.p, prepared["id"])
        document = current["document"]
        document["nodes"][0]["text"] = "later edit"
        self.write("save_creative_canvas", dict(canvas_id=prepared["id"], canvas_revision=1, document=document))
        stale = self.post(prepared, body)
        self.assertEqual(stale.status_code, 409, stale.text)
        latest_revision_old_canvas = self.post(prepared, dict(body, expected_revision=self.rev))
        self.assertEqual(latest_revision_old_canvas.status_code, 409, latest_revision_old_canvas.text)
        self.assertEqual(latest_revision_old_canvas.json()["error"], "canvas_revision_conflict")
        self.assertEqual(self.counts()["canvas_agent_turns"], 0)

    def test_atomic_failure_rolls_back_session_turn_dispatch_and_receipt(self):
        prepared, root = self.prepare()
        body = self.body(prepared, root)
        original = self.store.create_canvas_agent_turn
        def fail_after_insert(*args, **kw):
            original(*args, **kw)
            raise RuntimeError("synthetic failure before outer commit")
        with patch.object(self.store, "create_canvas_agent_turn", side_effect=fail_after_insert):
            with self.assertRaises(RuntimeError):
                self.start_direct(prepared, body)
        self.assertEqual(self.service.get_project(self.p)["revision"], body["expected_revision"])
        for table in ("canvas_agent_sessions", "canvas_agent_turns", "role_dispatches", "dispatch_consumptions"):
            self.assertEqual(self.counts()[table], 0)
        self.assertFalse(self.service.get_operation_receipt(self.p, body["idempotency_key"], actor="test-human")["found"])
        response = self.post(prepared, body)
        self.assertEqual(response.status_code, 200, response.text)

    def test_tampered_prepare_bytes_document_and_recycled_material_reject_before_turn(self):
        from sqlalchemy import insert, update
        from sqlalchemy.exc import IntegrityError
        from vsc.adapters.persistence.postgres import schema as S
        image = self.actual_image()
        prepared, root = self.prepare(media_ids=[image])
        body = self.body(prepared, root)
        media = self.service.get_media(self.p, image)
        location = self.service.storage.resolve(media["locations"][0]["object_key"])
        original = location.read_bytes()
        location.write_bytes(b"tampered bytes")
        failed = self.post(prepared, body)
        self.assertEqual(failed.status_code, 422, failed.text)
        location.write_bytes(original)
        # A deliberately constructed historical lifecycle state also checks the
        # transaction guard, even though normal UI recycling protects fixed refs.
        with self.engine.begin() as conn:
            project = self.store._project(conn, self.p, lock=True)
            decision = str(uuid.uuid4())
            conn.execute(insert(S.media_lifecycle_decisions).values(project_id=self.p, id=decision, media_id=image,
                outcome="deprecate", **self.store._decision(conn, project, "test-human", "synthetic recycled-state fixture")))
            conn.execute(insert(S.media_recycle_actions).values(project_id=self.p, id=str(uuid.uuid4()), media_id=image, decision_id=decision))
        failed = self.post(prepared, body)
        self.assertEqual(failed.status_code, 409, failed.text)
        self.assertEqual(failed.json()["error"], "marketing_media_recycled")
        other, _ = self.prepare(marketing_methods()[0])
        with self.assertRaises(IntegrityError), self.engine.begin() as conn:
            conn.execute(update(S.creative_canvas_nodes).where(S.creative_canvas_nodes.c.project_id == self.p,
                S.creative_canvas_nodes.c.version_id == other["version_id"]).values(content="tampered fixed document"))
        # A caller can create ordinary canvas data with copied marketing markers.
        # Those markers still cannot validate a method whose fixed text changed.
        original = self.service.get_creative_canvas(self.p, other["id"])
        document = original["document"]
        document["nodes"][1]["text"] = "forged method with old SHA"
        forged_root = str(uuid.uuid4())
        forged = self.write("create_creative_canvas", dict(title=other["title"], episode_id=None, document=document), idempotency_key=forged_root)
        failed = self.post(forged, self.body(forged, forged_root))
        self.assertEqual(failed.status_code, 409, failed.text)
        self.assertEqual(failed.json()["error"], "marketing_preparation_mismatch")
        self.assertEqual(self.counts()["canvas_agent_turns"], 0)

    def test_bounded_auto_scope_is_fixed_and_historical_start_survives_expiry(self):
        prepared, root = self.prepare()
        models = self.models()
        policy = dict(version="bounded-v1", first_draft_due_at="2099-01-01T00:00:00Z", stop_submitting_at="2099-01-01T01:00:00Z",
            max_attempts_per_purpose=1, max_repair_rounds=0)
        automatic = dict(max_jobs=2, max_images=2, max_video_ms=0, max_credits=10, stop_submitting_at=policy["stop_submitting_at"])
        settings = dict(duration_ms=5000, execution_policy=policy, auto_media=automatic)
        for changed in (dict(max_credits=None), dict(max_credits=-1), dict(stop_submitting_at="2099-01-01T02:00:00Z"),
                        dict(stop_submitting_at="2000-01-01T00:00:00Z"), dict(stop_submitting_at="2099-01-01T01:00:00")):
            with self.subTest(changed=changed):
                invalid = dict(settings, auto_media=dict(automatic, **changed))
                rejected = self.post(prepared, self.body(prepared, root, model_ids=models, mode="auto_drafts", execution_settings=invalid))
                self.assertEqual(rejected.status_code, 422, rejected.text)
        body = self.body(prepared, root, model_ids=models, mode="auto_drafts", execution_settings=settings)
        response = self.post(prepared, body)
        self.assertEqual(response.status_code, 200, response.text)
        saved = response.json()
        turn = self.service.get_canvas_agent_turn(self.p, saved["turn_id"])
        self.assertEqual(turn["execution_settings"], settings)
        self.assertEqual(turn["mode"], "auto_drafts")
        with patch("vsc.production.canvas_agent.validate_auto_media", side_effect=AssertionError("old receipt must not revalidate expiry")):
            replay = self.post(prepared, body)
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.json(), saved)
        changed = self.post(prepared, dict(body, payload=dict(body["payload"], execution_settings=dict(settings,
            auto_media=dict(automatic, max_credits=20)))))
        self.assertEqual(changed.status_code, 409, changed.text)
        self.assertEqual(self.counts()["generation_jobs"], 0)

    def test_original_execute_runs_only_once_and_unknown_never_restarts_host(self):
        for unknown in (False, True):
            with self.subTest(unknown=unknown):
                prepared, root = self.prepare()
                body = self.body(prepared, root)
                backend = PlanBackend(unknown)
                self.service.canvas_agent_backend = backend
                started = self.post(prepared, body)
                self.assertEqual(started.status_code, 200, started.text)
                self.assertEqual(backend.calls, 0)
                turn = started.json()["turn_id"]
                result = self.service.execute_canvas_agent_turn(self.p, turn)
                self.assertEqual(result["status"], "submission_unknown" if unknown else "needs_input")
                again = self.service.execute_canvas_agent_turn(self.p, turn)
                self.assertEqual(again["status"], result["status"])
                self.assertEqual(backend.calls, 1)
                self.assertEqual(self.post(prepared, body).json(), started.json())
                self.rev = self.service.get_project(self.p)["revision"]

    def test_read_only_and_share_cannot_start_and_recycled_scope_cannot_create_turn(self):
        from vsc.assets.access_control import Principal, set_principal, reset_principal
        prepared, root = self.prepare()
        body = self.body(prepared, root)
        token = set_principal(Principal(local_read=True))
        try:
            with self.assertRaises(ResourceError) as denied:
                self.start_direct(prepared, body)
            self.assertEqual(denied.exception.status_code, 403)
        finally:
            reset_principal(token)
        owner = self.service.ensure_local_access("test-human")
        owner_token = set_principal(Principal(**owner))
        try:
            preview = self.service.access_migration_preview(self.p, owner["workspace_id"])
            self.service.access_command("assign-project", dict(project_id=self.p, workspace_id=owner["workspace_id"], preview_sha256=preview["sha256"]),
                actor="test-human", expected_revision=self.service.access_snapshot()["access_revision"], idempotency_key=uuid.uuid4().hex)
            secret = secrets.token_urlsafe(32)
            self.service.access_command("share", dict(project_id=self.p, canvas_version_id=prepared["version_id"], mode="edit",
                secret=secret, expires_at=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat()),
                actor="test-human", expected_revision=self.service.access_snapshot()["access_revision"], idempotency_key=uuid.uuid4().hex)
            share = self.service.authenticate_access(secret)
            share_token = set_principal(Principal(**share))
            try:
                self.service.authorize_access(self.p, "edit", target_type="canvas", target_id=prepared["id"])
                with self.assertRaises(ResourceError) as denied:
                    self.start_direct(prepared, body, actor=share["actor"])
                self.assertEqual(denied.exception.status_code, 403)
            finally:
                reset_principal(share_token)
        finally:
            reset_principal(owner_token)
        episode = self.hierarchy()["episode"]
        scoped, scoped_root = self.prepare(episode_id=episode)
        self.write("management_command", dict(operation="trash", target_type="object", target_id=episode, reason="synthetic recycled episode"))
        rejected = self.post(scoped, self.body(scoped, scoped_root))
        self.assertEqual(rejected.status_code, 409, rejected.text)
        self.assertEqual(rejected.json()["error"], "object_recycled")
        self.assertEqual(self.counts()["canvas_agent_turns"], 0)
