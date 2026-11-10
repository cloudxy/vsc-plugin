"""Marketing preparation → original canvas/receipt → real media and Agent refs."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import uuid
from unittest.mock import Mock, patch

from support.fixtures.resource_store import ResourceStoreFixture, HAS_DB_DEPS, TEST_URL
from vsc.assets.marketing_studio import marketing_methods, _request
from vsc.assets.resource_service import ResourceService, ResourceError


PINS = {
    "short-drama-commerce": "23606d3d65f959ca25425c8dba14a2d7ee36b35f626a83c4856fcca535ebf18b",
    "product-poster": "50ea066fa93e78bf5300385e8787ffc6567e30c33a864849aad254dc4b4745c7",
    "viral-video-clone": "6fc2eb454473ebff1bb53948f4bc4b016c55116116d8b6cf3c87a31b9a4be4b8",
    "commercial-tvc": "59fcacd7c53da78c8fce839b4a6a03d60e66e2a23eddf5d2067c6820cf7e92f0",
    "ugc-commerce": "3add0921de6858c9bcadda902d0950eba0451ba0c01761744d764722ad1d2615",
    "viral-creative-variation": "287f7e1529ed5b90bd1f2e22ae2ff7dad0e4904375f6d925a6df5ce63683840e",
    "product-visual-materials": "d973503a3f5a481c601d60f758e501cadb85c99a63489386761439ce8b90fba7",
    "video-localization": "0232f091b599b11a09a670f5dc29f69577e9d3f27b26144d7dcabc045b043c0d",
}


class MarketingContractTests(unittest.TestCase):
    """No database/HTTP/provider calls; executable while database CI is busy."""
    def test_eight_independent_fixed_methods(self):
        methods = marketing_methods()
        self.assertEqual({item["id"] for item in methods}, set(PINS))
        self.assertEqual(len({item["text"] for item in methods}), 8)
        for item in methods:
            with self.subTest(method=item["id"]):
                self.assertEqual(item["version"], "1.0")
                self.assertEqual(item["sha256"], PINS[item["id"]])
                self.assertEqual(hashlib.sha256(item["text"].encode()).hexdigest(), PINS[item["id"]])
                for section in ("目标：", "输入：", "动作：", "产出：", "不得声称已观看"):
                    self.assertIn(section, item["text"])
                self.assertIn(item["skill_id"], {"image-generation", "video-generation"})
        methods[0]["actions"].clear()
        self.assertTrue(marketing_methods()[0]["actions"])

    def test_unicode_raw_prompt_and_invalid_payloads(self):
        raw = " \n" + "🛍" * 1996 + "\n "
        self.assertEqual(len(raw), 2000)
        self.assertEqual(_request({"prompt": raw})[0]["prompt"], raw)
        method = marketing_methods()[0]
        good = dict(prompt="商品事实待补问", method_id=method["id"], method_version=method["version"], method_sha256=method["sha256"])
        self.assertEqual(_request(good)[1]["id"], method["id"])
        invalid = [dict(prompt=""), dict(prompt=" \n "), dict(prompt="🛍" * 2001), dict(prompt=15),
            dict(prompt="需求", media_ids=["x"] * 16), dict(prompt="需求", media_ids=["x", "x"]),
            dict(prompt="需求", media_ids="x"), dict(prompt="需求", media_ids=[{}]),
            dict(prompt="需求", method_id=[]), dict(prompt="需求", method_id="unknown"),
            dict(good, method_sha256="0" * 64), dict(good, method_version="2.0"),
            dict(prompt="需求", method_sha256="0" * 64), dict(prompt="需求", actor="spoof"),
            dict(prompt="需求", episode_id=[]), dict(prompt="需求", model_ids=["ignored"])]
        for payload in invalid:
            with self.subTest(payload=payload):
                with self.assertRaises(ResourceError):
                    _request(payload)

    def test_original_transaction_and_historical_receipt_delegation(self):
        store = Mock()
        store.get_operation_receipt.return_value = dict(found=False, response=None)
        store.create_creative_canvas.return_value = dict(id="canvas", canvas_revision=1, revision=4)
        service = ResourceService(store)
        prompt = "  原始商品需求\n"
        kw = dict(actor="test-human", expected_revision=3, idempotency_key="request-one")
        first = service.create_marketing_canvas("project", dict(prompt=prompt), **kw)
        sent = store.create_creative_canvas.call_args.args[1]
        self.assertEqual(sent["document"]["nodes"][0]["text"], prompt)
        self.assertEqual(first["agent_handoff"], dict(skill_id="vsc-assets", node_ids=["marketing-brief"], message=prompt))
        store.get_operation_receipt.return_value = dict(found=True, response=first)
        store.get_creative_canvas.return_value = dict(title=sent["title"], episode_id=None, document=deepcopy(sent["document"]))
        self.assertEqual(first, service.create_marketing_canvas("project", dict(prompt=prompt), **kw))
        store.get_creative_canvas.assert_called_once_with("project", "canvas", 1)
        self.assertEqual(store.create_creative_canvas.call_args.kwargs, kw)
        with self.assertRaises(ResourceError):
            service.create_marketing_canvas("project", dict(prompt="不同需求"), **kw)
        self.assertEqual(store.create_creative_canvas.call_count, 2)


@unittest.skipUnless(TEST_URL and HAS_DB_DEPS and shutil.which("ffmpeg"), "requires isolated PostgreSQL, web dependencies and ffmpeg")
class MarketingStudioHTTPTests(ResourceStoreFixture, unittest.TestCase):
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
        app = create_app(dict(projects_root=self.directory.name + "/projects", media_root=self.directory.name,
            allowed_hosts=["testserver"], allowed_origins=["http://testserver"], human_identity="test-human",
            access_token="test-token", background_enabled=False), service=self.service)
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        session = self.client.post("/api/v1/session", headers={"Origin": "http://testserver"}, json={"token": "test-token"})
        self.headers = {"Origin": "http://testserver", "X-CSRF-Token": session.json()["csrf_token"]}
        self.base = "/api/v1/projects/" + self.p

    def command(self, path, payload, expected=None, key=None):
        response = self.client.post(self.base + path, headers=self.headers, json=dict(payload=payload,
            expected_revision=self.rev if expected is None else expected, idempotency_key=key or uuid.uuid4().hex))
        if response.status_code == 200:
            self.rev = response.json()["revision"]
        return response

    def actual_media(self, kind="png"):
        from support.fixtures.media import production_media
        content = production_media()[kind]
        upload = self.client.post(self.base + "/uploads", content=content,
            headers=dict(self.headers, **{"X-Filename": "product." + kind}))
        self.assertEqual(upload.status_code, 200, upload.text)
        media = self.command("/media", dict(staged_upload=upload.json()["staged_upload"], name="商品." + kind,
            rights="owned", source=dict(kind="test-owned", content="Synthetic marketing media")))
        self.assertEqual(media.status_code, 200, media.text)
        return media.json()["id"], content

    def test_case_http_catalog_projection_prepare_and_recovery_without_current_catalog(self):
        from urllib.parse import quote
        from vsc.assets.marketing_cases import case_spec_from_params
        pages = []
        catalog_sha = None
        for number in range(1, 7):
            response = self.client.get("/api/v1/marketing-cases", params=dict(page=number, **({"catalog_sha256": catalog_sha} if catalog_sha else {})))
            self.assertEqual(response.status_code, 200, response.text)
            page = response.json()
            catalog_sha = page["catalog_sha256"]
            pages.append(page)
        self.assertEqual([len(page["items"]) for page in pages], [20, 20, 20, 20, 20, 14])
        cases = [case for page in pages for group in page["items"] for case in group["examples"]]
        selected, alternate = cases[:2]
        ref = lambda case: {key: case[key] for key in ("id", "version", "sha256")}
        observed = next(case for case in cases if case["template_key"] == "approved_7135edbbae7c4181")
        detail = self.client.get("/api/v1/marketing-cases/" + quote(observed["id"], safe=""), params={k: observed[k] for k in ("version", "sha256")})
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()["case"], observed)
        self.assertTrue(detail.json()["detail_coverage"]["observed_source_detail"])
        Path("/private/tmp/marketing-cases-http-fixture.json").write_text(json.dumps(dict(pages=pages, detail=detail.json(),
            case=selected, case_ref=ref(selected), second_case=alternate, second_case_ref=ref(alternate), catalog_sha256=catalog_sha), ensure_ascii=False, indent=2) + "\n")
        for query, status in ((dict(catalog_sha256="0" * 64), 409), (dict(category_name="unknown"), 422), (dict(page_size=21), 422)):
            with self.subTest(query=query):
                self.assertEqual(self.client.get("/api/v1/marketing-cases", params=query).status_code, status)
        unknown = self.client.get("/api/v1/marketing-cases/skyproduction:unknown", params=dict(version=1, sha256="0" * 64))
        self.assertEqual(unknown.status_code, 404, unknown.text)
        image, _ = self.actual_media()
        method = marketing_methods()[1]
        raw = " \n原商品海报需求🛍\n "
        payload = dict(prompt=raw, case_ref=ref(selected), method_id=method["id"], method_version=method["version"],
            method_sha256=method["sha256"], media_ids=[image])
        before = self.rev
        prepared = self.command("/marketing-canvases", payload, key="selected-case")
        self.assertEqual(prepared.status_code, 200, prepared.text)
        original = prepared.json()
        canvas = self.client.get(self.base + "/creative-canvases/" + original["canvas_id"]).json()
        self.assertEqual(len(canvas["document"]["nodes"]), 3)
        brief, fixed_method = canvas["document"]["nodes"][:2]
        self.assertEqual(brief["text"], raw)
        self.assertEqual(fixed_method["text"], method["text"])
        self.assertEqual(len(brief["params"]), 21)
        self.assertEqual(case_spec_from_params(brief["params"]), selected)
        from vsc.assets.marketing_studio import marketing_start_key
        start_input = dict(prepare_key="selected-case", canvas_revision=original["canvas_revision"], canvas_sha256=original["sha256"],
            model_ids=[], mode="manual", execution_settings={})
        started = self.command("/marketing-canvases/" + original["canvas_id"] + "/start", start_input, key=marketing_start_key("selected-case"))
        self.assertEqual(started.status_code, 200, started.text)
        start_result = started.json()
        with patch("vsc.assets.marketing_cases.load_catalog", side_effect=AssertionError("historical R/S/T must be self contained")):
            replay = self.command("/marketing-canvases", payload, expected=before, key="selected-case")
            self.assertEqual(replay.status_code, 200, replay.text)
            self.assertEqual(replay.json(), original)
            for changed in (dict(payload, case_ref=ref(alternate)), dict(payload, case_ref=None),
                            {k: v for k, v in payload.items() if k != "case_ref"}):
                with self.subTest(changed=changed):
                    conflict = self.command("/marketing-canvases", changed, expected=before, key="selected-case")
                    self.assertEqual(conflict.status_code, 409, conflict.text)
                    self.assertEqual(conflict.json()["error"], "idempotency_conflict")
            replay_start = self.command("/marketing-canvases/" + original["canvas_id"] + "/start", start_input,
                expected=start_result["revision"] - 1, key=marketing_start_key("selected-case"))
            self.assertEqual(replay_start.json(), start_result)
            turn = self.client.get(self.base + "/creative-canvas-agent-turns/" + start_result["turn_id"]).json()
            self.assertEqual(turn["message"], raw)
            self.assertEqual(case_spec_from_params(turn["referenced_nodes"][0]["params"]), selected)
        self.rev = self.service.get_project(self.p)["revision"]
        for bad in (dict(payload, case_ref=dict(ref(selected), version=2)), dict(payload, case_ref=selected), dict(payload, prompt="")):
            with self.subTest(bad=bad):
                rejected = self.command("/marketing-canvases", bad)
                self.assertIn(rejected.status_code, {409, 422}, rejected.text)

    def test_real_legacy_030_receipt_accepts_omitted_or_null_case_without_changing_document(self):
        # Literal 0.47.30 golden, captured before case support; deliberately
        # register via the original canvas command, never new prepare helpers.
        golden = {"title": "营销工作室 · 通用需求", "episode_id": None, "document": {"edges": [], "nodes": [
            {"group": "", "id": "marketing-brief", "job_id": None, "media_id": None,
             "params": {"marketing_request_sha256": "5aed26603b8d084949126662607430db194af4f10fea51ee336e7eb101632b62",
                        "marketing_role": "brief", "skill_id": "vsc-assets"},
             "text": "  旧版原始需求🛍\n", "title": "营销原始需求", "type": "text", "x": 80.0, "y": 80.0}],
            "viewport": {"x": 0.0, "y": 0.0, "zoom": 1.0}}}
        old = self.write("create_creative_canvas", golden, idempotency_key="legacy-before-case")
        expected = dict(old, canvas_id=old["id"], episode_id=None, provider_submitted=False, brief_node_id="marketing-brief",
            method_node_id=None, material_node_ids=[], agent_handoff=dict(skill_id="vsc-assets", node_ids=["marketing-brief"], message="  旧版原始需求🛍\n"))
        with patch("vsc.assets.marketing_cases.load_catalog", side_effect=AssertionError("legacy must not read current catalog")):
            for extra in ({}, {"case_ref": None}):
                with self.subTest(extra=extra):
                    restored = self.command("/marketing-canvases", dict(prompt="  旧版原始需求🛍\n", **extra), expected=0, key="legacy-before-case")
                    self.assertEqual(restored.status_code, 200, restored.text)
                    self.assertEqual(restored.json(), expected)
        document = self.service.get_creative_canvas(self.p, old["id"])["document"]
        self.assertEqual(document, golden["document"])
        from vsc.assets.marketing_cases import list_cases
        case = list_cases()["items"][0]["examples"][0]
        conflict = self.command("/marketing-canvases", dict(prompt="  旧版原始需求🛍\n", case_ref={k: case[k] for k in ("id", "version", "sha256")}),
            expected=0, key="legacy-before-case")
        self.assertEqual(conflict.status_code, 409, conflict.text)
        self.assertEqual(conflict.json()["error"], "idempotency_conflict")

    def test_case_pg_turn_reaches_original_prompt_file_with_fifteen_image_refs(self):
        import base64
        import io
        import os
        from PIL import Image
        from sqlalchemy import func, select
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.assets.marketing_cases import case_spec_from_params
        from vsc.assets.marketing_studio import marketing_start_key
        from vsc.production.canvas_agent import GrokBuildCanvasAgent

        # Fifteen registrations deliberately contain five distinct byte hashes.
        # Fixed refs remain fifteen; host image blocks must honor byte aliases.
        media_ids, shas = [], {}
        for index in range(15):
            data = io.BytesIO()
            color = index % 5
            Image.new("RGB", (12, 9), (color * 31, color * 19, color * 13)).save(data, format="PNG")
            raw_image = data.getvalue()
            uploaded = self.client.post(self.base + "/uploads", content=raw_image,
                headers=dict(self.headers, **{"X-Filename": "integrated-" + str(index) + ".png"}))
            self.assertEqual(uploaded.status_code, 200, uploaded.text)
            registered = self.command("/media", dict(staged_upload=uploaded.json()["staged_upload"], name="合成商品图" + str(index),
                rights="owned", source=dict(kind="test-owned", content="Synthetic integrated planning bytes")))
            self.assertEqual(registered.status_code, 200, registered.text)
            identifier = registered.json()["id"]
            media_ids.append(identifier)
            shas[identifier] = hashlib.sha256(raw_image).hexdigest()
        case = self.client.get("/api/v1/marketing-cases").json()["items"][0]["examples"][0]
        method = marketing_methods()[1]
        raw_prompt = " \n真实PG原始首句🛍；只补问，不执行媒体。\r\n "
        root = str(uuid.uuid4())
        request = dict(prompt=raw_prompt, case_ref={k: case[k] for k in ("id", "version", "sha256")}, media_ids=media_ids,
            method_id=method["id"], method_version=method["version"], method_sha256=method["sha256"])
        prepared = self.command("/marketing-canvases", request, key=root)
        self.assertEqual(prepared.status_code, 200, prepared.text)
        fixed = prepared.json()
        started = self.command("/marketing-canvases/" + fixed["canvas_id"] + "/start", dict(prepare_key=root,
            canvas_revision=fixed["canvas_revision"], canvas_sha256=fixed["sha256"], model_ids=[], mode="manual", execution_settings={}),
            key=marketing_start_key(root))
        self.assertEqual(started.status_code, 200, started.text)
        receipt = started.json()
        path = self.base + "/creative-canvas-agent-turns/" + receipt["turn_id"]
        before = self.client.get(path).json()
        self.assertEqual(before["status"], "queued")
        self.assertEqual(len(before["referenced_nodes"]), 17)
        self.assertEqual(before["attachments"], [])
        self.assertEqual(case_spec_from_params(before["referenced_nodes"][0]["params"]), case)
        captures, claims = [], []
        original_claim = self.store.claim_canvas_agent_turn

        def claim(*args, **kwargs):
            result = original_claim(*args, **kwargs)
            claims.append(result["claimed"])
            return result

        class PromptCaptureProcess:
            """OS pipes exercise the real bounded runner without spawning a process."""
            returncode = 0
            pid = None

            def __init__(self, command, **kwargs):
                prompt = Path(command[command.index("--prompt-file") + 1])
                text = prompt.read_text(encoding="utf-8")
                blocks = json.loads(text)
                first = blocks[0]["text"]
                payload = json.loads(first[first.index('{"role_context"'):])
                captures.append(dict(command=list(command), blocks=blocks, payload=payload,
                    prompt_file_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest()))
                plan = dict(message="离线集成补问", questions=["请补充商品事实。"],
                    actions=[dict(kind="none", title="", text="", source_node_id="")])
                self.stdout = self.pipe(json.dumps(plan, ensure_ascii=False).encode("utf-8"))
                self.stderr = self.pipe(b"")

            @staticmethod
            def pipe(data):
                read_fd, write_fd = os.pipe()
                try:
                    if data:
                        os.write(write_fd, data)
                finally:
                    os.close(write_fd)
                return os.fdopen(read_fd, "rb", buffering=0)

            def wait(self, timeout=None):
                return self.returncode

            def poll(self):
                return self.returncode

        previous = getattr(self.service, "canvas_agent_backend", None)
        self.addCleanup(setattr, self.service, "canvas_agent_backend", previous)
        backend = GrokBuildCanvasAgent(executable="synthetic-no-cli")
        self.service.canvas_agent_backend = backend
        # generate(), role_planner, prompt-file creation and _run_bounded stay
        # real. Only process construction is replaced; no CLI can be launched.
        with patch.object(backend, "available", return_value=True), \
                patch("vsc.assets.script_ai.subprocess.Popen", side_effect=PromptCaptureProcess) as process, \
                patch("vsc.assets.script_ai.os.killpg", side_effect=AssertionError("no real process group exists")) as kill, \
                patch.object(self.store, "claim_canvas_agent_turn", side_effect=claim):
            executed = self.client.post(path + "/execute", headers=self.headers)
            self.assertEqual(executed.status_code, 200, executed.text)
            self.assertEqual(executed.json()["status"], "needs_input", executed.text)
            repeated = self.client.post(path + "/execute", headers=self.headers)
            self.assertEqual(repeated.status_code, 200, repeated.text)
            self.assertEqual(repeated.json()["id"], receipt["turn_id"])
            self.assertEqual(repeated.json()["status"], "needs_input")
            reread = self.client.get(path)
            self.assertEqual(reread.status_code, 200, reread.text)
            self.assertEqual(reread.json()["id"], receipt["turn_id"])
            self.assertEqual(process.call_count, 1)
            kill.assert_not_called()
        self.assertEqual(claims, [True, False])
        self.assertEqual(len(captures), 1)
        capture = captures[0]
        payload, blocks = capture["payload"], capture["blocks"]
        source = payload["input"]
        self.assertEqual(payload["role_context"]["project"]["project_id"], self.p)
        self.assertEqual(payload["role_context"]["dispatch"]["id"], receipt["dispatch_id"])
        self.assertEqual(source["id"], receipt["turn_id"])
        self.assertEqual(source["message"], raw_prompt)
        self.assertEqual(source["marketing_case"], case)
        self.assertEqual(len(source["marketing_case"]), 18)
        self.assertEqual(source["referenced_nodes"], before["referenced_nodes"])
        self.assertEqual(source["referenced_nodes"][0]["text"], raw_prompt)
        self.assertEqual(source["referenced_nodes"][1]["text"], method["text"])
        self.assertEqual(source["referenced_nodes"][1]["params"]["method_sha256"], method["sha256"])
        self.assertEqual(len(source["referenced_nodes"]), 17)
        self.assertEqual(len(source["reference_basis"]), 15)
        self.assertEqual({ref["media_id"]: ref["sha256"] for ref in source["reference_basis"]}, shas)
        self.assertEqual(source["attachments"], [])
        self.assertIn("外部目录元数据", source["case_basis"])
        self.assertIn("私有方法未知", source["case_basis"])
        self.assertIn("未观看", source["case_basis"])
        images = [block for block in blocks if block["type"] == "image"]
        self.assertEqual(len(set(shas.values())), 5)
        self.assertEqual(len(images), len(set(shas.values())))
        for block in images:
            with Image.open(io.BytesIO(base64.b64decode(block["data"]))) as image:
                image.load()
                self.assertEqual(image.format, "JPEG")
        self.assertNotIn(case["video_url"], json.dumps(images))
        self.assertNotIn(case["cover_url"], json.dumps(images))
        command = capture["command"]
        self.assertEqual(command[command.index("--tools") + 1], "")
        self.assertIn("--no-subagents", command)
        self.assertIn("--disable-web-search", command)
        with self.engine.connect() as conn:
            for table, count in ((S.canvas_agent_turns, 1), (S.canvas_agent_sessions, 1), (S.role_dispatches, 1),
                                 (S.dispatch_consumptions, 1), (S.dispatch_returns, 1), (S.generation_jobs, 0), (S.artifact_decisions, 0)):
                self.assertEqual(conn.scalar(select(func.count()).select_from(table).where(table.c.project_id == self.p)), count)
        capture["checks"] = dict(project_id=self.p, canvas_id=fixed["canvas_id"], turn_id=receipt["turn_id"],
            claim_flags=claims, registered_images=15, fixed_refs=17, distinct_image_sha256=len(set(shas.values())),
            image_blocks=len(images), runner_calls=1, media_jobs=0, repeated_execute_and_get_same_turn=True)
        Path("/private/tmp/marketing-cases-integrated-pg-capture-" + receipt["turn_id"] + ".json").write_text(
            json.dumps(capture, ensure_ascii=False, indent=2) + "\n")

    def test_all_eight_methods_real_media_readback_and_original_agent_material(self):
        from sqlalchemy import func, select
        from vsc.adapters.persistence.postgres import schema as S
        episode = self.hierarchy()["episode"]
        image, image_bytes = self.actual_media()
        video, video_bytes = self.actual_media("mp4")
        options = self.client.get(self.base + "/marketing-options")
        self.assertEqual(options.status_code, 200, options.text)
        self.assertEqual({m["id"]: m["sha256"] for m in options.json()["methods"]}, PINS)
        self.assertEqual([row["id"] for row in options.json()["episodes"]], [episode])
        self.assertEqual(options.json()["models"], options.json()["canvas_agent_options"]["models"])
        self.assertFalse(options.json()["provider_submit"])
        for index, method in enumerate(options.json()["methods"]):
            with self.subTest(method=method["id"]):
                raw = " \n仅使用已确认商品事实；缺项请补问。🛍\n "
                request = dict(prompt=raw, episode_id=episode.upper(), method_id=method["id"], method_version=method["version"],
                    method_sha256=method["sha256"], media_ids=[image.upper(), video.upper()])
                saved = self.command("/marketing-canvases", request)
                self.assertEqual(saved.status_code, 200, saved.text)
                result = saved.json()
                path = "/creative-canvases/" + result["canvas_id"]
                read = self.client.get(self.base + path)
                self.assertEqual(read.status_code, 200, read.text)
                nodes = {node["id"]: node for node in read.json()["document"]["nodes"]}
                self.assertEqual(nodes["marketing-brief"]["text"], raw)
                self.assertEqual(nodes["marketing-method"]["text"], method["text"])
                self.assertEqual(nodes["marketing-method"]["params"]["method_sha256"], method["sha256"])
                materials = [nodes[key] for key in result["material_node_ids"]]
                self.assertEqual([(node["type"], node["media_id"]) for node in materials], [("image", image), ("video", video)])
                for node, content in zip(materials, [image_bytes, video_bytes]):
                    self.assertEqual(self.client.get(node["preview_url"]).content, content)
                    self.assertEqual(node["params"]["source_sha256"], hashlib.sha256(content).hexdigest())
                with self.engine.connect() as conn:
                    self.assertEqual(conn.scalar(select(func.count()).select_from(S.canvas_agent_turns).where(S.canvas_agent_turns.c.project_id == self.p)), index)
                # Explicitly submit only an original queued Agent turn. No host
                # execution or provider is invoked; fixed references are read back.
                handoff = result["agent_handoff"]
                turn = self.command(path + "/agent-turns", dict(handoff, canvas_revision=result["canvas_revision"], mode="manual"))
                self.assertEqual(turn.status_code, 200, turn.text)
                fixed = self.client.get(self.base + "/creative-canvas-agent-turns/" + turn.json()["id"]).json()
                self.assertEqual(fixed["message"], raw)
                refs = {node["id"]: node for node in fixed["referenced_nodes"]}
                self.assertEqual(refs["marketing-method"]["text"], method["text"])
                self.assertEqual(set(refs), set(handoff["node_ids"]))
                self.assertFalse(fixed["provider_submitted"])
        with self.engine.connect() as conn:
            for table in (S.generation_jobs, S.artifact_decisions):
                self.assertEqual(conn.scalar(select(func.count()).select_from(table).where(table.c.project_id == self.p)), 0)

    def test_no_method_lost_response_replay_after_edit_and_concurrent_retry(self):
        from concurrent.futures import ThreadPoolExecutor
        image, _ = self.actual_media()
        payload = dict(prompt="  保留原需求\n", media_ids=[image])
        before = self.rev
        first = self.command("/marketing-canvases", payload, key="lost-response")
        self.assertEqual(first.status_code, 200, first.text)
        result = first.json()
        self.assertIsNone(result["method_node_id"])
        self.assertEqual(result["agent_handoff"]["skill_id"], "vsc-assets")
        self.assertEqual(self.command("/marketing-canvases", payload, expected=before, key="lost-response").json(), result)
        receipt = self.service.get_operation_receipt(self.p, "lost-response", actor="test-human")
        self.assertEqual(receipt["response"]["id"], result["canvas_id"])
        with self.assertRaises(ResourceError):
            self.service.create_marketing_canvas(self.p, payload, actor="other-actor", expected_revision=before,
                idempotency_key="lost-response")
        current = self.service.get_creative_canvas(self.p, result["canvas_id"])
        document = current["document"]
        for node in document["nodes"]:
            node.pop("preview_url", None)
        document["nodes"][0]["text"] = "后来的编辑"
        self.write("save_creative_canvas", dict(canvas_id=result["canvas_id"], canvas_revision=1, document=document))
        self.assertEqual(self.command("/marketing-canvases", payload, expected=before, key="lost-response").json(), result)
        self.assertEqual(self.service.get_creative_canvas(self.p, result["canvas_id"])["document"]["nodes"][0]["text"], "后来的编辑")
        self.rev = self.service.get_project(self.p)["revision"]
        expected = self.rev
        def prepare():
            return self.service.create_marketing_canvas(self.p, dict(prompt="并发同键"), actor="test-human",
                expected_revision=expected, idempotency_key="concurrent-marketing")
        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = [future.result() for future in [pool.submit(prepare), pool.submit(prepare)]]
        self.assertEqual(a, b)
        self.assertEqual(len(self.service.list_creative_canvases(self.p)["items"]), 2)
        conflict = self.command("/marketing-canvases", dict(payload, prompt="不同输入"), key="lost-response")
        self.assertEqual(conflict.status_code, 409, conflict.text)

    def test_historical_method_receipt_survives_catalog_upgrade_without_relaxing_new_requests(self):
        image, _ = self.actual_media()
        methods = marketing_methods()
        method = next(item for item in methods if item["id"] == "product-poster")
        payload = dict(prompt="  原始海报需求\n", method_id=method["id"], method_version=method["version"],
            method_sha256=method["sha256"], media_ids=[image])
        before = self.rev
        first = self.command("/marketing-canvases", payload, key="historical-method")
        self.assertEqual(first.status_code, 200, first.text)
        result = first.json()
        updated = deepcopy(methods)
        latest = next(item for item in updated if item["id"] == method["id"])
        latest.update(version="2.0", text=method["text"] + "\n新版动作：复核新规格。", skill_id="video-generation")
        latest["sha256"] = hashlib.sha256(latest["text"].encode()).hexdigest()
        current = dict(payload, method_version=latest["version"], method_sha256=latest["sha256"])
        with patch("vsc.assets.marketing_studio.marketing_methods", return_value=updated):
            replay = self.command("/marketing-canvases", payload, expected=before, key="historical-method")
            self.assertEqual(replay.status_code, 200, replay.text)
            self.assertEqual(replay.json(), result)
            read = self.client.get(self.base + "/creative-canvases/" + result["canvas_id"]).json()
            stored = next(node for node in read["document"]["nodes"] if node["id"] == "marketing-method")
            self.assertEqual(stored["text"], method["text"])
            self.assertEqual(stored["params"]["method_version"], method["version"])
            self.assertEqual(stored["params"]["method_sha256"], method["sha256"])
            self.assertEqual(result["agent_handoff"]["skill_id"], "image-generation")
            for changed in (dict(payload, prompt="改过的需求"), current, dict(payload, media_ids=[])):
                with self.subTest(changed=changed):
                    rejected = self.command("/marketing-canvases", changed, key="historical-method")
                    self.assertEqual(rejected.status_code, 409, rejected.text)
                    self.assertEqual(rejected.json()["error"], "idempotency_conflict")
            self.assertFalse(self.service.get_operation_receipt(self.p, "historical-method", actor="other-actor")["found"])
            # Even a currently valid pin cannot use another actor's key.
            with self.assertRaises(ResourceError) as wrong_actor:
                self.service.create_marketing_canvas(self.p, current, actor="other-actor", expected_revision=self.rev,
                    idempotency_key="historical-method")
            self.assertEqual(wrong_actor.exception.code, "idempotency_conflict")
            other = self.service.create_project(dict(name="isolated historical receipt target"), actor="test-human")
            self.assertFalse(self.service.get_operation_receipt(other["id"], "historical-method", actor="test-human")["found"])
            for foreign_input in (payload, current):
                with self.subTest(foreign_input=foreign_input):
                    with self.assertRaises(ResourceError):
                        self.service.create_marketing_canvas(other["id"], foreign_input, actor="test-human", expected_revision=0,
                            idempotency_key="historical-method")
            self.assertEqual(self.service.list_creative_canvases(other["id"])["items"], [])
            stale = self.command("/marketing-canvases", payload, key="new-request-old-pin")
            self.assertEqual(stale.status_code, 409, stale.text)
            self.assertEqual(stale.json()["error"], "marketing_method_mismatch")
            fresh = self.command("/marketing-canvases", current, key="new-request-current-pin")
            self.assertEqual(fresh.status_code, 200, fresh.text)
            self.assertNotEqual(fresh.json()["canvas_id"], result["canvas_id"])
            self.assertEqual(fresh.json()["agent_handoff"]["skill_id"], latest["skill_id"])
            new_nodes = self.client.get(self.base + "/creative-canvases/" + fresh.json()["canvas_id"]).json()["document"]["nodes"]
            self.assertEqual(next(node for node in new_nodes if node["id"] == "marketing-method")["text"], latest["text"])
        # Removal from today's catalog must also leave old operations readable.
        with patch("vsc.assets.marketing_studio.marketing_methods", return_value=[]):
            replay = self.command("/marketing-canvases", payload, expected=before, key="historical-method")
            self.assertEqual(replay.status_code, 200, replay.text)
            self.assertEqual(replay.json(), result)
            missing = self.command("/marketing-canvases", payload, key="new-request-removed-method")
            self.assertEqual(missing.status_code, 422, missing.text)
        self.assertEqual(len(self.service.list_creative_canvases(self.p)["items"]), 2)

    def test_bad_scope_recycled_type_bytes_limit_and_method_drift_are_rejected(self):
        image, _ = self.actual_media()
        audio, _ = self.actual_media("wav")
        self.write("recycle_media", dict(action="trash", media_ids=[image], reason="Synthetic recovery check"))
        method = marketing_methods()[0]
        bad = [dict(prompt="需求", media_ids=[image]), dict(prompt="需求", media_ids=[audio]),
            dict(prompt="需求", media_ids=[str(uuid.uuid4())]), dict(prompt="需求", media_ids=[image] * 16),
            dict(prompt="需求", method_id=method["id"], method_version=method["version"], method_sha256="0" * 64),
            dict(prompt="🛍" * 2001), dict(prompt=" \n "), dict(prompt="需求", episode_id=str(uuid.uuid4()))]
        for payload in bad:
            with self.subTest(payload=payload):
                response = self.command("/marketing-canvases", payload)
                self.assertIn(response.status_code, {404, 409, 422}, response.text)
        other = self.service.create_project(dict(name="other synthetic"), actor="test-human")
        foreign = self.service.create_object(other["id"], dict(kind="work", display_code="W"), actor="test-human", expected_revision=0, idempotency_key="work")
        episode = self.service.create_object(other["id"], dict(kind="episode", display_code="E", parent_id=foreign["id"]), actor="test-human", expected_revision=foreign["revision"], idempotency_key="episode")
        # Cross-project ownership is checked before local byte verification.
        foreign_media = self.service.register_media(other["id"], dict(name="foreign", modality="image", sha256=hashlib.sha256(b"foreign").hexdigest(),
            size_bytes=7, mime_type="image/png", storage="local", object_key="foreign.bin", rights="owned",
            source=dict(kind="test-owned", content="synthetic")), actor="test-human", expected_revision=episode["revision"], idempotency_key="foreign")
        for payload in (dict(prompt="需求", media_ids=[foreign_media["id"]]), dict(prompt="需求", episode_id=episode["id"])):
            response = self.command("/marketing-canvases", payload)
            self.assertEqual(response.status_code, 404, response.text)
        good, _ = self.actual_media()
        media = self.service.get_media(self.p, good)
        self.service.storage.resolve(media["locations"][0]["object_key"]).write_bytes(b"tampered")
        rejected = self.command("/marketing-canvases", dict(prompt="需求", media_ids=[good]))
        self.assertEqual(rejected.status_code, 422, rejected.text)
        self.assertEqual(self.service.list_creative_canvases(self.p)["items"], [])

    def test_session_csrf_actor_and_stale_revision_rejected(self):
        body = dict(payload=dict(prompt="需求"), expected_revision=self.rev, idempotency_key="auth-request")
        response = self.client.post(self.base + "/marketing-canvases", headers={"Origin": "http://testserver"}, json=body)
        self.assertEqual(response.status_code, 403, response.text)
        response = self.client.post(self.base + "/marketing-canvases", headers=self.headers, json=dict(body, actor="spoof"))
        self.assertEqual(response.status_code, 422, response.text)
        response = self.command("/marketing-canvases", dict(prompt="需求", actor="spoof"))
        self.assertEqual(response.status_code, 422, response.text)
        self.write("create_object", dict(kind="work", display_code="W"))
        response = self.command("/marketing-canvases", dict(prompt="需求"), expected=0)
        self.assertEqual(response.status_code, 409, response.text)
        self.client.cookies.clear()
        response = self.client.post(self.base + "/marketing-canvases", headers=self.headers, json=body)
        self.assertEqual(response.status_code, 403, response.text)
