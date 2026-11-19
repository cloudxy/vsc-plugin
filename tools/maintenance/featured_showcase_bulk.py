"""Continuously recover an existing showcase inventory, with durable block receipts.

Run as a module with --root and --sync. Storage policy and inventory must already
exist in that root; this worker never copies media from an implicit fallback.
"""
import argparse
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import heapq
import json
import math
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import threading
import time
import urllib.error
import urllib.request

from tools.maintenance.featured_showcase import (
    CacheSync, cache_lock, file_sha256, media_bytes, now, probe, save_json,
    _extract_thumbnail, _is_jpeg,
)
from vsc.assets.featured_showcase import find_media, media_digest, media_paths, media_suffix
from tools.maintenance.featured_showcase_metrics import capacity_forecast


def transient_failure(exc):
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in (408, 425, 500, 502, 503, 504)
    return isinstance(exc, (TimeoutError, ConnectionError, urllib.error.URLError))


class Receipts:
    """One SQLite ledger; a block is recorded only after CacheSync fsyncs it."""

    def __init__(self, path):
        self.guard = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self.db.execute("CREATE TABLE IF NOT EXISTS receipts(digest TEXT PRIMARY KEY,record_json TEXT NOT NULL)")
        self.db.commit()
        # FSKit exFAT assigns a fresh file its stable identity after first close.
        # Reopen rather than bypassing SQLite's DBMOVED or locking protections.
        self.db.close()
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self.db.execute("PRAGMA synchronous=FULL")

    def load(self, digest):
        with self.guard:
            row = self.db.execute("SELECT record_json FROM receipts WHERE digest=?", (digest,)).fetchone()
            return json.loads(row[0]) if row else None

    def save(self, record):
        value = {k: v for k, v in record.items() if k not in ("fd", "part", "reserved", "failed")}
        with self.guard, self.db:
            self.db.execute("INSERT INTO receipts VALUES(?,?) ON CONFLICT(digest) DO UPDATE SET record_json=excluded.record_json",
                            (record["digest"], json.dumps(value)))

    def close(self):
        self.db.close()


def storage_policy(root):
    value = json.loads((Path(root) / "bulk-sync" / "storage-policy.json").read_text())
    floor = value["minimum_free_bytes"]
    if (value.get("allocation_mode") != "all_available_physical_space" or
            isinstance(floor, bool) or not isinstance(floor, int) or floor < 0):
        raise ValueError("Invalid explicit storage policy")
    if value.get("root") and Path(value["root"]).resolve() != Path(root).resolve():
        raise ValueError("Storage policy belongs to a different root")
    return floor


class BulkSync(CacheSync):
    def __init__(self, root, receipts, stop_event, **options):
        self.receipts = receipts
        self.floor = storage_policy(root)
        self.cluster = os.statvfs(root).f_frsize
        self.stop_reason = None
        super().__init__(root, 2**63-1, stop_event=stop_event, **options)

    def measure_media_bytes(self):
        return self.allocated if hasattr(self, "allocated") else media_bytes(self.root)

    def load_record(self, digest):
        return self.receipts.load(digest) or super().load_record(digest)

    def save_record(self, record):
        self.receipts.save(record)

    def prepare(self, item, remote):
        self.floor = storage_policy(self.root)
        available = max(0, shutil.disk_usage(self.root).free-self.floor-8*self.cluster-self.reserved)
        _, part = media_paths(self.root, item["url"])
        occupied = part.stat().st_blocks*512 if part.is_file() else 0
        required = max(0, math.ceil(remote["total"]/self.cluster)*self.cluster-occupied) if remote["total"] is not None else 1
        if required > available or not available:
            self.outcome(item, "space_deferred", total=remote["total"], needed_physical_bytes=required,
                         available_physical_bytes=available)
            return None
        self.budget = self.allocated+self.reserved+available
        record = super().prepare(item, remote)
        if record and record["total"] is None:
            old = record["reserved"]
            record["reserved"] = min(old, available)
            self.reserved -= old-record["reserved"]
        return record

    def fail(self, record, exc):
        super().fail(record, exc)
        with self.guard:
            self.outcomes[record["digest"]]["error_type"] = type(exc).__name__
            self.outcomes[record["digest"]]["retryable"] = transient_failure(exc)
        if getattr(exc, "code", None):
            with self.guard:
                self.outcomes[record["digest"]]["http_status"] = exc.code
        if getattr(exc, "code", None) == 429:
            self.stop_reason = "rate_limited"
            self.stop_event.set()


