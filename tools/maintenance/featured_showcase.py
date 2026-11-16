"""Inventory and explicitly recover the local featured-canvas media cache.

Run ``python -m tools.maintenance.featured_showcase --help``. The default only
reads local snapshots and writes an inventory; only ``--sync`` uses the network.
Raw API captures and legacy download ledgers are never rewritten.
"""
import argparse
import concurrent.futures
import contextlib
import datetime
import fcntl
from functools import lru_cache
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request

from vsc.assets.featured_showcase import (
    find_media, media_digest, media_paths, media_suffix, sniff_suffix,
)

BLOCK_SIZE = 4 * 1024 ** 2
READ_SIZE = 256 * 1024
MANIFEST = "canvas-media-manifest.json"
PROGRESS = "canvas-download-progress.json"
STATE = "canvas-download-state"
THUMBNAILS = "thumbnails.json"
THUMBNAIL_PROGRESS = "canvas-thumbnail-progress.json"
URLS = re.compile(r"https?://[^\s\"'<>\\]+")
LOCAL_URLS = re.compile(r"/featured-showcase-media/([a-f0-9]{64})(?:\.[a-zA-Z0-9]+)?")
SAFE_WORK = re.compile(r"[a-zA-Z0-9_-]{1,128}\Z")
CONTENT_RANGE = re.compile(r"bytes (\d+)-(\d+)/(\d+)\Z")
MEDIA_CONTEXT = re.compile(r"url|image|video|audio|media|src|file|poster|cover", re.I)


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_json(path, value):
    """Atomic replacement, with no durable-file deletion during recovery."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".writing")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


@contextlib.contextmanager
def cache_lock(root):
    """One inventory/sync writer per cache, also across independent processes."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".canvas-media.lock").open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Another canvas media inventory/sync holds the cache lock") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def file_sha256(path, start=0, length=None):
    checksum = hashlib.sha256()
    with Path(path).open("rb") as handle:
        handle.seek(start)
        while length is None or length > 0:
            chunk = handle.read(READ_SIZE if length is None else min(READ_SIZE, length))
            if not chunk:
                if length:
                    return None
                break
            checksum.update(chunk)
            if length is not None:
                length -= len(chunk)
    return checksum.hexdigest()


def media_bytes(root):
    media = Path(root) / "media"
    return sum(path.stat().st_size for path in media.rglob("*") if path.is_file()) if media.is_dir() else 0


@lru_cache(maxsize=2)
def _read_origins(path, signature):
    # Stream a potentially large provenance file; consumers treat this map as read-only.
    origins = {}
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            for url in URLS.findall(line):
                origins[media_digest(url)] = url
    return origins


def origin_urls(root):
    path = Path(root) / "sources" / "origin-urls.txt"
    try:
        stat = path.stat()
    except FileNotFoundError:
        return {}
    return _read_origins(str(path.resolve()), (stat.st_dev, stat.st_ino, stat.st_mtime_ns, stat.st_size))


def load_snapshot(root, work):
    """Prefer the unlocalized raw API response for this exact snapshot."""
    if SAFE_WORK.fullmatch(work) is None:
        raise ValueError("Invalid work ID")
    root = Path(root)
    process = root / "processes" / (work + ".json.gz")
    if not process.is_file():
        raise FileNotFoundError("Missing local canvas snapshot: " + str(process))
    with gzip.open(process, "rt", encoding="utf-8") as handle:
        record = json.load(handle)
    snapshot_id = record.get("snapshotId")
    source = process
    folder = root / "sources" / "process-detail"
    if snapshot_id is not None:
        candidate = folder / (work + "-" + str(snapshot_id) + ".json")
        if candidate.is_file():
            source = candidate
    else:
        candidates = sorted(folder.glob(work + "-*.json")) if folder.is_dir() else []
        if len(candidates) == 1:
            source = candidates[0]
    if source != process:
        raw = read_json(source)
        detail = raw.get("data", {}).get("detail", {})
        # Archive filenames are discovery hints, not proof of response identity.
        # Older captures omit these fields; explicit conflicting values are unsafe.
        if "templateUuid" in detail and detail["templateUuid"] != work:
            raise ValueError("Archive detail.templateUuid does not match requested work: " + str(source))
        if "snapshotId" in detail and str(detail["snapshotId"]) != str(snapshot_id):
            raise ValueError("Archive detail.snapshotId does not match local snapshot version: " + str(source))
        snapshot = detail.get("snapshotData")
        if snapshot_id is None:
            snapshot_id = detail.get("snapshotId")
    else:
        snapshot = record.get("snapshot", record.get("snapshotData"))
    if isinstance(snapshot, str):
        snapshot = json.loads(snapshot)
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("nodes"), list):
        raise ValueError("No canvas nodes in " + str(source))
    return snapshot, {"snapshotId": snapshot_id, "source": str(source.relative_to(root))}


