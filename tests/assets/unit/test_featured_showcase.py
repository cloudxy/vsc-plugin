"""Local 创作精选 catalog, search, and canvas process projection."""
import gzip
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from support.paths import ROOT
from vsc.assets.featured_showcase import list_works, localize_value, media_digest, project_snapshot, read_process, showcase_root, store_media
from vsc.interfaces.web.featured_showcase import install_featured_showcase_routes


def write_snapshot(root, identity, snapshot, snapshot_id=7):
    record = {"templateUuid": identity, "name": "旧日", "snapshotId": snapshot_id, "snapshot": snapshot,
              "finalOutput": "https://example.test/out.mp4"}
    target = root / "processes" / f"{identity}.json.gz"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(gzip.compress(json.dumps(record).encode()))


def write_source(root, identity, snapshot, snapshot_id=7):
    path = root / "sources" / "process-detail" / f"{identity}-{snapshot_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"data": {"detail": {"templateUuid": identity, "snapshotId": snapshot_id,
                    "name": "原始归档", "snapshotData": json.dumps(snapshot)}}}), encoding="utf-8")
    return path


class FeaturedShowcaseTests(unittest.TestCase):
    def test_legacy_node_keys_and_serialized_data_keep_graph_and_outputs(self):
        snapshot = {"nodes": [
            {"nodeKey": "group-a", "type": 5, "parentKey": "",
             "position": {"positionX": "100", "positionY": "40"},
             "data": json.dumps({"type": "group", "childNodeIds": ["image-a"]})},
            {"nodeKey": "image-a", "type": 2, "parentKey": "group-a",
             "position": {"positionX": "12.5", "positionY": "20"},
             "data": json.dumps({"type": "image", "url": ["https://example.test/a.png"],
                                 "params": {"prompt": "A complete image", "enabled": False},
                                 "_resourceMeta": {"items": [{"width": 640, "height": 480}]}})},
        ], "edges": [{"connectionId": "edge-a", "source": "group-a", "target": "image-a",
                       "sourceHandle": "out", "targetHandle": "in"}]}
        original = json.dumps(snapshot)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.catalog(root)
            write_snapshot(root, "a" * 32, snapshot)
            source = write_source(root, "a" * 32, snapshot)
            source_bytes = source.read_bytes()
            image = store_media(root, "https://example.test/a.png", b"\x89PNG\r\n\x1a\nimage")
            view = read_process(root, "a" * 32)["process"]
            self.assertEqual([n["id"] for n in view["nodes"]], ["group-a", "image-a"])
            node = view["nodes"][1]
            self.assertEqual((node["x"], node["y"]), (112.5, 60))
            self.assertEqual(node["parentId"], "group-a")
            self.assertEqual(node["params"]["enabled"], False)
            self.assertEqual(node["resourceMeta"]["items"][0]["width"], 640)
            self.assertEqual(node["url"], "/featured-showcase-media/" + image.name)
            self.assertEqual(view["edges"][0]["id"], "edge-a")
            self.assertEqual(view["edges"][0]["targetHandle"], "in")
            self.assertEqual(view["issues"], [])
            self.assertEqual(view["coverage"]["status"], "complete")
            self.assertEqual(source.read_bytes(), source_bytes)
        self.assertEqual(json.dumps(snapshot), original)

    @unittest.skipUnless(shutil.which("node"), "requires Node.js")
    def test_frontend_latest_intent_and_late_responses(self):
        result = subprocess.run(["node", "--test", str(Path(__file__).with_name("featured_showcase.test.mjs"))],
                                cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_workspace_assets_default_and_explicit_override(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(showcase_root(), ROOT / "assets" / "featured-showcase")
            with patch.dict("os.environ", {"VSC_FEATURED_SHOWCASE_ROOT": "/explicit/showcase"}):
                self.assertEqual(showcase_root(), Path("/explicit/showcase"))
                self.assertEqual(showcase_root("/override/showcase"), Path("/override/showcase"))

    def test_localized_links_are_rechecked_after_media_loss(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            url = "https://example.test/cover.png"
            stored = store_media(root, url, b"\x89PNG\r\n\x1a\ncover")
            local = "/featured-showcase-media/" + stored.name
            payload = {"coverUrl": local, "prompt": "参考 " + local}
            self.assertEqual(localize_value(root, payload), payload)
            stored.unlink()
            self.assertEqual(localize_value(root, payload), {"coverUrl": "", "prompt": "参考 "})
            self.assertEqual(localize_value(root, payload, drop_missing=False), payload)

    def catalog(self, root):
        cards = {
            "a" * 32: {"templateUuid": "a" * 32, "name": "旧日将尽", "description": "末世", "nickname": "熵变",
                       "snapshotId": 7, "coverUrl": "https://example.test/cover.png",
                       "tags": [{"code": "viral_likes_30", "label": "全网点赞30万+"}], "userTags": [{"name": "先锋"}]},
            "b" * 32: {"templateUuid": "b" * 32, "name": "绵羊奶粉", "description": "", "nickname": "阿松", "snapshotId": None},
        }
        payload = {"schema": "vsc.featured-showcase/v1", "tags": [{"id": 0, "code": "all", "label": "全部"},
                   {"id": 1800, "code": "short_play", "label": "短剧漫剧"}],
                   "feeds": {"0": ["a" * 32, "b" * 32], "1800": ["a" * 32]}, "cards": cards}
        root.mkdir(parents=True, exist_ok=True)
        (root / "catalog.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return cards

    def test_search_tag_and_closed_canvas(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.catalog(root)
            page = list_works(root, "0", "旧日", 0, 20)
            self.assertTrue(page["ready"])
            self.assertEqual([item["name"] for item in page["items"]], ["旧日将尽"])
            self.assertFalse(page["items"][0]["processReady"])
            self.assertEqual(page["items"][0]["structureStatus"], "missing")
            self.assertTrue(page["items"][0]["processAvailable"])
            tagged = list_works(root, "1800", "", 0, 20)
            self.assertEqual(tagged["total"], 1)
            self.assertEqual(list_works(root, "999", "", 0, 20)["total"], 2)
            closed = list_works(root, "0", "绵羊", 0, 20)["items"][0]
            self.assertFalse(closed["processAvailable"])
            self.assertEqual(closed["structureStatus"], "unpublished")

    def test_process_uses_parent_offsets_and_mixed_refs(self):
        snapshot = {"nodes": [
            {"id": "g-1", "type": "group", "position": {"x": 100, "y": 40}, "width": 800, "height": 500,
             "data": {"type": "group", "name": "第一幕", "childNodeIds": ["v-1"], "groupColor": "#F4B740"}},
            {"id": "v-1", "type": "video", "parentId": "g-1", "position": {"x": 12, "y": 20},
             "measured": {"width": 320, "height": 180},
             "data": {"type": "video", "name": "镜头", "action": "video_generate",
                      "url": ["https://example.test/a.mp4", "https://example.test/b.mp4"],
                      "params": {"model": "star-video2.5", "modeType": "mixed2video", "prompt": "林芸调动无人机",
                                 "settings": {"ratio": "21:9", "duration": 10},
                                 "imageList": [{"nodeId": "i-1", "label": "忽略"}],
                                 "mixedList": [{"nodeId": "i-2", "label": "调度员"}]},
                      "taskInfo": {"status": 2}}},
        ], "edges": [{"id": "e-1", "source": "i-missing", "target": "v-1"}, {"id": "e-2", "source": "g-1", "target": "v-1"}]}
        projected = project_snapshot(snapshot)
        video = next(node for node in projected["nodes"] if node["id"] == "v-1")
        self.assertEqual((video["x"], video["y"]), (112, 60))
        self.assertEqual(video["url"], "")
        self.assertEqual([(ref["nodeId"], ref["label"], ref["kind"]) for ref in video["refs"]], [("i-2", "调度员", "mixed")])
        self.assertEqual(video["relativePosition"], {"x": 12, "y": 20})
        self.assertEqual(video["position"], {"x": 12, "y": 20})
        self.assertEqual(video["settings"]["ratio"], "21:9")
        self.assertEqual([edge["id"] for edge in projected["edges"]], ["e-1", "e-2"])
        self.assertEqual(projected["issues"][0]["code"], "dangling_edge")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.catalog(root)
            write_snapshot(root, "a" * 32, snapshot)
            loaded = read_process(root, "a" * 32)
            self.assertEqual(loaded["process"]["nodes"][1]["prompt"], "林芸调动无人机")
            self.assertEqual(loaded["process"]["nodes"][1]["url"], "")
            self.assertEqual(loaded["finalOutput"], "")
            self.assertNotIn("https://", json.dumps(loaded))
            self.assertTrue(list_works(root)["items"][0]["processReady"])
            self.assertEqual(list_works(root)["items"][0]["coverUrl"], "")
            store_media(root, "https://example.test/cover.png", b"\x89PNG\r\n\x1a\ncover")
            self.assertTrue(list_works(root)["items"][0]["coverUrl"].startswith("/featured-showcase-media/"))
            with self.assertRaises(FileNotFoundError):
                read_process(root, "../secret")

    def test_http_reads_local_snapshot_without_remote_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.catalog(root)
            app = FastAPI()
            install_featured_showcase_routes(app, lambda _request, value: value, lambda _request: None, root=root)
            with TestClient(app) as client:
                listed = client.get("/api/v1/featured-showcase", params={"q": "旧日"})
                self.assertEqual(listed.status_code, 200)
                self.assertEqual(listed.json()["items"][0]["name"], "旧日将尽")
                self.assertEqual(listed.json()["items"][0]["coverUrl"], "")
                self.assertNotIn("https://", listed.text)
                missing = client.get("/api/v1/featured-showcase/" + "a" * 32)
                self.assertEqual(missing.status_code, 404)
                stored = store_media(root, "https://example.test/cover.png", b"\x89PNG\r\n\x1a\ncover")
                media = client.get("/featured-showcase-media/" + stored.name)
                self.assertEqual(media.status_code, 200)
                self.assertEqual(media.content, b"\x89PNG\r\n\x1a\ncover")
                again = client.get("/api/v1/featured-showcase", params={"q": "旧日"})
                self.assertEqual(again.json()["items"][0]["coverUrl"], "/featured-showcase-media/" + stored.name)
                self.assertNotIn("https://", again.text)

    def test_http_reports_missing_corrupt_and_invalid_structure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.catalog(root)
            identity = "a" * 32
            app = FastAPI()
            install_featured_showcase_routes(app, lambda _request, value: value, lambda _request: None, root=root)
            target = root / "processes" / f"{identity}.json.gz"
            target.parent.mkdir()
            with TestClient(app) as client:
                self.assertEqual(client.get("/api/v1/featured-showcase/" + identity).status_code, 404)
                for name, body, status, code in [
                    ("bad gzip", b"broken gzip", 409, "corrupt_snapshot"),
                    ("bad json", gzip.compress(b"{"), 409, "corrupt_snapshot"),
                    ("missing node list", gzip.compress(json.dumps({"snapshot": {"edges": []}}).encode()), 422, "invalid_snapshot"),
                ]:
                    with self.subTest(name=name):
                        target.write_bytes(body)
                        response = client.get("/api/v1/featured-showcase/" + identity)
                        self.assertEqual(response.status_code, status)
                        self.assertEqual(response.json()["detail"]["code"], code)
                        item = client.get("/api/v1/featured-showcase").json()["items"][0]
                        self.assertEqual(item["structureStatus"], "invalid")
                        self.assertFalse(item["processReady"])
                write_snapshot(root, identity, {"nodes": [], "edges": []})
                self.assertEqual(client.get("/api/v1/featured-showcase/" + identity).status_code, 200)
                self.assertEqual(client.get("/api/v1/featured-showcase").json()["items"][0]["structureStatus"], "ready")
                self.assertEqual(client.get("/api/v1/featured-showcase/" + "b" * 32).status_code, 409)

    def test_duplicate_nodes_and_parent_cycles_are_invalid_but_dangling_edges_survive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.catalog(root)
            app = FastAPI()
            install_featured_showcase_routes(app, lambda _request, value: value, lambda _request: None, root=root)
            identity = "a" * 32
            with TestClient(app) as client:
                for name, nodes, code in [
                    ("duplicate", [{"id": "x"}, {"id": "x"}], "duplicate_node_id"),
                    ("cycle", [{"id": "x", "parentId": "y"}, {"id": "y", "parentId": "x"}], "parent_cycle"),
                    ("illegal parent", [{"id": "x", "parentId": []}], "invalid_parent"),
                ]:
                    with self.subTest(name=name):
                        write_snapshot(root, identity, {"nodes": nodes, "edges": []})
                        response = client.get("/api/v1/featured-showcase/" + identity)
                        self.assertEqual(response.status_code, 422)
                        self.assertIn(code, [issue["code"] for issue in response.json()["detail"]["issues"]])
                edge = {"id": "dangling", "source": "outside", "target": "x", "sourceHandle": "out-1",
                        "targetHandle": "input-2", "type": "wire", "selectable": False}
                write_snapshot(root, identity, {"nodes": [{"id": "x", "type": "unrecognized", "data": {"custom": {"flag": False}}}], "edges": [edge]})
                process = client.get("/api/v1/featured-showcase/" + identity).json()["process"]
                self.assertEqual(process["edges"], [edge])
                self.assertEqual(process["issues"][0]["code"], "dangling_edge")
                self.assertFalse(process["nodes"][0]["metadata"]["custom"]["flag"])

    def test_full_params_outputs_reference_order_history_and_thumbnail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.catalog(root)
            first, second, thumb = ["https://example.test/" + value for value in ("a.mp4", "b.mp4", "thumb.jpg")]
            first_path = store_media(root, first, b"video-a")
            second_path = store_media(root, second, b"video-b")
            thumb_path = store_media(root, thumb, b"thumb")
            (root / "thumbnails.json").write_text(json.dumps({media_digest(second): thumb_path.name}))
            params = {"enableSound": False, "settings": {"enableSound": True, "duration": 4},
                      "advancedSettings": {"seed": 0, "enhance": False}, "cameraControl": {"pan": 0.5},
                      "mixedList": [{"nodeId": "same", "index": 0, "slot": "first", "url": first},
                                    {"nodeId": "same", "index": 1, "slot": "last", "url": second}],
                      "mixedListOrder": [{"nodeId": "same", "index": 1}, {"nodeId": "same", "index": 0}],
                      "imageList": [{"nodeId": "same", "index": 0}]}
            history = {"count": 19, "items": [{"url": "https://example.test/old.mp4", "seed": 7}]}
            snapshot = {"nodes": [{"id": "group", "type": "group", "position": {"x": 8, "y": 10},
                                    "data": {"childNodeIds": ["clip"]}},
                                   {"id": "clip", "type": "video", "parentId": "group", "position": {"x": 2, "y": 3},
                                    "measured": {"width": 450, "height": 280}, "createdAtMs": 123,
                                    "data": {"url": [first, second], "selectedOutputIndex": 1, "params": params,
                                             "resourceMeta": {"items": [{"mimeType": "video/mp4"}, {"byteSize": 7}]},
                                             "nodeHistory": history}}], "edges": [], "savedAt": 42, "extraState": {"enabled": False}}
            write_snapshot(root, "a" * 32, snapshot)
            loaded = read_process(root, "a" * 32)
            process, node = loaded["process"], loaded["process"]["nodes"][1]
            self.assertEqual(process["projectionVersion"], 2)
            self.assertEqual(process["extraState"], {"enabled": False})
            self.assertEqual(process["issues"], [])
            self.assertEqual((node["x"], node["y"]), (10, 13))
            self.assertEqual((node["width"], node["height"]), (450, 280))
            self.assertEqual(node["createdAtMs"], 123)
            self.assertFalse(node["params"]["enableSound"])
            self.assertFalse(node["params"]["advancedSettings"]["enhance"])
            self.assertTrue(node["settings"]["enableSound"])
            self.assertEqual(node["params"]["cameraControl"], {"pan": 0.5})
            self.assertEqual([(ref["nodeId"], ref["index"], ref["slot"]) for ref in node["refs"]], [("same", 1, "last"), ("same", 0, "first")])
            self.assertEqual(node["url"], "/featured-showcase-media/" + second_path.name)
            self.assertEqual(node["poster"], "/featured-showcase-media/" + thumb_path.name)
            self.assertEqual([item["index"] for item in node["outputs"]], [0, 1])
            self.assertEqual(node["outputs"][1]["metadata"], {"byteSize": 7})
            self.assertEqual(node["nodeHistory"]["count"], 19)
            self.assertEqual(node["nodeHistory"]["items"][0]["url"], "")
            self.assertEqual(process["coverage"], {"scope": "currentOutputs", "mediaNodes": 1, "localMediaNodes": 1,
                             "missingMediaNodes": 0, "outputCount": 2, "localOutputs": 2, "status": "complete"})
            self.assertNotIn("https://", json.dumps(loaded))
            # Parsing may be cached; file existence and thumbnail presence may not be.
            second_path.unlink()
            thumb_path.unlink()
            partial = read_process(root, "a" * 32)["process"]
            self.assertEqual(partial["nodes"][1]["url"], "")
            self.assertEqual(partial["nodes"][1]["poster"], "")
            self.assertEqual(partial["coverage"]["status"], "partial")
            first_path.unlink()
            missing = read_process(root, "a" * 32)["process"]
            self.assertEqual([node["id"] for node in missing["nodes"]], ["group", "clip"])
            self.assertEqual(missing["nodes"][1]["mediaStatus"], "missing")
            self.assertEqual(missing["coverage"]["missingMediaNodes"], 1)
            self.assertEqual(missing["coverage"]["status"], "missing")
            self.assertTrue(list_works(root)["items"][0]["processReady"])

    def test_typed_reference_order_preserves_duplicate_node_slots(self):
        params = {"imageList": [{"nodeId": "same", "index": 0}, {"nodeId": "other", "index": 0},
                                {"nodeId": "same", "index": 1}], "imageListOrder": ["other", "same", "same"]}
        process = project_snapshot({"nodes": [{"id": "target", "data": {"params": params}}], "edges": []})
        self.assertEqual([(ref["nodeId"], ref["index"], ref["order"]) for ref in process["nodes"][0]["refs"]],
                         [("other", 0, 0), ("same", 0, 1), ("same", 1, 2)])

    def test_raw_archive_is_preferred_localized_and_never_rewritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.catalog(root)
            identity = "a" * 32
            write_snapshot(root, identity, {"nodes": [{"id": "old"}], "edges": []})
            url = "https://example.test/archive.mp4"
            original = {"nodes": [{"id": "full", "type": "video", "data": {"url": [url], "params": {"flag": False}}}], "edges": []}
            archive = write_source(root, identity, original)
            gzip_path = root / "processes" / f"{identity}.json.gz"
            before = (archive.read_bytes(), gzip_path.read_bytes())
            loaded = read_process(root, identity)
            self.assertEqual([node["id"] for node in loaded["process"]["nodes"]], ["full"])
            self.assertEqual(loaded["process"]["source"], {"kind": "rawArchive", "snapshotId": 7})
            self.assertNotIn("https://", json.dumps(loaded))
            self.assertIn(url.encode(), archive.read_bytes())
            self.assertEqual((archive.read_bytes(), gzip_path.read_bytes()), before)
            # A newer source written in the fixed old-version slot cannot replace the graph.
            response = json.loads(archive.read_text())
            response["data"]["detail"]["snapshotId"] = 8
            archive.write_text(json.dumps(response))
            fallback = read_process(root, identity)["process"]
            self.assertEqual([node["id"] for node in fallback["nodes"]], ["old"])
            self.assertEqual(fallback["issues"][0]["code"], "source_version_mismatch")
            self.assertEqual(fallback["source"]["kind"], "gzip")

    def test_raw_archive_can_supply_structure_when_gzip_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.catalog(root)
            write_source(root, "a" * 32, {"nodes": [], "edges": []})
            self.assertEqual(list_works(root)["items"][0]["structureStatus"], "ready")
            self.assertEqual(read_process(root, "a" * 32)["process"]["coverage"]["status"], "empty")

    def test_card_structure_checks_do_not_reparse_every_canvas_on_repeated_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            identities = [f"{index:032x}" for index in range(12)]
            catalog = {"schema": "vsc.featured-showcase/v1", "tags": [], "feeds": {"0": identities},
                       "cards": {identity: {"templateUuid": identity, "snapshotId": 7} for identity in identities}}
            (root / "catalog.json").write_text(json.dumps(catalog))
            for identity in identities:
                write_snapshot(root, identity, {"nodes": [], "edges": []})
            with patch("vsc.assets.featured_showcase.gzip.decompress", wraps=gzip.decompress) as decompress:
                self.assertTrue(all(card["processReady"] for card in list_works(root, limit=12)["items"]))
                count = decompress.call_count
                self.assertEqual(count, 12)
                self.assertTrue(all(card["processReady"] for card in list_works(root, limit=12)["items"]))
                self.assertEqual(decompress.call_count, count)

    def test_real_app_media_tags_read_without_csrf_and_apis_require_session(self):
        from vsc.interfaces.web.app import create_app

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stored = store_media(root, "https://example.test/clip.mp4", b"0123456789")
            # Use the actual app boundary and read_actor: media tags have neither a
            # CSRF header nor a human session; JSON requests retain their session guard.
            with patch.dict("os.environ", {"VSC_FEATURED_SHOWCASE_ROOT": str(root)}):
                app = create_app({"allowed_hosts": ["testserver"]}, catalog=SimpleNamespace(service=None))
                with TestClient(app) as client:
                    media_path = "/featured-showcase-media/" + stored.name
                    media = client.get(media_path)
                    self.assertEqual(media.status_code, 200)
                    self.assertEqual(media.content, b"0123456789")
                    partial = client.get(media_path, headers={"Range": "bytes=2-5"})
                    self.assertEqual(partial.status_code, 206)
                    self.assertEqual(partial.headers["content-range"], "bytes 2-5/10")
                    self.assertEqual(partial.content, b"2345")
                    for path in ("/api/v1/featured-showcase", "/api/v1/featured-showcase/" + "a" * 32):
                        with self.subTest(path=path):
                            response = client.get(path)
                            self.assertEqual(response.status_code, 403)
                            self.assertEqual(response.json()["detail"], "请先建立本机人工操作会话")

    def test_shell_keeps_community_and_adds_showcase(self):
        html = (ROOT / "src/vsc/interfaces/web/templates/index.html").read_text(encoding="utf-8")
        panel = (ROOT / "src/vsc/interfaces/web/static/panel.js").read_text(encoding="utf-8")
        self.assertIn('id="community-view"', html)
        self.assertIn('id="nav-featured-showcase"', html)
        self.assertIn('id="featured-showcase-view"', html)
        self.assertIn("'featured-showcase'", panel)
        self.assertIn("createFeaturedShowcase", panel)
        app = (ROOT / "src/vsc/interfaces/web/app.py").read_text(encoding="utf-8")
        self.assertIn("install_featured_showcase_routes", app)


if __name__ == "__main__":
    unittest.main()
