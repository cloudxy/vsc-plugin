"""Real local HTTP transfers for the explicitly invoked canvas cache tool."""
import contextlib
import gzip
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from tools.maintenance.featured_showcase import (
    CacheSync, MANIFEST, PROGRESS, STATE, build_manifest, cache_lock,
    THUMBNAILS, file_sha256, generate_thumbnails, main, media_bytes, read_json,
)
from vsc.assets.featured_showcase import find_media, media_digest, media_paths


@contextlib.contextmanager
def origin(payload, ranges=True, known_length=True):
    state = {"payload": payload, "etag": '"version-1"', "requests": [],
             "interrupt": set(), "ranges": ranges, "known_length": known_length,
             "bad_range": False}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            content = state["payload"]
            requested = self.headers.get("Range", "")
            state["requests"].append((self.path, requested, self.headers.get("If-Match")))
            if self.headers.get("If-Match") not in (None, state["etag"]):
                self.send_response(412)
                self.end_headers()
                return
            match = re.fullmatch(r"bytes=(\d+)-(\d+)", requested) if state["ranges"] else None
            start, end = (int(match[1]), int(match[2])) if match else (0, len(content)-1)
            self.send_response(206 if match else 200)
            self.send_header("ETag", state["etag"])
            if state["known_length"]:
                self.send_header("Content-Length", str(end-start+1))
            if match:
                self.send_header("Content-Range", "bytes %d-%d/%d" % (start + int(state["bad_range"]), end, len(content)))
            self.end_headers()
            if (start, end) in state["interrupt"]:
                self.wfile.write(content[start:start+max(1, (end-start)//2)])
                self.wfile.flush()
                self.connection.shutdown(socket.SHUT_WR)
                return
            try:
                self.wfile.write(content[start:end+1])
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:%d/media" % server.server_port, state
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def snapshot(root, work, nodes, snapshot_id=7):
    folder = root / "processes"
    folder.mkdir(exist_ok=True)
    with gzip.open(folder / (work + ".json.gz"), "wt", encoding="utf-8") as handle:
        json.dump({"snapshotId": snapshot_id, "snapshot": {"nodes": nodes, "edges": []}}, handle)


def manifest_for(root, urls):
    snapshot(root, "work-a", [{"id": "node-%d" % i, "type": "video", "data": {"url": url}}
                              for i, url in enumerate(urls)])
    return build_manifest(root, ["work-a"])


class FeaturedShowcaseCache(unittest.TestCase):
    def test_custom_receipt_store_resumes_verified_blocks_without_per_file_ledgers(self):
        receipts = {}
        class ReceiptCache(CacheSync):
            def load_record(self, digest):
                return receipts.get(digest)

            def save_record(self, record):
                receipts[record["digest"]] = json.loads(json.dumps({
                    key: value for key, value in record.items()
                    if key not in ("fd", "part", "reserved", "failed")}))

        payload = b"abcdefghijkl"
        with tempfile.TemporaryDirectory() as temp, origin(payload) as (url, remote):
            root = Path(temp)
            manifest = manifest_for(root, [url])
            remote["interrupt"].add((4, 7))
            first = ReceiptCache(root, 100, workers=1, block_size=4).run(manifest, ["work-a"])
            self.assertEqual(first["outcomes"][media_digest(url)]["status"], "failed")
            remote["interrupt"].clear()
            remote["requests"].clear()
            second = ReceiptCache(root, 100, workers=1, block_size=4).run(manifest, ["work-a"])
            self.assertEqual(second["status"], "completed")
            self.assertEqual(find_media(root, url).read_bytes(), payload)
            self.assertEqual([r[1] for r in remote["requests"]], ["bytes=0-0", "bytes=4-7", "bytes=8-11"])
            ReceiptCache(root, 100, workers=1, block_size=4).run(manifest, ["work-a"])
            self.assertEqual(receipts[media_digest(url)]["status"], "local")
            self.assertFalse((root / STATE).exists())

    def test_legacy_serialized_outputs_are_outputs_in_inventory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            snapshot(root, "work-a", [{"nodeKey": "image-a", "type": 2,
                "position": {"positionX": "0", "positionY": "20"},
                "data": json.dumps({"type": "image", "url": ["https://example.test/a.png"]})}])
            item = build_manifest(root, ["work-a"])["works"]["work-a"]["media"][0]
            self.assertEqual(item["roles"], ["output"])
            self.assertEqual(item["output_type"], "image")
            self.assertEqual(item["occurrences"][0]["nodeId"], "image-a")

    def test_malformed_links_do_not_block_other_canvas_outputs(self):
        payload = b"valid-output-bytes"
        malformed = "https://[unfinished"
        with tempfile.TemporaryDirectory() as temp, origin(payload) as (url, _):
            root = Path(temp)
            snapshot(root, "work-a", [
                {"id": "valid", "type": "video", "data": {
                    "url": url, "params": {"prompt": "A guide mentions " + malformed}}},
                {"id": "invalid", "type": "image", "data": {"url": malformed}},
            ])
            manifest = build_manifest(root, ["work-a"])
            self.assertEqual({item["url"] for item in manifest["works"]["work-a"]["media"]},
                             {url, malformed})
            result = CacheSync(root, len(payload) * 2, workers=2).run(manifest, ["work-a"])
            self.assertEqual(find_media(root, url).read_bytes(), payload)
            self.assertEqual(result["outcomes"][media_digest(malformed)]["status"], "failed")
            self.assertEqual(result["works"]["work-a"]["local"], 1)
            self.assertEqual(result["works"]["work-a"]["remaining"], 1)

    def test_reference_owner_does_not_override_the_actual_output_media_type(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);video='https://example.test/clip.mp4'
            snapshot(root,'work-a',[
                {'id':'image','type':'image','data':{'params':{'videoList':[{'url':video}]}}},
                {'id':'video','type':'video','data':{'url':video}}])
            item=build_manifest(root,['work-a'])['works']['work-a']['media'][0]
            self.assertEqual(item['roles'],['reference','output'])
            self.assertEqual(item['output_type'],'video')

    def test_multi_canvas_budget_prioritizes_visible_image_outputs_before_video(self):
        payload=b'synthetic-media-bytes'
        with tempfile.TemporaryDirectory() as temp, origin(payload) as (url, _):
            root=Path(temp)
            video=url+'/first.mp4';image=url+'/second.png'
            snapshot(root,'work-a',[{'id':'video','type':'video','data':{'url':video}}])
            snapshot(root,'work-b',[{'id':'image','type':'image','data':{'url':image}}])
            manifest=build_manifest(root,['work-a','work-b'])
            result=CacheSync(root,len(payload),workers=2).run(manifest,['work-a','work-b'])
            self.assertIsNotNone(find_media(root,image))
            self.assertIsNone(find_media(root,video))
            self.assertEqual(result['outcomes'][media_digest(video)]['status'],'budget_skip')
            self.assertLessEqual(media_bytes(root),len(payload))

    def test_archive_identity_mismatch_preserves_manifest_and_sources_before_sync(self):
        for field, conflicting in (("templateUuid", "wrong-work"), ("snapshotId", 8)):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                manifest_for(root, ["https://example.test/old.mp4"])
                process = root / "processes" / "work-a.json.gz"
                source = root / "sources" / "process-detail" / "work-a-7.json"
                source.parent.mkdir(parents=True)
                detail = {"templateUuid": "work-a", "snapshotId": 7,
                          "snapshotData": json.dumps({"nodes": [{"id": "wrong", "data": {
                              "url": "https://example.test/wrong-version.mp4"}}]})}
                detail[field] = conflicting
                source.write_text(json.dumps({"data": {"detail": detail}}))
                originals = {path: path.read_bytes() for path in (root / MANIFEST, process, source)}
                with patch("urllib.request.urlopen", side_effect=AssertionError("Mismatch must fail before network")) as network:
                    with self.assertRaisesRegex(ValueError, "detail\\." + field + " does not match"):
                        build_manifest(root, ["work-a"])
                    with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stopped:
                        main(["--root", str(root), "--work", "work-a", "--sync"])
                    self.assertEqual(stopped.exception.code, 1)
                    network.assert_not_called()
                for path, original in originals.items():
                    self.assertEqual(path.read_bytes(), original)
                self.assertFalse((root / "media").exists())

    def test_archive_matching_identity_and_legacy_missing_fields_use_raw_snapshot(self):
        identities = ({"templateUuid": "work-a", "snapshotId": 7},
                      {"templateUuid": "work-a", "snapshotId": "7"}, {})
        for identity in identities:
            with self.subTest(identity=identity), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                snapshot(root, "work-a", [{"id": "old", "data": {"url": "https://example.test/old.mp4"}}])
                source = root / "sources" / "process-detail" / "work-a-7.json"
                source.parent.mkdir(parents=True)
                detail = dict(identity, snapshotData=json.dumps({"nodes": [{"id": "raw", "data": {
                    "url": "https://example.test/raw.mp4"}}]}))
                source.write_text(json.dumps({"data": {"detail": detail}}))
                manifest = build_manifest(root, ["work-a"])
                work = manifest["works"]["work-a"]
                self.assertEqual(work["source"], "sources/process-detail/work-a-7.json")
                self.assertEqual(work["media"][0]["url"], "https://example.test/raw.mp4")
                self.assertEqual(work["snapshotId"], 7)

    def test_inventory_prefers_raw_preserves_other_work_deduplicates_and_recovers_origin(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            remote = "https://example.test/movie?download=1"
            historical = "https://example.test/old.mp4"
            snapshot(root, "work-a", [{"id": "stale", "data": {"url": "https://example.test/stale.mp4"}}])
            snapshot(root, "work-b", [{"id": "b", "data": {"url": "https://example.test/b.mp4"}}])
            build_manifest(root, ["work-b"])
            source = root / "sources" / "process-detail" / "work-a-7.json"
            source.parent.mkdir(parents=True)
            local = "/featured-showcase-media/" + media_digest(historical) + ".mp4"
            raw = {"data": {"detail": {"snapshotData": json.dumps({"nodes": [{
                "id": "current", "type": "video", "data": {"url": [remote, remote],
                "params": {"imageList": [{"url": remote}]}, "poster": "https://example.test/p.jpg",
                "history": json.dumps([{"url": local}])}}]})}}}
            source.write_text(json.dumps(raw), encoding="utf-8")
            original = source.read_bytes()
            (root / "sources" / "origin-urls.txt").write_text(historical + "\n")
            with patch("urllib.request.urlopen", side_effect=AssertionError("Inventory must be offline")):
                manifest = build_manifest(root, ["work-a"])
            self.assertEqual(set(manifest["works"]), {"work-a", "work-b"})
            entries = {entry["url"]: entry for entry in manifest["works"]["work-a"]["media"]}
            self.assertEqual(set(entries), {remote, historical, "https://example.test/p.jpg"})
            self.assertEqual(entries[remote]["roles"], ["output", "reference"])
            self.assertEqual(len(entries[remote]["occurrences"]), 3)
            self.assertEqual(entries[remote]["occurrences"][1]["index"], 1)
            self.assertEqual(entries[historical]["roles"], ["history"])
            self.assertIn("history.<json>[0].url", entries[historical]["occurrences"][0]["path"])
            self.assertEqual(source.read_bytes(), original)
            self.assertFalse((root / "media").exists())

    def test_range_transfer_reuses_complete_and_records_whole_file_digest(self):
        payload = b"range-test-" * 300
        with tempfile.TemporaryDirectory() as temp, origin(payload) as (url, state):
            root = Path(temp)
            manifest = manifest_for(root, [url, url])
            with cache_lock(root):
                result = CacheSync(root, len(payload), workers=3, block_size=1024).run(manifest, ["work-a"])
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["works"]["work-a"]["total"], 1)
            target = find_media(root, url)
            self.assertEqual(target.read_bytes(), payload)
            ledger = read_json(root / STATE / (media_digest(url) + ".json"))
            self.assertEqual(ledger["sha256"], hashlib.sha256(payload).hexdigest())
            self.assertTrue(all(request[2] == '"version-1"' for request in state["requests"] if request[1] != "bytes=0-0"))
            state["requests"].clear()
            CacheSync(root, len(payload), block_size=1024).run(manifest, ["work-a"])
            self.assertEqual(state["requests"], [])

    def test_interrupted_range_resumes_only_verified_blocks_and_rechecks_tampering(self):
        payload = bytes(range(256)) * 12
        for tamper in (False, True):
            with self.subTest(tamper=tamper), tempfile.TemporaryDirectory() as temp, origin(payload) as (url, state):
                root = Path(temp)
                manifest = manifest_for(root, [url])
                state["interrupt"].add((1024, 2047))
                result = CacheSync(root, len(payload), workers=1, block_size=1024).run(manifest, ["work-a"])
                self.assertEqual(result["status"], "incomplete")
                self.assertEqual(result["works"]["work-a"]["remaining"], 1)
                self.assertIsNone(find_media(root, url))
                _, part = media_paths(root, url)
                ledger = read_json(root / STATE / (media_digest(url) + ".json"))
                self.assertEqual(set(ledger["completed"]), {"0"})
                if tamper:
                    with part.open("r+b") as handle:
                        handle.write(b"corrupt")
                state["interrupt"].clear()
                state["requests"].clear()
                result = CacheSync(root, len(payload), workers=1, block_size=1024).run(manifest, ["work-a"])
                self.assertEqual(result["status"], "completed")
                self.assertEqual(find_media(root, url).read_bytes(), payload)
                requested = [request[1] for request in state["requests"]]
                self.assertEqual("bytes=0-1023" in requested, tamper)

    def test_origin_version_change_keeps_partial_and_refuses_mixed_completion(self):
        payload = b"a" * 3072
        with tempfile.TemporaryDirectory() as temp, origin(payload) as (url, state):
            root = Path(temp)
            manifest = manifest_for(root, [url])
            state["interrupt"].add((1024, 2047))
            CacheSync(root, len(payload), workers=1, block_size=1024).run(manifest, ["work-a"])
            _, part = media_paths(root, url)
            before = part.read_bytes()
            state["etag"], state["payload"] = '"version-2"', b"b" * len(payload)
            state["interrupt"].clear()
            result = CacheSync(root, len(payload), workers=1, block_size=1024).run(manifest, ["work-a"])
            self.assertEqual(result["outcomes"][media_digest(url)]["status"], "version_changed")
            self.assertEqual(part.read_bytes(), before)
            self.assertIsNone(find_media(root, url))

    def test_budget_includes_existing_files_and_partials_and_prefers_outputs(self):
        payload = b"a" * 2048
        with tempfile.TemporaryDirectory() as temp, origin(payload) as (url, state):
            root = Path(temp)
            old = root / "media" / "old.bin"
            old.parent.mkdir()
            old.write_bytes(b"keep-existing")
            unknown_part = old.with_name("unknown.part")
            unknown_part.write_bytes(b"keep-part")
            base = media_bytes(root)
            snapshot(root, "work-a", [{"id": "r", "type": "video", "data": {
                "params": {"referenceUrl": url + "?ref"}, "url": url + "?output"}}])
            manifest = build_manifest(root, ["work-a"])
            result = CacheSync(root, base + len(payload), workers=2, block_size=1024).run(manifest, ["work-a"])
            self.assertIsNotNone(find_media(root, url + "?output"))
            self.assertIsNone(find_media(root, url + "?ref"))
            self.assertEqual(result["outcomes"][media_digest(url + "?ref")]["status"], "budget_skip")
            self.assertEqual(result["status"], "incomplete")
            self.assertEqual(result["works"]["work-a"]["remaining"], 1)
            self.assertLessEqual(media_bytes(root), base + len(payload))
            self.assertEqual(old.read_bytes(), b"keep-existing")
            self.assertEqual(unknown_part.read_bytes(), b"keep-part")

    def test_full_stream_fallback_and_unknown_length_cannot_exceed_cap(self):
        payload = b"stream-" * 500
        for known_length in (True, False):
            with self.subTest(known_length=known_length), tempfile.TemporaryDirectory() as temp, origin(
                    payload, ranges=False, known_length=known_length) as (url, state):
                root = Path(temp)
                manifest = manifest_for(root, [url])
                cap = len(payload) if known_length else len(payload)-1
                result = CacheSync(root, cap, workers=1, block_size=1024).run(manifest, ["work-a"])
                self.assertLessEqual(media_bytes(root), cap)
                if known_length:
                    self.assertEqual(result["status"], "completed")
                    self.assertEqual(file_sha256(find_media(root, url)), hashlib.sha256(payload).hexdigest())
                else:
                    self.assertEqual(result["status"], "incomplete")
                    self.assertIsNone(find_media(root, url))

    def test_zero_byte_complete_is_invalid_and_strict_content_range_is_required(self):
        payload = b"a" * 2048
        with tempfile.TemporaryDirectory() as temp, origin(payload) as (url, state):
            root = Path(temp)
            manifest = manifest_for(root, [url])
            target, _ = media_paths(root, url)
            target.touch()
            self.assertIsNone(find_media(root, url))
            state["bad_range"] = True
            result = CacheSync(root, len(payload), workers=1, block_size=1024).run(manifest, ["work-a"])
            self.assertEqual(result["status"], "incomplete")
            self.assertEqual(target.stat().st_size, 0)
            state["bad_range"] = False
            result = CacheSync(root, len(payload), workers=1, block_size=1024).run(manifest, ["work-a"])
            self.assertEqual(result["status"], "completed")
            self.assertEqual(find_media(root, url).read_bytes(), payload)

    def test_lock_prevents_another_writer_and_missing_snapshot_is_clear(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with cache_lock(root):
                with self.assertRaisesRegex(RuntimeError, "holds the cache lock"):
                    with cache_lock(root):
                        self.fail("A second writer obtained the lock")
            with self.assertRaisesRegex(FileNotFoundError, "Missing local canvas snapshot"):
                build_manifest(root, ["absent"])
            self.assertFalse((root / MANIFEST).exists())

    def test_cli_inventory_has_no_network_and_does_not_touch_legacy_progress(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            snapshot(root, "work-a", [{"id": "a", "data": {"url": "https://example.test/no-extension"}}])
            legacy = root / "download-progress.json"
            legacy.write_text("old progress\n")
            with patch("urllib.request.urlopen", side_effect=AssertionError("Offline inventory")):
                self.assertEqual(main(["--root", str(root), "--work", "work-a"]), 0)
            self.assertEqual(legacy.read_text(), "old progress\n")
            self.assertFalse((root / PROGRESS).exists())

    def test_origin_file_is_shared_between_works_and_invalidated_when_changed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "sources" / "origin-urls.txt"
            source.parent.mkdir()
            url = "https://example.test/shared.mp4"
            local = "/featured-showcase-media/" + media_digest(url) + ".mp4"
            source.write_text(url + "\n")
            for work in ("work-a", "work-b"):
                snapshot(root, work, [{"id": "a", "data": {"url": local}}])
            original_open = Path.open
            reads = []

            def track_open(path, *args, **kwargs):
                mode = args[0] if args else kwargs.get("mode", "r")
                if path.resolve() == source.resolve() and "r" in mode:
                    reads.append(path)
                return original_open(path, *args, **kwargs)

            with patch.object(Path, "open", track_open):
                manifest = build_manifest(root, ["work-a", "work-b"])
                build_manifest(root, ["work-b"])
                self.assertEqual(len(reads), 1)
                source.write_text(url + "\nhttps://example.test/new.jpg\n")
                build_manifest(root, ["work-a"])
                self.assertEqual(len(reads), 2)
            self.assertEqual(manifest["works"]["work-b"]["media"][0]["url"], url)

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is required for the real local video path")
    def test_thumbnail_cli_creates_actual_jpeg_offline_and_reuses_without_rehashing_video(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            url = "https://example.test/video.mp4"
            manifest_for(root, [url, url])
            video, _ = media_paths(root, url)
            subprocess.run([shutil.which("ffmpeg"), "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                            "color=c=blue:s=16x16:r=1", "-t", "1", "-c:v", "mpeg4", str(video)],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=30)
            before = video.read_bytes()
            cap = video.stat().st_size + 1024 ** 2
            with patch("urllib.request.urlopen", side_effect=AssertionError("Thumbnails must be offline")), patch(
                    "tools.maintenance.featured_showcase.file_sha256", side_effect=AssertionError("Do not rehash videos")):
                result = main(["--root", str(root), "--work", "work-a", "--thumbnails",
                               "--budget-gib", str(cap / 1024 ** 3)])
            self.assertEqual(result, 0)
            mapping = read_json(root / THUMBNAILS)
            filename = media_digest("thumbnail:v1:" + media_digest(url)) + ".jpg"
            self.assertEqual(mapping[media_digest(url)], filename)
            thumbnail = root / "media" / filename[:2] / filename
            payload = thumbnail.read_bytes()
            self.assertTrue(payload.startswith(b"\xff\xd8"))
            self.assertTrue(payload.endswith(b"\xff\xd9"))
            subprocess.run([shutil.which("ffmpeg"), "-nostdin", "-v", "error", "-xerror", "-i", str(thumbnail),
                            "-frames:v", "1", "-f", "null", "-"],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=30)
            modified = thumbnail.stat().st_mtime_ns
            with patch("subprocess.Popen", side_effect=AssertionError("Existing JPEG must be reused")):
                result = generate_thumbnails(root, read_json(root / MANIFEST), ["work-a"], cap)
            self.assertEqual(result["statuses"], {"reused": 1})
            self.assertEqual(thumbnail.stat().st_mtime_ns, modified)
            self.assertEqual(video.read_bytes(), before)

    def test_failed_or_non_jpeg_ffmpeg_output_is_never_registered(self):
        for exit_code in (0, 3):
            with self.subTest(exit_code=exit_code), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                url = "https://example.test/video.mp4"
                manifest = manifest_for(root, [url])
                video, _ = media_paths(root, url)
                video.write_bytes(b"existing-video")
                process = Mock(stdout=io.BytesIO(b"invalid-jpeg"))
                process.wait.return_value = exit_code
                process.poll.return_value = exit_code
                with patch("subprocess.Popen", return_value=process):
                    result = generate_thumbnails(root, manifest, ["work-a"], 1000, ffmpeg="mock-ffmpeg")
                self.assertEqual(result["status"], "incomplete")
                self.assertEqual(result["statuses"], {"failed": 1})
                self.assertFalse((root / THUMBNAILS).exists())
                self.assertEqual(video.read_bytes(), b"existing-video")
                self.assertEqual(len(list((root / "media").rglob("*.thumbnail.part"))), 1)

    def test_thumbnail_stream_budget_counts_prior_partials_and_stops_further_generation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            urls = ["https://example.test/one.mp4", "https://example.test/two.mp4"]
            manifest = manifest_for(root, urls)
            for url in urls:
                video, _ = media_paths(root, url)
                video.write_bytes(b"video")
            partial = root / "media" / "keep.part"
            partial.write_bytes(b"keep-partial")
            cap = media_bytes(root) + 4
            process = Mock(stdout=io.BytesIO(b"more-than-four-bytes"))
            process.wait.return_value = 0
            process.poll.return_value = 0
            with patch("subprocess.Popen", return_value=process) as popen:
                result = generate_thumbnails(root, manifest, ["work-a"], cap, ffmpeg="mock-ffmpeg")
            self.assertEqual(popen.call_count, 1)
            self.assertEqual(result["statuses"], {"budget_skip": 2})
            self.assertLessEqual(media_bytes(root), cap)
            self.assertEqual(partial.read_bytes(), b"keep-partial")
            self.assertFalse((root / THUMBNAILS).exists())


if __name__ == "__main__":
    unittest.main()
