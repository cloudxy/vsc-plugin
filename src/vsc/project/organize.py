#!/usr/bin/env python3
"""Evidence-bound, read-only legacy project organization preview.

Current and historical references outrank recovery and reproducible previews.
Extensions and directory names never establish that bytes may be reclaimed.
"""
import hashlib
import json
from pathlib import Path


CATEGORIES = ("current", "history", "backup", "renewable", "unknown")


def organize_preview(project, inventory=None):
    """Consume migration.inventory's state/facts/files, without migrating or deleting."""
    project = Path(project).resolve()
    if inventory is None and (project / ".vsc-postgres.json").exists():
        raise ValueError("项目已切换 PostgreSQL 权威；须提供关系库固定引用清单，不能用旧镜像整理")
    if inventory is None and (project / "vsc.json").is_file():
        from vsc.project.migration import inventory as legacy_inventory
        inventory = legacy_inventory(project)
    snapshot = inventory or {}
    state, issues = snapshot.get("state", {}), list(snapshot.get("issues", []))
    files = {row["path"]: dict(row) for row in snapshot.get("files", [])
             if isinstance(row, dict) and isinstance(row.get("path"), str)}
    for path in sorted(project.rglob("*")):
        if path.is_file() or path.is_symlink():
            relative = path.relative_to(project).as_posix()
            files.setdefault(relative, {"path": relative})
    evidence = {relative: [] for relative in files}
    digests = {}

    def sha(path):
        stat = path.stat()
        key = (str(path), stat.st_size, stat.st_mtime_ns)
        if key not in digests:
            value = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    value.update(block)
            digests[key] = value.hexdigest()
        return digests[key]

    def local(relative):
        if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
            return None
        path = project / relative
        if any(part.is_symlink() for part in (path, *path.parents) if part != project.parent):
            return None
        return path if path.is_file() else None

    def mark(relative, category, consumer, reason, digest=None):
        if relative not in files:
            return
        path = local(relative)
        valid = bool(path)
        if digest and path:
            valid = sha(path) == digest
        evidence[relative].append({"category": category, "consumer": consumer, "reason": reason,
                                   "sha256": digest, "bytes_verified": valid})

    def references(value, category, consumer):
        if isinstance(value, dict):
            if isinstance(value.get("path"), str):
                mark(value["path"], category, consumer, "固定内容引用", value.get("sha256"))
            for key in ("inputs_sha256", "outputs_sha256"):
                if isinstance(value.get(key), dict):
                    for relative, digest in value[key].items():
                        mark(relative, category, consumer, "恢复请求的输入/输出凭据", digest)
            for child in value.values():
                references(child, category, consumer)
        elif isinstance(value, list):
            for child in value:
                references(child, category, consumer)

    artifacts = {row.get("id"): row for row in state.get("artifacts", []) if isinstance(row, dict)}
    roots = {key for key, row in artifacts.items() if not row.get("superseded_by")
             and row.get("status") not in {"rejected", "revoked", "superseded"}}
    for obj in state.get("objects", []):
        if isinstance(obj, dict):
            roots.update(ref for ref in (obj.get("artifact"), obj.get("artifact_id")) if ref in artifacts)
    current = set()
    def visit(identifier):
        if identifier in current or identifier not in artifacts:
            return
        current.add(identifier)
        for dependency in artifacts[identifier].get("depends_on", []):
            visit(dependency)
    for identifier in roots:
        visit(identifier)
    for identifier, row in artifacts.items():
        category = "current" if identifier in current else "history"
        references(row, category, identifier)
        path = local(row.get("path"))
        if path and row.get("sha256") == sha(path) and path.stat().st_size <= 8 * 1024 * 1024:
            try:
                references(json.loads(path.read_bytes()), category, identifier)
            except (ValueError, UnicodeDecodeError):
                pass
    for source in state.get("sources", []):
        if isinstance(source, dict):
            references(source, "history" if source.get("superseded_by") else "current", "source:" + str(source.get("id")))
    for event in state.get("events", []):
        if isinstance(event, dict) and event.get("event") in {"schema_migrated", "profile_migrated"} and event.get("backup"):
            mark(event["backup"], "backup", "event:" + str(event.get("id")), "权威事件记录的恢复备份")

    # SQLite inventory facts retain typed media/provenance information. A
    # generation derivation alone is never evidence of free reproducibility.
    facts = [fact for fact in snapshot.get("facts", []) if isinstance(fact, dict)]
    media = {fact["payload"].get("id"): fact["payload"] for fact in facts
             if fact.get("category") == "sqlite:media_assets" and isinstance(fact.get("payload"), dict)}
    derivatives = set()
    for fact in facts:
        row = fact.get("payload", {})
        if fact.get("category") != "sqlite:asset_derivations" or not isinstance(row, dict):
            continue
        try:
            params = json.loads(row.get("parameters", "{}")) if isinstance(row.get("parameters"), str) else row.get("parameters", {})
        except ValueError:
            continue
        if not isinstance(params, dict):
            continue
        child, parent = media.get(row.get("child_id")), media.get(row.get("parent_id"))
        if (child and parent and row.get("relation") in {"thumbnail", "poster", "waveform", "proxy_video", "document_pages"}
                and params.get("recipe_version") == "vsc-preview-v1" and params.get("source_sha256") == parent.get("sha256")
                and local(parent.get("path")) and sha(local(parent["path"])) == parent.get("sha256")):
            derivatives.add(child.get("id"))
            mark(child.get("path"), "renewable", fact.get("key"), "固定原始字节与本地预览配方可重建", child.get("sha256"))
    for identifier, row in media.items():
        if identifier not in derivatives:
            references(row, "history", "media:" + str(identifier))
    generation = {fact["payload"].get("id"): fact["payload"] for fact in facts
                  if fact.get("category") == "sqlite:generation_jobs" and isinstance(fact.get("payload"), dict)}
    for fact in facts:
        row, category = fact.get("payload", {}), fact.get("category")
        if not isinstance(row, dict):
            continue
        if category == "sqlite:media_bindings":
            kind = "history" if row.get("status") in {"rejected", "retired"} else "current"
            references(row, kind, fact.get("key"))
            references(media.get(row.get("media_id")), kind, fact.get("key"))
        elif category in {"sqlite:generation_jobs", "sqlite:generated_assets"}:
            job = row if category == "sqlite:generation_jobs" else generation.get(row.get("job_id"), {})
            kind = "current" if job.get("run_artifact_id") in current else "history"
            references(row, kind, fact.get("key"))
            references(media.get(row.get("media_id")), kind, fact.get("key"))

    for relative in files:
        path = local(relative)
        if relative in {"vsc.json", ".vsc-series.sqlite3", ".vsc-postgres.json"}:
            mark(relative, "current", "project-authority", "项目权威或显式权威指针")
        if not path or path.stat().st_size > 8 * 1024 * 1024:
            continue
        # Only established recovery protocols confer recovery semantics. A file
        # called backup.mp4 or placed under .vsc-local is otherwise unknown.
        if Path(relative).parts[0] not in {".vsc-production", ".vsc-migration", ".vsc-migration.json"}:
            continue
        try:
            document = json.loads(path.read_bytes())
        except (ValueError, UnicodeDecodeError):
            continue
        if not isinstance(document, dict):
            continue
        if document.get("format") == "vsc.production-journal/v1" and isinstance(document.get("jobs"), dict):
            mark(relative, "backup", relative, "生产队列恢复凭据；不能按临时文件清理")
            references(document, "backup", relative)
        elif document.get("status") in {"backed_up", "frozen", "imported", "compared", "cut_over"} and document.get("migration_id") and isinstance(document.get("backup_files"), list):
            mark(relative, "backup", relative, "显式迁移恢复记录")
            for row in document["backup_files"]:
                mark(str(Path(document.get("backup", "")) / row["path"]), "backup", relative, "迁移原始备份", row.get("sha256"))

    buckets = {category: [] for category in CATEGORIES}
    details = []
    for relative, row in sorted(files.items()):
        refs = evidence[relative]
        category = next((kind for kind in CATEGORIES[:-1] if any(ref["category"] == kind for ref in refs)), "unknown")
        if any(not ref["bytes_verified"] for ref in refs):
            # Missing/drifted evidence never becomes a reclamation suggestion.
            if category == "renewable":
                category = "unknown"
            issues.append("引用字节缺失或漂移，须保留核查：" + relative)
        buckets[category].append(relative)
        path = local(relative)
        details.append({**row, "category": category, "sha256": sha(path) if path else row.get("sha256"),
                        "size_bytes": path.stat().st_size if path else row.get("size_bytes"), "references": refs})
    return {"format": "vsc.organize-preview/v1", "project": str(project), "read_only": True,
        "counts": {key: len(value) for key, value in buckets.items()}, "files": buckets, "details": details, "issues": issues,
        "actions": {"current": "正式或当前引用：保留；删除前须核对消费者", "history": "历史版本：保留或归档；不自动删除",
                    "backup": "备份与恢复凭据：保留可恢复字节；不自动删除", "renewable": "有固定来源与本地配方的派生预览：核对引用后可重建；本预览不执行回收",
                    "unknown": "未知归属：人工核对后归类；不自动删除"},
        "meaning": "预览不计为清理完成；不删除任何文件；批准与恢复引用保持可读"}


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="旧项目整理预览（只读五分类；预览不计为清理完成）")
    parser.add_argument("project")
    args = parser.parse_args(argv)
    try:
        result = organize_preview(args.project)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
