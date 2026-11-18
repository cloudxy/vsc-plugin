"""Rolling admission, graceful recovery and honest forecasts for bulk caching."""
import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
from unittest.mock import patch

from tools.maintenance.featured_showcase import CacheSync
from tools.maintenance.featured_showcase_bulk import BulkSync, Receipts, run_rolling
from tools.maintenance.featured_showcase_metrics import forecast, eta, sample_sizes, capacity_forecast
from vsc.assets.featured_showcase import media_digest
from vsc.assets.featured_showcase import find_media


@contextlib.contextmanager
def range_origin():
    payload = b"abcdefghijkl"
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            requested = self.headers["Range"]
            requests.append(requested)
            start, end = map(int, requested.removeprefix("bytes=").split("-"))
            self.send_response(206)
            self.send_header("ETag", '"fixed"')
            self.send_header("Content-Length", str(end-start+1))
            self.send_header("Content-Range", "bytes %d-%d/12" % (start, end))
            self.end_headers()
            self.wfile.write(payload[start:end+1])

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:%d/media" % server.server_port, payload, requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


class FeaturedShowcaseBulk(unittest.TestCase):
    def test_transient_range_retry_reuses_verified_receipt(self):
        with tempfile.TemporaryDirectory() as folder, range_origin() as (url, payload, requests):
            root = Path(folder)
            (root/"bulk-sync").mkdir()
            (root/"bulk-sync"/"storage-policy.json").write_text(json.dumps(dict(
                allocation_mode="all_available_physical_space", minimum_free_bytes=100)))
            receipts = Receipts(root/"bulk-sync"/"receipts.sqlite3")

            class OneTimeout(BulkSync):
                once = True

                def fetch_range(self, record, start, end):
                    if start==4 and self.once:
                        self.once = False
                        self.fail(record, TimeoutError("timed out"))
                    else:
                        super().fetch_range(record, start, end)

            try:
                sync = OneTimeout(root, receipts, threading.Event(), workers=1, block_size=4)
                results = []
                item = dict(digest=media_digest(url), url=url)
                run_rolling(sync, [item], lambda item, result: results.append(result), probe_workers=1, retry_delay=.001)
                self.assertEqual(find_media(root, url).read_bytes(), payload)
                self.assertEqual(requests, ["bytes=0-0", "bytes=0-3", "bytes=0-0", "bytes=4-7", "bytes=8-11"])
                self.assertEqual(len(results), 1)
                self.assertEqual(results[0]["status"], "local")
            finally:
                receipts.close()

    def test_transient_probe_retries_are_bounded_and_do_not_hide_permanent_403(self):
        with tempfile.TemporaryDirectory() as folder, range_origin() as (url, payload, _):
            sync = CacheSync(folder, 100, workers=1, stop_event=threading.Event())
            item = dict(digest=media_digest(url), url=url)
            results = []
            from tools.maintenance.featured_showcase import probe
            outcomes = [TimeoutError("timed out"), TimeoutError("timed out"), probe(url)]
            with patch("tools.maintenance.featured_showcase_bulk.probe", side_effect=outcomes) as request:
                run_rolling(sync, [item], lambda item, result: results.append(result), probe_workers=1, retry_delay=.001)
            self.assertEqual(request.call_count, 3)
            self.assertEqual(find_media(Path(folder), url).read_bytes(), payload)
            self.assertEqual(len(results), 1)
            missing = dict(digest="unavailable", url="https://example.test/forbidden")
            exc = urllib.error.HTTPError(missing["url"], 403, "Forbidden", {}, None)
            with patch("tools.maintenance.featured_showcase_bulk.probe", side_effect=exc) as request:
                run_rolling(sync, [missing], lambda item, result: results.append(result), probe_workers=1, retry_delay=.001)
            self.assertEqual(request.call_count, 1)
            self.assertEqual(results[-1]["http_status"], 403)
            with patch("tools.maintenance.featured_showcase_bulk.probe", side_effect=TimeoutError("timed out")) as request:
                run_rolling(sync, [missing], lambda item, result: results.append(result), probe_workers=1, retry_delay=.001)
            self.assertEqual(request.call_count, 3)
            self.assertEqual(results[-1]["status"], "failed")

    def test_sampler_journal_resumes_without_reprobing_finished_cohort(self):
        with tempfile.TemporaryDirectory() as folder, range_origin() as (url, _, requests):
            root = Path(folder)
            task = root/"bulk-sync"
            task.mkdir()
            with sqlite3.connect(task/"inventory.sqlite3") as db:
                db.execute("CREATE TABLE resources(digest,url,priority,sync_status,known_bytes)")
                db.execute("INSERT INTO resources VALUES(?,?,0,'pending',NULL)", (media_digest(url), url))
            first = sample_sizes(root, workers=1)
            second = sample_sizes(root, workers=1)
            self.assertEqual(requests, ["bytes=0-0"])
            self.assertEqual(first["estimated_remaining_bytes_assuming_accessible_sizes"], 12)
            self.assertEqual(second["sampled_resources"], 1)
            self.assertTrue(second["sample_complete"])
            projection = capacity_forecast(dict(second, recorded_at="fixed"), 2, 4)
            self.assertEqual(projection["content_only_seconds_for_estimated_scope"], 6)
            self.assertEqual(projection["content_only_seconds_to_use_free_bytes"], 2)

    def test_stop_keeps_synced_blocks_and_resume_fetches_only_remaining_ranges(self):
        with tempfile.TemporaryDirectory() as folder, range_origin() as (url, payload, requests):
            root = Path(folder)
            stop = threading.Event()

            class StopAfterFirstBlock(CacheSync):
                def save_record(self, record):
                    super().save_record(record)
                    if record.get("completed"):
                        stop.set()

            item = dict(digest=media_digest(url), url=url)
            results = []
            first = StopAfterFirstBlock(root, 100, block_size=4, workers=1, stop_event=stop)
            run_rolling(first, [item], lambda item, outcome: results.append(outcome), probe_workers=1)
            self.assertEqual(results[0]["status"], "interrupted")
            self.assertIsNone(find_media(root, url))
            self.assertEqual(requests, ["bytes=0-0", "bytes=0-3"])
            requests.clear()
            second = CacheSync(root, 100, block_size=4, workers=1, stop_event=threading.Event())
            run_rolling(second, [item], lambda item, outcome: results.append(outcome), probe_workers=1)
            self.assertEqual(find_media(root, url).read_bytes(), payload)
            self.assertEqual(results[-1]["status"], "local")
            self.assertEqual(requests, ["bytes=0-0", "bytes=4-7", "bytes=8-11"])

    def test_rate_limit_stops_admission_and_reports_http_status(self):
        with tempfile.TemporaryDirectory() as folder:
            sync = CacheSync(folder, 100, workers=1, stop_event=threading.Event())
            sync.stop_reason = None
            items = [dict(digest=str(i), url="https://example.test/"+str(i)) for i in range(20)]
            results = []
            exc = urllib.error.HTTPError(items[0]["url"], 429, "Too Many Requests", {}, None)
            with patch("tools.maintenance.featured_showcase_bulk.probe", side_effect=exc) as request:
                run_rolling(sync, items, lambda item, outcome: results.append(outcome), window=1, probe_workers=1)
            self.assertEqual(request.call_count, 1)
            self.assertTrue(sync.stop_event.is_set())
            self.assertEqual(sync.stop_reason, "rate_limited")
            self.assertEqual(results[0]["http_status"], 429)

    def test_unknown_probe_failures_are_not_counted_as_zero_byte_media(self):
        report = forecast({"0": 100}, [
            dict(stratum="0", total=100), dict(stratum="0", total=300),
            dict(stratum="0", http_status=403)])
        self.assertEqual(report["estimated_remaining_bytes_assuming_accessible_sizes"], 20000)
        self.assertEqual(report["failed_sample_sizes_unknown"], 1)
        self.assertFalse(report["all_sample_sizes_known"])
        self.assertEqual(eta(0, 100), 0)
        self.assertIsNone(eta(100, 0))

    def test_unsampled_strata_cannot_be_reported_as_complete(self):
        report = forecast({"0": 100, "2": 10}, [dict(stratum="0", total=100)])
        self.assertEqual(report["unestimated_strata"], ["2"])
        self.assertFalse(report["strata_covered"])

    def test_fast_files_finish_and_refill_while_slow_probe_and_transfer_are_held(self):
        entered_probe, entered_transfer = threading.Event(), threading.Event()
        release_probe, release_transfer, third_done = threading.Event(), threading.Event(), threading.Event()
        urls = ["https://example.test/"+name for name in ("slow-probe", "slow-transfer", "fast", "third")]
        items = [dict(digest=media_digest(u), url=u) for u in urls]
        results = []

        class ControlledCache(CacheSync):
            def prepare(self, item, remote):
                record = dict(item, ranges=False, failed=False, reserved=0)
                self.records[item["digest"]] = record
                return record

            def allocate(self, record):
                pass

            def fetch_full(self, record):
                if record["url"].endswith("slow-transfer"):
                    entered_transfer.set()
                    release_transfer.wait(4)

            def finish(self, record):
                self.outcome(record, "local")

        def controlled_probe(url, timeout):
            if url.endswith("slow-probe"):
                entered_probe.set()
                release_probe.wait(4)
            return dict(total=1, ranges=False)

        def result(item, outcome):
            results.append(item["url"])
            if item["url"].endswith("third"):
                third_done.set()

        with tempfile.TemporaryDirectory() as folder:
            sync = ControlledCache(folder, 100, workers=2, stop_event=threading.Event())
            with patch("tools.maintenance.featured_showcase_bulk.probe", controlled_probe):
                thread = threading.Thread(target=run_rolling, args=(sync, items, result), kwargs=dict(window=3, probe_workers=2))
                thread.start()
                try:
                    self.assertTrue(entered_probe.wait(1))
                    self.assertTrue(entered_transfer.wait(1))
                    self.assertTrue(third_done.wait(2), results)
                    self.assertNotIn(urls[0], results)
                    self.assertNotIn(urls[1], results)
                finally:
                    release_probe.set()
                    release_transfer.set()
                    thread.join(5)
                self.assertFalse(thread.is_alive())
                self.assertCountEqual(results, urls)
                self.assertEqual(sync.records, {})

    def test_storage_policy_fails_closed_and_large_file_does_not_block_small_one(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            task = root/"bulk-sync"
            task.mkdir()
            policy = dict(allocation_mode="all_available_physical_space", minimum_free_bytes=100)
            (task/"storage-policy.json").write_text(json.dumps(policy))
            receipts = Receipts(task/"receipts.sqlite3")
            try:
                sync = BulkSync(root, receipts, threading.Event())
                sync.cluster = 1
                remote = dict(total=1000, ranges=True, etag='"1"', last_modified=None)
                with patch("tools.maintenance.featured_showcase_bulk.shutil.disk_usage") as usage:
                    usage.return_value.free = 500
                    large = dict(digest=media_digest("https://example.test/large"), url="https://example.test/large")
                    self.assertIsNone(sync.prepare(large, remote))
                    self.assertEqual(sync.outcomes[large["digest"]]["status"], "space_deferred")
                    small = dict(digest=media_digest("https://example.test/small"), url="https://example.test/small")
                    self.assertIsNotNone(sync.prepare(small, dict(remote, total=10)))
                (task/"storage-policy.json").write_text(json.dumps(dict(policy, minimum_free_bytes=True)))
                with self.assertRaises(ValueError):
                    sync.prepare(small, remote)
                receipts.save(dict(digest="receipt", completed={"0": dict(bytes=4, sha256="verified")}, fd=5))
            finally:
                receipts.close()
            reopened = Receipts(task/"receipts.sqlite3")
            try:
                self.assertEqual(reopened.load("receipt")["completed"]["0"]["bytes"], 4)
                self.assertNotIn("fd", reopened.load("receipt"))
            finally:
                reopened.close()


if __name__ == "__main__":
    unittest.main()