def inventory_work(root, work, origins=None):
    snapshot, info = load_snapshot(root, work)
    if origins is None:
        origins = origin_urls(root)
    entries, unresolved = {}, []

    def walk(value, path, role, node_id, node_index, hint="", estimated=None, output_type="", slot_index=0):
        if not isinstance(estimated, (int, float)) or isinstance(estimated, bool) or estimated <= 0:
            estimated = None
        if isinstance(value, dict):
            size = value.get("byteSize")
            if isinstance(size, (float, int)) and not isinstance(size, bool) and size > 0:
                estimated = int(size)
            for key, child in value.items():
                label = str(key)
                next_role = role
                if "histor" in label.lower():
                    next_role = "history"
                elif re.search(r"poster|thumbnail|thumb|cover", label, re.I):
                    next_role = "poster"
                walk(child, path + "." + label, next_role, node_id, node_index,
                     hint + "." + label, estimated, output_type, slot_index)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, path + "[" + str(index) + "]", role, node_id, node_index,
                     hint, estimated, output_type, index)
        elif isinstance(value, str):
            # A few providers serialize task parameters/history as JSON strings.
            if value.lstrip().startswith(("{", "[")):
                try:
                    decoded = json.loads(value)
                except ValueError:
                    decoded = None
                if isinstance(decoded, (dict, list)):
                    walk(decoded, path + ".<json>", role, node_id, node_index, hint, estimated, output_type, slot_index)
                    return
            candidates = URLS.findall(value)
            for match in LOCAL_URLS.finditer(value):
                restored = origins.get(match.group(1))
                if restored:
                    candidates.append(restored)
                else:
                    unresolved.append({"localUrl": match.group(0), "digest": match.group(1),
                                       "role": role, "nodeId": node_id, "nodeIndex": node_index, "path": path})
            for index, url in enumerate(dict.fromkeys(candidates)):
                suffix = media_suffix(url)
                if not suffix and role not in ("output", "poster") and not MEDIA_CONTEXT.search(hint):
                    continue
                item = entries.setdefault(url, {"url": url, "digest": media_digest(url),
                                               "roles": [], "occurrences": [], "estimated_bytes": None,
                                               "suffix": suffix, "output_type": output_type})
                if role not in item["roles"]:
                    item["roles"].append(role)
                occurrence = {"role": role, "nodeId": node_id, "nodeIndex": node_index,
                              "index": slot_index, "path": path}
                if occurrence not in item["occurrences"]:
                    item["occurrences"].append(occurrence)
                if estimated:
                    item["estimated_bytes"] = max(item["estimated_bytes"] or 0, estimated)

    for index, node in enumerate(snapshot["nodes"]):
        if not isinstance(node, dict):
            continue
        node_id = node.get("id", "")
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        output_type = str(node.get("type") or data.get("type") or "")
        base = "snapshot.nodes[" + str(index) + "]"
        for key, value in node.items():
            if key == "data" and isinstance(value, dict):
                for field, child in value.items():
                    role = "output" if field == "url" else "reference"
                    if "histor" in field.lower():
                        role = "history"
                    elif re.search(r"poster|thumbnail|thumb|cover", field, re.I):
                        role = "poster"
                    walk(child, base + ".data." + field, role, node_id, index,
                         field, value.get("byteSize"), output_type)
            else:
                walk(value, base + "." + key, "reference", node_id, index, key, output_type=output_type)
    for key, value in snapshot.items():
        if key != "nodes":
            walk(value, "snapshot." + key, "reference", "", None, key)
    return dict(info, media=list(entries.values()), unresolved=unresolved, generated_at=now())


