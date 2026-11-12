"""Character studio galleries, media boundary, provider proxy and ComfyUI relay."""
import json
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from vsc.assets import pose_gallery as g
from vsc.interfaces.web.character_studio import proxy_target_allowed


def write(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, (bytes, bytearray)):
        path.write_bytes(value)
    else:
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def build_gallery(repo: Path):
    data = repo / "assets" / "pose-gallery" / "data"
    write(data / "costume-zh.json", [
        {"id": f"SPR-{i:04d}", "分类": "春季穿搭", "服装名称": f"春装{i}", "标签": ["象牙白"], "关键词": "ivory knit",
         "缩略图": f"thumbs/costume/SPR-{i:04d}.webp", "预览图": f"img/costume/SPR-{i:04d}.webp", "原图": f"img/costume/SPR-{i:04d}.webp",
         "检索": f"SPR-{i:04d} 春季穿搭 ivory"} for i in range(30)
    ] + [{"id": "LIN-0001", "分类": "内衣・睡衣", "服装名称": "睡衣", "标签": [], "关键词": "", "缩略图": "thumbs/costume/LIN-0001.webp",
          "预览图": "img/costume/LIN-0001.webp", "原图": "img/costume/LIN-0001.webp", "检索": "LIN-0001"}])
    write(data / "costume-shisei-zh.json", [{"id": "shisei-C001", "source": "shisei", "一级分类": "现实", "分类": "中国历代", "服装名称": "商",
        "标签": ["商"], "关键词": "", "缩略图": "thumbs/costumes/shisei/c1.webp", "预览图": "img/costumes/shisei/c1.webp", "原图": "img/costumes/shisei/c1.webp",
        "views": [{"id": "front", "label": "正面", "缩略图": "thumbs/costumes/shisei/c1.webp", "预览图": "img/costumes/shisei/c1.webp", "原图": "img/costumes/shisei/c1.webp"}], "检索": "shisei 商"}])
    write(data / "costume-gia-anime-zh.json", [])
    write(data / "costume-anime-zh.json", [{"id": "charadb-O001", "source": "charadb", "一级分类": "二次元", "分类": "泳装", "服装名称": "泳装",
        "标签": [], "关键词": "", "缩略图": "https://charadb-2fi.pages.dev/thumb/O001.webp", "预览图": "https://charadb-2fi.pages.dev/img/O001.jpg",
        "原图": "https://charadb-2fi.pages.dev/img/O001.jpg", "敏感": True, "检索": "charadb 泳装"}])
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

    def test_proxy_allow_list(self):
        self.assertTrue(proxy_target_allowed("https://api.openai.com/v1/images/edits"))
        self.assertTrue(proxy_target_allowed("https://ark.cn-beijing.volces.com/api/v3/images/generations"))
        self.assertFalse(proxy_target_allowed("http://api.openai.com/v1"))
        self.assertFalse(proxy_target_allowed("https://api.openai.com.evil.com/v1"))
        self.assertFalse(proxy_target_allowed("https://user:pw@api.openai.com/v1"))
        self.assertFalse(proxy_target_allowed("https://127.0.0.1/", "*"))
        self.assertFalse(proxy_target_allowed("https://localhost/", "*"))
        self.assertTrue(proxy_target_allowed("https://img.example.volces.com/a", "*.volces.com"))
        self.assertFalse(proxy_target_allowed("https://volces.com/a", "*.volces.com"))