def run_rolling(sync, items, on_result, on_tick=lambda active: None, window=96, probe_workers=6, retry_delay=2):
    """Bound live files and jobs, refill immediately, finish each file independently.

    Only the caller thread prepares files, publishes outcomes and releases file
    descriptors. Transfer jobs share CacheSync's durable range implementation.
    """
    if window < 1 or probe_workers < 1:
        raise ValueError("Window and probe concurrency must be positive")
    iterator = iter(items)
    probes, transfers, active = {}, {}, {}
    ready = deque()
    retries = []
    exhausted = False

    def retry(item):
        attempt = item.get("_attempt", 0)
        if attempt >= 2 or sync.stop_event is not None and sync.stop_event.is_set():
            return False
        item = dict(item, _attempt=attempt+1)
        heapq.heappush(retries, (time.monotonic()+retry_delay*2**attempt, item["digest"], item))
        return True

    def publish(item):
        outcome = dict(sync.outcomes[item["digest"]])
        on_result(item, outcome)
        sync.outcomes.pop(item["digest"], None)
        sync.records.pop(item["digest"], None)

    def close_record(record):
        if record.get("fd") is not None:
            os.close(record["fd"])
            record["fd"] = None
        sync.reserved -= record["reserved"]
        record["reserved"] = 0

    def jobs(record):
        if not record["ranges"]:
            yield None
        else:
            for start in range(0, record["total"], sync.block_size):
                if str(start) not in record["completed"]:
                    yield (start, min(record["total"]-1, start+sync.block_size-1))

    with ThreadPoolExecutor(max_workers=probe_workers) as probing, ThreadPoolExecutor(max_workers=sync.workers) as downloading:
        try:
            while probes or transfers or active or retries or not exhausted:
                stopping = sync.stop_event is not None and sync.stop_event.is_set()
                while not stopping and len(probes) < probe_workers*2:
                    if retries and retries[0][0] <= time.monotonic():
                        item = heapq.heappop(retries)[2]
                    elif not exhausted and len(active)+len(probes)+len(retries) < window:
                        try:
                            item = next(iterator)
                        except StopIteration:
                            exhausted = True
                            break
                    else:
                        break
                    local = find_media(sync.root, item["url"])
                    if local is not None:
                        checksum = file_sha256(local)
                        sync.outcome(item, "local", bytes=local.stat().st_size, sha256=checksum,
                                     local_path=str(local.relative_to(sync.root)))
                        sync.save_record(dict(item, status="local", total=local.stat().st_size,
                                              sha256=checksum, local_path=str(local.relative_to(sync.root))))
                        publish(item)
                    else:
                        probes[probing.submit(probe, item["url"], sync.timeout)] = item
                for future in [f for f in probes if f.done()]:
                    item = probes.pop(future)
                    try:
                        remote = future.result()
                    except Exception as exc:
                        sync.outcome(item, "failed", error=str(exc)[:400], error_type=type(exc).__name__,
                                     http_status=getattr(exc, "code", None))
                        if getattr(exc, "code", None) == 429:
                            sync.stop_reason = "rate_limited"
                            sync.stop_event.set()
                        if transient_failure(exc) and retry(item):
                            continue
                        publish(item)
                        continue
                    if sync.stop_event is not None and sync.stop_event.is_set():
                        sync.outcome(item, "interrupted", total=remote["total"])
                        publish(item)
                        continue
                    with sync.guard:
                        record = sync.prepare(item, remote)
                        if record:
                            sync.allocate(record)
                    if record:
                        digest = item["digest"]
                        active[digest] = dict(item=item, record=record, jobs=iter(jobs(record)), running=0, exhausted=False)
                        ready.append(digest)
                    else:
                        publish(item)
                for future in [f for f in transfers if f.done()]:
                    digest = transfers.pop(future)
                    future.result()
                    active[digest]["running"] -= 1
                stopping = sync.stop_event is not None and sync.stop_event.is_set()
                # Round-robin admission: many blocks from a huge file cannot
                # occupy an unbounded executor queue ahead of other files.
                while ready and len(transfers) < sync.workers and not stopping:
                    digest = ready.popleft()
                    entry = active[digest]
                    if entry["record"]["failed"]:
                        entry["exhausted"] = True
                        continue
                    try:
                        job = next(entry["jobs"])
                    except StopIteration:
                        entry["exhausted"] = True
                        continue
                    ready.append(digest)
                    record = entry["record"]
                    future = downloading.submit(sync.fetch_full, record) if job is None else downloading.submit(sync.fetch_range, record, *job)
                    transfers[future] = digest
                    entry["running"] += 1
                for digest, entry in list(active.items()):
                    if entry["running"] or not (entry["exhausted"] or stopping or entry["record"]["failed"]):
                        continue
                    record = entry["record"]
                    if stopping and not record["failed"] and not entry["exhausted"]:
                        sync.outcome(record, "interrupted", total=record["total"])
                        record["status"] = "interrupted"
                        sync.save_record(record)
                    elif not record["failed"]:
                        sync.finish(record)
                    close_record(record)
                    outcome = sync.outcomes[digest]
                    if outcome.get("retryable") and retry(entry["item"]):
                        sync.records.pop(digest, None)
                    else:
                        publish(entry["item"])
                    del active[digest]
                ready = deque(d for d in ready if d in active)
                on_tick(dict(files=len(active), probes=len(probes), transfers=len(transfers)))
                if stopping and not probes and not transfers:
                    break
                pending = set(probes) | set(transfers)
                if pending:
                    wait(pending, timeout=.2, return_when=FIRST_COMPLETED)
                elif retries and not stopping:
                    time.sleep(min(.2, max(0, retries[0][0]-time.monotonic())))
        finally:
            # On an unexpected callback/IO failure, first stop and drain jobs;
            # never close an fd while another thread may still pwrite into it.
            if probes or transfers or active:
                if sync.stop_event is not None:
                    sync.stop_event.set()
                wait(set(probes) | set(transfers))
            for entry in active.values():
                close_record(entry["record"])