def build_manifest(root, works):
    root = Path(root)
    existing = read_json(root / MANIFEST) if (root / MANIFEST).is_file() else {}
    if existing and existing.get("schema") != "vsc.canvas-media-manifest/v1":
        raise ValueError("Unsupported existing canvas media manifest schema")
    manifest = {"schema": "vsc.canvas-media-manifest/v1", "works": dict(existing.get("works", {}))}
    # Build all requested snapshots before replacing a previous usable manifest.
    origins = origin_urls(root)
    additions = {work: inventory_work(root, work, origins) for work in dict.fromkeys(works)}
    manifest["works"].update(additions)
    manifest["updated_at"] = now()
    save_json(root / MANIFEST, manifest)
    return manifest


class OriginChanged(RuntimeError):
    pass


def request_headers(**extra):
    return {"User-Agent": "VSC-Canvas-Cache/1", "Accept": "*/*", "Accept-Encoding": "identity", **extra}


def probe(url, timeout=40):
    request = urllib.request.Request(url, headers=request_headers(Range="bytes=0-0"))
    with urllib.request.urlopen(request, timeout=timeout) as response:
        status = response.status
        etag = response.headers.get("ETag")
        modified = response.headers.get("Last-Modified")
        validator = etag if etag and not etag.startswith("W/") else None
        if status == 206:
            match = CONTENT_RANGE.fullmatch(response.headers.get("Content-Range", "").strip())
            if match is None or tuple(map(int, match.groups()[:2])) != (0, 0):
                raise OSError("Invalid probe Content-Range")
            total = int(match.group(3))
            if total <= 0 or len(response.read(2)) != 1:
                raise OSError("Invalid/empty media probe body")
            ranges = bool(validator or modified)
        elif status == 200:
            length = response.headers.get("Content-Length")
            total = int(length) if length is not None else None
            if total is not None and total <= 0:
                raise OSError("Empty media")
            ranges = False
        else:
            raise OSError("Unexpected media probe HTTP status " + str(status))
        return {"total": total, "etag": etag, "last_modified": modified, "ranges": ranges}


def conditional_headers(record):
    etag = record.get("etag")
    if etag and not etag.startswith("W/"):
        return {"If-Match": etag}
    if record.get("last_modified"):
        return {"If-Unmodified-Since": record["last_modified"]}
    return {}


def check_version(response, record):
    if record.get("etag") and response.headers.get("ETag") != record["etag"]:
        raise OriginChanged("Origin ETag changed or disappeared; preserved partial cannot be mixed")
    if record.get("last_modified") and response.headers.get("Last-Modified") != record["last_modified"]:
        raise OriginChanged("Origin Last-Modified changed or disappeared; preserved partial cannot be mixed")


