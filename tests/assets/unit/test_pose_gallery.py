"""Character studio galleries, media boundary, CLI/OAuth auth bridges and HTTPS provider proxy."""
import base64
import json
import random
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from vsc.adapters.providers.xai_grok import credentials as grok_credentials
from vsc.assets import pose_gallery as g
from vsc.interfaces.web.character_studio import proxy_target_allowed

PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/iZk9HQAAAABJRU5ErkJggg=="
)


def write(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, (bytes, bytearray)):
        path.write_bytes(value)
    else:
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def build_gallery(repo: Path):
    gallery = repo / "assets" / "pose-gallery"
    data = gallery / "data"
    write(data / "costume-zh.json", [
        {"id": f"SPR-{i:04d}", "分类": "春季穿搭", "服装名称": f"春装{i}", "标签": ["象牙白"], "关键词": "ivory knit",
         "缩略图": f"thumbs/costume/SPR-{i:04d}.webp", "预览图": f"img/costume/SPR-{i:04d}.webp", "原图": f"img/costume/SPR-{i:04d}.webp",
         "检索": f"SPR-{i:04d} 春季穿搭 ivory"} for i in range(30)
    ] + [
        {"id": "LIN-0001", "分类": "内衣・睡衣", "服装名称": "睡衣", "标签": [], "关键词": "", "缩略图": "thumbs/costume/LIN-0001.webp",
         "预览图": "img/costume/LIN-0001.webp", "原图": "img/costume/LIN-0001.webp", "检索": "LIN-0001"},
        {"id": "missing-local", "分类": "春季穿搭", "服装名称": "缺失文件", "标签": [], "关键词": "",
         "缩略图": "thumbs/costume/MISSING.webp", "预览图": "img/costume/MISSING.webp", "原图": "img/costume/MISSING.webp", "检索": "missing"},
    ])
    write(data / "costume-shisei-zh.json", [{"id": "shisei-C001", "source": "shisei", "一级分类": "现实", "分类": "中国历代", "服装名称": "商",
        "标签": ["商"], "关键词": "", "缩略图": "thumbs/costumes/shisei/c1.webp", "预览图": "img/costumes/shisei/c1.webp", "原图": "img/costumes/shisei/c1.webp",
        "views": [{"id": "front", "label": "正面", "缩略图": "thumbs/costumes/shisei/c1.webp", "预览图": "img/costumes/shisei/c1.webp", "原图": "img/costumes/shisei/c1.webp"}], "检索": "shisei 商"}])
    write(data / "costume-gia-anime-zh.json", [
        {"id": "remote-bad", "source": "gia-anime", "一级分类": "二次元", "分类": "春季穿搭", "服装名称": "外链禁止",
         "缩略图": "https://evil.example.com/a.webp", "预览图": "https://evil.example.com/b.webp", "原图": "https://evil.example.com/c.png", "检索": "remote-bad"},
    ])
    write(data / "costume-anime-zh.json", [{"id": "charadb-O001", "source": "charadb", "一级分类": "二次元", "分类": "泳装", "服装名称": "泳装",
        "标签": [], "关键词": "", "缩略图": "https://charadb-2fi.pages.dev/thumb/O001.webp", "预览图": "https://charadb-2fi.pages.dev/img/O001.jpg",
        "原图": "https://charadb-2fi.pages.dev/img/O001.jpg", "敏感": True, "检索": "charadb 泳装"}])
    for i in range(30):
        write(gallery / "thumbs" / "costume" / f"SPR-{i:04d}.webp", b"RIFF0000WEBPVP8 ")
        write(gallery / "img" / "costume" / f"SPR-{i:04d}.webp", b"RIFF0000WEBPVP8 ")
    write(gallery / "thumbs" / "costume" / "LIN-0001.webp", b"RIFF0000WEBPVP8 ")
    write(gallery / "img" / "costume" / "LIN-0001.webp", b"RIFF0000WEBPVP8 ")
    write(gallery / "thumbs" / "costumes" / "shisei" / "c1.webp", b"RIFF0000WEBPVP8 ")
    write(gallery / "img" / "costumes" / "shisei" / "c1.webp", b"RIFF0000WEBPVP8 ")
    write(gallery / "thumbs" / "costumes" / "charadb" / "O001.webp", b"RIFF0000WEBPVP8 ")
    write(gallery / "img" / "costumes" / "charadb" / "O001.jpg", b"\xff\xd8\xff\xe0\x00\x10JFIF")
    poses = []
    for system, prefix in (("全身单人・标准系", "full_std"), ("全身单人・性感系", "full_sexy")):
        for number in ("P001", "P002"):
            for angle in ("侧面", "正面"):
                pid = f"{prefix}_{number}_{angle}"
                poses.append({"id": pid, "体系": system, "姿势编号": number, "分类": "站姿", "姿势名称": f"站立{number}", "角度": angle,
                              "缩略图": f"thumbs/{pid}.jpg", "原图": f"img/{pid}.png", "检索": pid})
    write(data / "pose-zh.json", poses)
    write(data / "portrait-zh.json", [{"id": f"p{i}", "分区": "正脸参考" if i % 2 else "造型氛围", "发长": "短发" if i < 3 else "长发",
        "发型名称": "标准基础款" if i < 2 else "波浪", "标题": f"人像{i}", "热门": i == 0, "缩略图": f"thumbs/portrait/p{i}.webp",
        "原图": f"img/portrait/p{i}.webp", "检索": f"p{i}"} for i in range(5)])
    write(data / "portrait-meta-zh.json", {"分区列表": ["正脸参考", "造型氛围"], "发长列表": ["短发", "中发", "中长发", "长发"]})
    write(repo / "assets" / "pose-gallery" / "thumbs" / "portrait" / "p0.webp", b"RIFF0000WEBPVP8 ")
    write(repo / "assets" / "pose-gallery" / "img" / "portrait" / "p0.png", PNG_1X1)
    write(repo / "assets" / "pose-gallery" / "secret.json", {"x": 1})
    (repo / "workflow").mkdir(parents=True, exist_ok=True)
    (repo / "workflow" / "kernel.json").write_text("{}", encoding="utf-8")


class PoseGalleryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        build_gallery(self.repo)

    def tearDown(self):
        self.tmp.cleanup()

    def test_costume_filters_safe_mode_and_paging(self):
        page = g.costume_page(self.repo)
        self.assertEqual(page["dataset_mode"], "pose-gallery")
        self.assertEqual(page["total_all"], 31)
        self.assertEqual(page["hidden_sensitive_count"], 2)
        self.assertEqual(len(page["items"]), 24)
        self.assertEqual(page["next_offset"], 24)
        self.assertNotIn("_text", page["items"][0])
        self.assertEqual(page["items"][0]["source"], "gia")
        self.assertEqual(g.costume_page(self.repo, offset=24)["next_offset"], None)
        self.assertEqual(g.costume_page(self.repo, safe=False)["total_all"], 33)
        self.assertEqual(g.costume_page(self.repo, source="shisei")["items"][0]["views"][0]["id"], "front")
        self.assertEqual(g.costume_page(self.repo, top="二次元", safe=False)["total"], 1)
        self.assertEqual(g.costume_page(self.repo, q="spr-0007")["total"], 1)
        self.assertEqual({s["id"] for s in page["sources"]}, {"gia", "shisei"})
        with self.assertRaises(ValueError):
            g.costume_page(self.repo, top="未知")
        with self.assertRaises(ValueError):
            g.costume_page(self.repo, limit=0)

    def test_costume_forbids_external_urls_and_localizes_known_cdn(self):
        all_items = g.costume_page(self.repo, safe=False, limit=120)["items"]
        ids = {item["id"] for item in all_items}
        self.assertNotIn("remote-bad", ids)
        self.assertNotIn("missing-local", ids)
        charadb = next(item for item in all_items if item["id"] == "charadb-O001")
        self.assertEqual(charadb["缩略图"], "thumbs/costumes/charadb/O001.webp")
        self.assertEqual(charadb["预览图"], "img/costumes/charadb/O001.jpg")
        self.assertEqual(charadb["原图"], "img/costumes/charadb/O001.jpg")
        for item in all_items:
            for key in ("缩略图", "预览图", "原图"):
                self.assertFalse(str(item.get(key, "")).startswith(("http://", "https://")), item)
        self.assertEqual(
            g.localize_costume_path("https://ai-costume-anime-gallery.pages.dev/png/SPR-0001.png"),
            "img/costumes/gia-anime/SPR-0001.webp",
        )
        self.assertEqual(g.localize_costume_path("https://evil.example.com/a.webp"), "")

    def test_poses_group_by_number_with_angle_order_and_safe_mode(self):
        grouped = g.pose_page(self.repo)
        self.assertEqual(grouped["total"], 2)
        self.assertEqual(grouped["hidden_sensitive_count"], 4)
        self.assertEqual([i["角度"] for i in grouped["items"][0]["items"]], ["正面", "侧面"])
        self.assertEqual([s["name"] for s in grouped["systems"]], ["全身单人・标准系"])
        self.assertEqual(g.pose_page(self.repo, safe=False)["total"], 4)
        self.assertEqual(g.pose_page(self.repo, system="全身单人・性感系")["total"], 2, "safe mode ignores a hidden system")
        self.assertEqual(g.pose_page(self.repo, view="single", angle="正面")["total"], 2)

    def test_portraits_sections_styles_and_hot(self):
        page = g.portrait_page(self.repo)
        self.assertEqual(page["total"], 5)
        self.assertEqual([h["name"] for h in page["hair_lengths"]], ["短发", "中发", "中长发", "长发"])
        self.assertEqual(g.portrait_page(self.repo, hot=True)["total"], 1)
        self.assertEqual(g.portrait_page(self.repo, hair="长发")["total"], 2)

    def test_random_reference_respects_scope_and_safety(self):
        rng = random.Random(7)
        pick = g.random_reference(self.repo, "pose", scope="similar", current_id="full_std_P001_正面", rng=rng)
        self.assertEqual(pick["体系"], "全身单人・标准系")
        self.assertNotEqual(pick["id"], "full_std_P001_正面")
        for _ in range(20):
            self.assertFalse(g.random_reference(self.repo, "costume", scope="all", rng=rng)["敏感"])
        self.assertIsNone(g.random_reference(self.repo, "portrait", scope="similar", current_id="upload-uuid"))
        recipe = g.random_recipe(self.repo, rng=rng)
        self.assertEqual(recipe["costume"]["source"], "gia")
        with self.assertRaises(ValueError):
            g.random_reference(self.repo, "unknown")

    def test_media_resolver_stays_inside_gallery(self):
        self.assertTrue(g.media_file(self.repo, "thumbs/portrait/p0.webp").is_file())
        for bad in ("thumbs/../secret.json", "data/pose-zh.json", "thumbs/.hidden.webp", "/etc/passwd", "img/portrait/missing.webp", "thumbs//p0.webp"):
            self.assertIsNone(g.media_file(self.repo, bad), bad)

    def test_legacy_costume_fallback_without_dataset(self):
        (self.repo / "assets" / "pose-gallery" / "data" / "costume-zh.json").unlink()
        spring = self.repo / "assets" / "服饰" / "春"
        spring.mkdir(parents=True)
        (spring / "SPR-0001.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        page = g.costume_page(self.repo)
        self.assertEqual(page["dataset_mode"], "legacy")
        self.assertEqual(page["items"][0]["缩略图"], "/api/v1/asset-center/costumes/SPR-0001/content")

    def test_proxy_allow_list_includes_xai_and_gemini(self):
        self.assertTrue(proxy_target_allowed("https://api.openai.com/v1/images/edits"))
        self.assertTrue(proxy_target_allowed("https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-image-preview:generateContent"))
        self.assertTrue(proxy_target_allowed("https://api.x.ai/v1/images/edits"))
        self.assertTrue(proxy_target_allowed("https://imgen.x.ai/tmp/out.png"))
        self.assertTrue(proxy_target_allowed("https://ark.cn-beijing.volces.com/api/v3/images/generations"))
        self.assertFalse(proxy_target_allowed("https://x.ai/v1"))
        self.assertFalse(proxy_target_allowed("http://api.x.ai/v1"))
        self.assertFalse(proxy_target_allowed("https://api.openai.com.evil.com/v1"))
        self.assertFalse(proxy_target_allowed("https://user:pw@api.openai.com/v1"))
        self.assertFalse(proxy_target_allowed("https://127.0.0.1/", "*"))
        self.assertFalse(proxy_target_allowed("https://localhost/", "*"))


class CharacterStudioHttpTests(unittest.TestCase):
    def test_routes_media_proxy_auth_bridges_and_no_comfy(self):
        import httpx
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            build_gallery(repo)
            projects = repo / "projects"
            projects.mkdir()
            fake_state = repo / "jetski_state.pbtxt"
            fake_state.write_text("oauth_ready: true\n", encoding="utf-8")
            with patch("vsc.interfaces.web.character_studio.repository_root", return_value=repo):
                app = create_app({"projects_root": str(projects), "allowed_hosts": ["testserver"], "allowed_origins": ["http://testserver"],
                                  "access_token": "studio-test", "human_identity": "test-human", "background_enabled": False})
                with TestClient(app) as client:
                    for path in ("/character-studio", "/api-settings"):
                        page = client.get(path)
                        self.assertEqual(page.status_code, 200)
                        self.assertIn("nav-character-studio", page.text)
                        self.assertIn("api-settings-open", page.text)
                        csp = page.headers["content-security-policy"]
                        self.assertIn("img-src 'self' data: blob: https:", csp)
                        self.assertNotIn("127.0.0.1:*", csp)
                        self.assertIn("style-src 'self'", csp)
                    denied = client.get("/api/v1/asset-center/pose-gallery/costumes")
                    self.assertEqual(denied.status_code, 403)
                    login = client.post("/api/v1/session", json={"token": "studio-test"}, headers={"Origin": "http://testserver"})
                    self.assertEqual(login.status_code, 200, login.text)
                    headers = {"Origin": "http://testserver", "X-CSRF-Token": login.json()["csrf_token"]}
                    costumes = client.get("/api/v1/asset-center/pose-gallery/costumes?safe=true", headers=headers)
                    self.assertEqual(costumes.status_code, 200, costumes.text)
                    self.assertEqual(costumes.json()["limit"], 24)
                    media = client.get("/api/v1/asset-center/pose-gallery/media/thumbs/portrait/p0.webp")
                    self.assertEqual(media.status_code, 200)
                    self.assertEqual(media.headers.get("cache-control"), "private, max-age=86400")
                    self.assertEqual(client.get("/api/v1/asset-center/pose-gallery/media/thumbs/%2e%2e/secret.json").status_code, 404)

                    # Local ComfyUI relay is completely removed.
                    self.assertEqual(client.get("/comfy/system_stats", headers=headers).status_code, 404)
                    self.assertEqual(client.get("/comfy/system_stats", headers={**headers, "Authorization": "Bearer token"}).status_code, 403)

                    # Provider proxy: xAI & Gemini allowed, User-Agent attached, GET download supported.
                    bearer = {**headers, "Authorization": "Bearer xai-test-key", "Content-Type": "application/json"}
                    self.assertEqual(client.post("/api/proxy", content=b"{}", headers={"Authorization": "Bearer xai-test-key"}).status_code, 403)
                    self.assertEqual(client.post("/api/proxy", content=b"{}", headers={**bearer, "x-target-url": "https://evil.example.com/x"}).status_code, 403)
                    upstream = httpx.Response(200, json={"data": [{"url": "https://imgen.x.ai/out.png"}]}, headers={"content-type": "application/json"})
                    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=upstream)) as forwarded:
                        relayed = client.post("/api/proxy", content=b'{"model":"grok-imagine-image-2.0"}',
                                              headers={**bearer, "x-target-url": "https://api.x.ai/v1/images/edits"})
                    self.assertEqual(relayed.status_code, 200, relayed.text)
                    sent = forwarded.call_args
                    self.assertEqual(sent.args[0], "https://api.x.ai/v1/images/edits")
                    self.assertEqual(sent.kwargs["headers"]["authorization"], "Bearer xai-test-key")
                    self.assertEqual(sent.kwargs["headers"]["user-agent"], grok_credentials.USER_AGENT)
                    self.assertNotIn("x-csrf-token", {k.lower() for k in sent.kwargs["headers"]})

                    img_upstream = httpx.Response(200, content=PNG_1X1, headers={"content-type": "image/png"})
                    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=img_upstream)) as get_mock:
                        fetched = client.post("/api/proxy", headers={**headers, "x-target-url": "https://imgen.x.ai/out.png", "x-target-method": "GET"})
                    self.assertEqual(fetched.status_code, 200)
                    self.assertEqual(fetched.content, PNG_1X1)
                    self.assertEqual(get_mock.call_args.args[0], "https://imgen.x.ai/out.png")

                    # Auth status & online verification never leak secret tokens.
                    with patch("vsc.interfaces.web.character_studio._agy_state_file", return_value=fake_state), \
                         patch("vsc.interfaces.web.character_studio.shutil.which", side_effect=lambda b: f"/usr/local/bin/{b}"), \
                         patch("vsc.adapters.providers.xai_grok.credentials.key_problem", return_value=None), \
                         patch("vsc.adapters.providers.xai_grok.credentials.account_id", return_value="alice@example.com"):
                        st = client.get("/api/v1/character-studio/auth/status", headers=headers)
                        self.assertEqual(st.status_code, 200, st.text)
                        body = st.json()
                        self.assertTrue(body["grok"]["ready"])
                        self.assertEqual(body["grok"]["account"], "al***@example.com")
                        self.assertTrue(body["agy"]["ready"])
                        self.assertNotIn("oauth_ready", st.text)

                        proc_ok = subprocess.CompletedProcess(["agy", "models"], 0, stdout="gemini-4-carbon-pro\nclaude-opus-4-6\n", stderr="")
                        with patch("vsc.interfaces.web.character_studio.subprocess.run", return_value=proc_ok):
                            ver = client.post("/api/v1/character-studio/auth/verify", json={"provider": "agy"}, headers=headers)
                        self.assertEqual(ver.status_code, 200, ver.text)
                        self.assertTrue(ver.json()["verified"])
                        self.assertEqual(ver.json()["model_count"], 2)

                    # Backend Grok subscription generation (`grok_auth`) uses `~/.grok/auth.json` and immediately stores temporary URL.
                    fake_client = MagicMock()
                    fake_client.__enter__.return_value = fake_client
                    fake_client.post.return_value = httpx.Response(200, json={"data": [{"url": "https://imgen.x.ai/gen1.png"}]})
                    fake_client.get.return_value = httpx.Response(200, content=PNG_1X1, headers={"content-type": "image/png"})
                    with patch("vsc.adapters.providers.xai_grok.credentials.read_key", return_value="secret-sub-token-999"), \
                         patch("httpx.Client", return_value=fake_client):
                        gen_grok = client.post(
                            "/api/v1/character-studio/generate",
                            json={
                                "provider": "grok_auth",
                                "model": "grok-imagine-image-2.0",
                                "prompt": "生成角色立绘",
                                "references": ["/api/v1/asset-center/pose-gallery/media/img/portrait/p0.png"],
                                "aspect_ratio": "3:4",
                                "resolution": "2k",
                            },
                            headers=headers,
                        )
                    self.assertEqual(gen_grok.status_code, 200, gen_grok.text)
                    self.assertTrue(gen_grok.json()["image_url"].startswith("data:image/png;base64,"))
                    self.assertNotIn("secret-sub-token-999", gen_grok.text)
                    post_call = fake_client.post.call_args
                    self.assertEqual(post_call.args[0], "https://api.x.ai/v1/images/edits")
                    self.assertEqual(post_call.kwargs["headers"]["Authorization"], "Bearer secret-sub-token-999")
                    self.assertEqual(post_call.kwargs["headers"]["User-Agent"], grok_credentials.USER_AGENT)

                    # Backend AGY generation (`agy_auth`) invokes `agy` CLI in isolated temp dir and reads result.png.
                    def fake_agy_run(cmd, cwd=None, **kwargs):
                        out = Path(cwd) / "result.png"
                        out.write_bytes(PNG_1X1)
                        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"saved_path": str(out), "error": ""}), stderr="")

                    with patch("vsc.interfaces.web.character_studio._agy_state_file", return_value=fake_state), \
                         patch("vsc.interfaces.web.character_studio.shutil.which", return_value="/opt/homebrew/bin/agy"), \
                         patch("vsc.interfaces.web.character_studio.subprocess.run", side_effect=fake_agy_run):
                        gen_agy = client.post(
                            "/api/v1/character-studio/generate",
                            json={
                                "provider": "agy_auth",
                                "model": "image-generator",
                                "prompt": "生成角色立绘",
                                "references": [f"data:image/png;base64,{base64.b64encode(PNG_1X1).decode('ascii')}"],
                                "aspect_ratio": "3:4",
                            },
                            headers=headers,
                        )
                    self.assertEqual(gen_agy.status_code, 200, gen_agy.text)
                    self.assertTrue(gen_agy.json()["image_url"].startswith("data:image/png;base64,"))
                    self.assertEqual(gen_agy.json()["provider"], "agy_auth")


if __name__ == "__main__":
    unittest.main()