def video_canvases(db):
    """Video canvases that still have pending media, nearest to complete first.

    A canvas is one work: its video outputs and the canvas media that belongs to
    them. Global priority order would download every canvas's images before any
    of those videos, so admission stays inside one canvas until it is finished.
    """
    rows = db.execute("""SELECT d.work FROM dependencies d
        JOIN resources r ON r.digest=d.digest
        GROUP BY d.work
        HAVING SUM(r.sync_status='pending')>0 AND SUM(d.output_type LIKE 'video%')>0
        ORDER BY SUM(r.sync_status='local')*1.0/COUNT(*) DESC,
                 SUM(r.sync_status='pending') ASC, d.work""").fetchall()
    return [row[0] for row in rows]


def pending_for_canvas(db, work):
    """Pending media for one canvas. Do not start the next canvas until this ends."""
    last_priority, last_digest = -1, ""
    while True:
        rows = db.execute("""SELECT r.digest,r.url,r.priority FROM dependencies d
            JOIN resources r ON r.digest=d.digest
            WHERE d.work=? AND r.sync_status='pending'
              AND (r.priority>? OR (r.priority=? AND r.digest>?))
            ORDER BY r.priority,r.digest LIMIT 256""",
                          (work, last_priority, last_priority, last_digest)).fetchall()
        if not rows:
            return
        for digest, url, priority in rows:
            last_priority, last_digest = priority, digest
            yield dict(digest=digest, url=url, priority=priority, work=work)


def canvas_names(root):
    path = Path(root)/"catalog.json"
    if not path.is_file():
        return {}
    cards = json.loads(path.read_text()).get("cards") or {}
    return {key: value.get("name") or "" for key, value in cards.items() if isinstance(value, dict)}


def persist_outcome(db, item, outcome):
    status = outcome["status"]
    if status == "interrupted":
        status = "pending"
    if status in ("disk_space_skip", "budget_skip"):
        status = "space_deferred"
    with db:
        db.execute("""UPDATE resources SET sync_status=?,sync_error=?,known_bytes=COALESCE(?,known_bytes),
            local_path=COALESCE(?,local_path),sha256=COALESCE(?,sha256) WHERE digest=?""",
            (status, outcome.get("error"), outcome.get("bytes", outcome.get("total")),
             outcome.get("local_path"), outcome.get("sha256"), item["digest"]))
    return status