class CacheSync:
    """A lock-owning CLI calls run(); tests can use a temporary isolated cache."""

    def __init__(self, root, budget_bytes, workers=12, block_size=BLOCK_SIZE, timeout=40):
        self.root = Path(root)
        self.budget = int(budget_bytes)
        self.workers = int(workers)
        self.block_size = block_size
        self.timeout = timeout
        self.guard = threading.RLock()
        self.records = {}
        self.outcomes = {}
        self.reserved = 0
        self.transferred = 0
        self.started = time.monotonic()
        self.allocated = media_bytes(root)
        if self.budget <= 0 or self.workers < 1 or block_size < 1:
            raise ValueError("Budget, workers and block size must be positive")

    def state_path(self, digest):
        return self.root / STATE / (digest + ".json")

    def save_record(self, record):
        save_json(self.state_path(record["digest"]), {key: value for key, value in record.items()
                                                    if key not in ("fd", "part", "reserved", "failed")})

    def outcome(self, item, status, **extra):
        self.outcomes[item["digest"]] = {"status": status, **extra}

    def prepare(self, item, remote):
        digest, url = item["digest"], item["url"]
        # Call media_paths only after a remote probe: inventory mode never creates media.
        _, part = media_paths(self.root, url)
        state_path = self.state_path(digest)
        prior = read_json(state_path) if state_path.is_file() else None
        size = part.stat().st_size if part.is_file() else 0
        if size and prior is None:
            self.outcome(item, "untracked_partial", error="Existing partial has no verified-block ledger; preserved")
            return None
        if size and prior:
            changed = any(prior.get(key) != remote.get(key) for key in ("total", "etag", "last_modified"))
            if changed:
                self.outcome(item, "version_changed", error="Origin version changed; partial and ledger preserved")
                return None
            if not remote["ranges"] and remote["total"] is None:
                self.outcome(item, "unresumable_partial", error="Origin cannot safely resume this partial; preserved")
                return None
        total = remote["total"]
        if total is not None and size > total:
            self.outcome(item, "invalid_partial", error="Existing partial exceeds probed length; preserved")
            return None
        available = max(0, self.budget - self.allocated - self.reserved)
        extra = max(0, total - size) if total is not None else available
        if extra > available or (total is None and not available):
            self.outcome(item, "budget_skip", total=total, needed_bytes=extra, available_bytes=available)
            return None
        record = {"schema": "vsc.canvas-media-part/v1", "digest": digest, "url": url,
                  **remote, "block_size": self.block_size, "completed": {}, "status": "pending",
                  "part": part, "reserved": extra, "failed": False}
        # Only hashes recorded after a full, synced block count as reusable bytes.
        if size and prior and remote["ranges"]:
            old_block = prior.get("block_size")
            if old_block != self.block_size:
                self.outcome(item, "invalid_partial", error="Partial block size differs; preserved")
                return None
            for offset, block in prior.get("completed", {}).items():
                try:
                    start = int(offset)
                    expected = min(self.block_size, total - start)
                    valid = (start >= 0 and start % self.block_size == 0 and expected > 0 and
                             block.get("bytes") == expected and
                             file_sha256(part, start, expected) == block.get("sha256"))
                except (ValueError, TypeError, AttributeError):
                    valid = False
                if valid:
                    record["completed"][offset] = block
        self.reserved += extra
        self.records[digest] = record
        self.outcome(item, "pending", total=total)
        self.save_record(record)
        return record

    def allocate(self, record):
        with self.guard:
            old_size = record["part"].stat().st_size if record["part"].is_file() else 0
            record["fd"] = os.open(record["part"], os.O_CREAT | os.O_RDWR, 0o600)
            if record["total"] is not None:
                os.ftruncate(record["fd"], record["total"])
                self.allocated += record["total"] - old_size
                self.reserved -= record["reserved"]
                record["reserved"] = 0
            record["status"] = "downloading"
            self.save_record(record)

    def fetch_range(self, record, start, end):
        if record["failed"]:
            return
        extra = conditional_headers(record)
        extra["Range"] = "bytes=" + str(start) + "-" + str(end)
        request = urllib.request.Request(record["url"], headers=request_headers(**extra))
        checksum, count = hashlib.sha256(), 0
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                check_version(response, record)
                expected = "bytes " + str(start) + "-" + str(end) + "/" + str(record["total"])
                if response.status != 206 or response.headers.get("Content-Range", "").strip() != expected:
                    raise OSError("Origin did not return the exact requested HTTP 206 byte range")
                while count < end - start + 1:
                    chunk = response.read(min(READ_SIZE, end - start + 1 - count))
                    if not chunk:
                        raise OSError("Interrupted HTTP byte range")
                    if os.pwrite(record["fd"], chunk, start + count) != len(chunk):
                        raise OSError("Incomplete local range write")
                    checksum.update(chunk)
                    count += len(chunk)
                    with self.guard:
                        self.transferred += len(chunk)
                if response.read(1):
                    raise OSError("Origin returned bytes beyond requested range")
            os.fsync(record["fd"])
            with self.guard:
                if record["failed"]:
                    return
                record["completed"][str(start)] = {"bytes": count, "sha256": checksum.hexdigest()}
                self.save_record(record)
        except Exception as exc:
            self.fail(record, exc)

    def fail(self, record, exc):
        with self.guard:
            version = isinstance(exc, OriginChanged) or isinstance(exc, urllib.error.HTTPError) and exc.code in (412, 416)
            status = "version_changed" if version else "failed"
            # A subsequent generic failure must not hide an origin-version conflict.
            if self.outcomes[record["digest"]]["status"] == "version_changed":
                status = "version_changed"
            record["failed"], record["status"] = True, status
            self.outcome(record, status, total=record["total"], error=str(exc)[:400])
            record["error"] = str(exc)[:400]
            self.save_record(record)

    def fetch_full(self, record):
        """One response, bounded writes, for origins without safe ranged access."""
        request = urllib.request.Request(record["url"], headers=request_headers(**conditional_headers(record)))
        count = 0
        limit = record["total"] if record["total"] is not None else record["reserved"]
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                check_version(response, record)
                if response.status != 200:
                    raise OSError("Expected HTTP 200 for full media transfer")
                length = response.headers.get("Content-Length")
                if length is not None and record["total"] is not None and int(length) != record["total"]:
                    raise OriginChanged("Origin length changed after probe")
                while True:
                    chunk = response.read(min(READ_SIZE, limit - count + 1))
                    if not chunk:
                        break
                    if count + len(chunk) > limit:
                        raise OSError("Full transfer exceeds reserved media budget/length")
                    if os.pwrite(record["fd"], chunk, count) != len(chunk):
                        raise OSError("Incomplete local full-media write")
                    count += len(chunk)
                    with self.guard:
                        self.transferred += len(chunk)
                        if record["total"] is None:
                            self.allocated += len(chunk)
                            self.reserved -= len(chunk)
                            record["reserved"] -= len(chunk)
                if not count or record["total"] is not None and count != record["total"]:
                    raise OSError("Interrupted/empty full-media response")
            os.fsync(record["fd"])
            with self.guard:
                self.reserved -= record["reserved"]
                record["reserved"] = 0
                record["total"] = count
                record["completed"] = {str(start): {"bytes": min(self.block_size, count-start),
                                                   "sha256": file_sha256(record["part"], start, min(self.block_size, count-start))}
                                       for start in range(0, count, self.block_size)}
                self.save_record(record)
        except Exception as exc:
            self.fail(record, exc)

    def finish(self, record):
        if record["failed"]:
            return
        total = record["total"]
        expected = range(0, total, self.block_size) if total else []
        if not total or any(str(start) not in record["completed"] for start in expected):
            self.fail(record, OSError("Media still has unverified blocks"))
            return
        os.fsync(record["fd"])
        os.close(record["fd"])
        record["fd"] = None
        with record["part"].open("rb") as handle:
            suffix = media_suffix(record["url"]) or sniff_suffix(handle.read(16))
        target, _ = media_paths(self.root, record["url"], suffix)
        if target.is_file() and target.stat().st_size:
            self.fail(record, OSError("Complete target appeared during sync; partial preserved"))
            return
        checksum = file_sha256(record["part"])
        record["part"].replace(target)
        record.update(status="local", sha256=checksum, local_path=str(target.relative_to(self.root)))
        self.save_record(record)
        self.outcome(record, "local", bytes=total, sha256=checksum, local_path=record["local_path"])

    def progress(self, manifest, works, status):
        with self.guard:
            coverage = {}
            for work in works:
                value = manifest["works"][work]
                counts, roles = {}, {}
                for item in value["media"]:
                    outcome = self.outcomes.get(item["digest"], {"status": "missing"})
                    key = outcome["status"]
                    counts[key] = counts.get(key, 0) + 1
                    for role in item["roles"]:
                        row = roles.setdefault(role, {"total": 0, "local": 0, "remaining": 0})
                        row["total"] += 1
                        row["local" if key == "local" else "remaining"] += 1
                missing = len(value.get("unresolved", []))
                local = counts.get("local", 0)
                coverage[work] = {"total": len(value["media"]), "local": local,
                                  "remaining": len(value["media"]) - local + missing,
                                  "unresolved_origins": missing, "statuses": counts, "roles": roles}
            result = {"schema": "vsc.canvas-media-progress/v1", "status": status,
                      "budget_bytes": self.budget, "allocated_media_bytes": self.allocated,
                      "reserved_bytes": self.reserved, "allocated_and_reserved_bytes": self.allocated + self.reserved,
                      "new_transfer_bytes": self.transferred, "works": coverage, "outcomes": dict(self.outcomes),
                      "elapsed_seconds": round(time.monotonic() - self.started, 2), "updated_at": now()}
            save_json(self.root / PROGRESS, result)
            return result

    def run(self, manifest, works):
        """Reuse cache, probe in parallel, reserve in priority order, then transfer."""
        selected = {}
        for work_index, work in enumerate(works):
            for item in manifest["works"][work]["media"]:
                rank = min({"output": 0, "reference": 1, "poster": 2, "history": 3}[r] for r in item["roles"])
                priority = (rank, work_index)
                if item["digest"] not in selected or priority < selected[item["digest"]][0]:
                    selected[item["digest"]] = (priority, item)
        ordered = [item for _, item in sorted(selected.values(), key=lambda pair: pair[0])]
        missing = []
        for item in ordered:
            local = find_media(self.root, item["url"])
            if local is not None:
                checksum = file_sha256(local)
                self.outcome(item, "local", bytes=local.stat().st_size, sha256=checksum,
                             local_path=str(local.relative_to(self.root)))
                save_json(self.state_path(item["digest"]), {"schema": "vsc.canvas-media-part/v1",
                          "digest": item["digest"], "url": item["url"], "status": "local",
                          "total": local.stat().st_size, "sha256": checksum,
                          "local_path": str(local.relative_to(self.root))})
            else:
                missing.append(item)
                self.outcome(item, "missing")
        if self.allocated > self.budget:
            for item in missing:
                self.outcome(item, "budget_skip", error="Existing cache already exceeds cap; no media written")
            return self.progress(manifest, works, "incomplete")
        stopped = threading.Event()

        def monitor():
            while not stopped.wait(5):
                self.progress(manifest, works, "running")

        monitor_thread = threading.Thread(target=monitor, daemon=True)
        monitor_thread.start()
        self.progress(manifest, works, "running")

        def probe_item(item):
            try:
                return probe(item["url"], self.timeout)
            except Exception as exc:
                return exc

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.workers) as pool:
                # executor.map preserves priority while network probes overlap.
                for item, remote in zip(missing, pool.map(probe_item, missing)):
                    with self.guard:
                        if isinstance(remote, Exception):
                            self.outcome(item, "failed", error=str(remote)[:400])
                        else:
                            record = self.prepare(item, remote)
                            if record:
                                self.allocate(record)
                # Interleave files so several large videos do not monopolize workers.
                jobs_by_file = []
                for record in self.records.values():
                    if record["ranges"]:
                        jobs_by_file.append([(record, start, min(record["total"]-1, start+self.block_size-1))
                                             for start in range(0, record["total"], self.block_size)
                                             if str(start) not in record["completed"]])
                    else:
                        jobs_by_file.append([(record, None, None)])
                import itertools
                futures = []
                for row in itertools.zip_longest(*jobs_by_file):
                    for job in row:
                        if job is None:
                            continue
                        record, start, end = job
                        futures.append(pool.submit(self.fetch_full, record) if start is None else
                                       pool.submit(self.fetch_range, record, start, end))
                for future in concurrent.futures.as_completed(futures):
                    future.result()
                for record in self.records.values():
                    self.finish(record)
        finally:
            stopped.set()
            monitor_thread.join()
            for record in self.records.values():
                if record.get("fd") is not None:
                    os.close(record["fd"])
                    record["fd"] = None
            # Partial allocations survive interruption and continue counting against cap.
            self.allocated = media_bytes(self.root)
            self.reserved = 0
            final = self.progress(manifest, works, "incomplete")
        if all(value["remaining"] == 0 for value in final["works"].values()):
            final = self.progress(manifest, works, "completed")
        return final


