"""Resumable stratified size sampling; estimates explicitly retain unknowns."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import random
import shutil
import signal
import sqlite3
import statistics
import threading
import time
import urllib.request

from tools.maintenance.featured_showcase import now, probe, save_json


def forecast(strata, rows, known_missing_bytes=0, seed=20261118, repetitions=600):
    """Extrapolate measured sizes, conditional on unmeasured URLs being similar.

    A timeout/403 is an unknown size, never a zero-byte file. The bootstrap
    describes sampling variability among measured sizes, not source recovery.
    """
    grouped = defaultdict(list)
    for row in rows:
        if row.get("attempted", True):
            grouped[str(row["stratum"])].append(row)
    rng = random.Random(seed)
    details, missing = {}, []
    draws = [float(known_missing_bytes)] * repetitions
    point = float(known_missing_bytes)
    failed = 0
    for key, population in strata.items():
        values = grouped[str(key)]
        good = [r["total"] for r in values if isinstance(r.get("total"), int) and not isinstance(r["total"], bool) and r["total"] > 0]
        unknown = len(values)-len(good)
        failed += unknown
        detail = dict(population=population, sampled=len(values), sized=len(good), unknown_sizes=unknown,
                      failure_codes=dict(Counter(str(r.get("http_status") or r.get("error_type") or "unknown_length")
                                                 for r in values if not r.get("total"))))
        details[str(key)] = detail
        if not good:
            missing.append(str(key))
            continue
        estimate = population*statistics.mean(good)
        point += estimate
        for index in range(repetitions):
            draws[index] += population*sum(rng.choice(good) for _ in good)/len(good)
        detail.update(mean_sized_bytes=statistics.mean(good), median_sized_bytes=statistics.median(good),
                      largest_sized_bytes=max(good), estimated_bytes_assuming_accessible_sizes=round(estimate))
    draws.sort()
    return dict(method="Stratified random sample; extrapolate measured sizes within each stratum",
        known_missing_bytes=known_missing_bytes, estimated_remaining_bytes_assuming_accessible_sizes=round(point),
        conditional_bootstrap_95_percent_bytes=[round(draws[int(repetitions*.025)]), round(draws[min(repetitions-1, int(repetitions*.975))])],
        strata=details, unestimated_strata=missing, strata_covered=not missing,
        failed_sample_sizes_unknown=failed, all_sample_sizes_known=not missing and failed==0,
        limitations=["Assumes inaccessible and unprobed objects have similar sizes to measured objects within their stratum.",
            "Bootstrap interval omits availability bias and unseen heavy tails; it is not a capacity guarantee.",
            "Unknown/expired sources are not zero bytes and are not proven recoverable.",
            "Known lengths and sampled lengths are full object sizes; existing verified partial blocks are not deducted.",
            "Content bytes exclude filesystem allocation, thumbnails, receipts and other disk overhead."])


def sample_sizes(root, per_large=64, per_other=32, workers=12, seed=20261118, stop_event=None):
    root = Path(root).resolve(strict=True)
    folder = root/"bulk-sync"/"performance-audit"
    folder.mkdir(parents=True, exist_ok=True)
    cohort_path = folder/"size-sample-cohort.json"
    raw_path = folder/"size-sample-results.jsonl"
    # One sampler owns both cohort and append-only results. The downloader uses
    # a different lock and can continue while these read-only probes run.
    from tools.maintenance.featured_showcase import cache_lock
    with cache_lock(folder):
        if cohort_path.is_file():
            cohort = json.loads(cohort_path.read_text())
            if cohort["root"] != str(root):
                raise ValueError("Sample belongs to a different root")
        else:
            connection = sqlite3.connect("file:"+str(root/"bulk-sync"/"inventory.sqlite3")+"?mode=ro", uri=True, timeout=30)
            try:
                known = connection.execute("SELECT COALESCE(SUM(known_bytes),0) FROM resources WHERE sync_status!='local' AND known_bytes IS NOT NULL").fetchone()[0]
                values = connection.execute("SELECT digest,url,priority FROM resources WHERE sync_status!='local' AND known_bytes IS NULL").fetchall()
            finally:
                connection.close()
            grouped = defaultdict(list)
            for digest, url, priority in values:
                grouped[str(priority)].append((digest, url))
            rng = random.Random(seed)
            selected = []
            for key, group in sorted(grouped.items()):
                chosen = rng.sample(group, min(len(group), per_large if key in ("0", "2") else per_other))
                selected.extend(dict(stratum=key, digest=digest, url=url) for digest, url in chosen)
            cohort = dict(root=str(root), seed=seed, created_at=now(), known_missing_bytes=known,
                          populations={key: len(group) for key, group in grouped.items()}, selected=selected)
            save_json(cohort_path, cohort)
        rows = {}
        if raw_path.is_file():
            for line in raw_path.read_text().splitlines():
                try:
                    row = json.loads(line)
                    rows[row["digest"]] = row
                except (ValueError, KeyError):
                    # An abrupt power loss can truncate the final append; the
                    # missing digest is probed again, prior raw bytes retained.
                    continue
        selected = [item for item in cohort["selected"] if item["digest"] not in rows]
        stop = stop_event or threading.Event()
        rate_limited = threading.Event()
        # This is an explicitly invoked standalone CLI, not the web process.
        urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))

        def measure(item):
            if stop.is_set():
                return None
            row = {key: item[key] for key in ("stratum", "digest")}
            start = time.monotonic()
            try:
                row.update(probe(item["url"], timeout=15))
            except Exception as exc:
                row.update(error_type=type(exc).__name__, error=str(exc)[:250], http_status=getattr(exc, "code", None))
                if getattr(exc, "code", None)==429:
                    rate_limited.set()
                    stop.set()
            row["seconds"] = time.monotonic()-start
            return row

        started = time.monotonic()
        with raw_path.open("a") as journal, ThreadPoolExecutor(max_workers=workers) as pool:
            # Ensure a previously truncated append cannot swallow a new JSON row.
            journal.write("\n")
            for future in as_completed([pool.submit(measure, item) for item in selected]):
                row = future.result()
                if row is None:
                    continue
                rows[row["digest"]] = row
                journal.write(json.dumps(row)+"\n")
                journal.flush()
                os.fsync(journal.fileno())
                save_json(folder/"size-sample-progress.json", dict(done=len(rows), total=len(cohort["selected"]),
                         rate_limited=rate_limited.is_set(), interrupted=stop.is_set(), updated_at=now()))
        result = forecast(cohort["populations"], list(rows.values()), cohort["known_missing_bytes"], cohort["seed"])
        result.update(seed=cohort["seed"], cohort_created_at=cohort["created_at"], recorded_at=now(),
                      elapsed_seconds_this_run=time.monotonic()-started, unknown_resources=sum(cohort["populations"].values()),
                      sampled_resources=len(rows), selected_resources=len(cohort["selected"]),
                      sample_complete=len(rows)==len(cohort["selected"]), rate_limited=rate_limited.is_set(),
                      interrupted=stop.is_set(), raw_results=str(raw_path))
        result["disk_free_bytes"] = shutil.disk_usage(root).free
        unit = os.statvfs(root).f_frsize
        result["filesystem_allocation_unit_bytes"] = unit
        result["conditional_unknown_loose_file_allocation_lower_bound_bytes"] = result["unknown_resources"]*unit
        result["allocation_bound_condition"] = "Every unknown resource becomes a distinct nonempty loose file; existing allocated partial clusters are not deducted."
        save_json(folder/"size-estimate.json", result)
        return result


def eta(remaining, bytes_per_second):
    if remaining is None or remaining < 0 or not bytes_per_second or bytes_per_second <= 0:
        return None
    return remaining/bytes_per_second


def capacity_forecast(estimate, bytes_per_second, free_bytes):
    """Conditional duration scenarios; storage exhaustion is not completion."""
    interval = estimate["conditional_bootstrap_95_percent_bytes"]
    return dict(size_estimate_recorded_at=estimate["recorded_at"],
        estimated_remaining_bytes_assuming_accessible_sizes=estimate["estimated_remaining_bytes_assuming_accessible_sizes"],
        conditional_size_interval_bytes=interval, observed_bytes_per_second=bytes_per_second,
        content_only_seconds_for_estimated_scope=eta(estimate["estimated_remaining_bytes_assuming_accessible_sizes"], bytes_per_second),
        conditional_scope_seconds_interval=[eta(n, bytes_per_second) for n in interval],
        content_only_seconds_to_use_free_bytes=eta(free_bytes, bytes_per_second),
        limitations="Assumes unchanged speed and recoverable sources; excludes allocation overhead and already transferred partial bytes; free-space exhaustion is not full completion.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--sample", action="store_true")
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--per-large", type=int, default=64)
    parser.add_argument("--per-other", type=int, default=32)
    args = parser.parse_args(argv)
    if not args.sample:
        parser.error("Use --sample to explicitly probe remote sizes")
    if not 1<=args.workers<=32 or min(args.per_large, args.per_other)<1:
        parser.error("Positive sample sizes and 1..32 workers are required")
    stop = threading.Event()
    previous = {s: signal.signal(s, lambda signum, frame: stop.set()) for s in (signal.SIGINT, signal.SIGTERM)}
    try:
        print(json.dumps(sample_sizes(args.root, args.per_large, args.per_other, args.workers, stop_event=stop)), flush=True)
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


if __name__ == "__main__":
    main()