class CharacterStudioHttpTests(unittest.TestCase):
    def test_routes_media_proxy_and_spa(self):
        import httpx
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            build_gallery(repo)
            projects = repo / "projects"
            projects.mkdir()
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
                        self.assertIn("style-src 'self'", csp)
                    denied = client.get("/api/v1/asset-center/pose-gallery/costumes")
                    self.assertEqual(denied.status_code, 403)
                    login = client.post("/api/v1/session", json={"token": "studio-test"}, headers={"Origin": "http://testserver"})
                    self.assertEqual(login.status_code, 200, login.text)
                    headers = {"Origin": "http://testserver", "X-CSRF-Token": login.json()["csrf_token"]}
                    costumes = client.get("/api/v1/asset-center/pose-gallery/costumes?safe=true", headers=headers)
                    self.assertEqual(costumes.status_code, 200, costumes.text)
                    self.assertEqual(costumes.json()["limit"], 24)
                    self.assertEqual(client.get("/api/v1/asset-center/pose-gallery/poses?view=bad", headers=headers).status_code, 422)
                    self.assertEqual(client.get("/api/v1/asset-center/pose-gallery/portraits?hot=true", headers=headers).json()["total"], 1)
                    pick = client.post("/api/v1/asset-center/pose-gallery/random", json={"slot": "recipe", "safe": True}, headers=headers)
                    self.assertEqual(set(pick.json()), {"portrait", "costume", "pose"})
                    media = client.get("/api/v1/asset-center/pose-gallery/media/thumbs/portrait/p0.webp")
                    self.assertEqual(media.status_code, 200)
                    self.assertEqual(media.headers["cache-control"], "private, max-age=3600")
                    self.assertEqual(media.headers["content-type"], "image/webp")
                    self.assertEqual(client.get("/api/v1/asset-center/pose-gallery/media/thumbs/%2e%2e/secret.json").status_code, 404)
                    # Provider proxy: same-origin session required, allow-list enforced, Bearer forwarded not rejected.
                    bearer = {**headers, "Authorization": "Bearer sk-test", "Content-Type": "application/json"}
                    self.assertEqual(client.post("/api/proxy", content=b"{}", headers={"Authorization": "Bearer sk-test"}).status_code, 403)
                    self.assertEqual(client.post("/api/proxy", content=b"{}", headers={**bearer, "x-target-url": "https://evil.example.com/x"}).status_code, 403)
                    self.assertEqual(client.post("/api/proxy", content=b"x" * (10 * 1024 * 1024 + 1),
                                                 headers={**bearer, "x-target-url": "https://api.openai.com/v1/images/edits"}).status_code, 413)
                    upstream = httpx.Response(200, json={"data": [{"url": "https://cdn.example/out.png"}]}, headers={"content-type": "application/json"})
                    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=upstream)) as forwarded:
                        relayed = client.post("/api/proxy", content=b'{"model":"gpt-image-1"}',
                                              headers={**bearer, "x-target-url": "https://api.openai.com/v1/images/edits"})
                    self.assertEqual(relayed.status_code, 200, relayed.text)
                    self.assertEqual(relayed.json()["data"][0]["url"], "https://cdn.example/out.png")
                    sent = forwarded.call_args
                    self.assertEqual(sent.args[0], "https://api.openai.com/v1/images/edits")
                    self.assertEqual(sent.kwargs["headers"]["authorization"], "Bearer sk-test")
                    self.assertNotIn("x-csrf-token", {k.lower() for k in sent.kwargs["headers"]})
                    # Other APIs still refuse Bearer credentials for UI login.
                    self.assertEqual(client.get("/api/v1/projects", headers={"Authorization": "Bearer sk-test"}).status_code, 403)
                    # ComfyUI relay reports an unreachable local server in Chinese without leaking credentials.
                    with patch("httpx.AsyncClient.request", new=AsyncMock(side_effect=httpx.ConnectError("refused"))):
                        comfy = client.get("/comfy/system_stats", headers={**headers, "Authorization": "Bearer comfy-token"})
                    self.assertEqual(comfy.status_code, 502)
                    self.assertIn("ComfyUI", comfy.json()["message"])
                    self.assertNotIn("comfy-token", comfy.text)
                    ok = httpx.Response(200, json={"system": {"comfyui_version": "0.3.60"}}, headers={"content-type": "application/json"})
                    with patch("httpx.AsyncClient.request", new=AsyncMock(return_value=ok)):
                        comfy = client.get("/comfy/system_stats", headers=headers)
                    self.assertEqual(comfy.json()["system"]["comfyui_version"], "0.3.60")
                    self.assertEqual(client.post("/comfy/prompt", json={}, headers={"X-CSRF-Token": headers["X-CSRF-Token"]}).status_code, 403)


if __name__ == "__main__":
    unittest.main()