def _is_jpeg(path):
    """Check JPEG framing, positive dimensions, a scan and the end marker."""
    try:
        with Path(path).open("rb") as handle:
            size = os.fstat(handle.fileno()).st_size
            if size < 12 or handle.read(2) != b"\xff\xd8":
                return False
            frame = False
            while handle.tell() < size - 2:
                if handle.read(1) != b"\xff":
                    return False
                marker = handle.read(1)
                while marker == b"\xff":
                    marker = handle.read(1)
                length = int.from_bytes(handle.read(2), "big")
                if length < 2 or handle.tell() + length - 2 > size:
                    return False
                if marker in (b"\xc0", b"\xc1", b"\xc2", b"\xc3", b"\xc5", b"\xc6", b"\xc7",
                              b"\xc9", b"\xca", b"\xcb", b"\xcd", b"\xce", b"\xcf"):
                    data = handle.read(length-2)
                    frame = len(data) >= 5 and int.from_bytes(data[1:3], "big") > 0 and int.from_bytes(data[3:5], "big") > 0
                elif marker == b"\xda":
                    handle.seek(-2, os.SEEK_END)
                    return frame and handle.read(2) == b"\xff\xd9"
                else:
                    handle.seek(length-2, os.SEEK_CUR)
    except OSError:
        pass
    return False