def thumbnail(root, item, mapping, sync):
    if media_suffix(item["url"]) not in (".mp4", ".mov", ".webm", ".m4v"):
        return False
    ffmpeg = shutil.which("ffmpeg")
    source = find_media(root, item["url"])
    if not ffmpeg or source is None:
        return False
    digest = media_digest("thumbnail:v1:"+item["digest"])
    target = root/"media"/digest[:2]/(digest+".jpg")
    if not _is_jpeg(target):
        temporary = target.with_name("."+digest+".thumbnail.part")
        if target.exists() or temporary.exists():
            return False
        available = min(1024**2, max(0, shutil.disk_usage(root).free-sync.floor-4*sync.cluster))
        if not available:
            return False
        target.parent.mkdir(exist_ok=True)
        try:
            _extract_thumbnail(ffmpeg, source, temporary, available)
            temporary.replace(target)
            sync.allocated += target.stat().st_size
        except Exception:
            return False
    mapping[item["digest"]] = target.name
    save_json(root/"thumbnails.json", mapping)
    return True


def run_worker(root, workers=32, window=96, timeout=30):
    root = Path(root).resolve(strict=True)
    task = root/"bulk-sync"
    location = json.loads((root/"storage-location.json").read_text())
    recorded_root = location.get("canvas_data_root", location.get("root", location.get("canonical_root")))
    if recorded_root and Path(recorded_root).resolve() != root:
        raise ValueError("Storage-location record disagrees with selected root")
    if location.get("required_volume") and not Path(location["required_volume"]).is_mount():
        raise ValueError("Required external volume is not mounted")
    storage_policy(root)  # Fail before opening any mutable ledger.
    stop = threading.Event()
    reason = {}

    def interrupt(signum, frame):
        reason["signal"] = signal.Signals(signum).name
        stop.set()

    previous = {s: signal.signal(s, interrupt) for s in (signal.SIGINT, signal.SIGTERM)}
    try:
        with cache_lock(root):
            db = sqlite3.connect(task/"inventory.sqlite3", timeout=30)
            db.execute("PRAGMA synchronous=FULL")
            receipts = Receipts(task/"download-receipts.sqlite3")
            sync = None
            state = dict(schema="vsc.featured-all-video-sync/v2", status="initialized", root=str(root),
                         pid=os.getpid(), started_at=now(), worker=str(Path(__file__).resolve()),
                         worker_sha256=file_sha256(Path(__file__)), inventory=str(task/"inventory.sqlite3"),
                         ledger=str(task/"download-receipts.sqlite3"), storage_policy=str(task/"storage-policy.json"),
                         full_scope_complete=False, network_route="direct_process_only",
                         tuning=dict(workers=workers, window=window, timeout=timeout),
                         capacity_note="Total content bytes require sampling. Loose-file allocation bounds are conditional on all resources being recovered.")
            prior_path = task/"state.json"
            if prior_path.is_file():
                with (task/"run-history.jsonl").open("a") as handle:
                    handle.write(prior_path.read_text().strip().replace("\n", "")+"\n")
                    handle.flush()
                    os.fsync(handle.fileno())
            started = time.monotonic()
            last_save = 0
            completed_bytes = 0
            completed_files = 0
            errors = Counter()
            rates = deque()
            estimate_path = task/"performance-audit"/"size-estimate.json"
            estimate = json.loads(estimate_path.read_text()) if estimate_path.is_file() else None
            try:
                # A prior stop may leave 'downloading'; these states are derived,
                # and the durable per-block receipt remains authoritative.
                with db:
                    db.execute("UPDATE resources SET sync_status='pending' WHERE sync_status IN ('space_deferred','interrupted','downloading')")
                    db.execute("""UPDATE resources SET sync_status='pending' WHERE sync_status='failed'
                        AND (sync_error LIKE '%timed out%' OR sync_error LIKE '%Connection reset%')""")
                counts = Counter(dict(db.execute("SELECT sync_status,COUNT(*) FROM resources GROUP BY sync_status")))
                # Direct routing is confined to this explicitly invoked process.
                urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))
                sync = BulkSync(root, receipts, stop, workers=workers, timeout=timeout)
                mapping = json.loads((root/"thumbnails.json").read_text()) if (root/"thumbnails.json").is_file() else {}

                def result(item, outcome):
                    nonlocal completed_bytes, completed_files
                    status = persist_outcome(db, item, outcome)
                    counts["pending"] -= 1
                    counts[status] += 1
                    with (task/"completion-events.jsonl").open("a") as journal:
                        journal.write(json.dumps(dict(digest=item["digest"], updated_at=now(), **outcome))+"\n")
                        journal.flush()
                        os.fsync(journal.fileno())
                    if status == "local":
                        completed_bytes += outcome["bytes"]
                        completed_files += 1
                        thumbnail(root, item, mapping, sync)
                    elif status not in ("pending", "space_deferred"):
                        errors[str(outcome.get("http_status") or outcome.get("error_type") or status)] += 1

                def tick(active, force=False):
                    nonlocal last_save
                    elapsed = time.monotonic()-started
                    if not force and elapsed-last_save < 5:
                        return
                    last_save = elapsed
                    rates.append((elapsed, sync.transferred))
                    while len(rates)>2 and rates[1][0] < elapsed-180:
                        rates.popleft()
                    measured = (sync.transferred-rates[0][1])/(elapsed-rates[0][0]) if elapsed>rates[0][0] else None
                    state.update(status="stopping" if stop.is_set() else "downloading", updated_at=now(),
                        elapsed_seconds=round(elapsed, 2), resource_statuses=dict(counts), active=active,
                        new_transfer_bytes=sync.transferred, new_completed_files=completed_files,
                        newly_completed_file_bytes=completed_bytes, media_bytes_accounted=sync.allocated,
                        reserve_free_bytes=sync.floor, disk_free_bytes=shutil.disk_usage(root).free,
                        failure_classes_this_run=dict(errors), effective_bytes_per_second=sync.transferred/max(1, elapsed),
                        recent_bytes_per_second=measured, recent_rate_window_seconds=elapsed-rates[0][0])
                    if estimate:
                        state["capacity_forecast"] = capacity_forecast(estimate, measured, state["disk_free_bytes"])
                        state["capacity_note"] = "Conditional sample estimate; continue within authorized physical space and preserve unfinished work."
                    save_json(task/"state.json", state)

                names = canvas_names(root)
                canvases = video_canvases(db)
                state["admission"] = "one_video_canvas_at_a_time"
                state["canvases_remaining"] = len(canvases)
                tick(dict(files=0, probes=0, transfers=0), True)
                for index, work in enumerate(canvases):
                    if stop.is_set():
                        break
                    state.update(current_canvas=work, current_canvas_name=names.get(work) or "",
                                 canvas_index=index+1, canvases_remaining=len(canvases)-index)
                    tick(dict(files=0, probes=0, transfers=0), True)
                    # run_rolling returns only after this canvas's admitted files finish.
                    run_rolling(sync, pending_for_canvas(db, work), result, tick, window=window)
                tick(dict(files=0, probes=0, transfers=0), True)
                final_status = (sync.stop_reason or "interrupted") if stop.is_set() else (
                    "needs_more_storage" if counts["space_deferred"] else
                    "finished_with_missing_sources" if any(v for k, v in counts.items() if k!="local") else "download_queue_complete")
                state.update(status=final_status, stop_signal=reason.get("signal"))
            except BaseException as exc:
                state.update(status="interrupted", error=type(exc).__name__+": "+str(exc))
                raise
            finally:
                state.update(updated_at=now(), disk_free_bytes=shutil.disk_usage(root).free,
                             full_scope_complete=False,
                             resource_statuses=dict(db.execute("SELECT sync_status,COUNT(*) FROM resources GROUP BY sync_status")))
                save_json(task/"state.json", state)
                db.close()
                receipts.close()
            return state
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--sync", action="store_true", help="Explicitly use the network and write media")
    parser.add_argument("--workers", type=int, default=32)
    parser.add_argument("--window", type=int, default=96)
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args(argv)
    if not args.sync:
        parser.error("Use --sync to explicitly resume the existing download inventory")
    if not 1 <= args.workers <= 64 or not 1 <= args.window <= 500 or not 0 < args.timeout <= 120:
        parser.error("Workers 1..64, window 1..500 and timeout 0..120 are required")
    print(json.dumps(run_worker(args.root, args.workers, args.window, args.timeout)), flush=True)


if __name__ == "__main__":
    main()