class ThumbnailBudgetExceeded(RuntimeError):
    pass


def _extract_thumbnail(ffmpeg, source, temporary, available, timeout=60):
    """Bound stdout before disk writes; ffmpeg cannot overshoot the cache cap."""
    command = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(source),
               "-map", "0:v:0", "-frames:v", "1", "-vf", "scale=320:-2", "-q:v", "6",
               "-c:v", "mjpeg", "-f", "image2pipe", "pipe:1"]
    with Path(temporary).open("xb") as handle:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        timer = threading.Timer(timeout, process.kill)
        timer.daemon = True
        timer.start()
        count = 0
        try:
            while True:
                chunk = process.stdout.read(min(READ_SIZE, available-count+1))
                if not chunk:
                    break
                if count + len(chunk) > available:
                    raise ThumbnailBudgetExceeded("Thumbnail exceeded remaining media budget; stopped adding thumbnails")
                handle.write(chunk)
                count += len(chunk)
            handle.flush()
            os.fsync(handle.fileno())
            if process.wait(timeout=5) or not count:
                raise RuntimeError("ffmpeg failed or returned an empty thumbnail; partial preserved")
        finally:
            timer.cancel()
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
            process.stdout.close()
    if not _is_jpeg(temporary):
        raise RuntimeError("ffmpeg output is not a framed JPEG image; partial preserved")


def generate_thumbnails(root, manifest, works, budget_bytes, ffmpeg=None):
    """Generate local video-output posters while the caller holds cache_lock.

    The deterministic name is SHA256('thumbnail:v1:' + output URL digest) + '.jpg'.
    Existing cache files and failed temporary files remain part of the budget.
    No source media hashing or network access is needed for this local operation.
    """
    root = Path(root)
    mapping = read_json(root / THUMBNAILS) if (root / THUMBNAILS).is_file() else {}
    if not isinstance(mapping, dict):
        raise ValueError("thumbnails.json must map output digests to thumbnail filenames")
    candidates, outcomes = {}, {}
    videos = (".mp4", ".webm", ".mov", ".m4v")
    for work in works:
        for item in manifest["works"][work]["media"]:
            if "output" not in item["roles"]:
                continue
            source = find_media(root, item["url"])
            is_video = ("video" in item.get("output_type", "").lower() or
                        media_suffix(item["url"]) in videos or source is not None and source.suffix.lower() in videos)
            if not is_video and source is not None and source.suffix == ".bin":
                with source.open("rb") as handle:
                    is_video = sniff_suffix(handle.read(16)) in videos
            if is_video:
                candidates[item["digest"]] = (item, source)
    allocated, stopped, changed = media_bytes(root), False, False
    ffmpeg = ffmpeg or shutil.which("ffmpeg")
    for digest, (item, source) in candidates.items():
        thumbnail_digest = media_digest("thumbnail:v1:" + digest)
        filename = thumbnail_digest + ".jpg"
        folder = root / "media" / thumbnail_digest[:2]
        target, temporary = folder / filename, folder / ("." + thumbnail_digest + ".thumbnail.part")
        if _is_jpeg(target):
            mapping[digest] = filename
            changed = True
            outcomes[digest] = {"status": "reused", "filename": filename, "bytes": target.stat().st_size}
            continue
        if target.exists():
            outcomes[digest] = {"status": "failed", "error": "Existing thumbnail is not a framed JPEG; preserved"}
            continue
        if source is None:
            outcomes[digest] = {"status": "missing_media"}
            continue
        if temporary.exists():
            outcomes[digest] = {"status": "failed", "error": "Existing thumbnail partial preserved; no overwrite"}
            continue
        available = max(0, int(budget_bytes)-allocated)
        if stopped or not available:
            stopped = True
            outcomes[digest] = {"status": "budget_skip", "available_bytes": available}
            continue
        if not ffmpeg:
            outcomes[digest] = {"status": "failed", "error": "ffmpeg is not installed"}
            continue
        folder.mkdir(parents=True, exist_ok=True)
        try:
            _extract_thumbnail(ffmpeg, source, temporary, available)
            temporary.replace(target)
            mapping[digest] = filename
            changed = True
            outcomes[digest] = {"status": "generated", "filename": filename, "bytes": target.stat().st_size}
            # Persist each successful thumbnail so an interruption keeps prior results usable.
            save_json(root / THUMBNAILS, mapping)
        except ThumbnailBudgetExceeded as exc:
            stopped = True
            outcomes[digest] = {"status": "budget_skip", "error": str(exc), "available_bytes": available}
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            outcomes[digest] = {"status": "failed", "error": str(exc)[:400]}
        allocated = media_bytes(root)
    if changed:
        save_json(root / THUMBNAILS, mapping)
    statuses = {}
    for outcome in outcomes.values():
        statuses[outcome["status"]] = statuses.get(outcome["status"], 0) + 1
    result = {"schema": "vsc.canvas-thumbnail-progress/v1", "budget_bytes": int(budget_bytes),
              "allocated_media_bytes": media_bytes(root), "total": len(candidates), "statuses": statuses,
              "remaining": sum(outcome["status"] not in ("reused", "generated") for outcome in outcomes.values()),
              "outcomes": outcomes, "updated_at": now()}
    result["status"] = "completed" if not result["remaining"] else "incomplete"
    save_json(root / THUMBNAIL_PROGRESS, result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("assets/featured-showcase"))
    parser.add_argument("--work", action="append", required=True, help="Canvas work ID; repeat to select more works")
    parser.add_argument("--budget-gib", type=float, default=30, help="Cap for all root/media bytes including partials (default: 30)")
    parser.add_argument("--workers", type=int, default=12, help="Concurrent network workers (default: 12)")
    parser.add_argument("--sync", action="store_true", help="Explicitly allow network probes and downloads")
    parser.add_argument("--thumbnails", action="store_true", help="Locally generate/reuse 320px JPEG posters for selected video outputs")
    args = parser.parse_args(argv)
    if not 1 <= args.workers <= 128 or not args.budget_gib > 0 or not args.budget_gib < float("inf"):
        parser.error("workers must be 1..128 and budget-gib must be finite and positive")
    try:
        if not args.root.is_dir():
            raise FileNotFoundError("Missing featured-showcase data root: " + str(args.root))
        with cache_lock(args.root):
            works = list(dict.fromkeys(args.work))
            manifest = build_manifest(args.root, works)
            exit_code = 0
            if args.sync:
                result = CacheSync(args.root, int(args.budget_gib * 1024 ** 3), args.workers).run(manifest, works)
                print(json.dumps({key: value for key, value in result.items() if key != "outcomes"}, ensure_ascii=False), flush=True)
                exit_code = 0 if result["status"] == "completed" else 2
            if args.thumbnails:
                result = generate_thumbnails(args.root, manifest, works, int(args.budget_gib * 1024 ** 3))
                print(json.dumps({key: value for key, value in result.items() if key != "outcomes"}, ensure_ascii=False), flush=True)
                return max(exit_code, 0 if result["status"] == "completed" else 2)
            if args.sync:
                return exit_code
            print(json.dumps({"status": "inventory", "manifest": str(args.root / MANIFEST),
                              "works": {work: {"media": len(manifest["works"][work]["media"]),
                                               "unresolved_origins": len(manifest["works"][work]["unresolved"])}
                                        for work in works}}, ensure_ascii=False), flush=True)
            return 0
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, "featured-showcase: " + str(exc) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
