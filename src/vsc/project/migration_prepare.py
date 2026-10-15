"""Prepare typed, reviewable legacy manifests without changing authority.

File paths classify storage evidence only. Creative relationships come from
registered objects and immutable documents, never from directory/file names.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import codecs
from datetime import datetime
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import tempfile
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from vsc.project import migration as M

PARSER = "legacy-relations/v1"
NO_REASON = "迁移保留原人工决定；原记录无备注"
SUBTYPES = {"work": "works", "episode": "episodes", "scene": "scenes",
            "sequence": "sequences", "shot": "shots", "asset": "asset_identities"}
PARENTS = {"episode": "work", "scene": "episode", "sequence": "scene", "shot": "sequence"}
ASSET_KINDS = {"character", "location", "prop", "voice", "style", "costume"}
LEGACY_ASSET_KINDS = {"object": "prop", "creature": "prop"}


def _document(path):
    try:
        value = json.loads(path.read_bytes())
        return value if isinstance(value, dict) else {}
    except (ValueError, UnicodeDecodeError):
        return {}


def _mpeg_audio_frame(head):
    if len(head) < 4 or head[0] != 0xFF or head[1] & 0xE0 != 0xE0:
        return False
    return ((head[1] >> 3) & 3) != 1 and ((head[1] >> 1) & 3) != 0 and ((head[2] >> 4) & 15) not in {0, 15} and ((head[2] >> 2) & 3) != 3 and (head[3] & 3) != 2


def classify_file(path):
    """Describe bytes/storage class without assigning a creative purpose."""
    with path.open("rb") as stream:
        head = stream.read(512)
    suffix = path.suffix.lower()
    context_mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    mime = "application/octet-stream"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif head.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    elif head.startswith((b"GIF87a", b"GIF89a")):
        mime = "image/gif"
    elif head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        mime = "image/webp"
    elif head.startswith(b"RIFF") and head[8:12] == b"WAVE":
        mime = "audio/wav"
    elif head.startswith(b"FORM") and head[8:12] in (b"AIFF", b"AIFC"):
        mime = "audio/aiff"
    elif head[4:8] == b"ftyp":
        mime = "video/mp4"
    elif head.startswith(b"ID3") or _mpeg_audio_frame(head):
        mime = "audio/mpeg"
    elif head.startswith(b"OggS"):
        mime = "video/ogg" if b"theora" in head else "audio/ogg"
    elif head.startswith(b"fLaC"):
        mime = "audio/flac"
    elif head.startswith(b"#!AMR\n"):
        mime = "audio/amr"
    elif len(head) >= 4 and head[0] == 0xFF and head[1] & 0xF6 == 0xF0 and (head[2] >> 2) & 15 < 13:
        mime = "audio/aac"
    elif head.startswith(b"%PDF"):
        mime = "application/pdf"
    elif head.startswith(b"PK\x03\x04"):
        mime = "application/zip"
    elif head.startswith((b"\x00\x01\x00\x00", b"OTTO")):
        mime = "font/ttf" if head.startswith(b"\x00\x01") else "font/otf"
    elif b"\x00" not in head:
        try:
            codecs.getincrementaldecoder("utf-8")().decode(head, final=False)
            mime = "text/plain"
            if head.lstrip().startswith((b"{", b"[")) and path.stat().st_size <= 64 * 1024 * 1024:
                try:
                    json.loads(path.read_bytes())
                    mime = "application/json"
                except (ValueError, UnicodeDecodeError):
                    pass
        except UnicodeDecodeError:
            pass
    if any(part in {"__pycache__", "node_modules", ".cache", ".pytest_cache"} for part in path.parts) or suffix in {".pyc", ".lock", ".log", ".backup"} or path.name == ".DS_Store":
        category = "cache"
    elif suffix in {".py", ".js", ".ts", ".tsx", ".css", ".html", ".ttf", ".otf", ".zip", ".lock"} or path.name in {"package.json", "package-lock.json", "tsconfig.json"}:
        category = "engineering"
    elif mime.startswith(("image/", "video/", "audio/")):
        category = mime.split("/", 1)[0]
    else:
        category = "document"
    modality = mime.split("/", 1)[0] if mime.startswith(("image/", "video/", "audio/")) else "text" if mime.startswith("text/") else "document" if category == "document" else "other"
    return {"mime_type": mime, "context_mime_type": context_mime, "classification": category, "modality": modality}


class Preparation:
    def __init__(self, project, actor, work_code=None, structure=None, media_root=None, media_prefix=None, archive_media=False, source_timezone="Asia/Shanghai"):
        if not isinstance(actor, str) or not actor.strip():
            raise M.MigrationError("prepare 必须明确登记操作人 --by")
        self.project, self.actor = Path(project).resolve(), actor
        try:
            self.source_zone = ZoneInfo(source_timezone)
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            raise M.MigrationError("源时间约定必须是有效 IANA timezone") from None
        seed = M.preview(self.project)
        self.manifest = seed["manifest"]
        self.target = self.manifest["target_project_id"]
        self.state = json.loads(self.manifest["tables"]["artifact_versions"][0]["document"]["utf8"])["state"]
        self.snapshot = {"source": seed["source"], "state": self.state, "facts": self.manifest["inventory"],
                         "files": [f["payload"] for f in self.manifest["inventory"] if f["category"] == "file"], "issues": seed["issues"]}
        self.facts = {f["key"]: f for f in self.snapshot["facts"]}
        self.files = {f["path"]: f for f in self.snapshot["files"]}
        self.tables, self.ids = self.manifest["tables"], self.manifest["id_mapping"]
        self.rows, self.documents, self.artifacts = {}, {}, {}
        self.objects = {o["id"]: o for o in self.state.get("objects", [])}
        self.media, self.blobs, self.file_sources = {}, {}, {}
        self.alias_media = {}
        self.candidates, self.operations = {}, {}
        self.blockers, self.warnings = [], []
        self.sequence = 0
        self.work_code, self.structure = work_code, structure or {}
        if archive_media and not media_root:
            raise M.MigrationError("--archive-media 必须指定 --media-root")
        if media_root:
            requested_root = Path(media_root).absolute()
            if any(path.is_symlink() for path in (requested_root, *requested_root.parents)):
                raise M.MigrationError("受控媒体根目录不能通过符号链接访问")
        self.media_root = Path(media_root).resolve() if media_root else self.project.parent
        self.media_prefix = media_prefix if media_prefix is not None else "blobs" if media_root else None
        if self.media_prefix is not None and (Path(self.media_prefix).is_absolute() or ".." in Path(self.media_prefix).parts or "\\" in self.media_prefix):
            raise M.MigrationError("媒体对象键前缀不能越过受控根目录")
        self.archive_media = archive_media
        self.manifest["media_root"] = str(self.media_root)
        self.manifest["preparation"] = {"version": PARSER, "actor": actor, "structure": self.structure,
            "work_code": work_code, "original_parents": {o["id"]: o.get("parent") for o in self.objects.values()},
            "technical_containers": [], "file_inventory": [], "legacy_unbound": [], "legacy_unindexed": [],
            "type_mapping": {"legacy_asset_kinds": LEGACY_ASSET_KINDS}, "source_timezone": source_timezone,
            "time_interpretation": "legacy local wall time; explicit workspace convention; source strings remain unchanged",
            "original_naive_timestamps": []}

    def ident(self, domain, key):
        value = str(uuid.uuid5(uuid.UUID(self.target), domain + ":" + str(key)))
        self.ids[domain + ":" + str(key)] = value
        return value

    def add(self, table, row, key=None):
        from sqlalchemy import DateTime
        from vsc.adapters.persistence.postgres.schema import metadata
        row = dict(row)
        if "project_id" in metadata.tables[table].c:
            row.setdefault("project_id", self.target)
        if "id" in metadata.tables[table].c and "id" not in row:
            row["id"] = self.ident(table, key if key is not None else M._json(row))
        identity = {c.name: row[c.name] for c in metadata.tables[table].primary_key.columns}
        for column in metadata.tables[table].c:
            if isinstance(column.type, DateTime) and isinstance(row.get(column.name), str):
                value = datetime.fromisoformat(row[column.name].replace("Z", "+00:00"))
                if value.tzinfo is None:
                    self.manifest["preparation"]["original_naive_timestamps"].append({"table": table, "key": identity,
                        "column": column.name, "original": row[column.name]})
                    row[column.name] = value.replace(tzinfo=self.source_zone).isoformat()
        token = table, M._json(identity)
        if token in self.rows and self.rows[token] != row:
            raise M.MigrationError("准备器生成冲突事实：" + table)
        if token not in self.rows:
            self.rows[token] = row
            self.tables.setdefault(table, []).append(row)
        return {"table": table, "key": identity}

    def map(self, fact, *refs, classification=None):
        if fact not in self.facts:
            return
        mapping = self.manifest["mappings"].setdefault(fact, {"targets": []})
        for ref in refs:
            if ref not in mapping["targets"]:
                mapping["targets"].append(ref)
        if classification:
            mapping["classification"] = classification

    def problem(self, code, evidence, message):
        item = {"code": code, "evidence": evidence, "message": message}
        if item not in self.blockers:
            self.blockers.append(item)

    def fixed(self, path, sha=None):
        path = str(path)
        record = self.files.get(path)
        if record and (not sha or record["sha256"] == sha):
            return self.media.get(path)
        if (path, sha) in self.alias_media:
            return self.alias_media[path, sha]
        # A content-addressed relocation locates original bytes only. It does
        # not identify a creative object, a selected take or a new source.
        candidates = [f for f, value in self.files.items() if sha and value["sha256"] == sha]
        explicit = self.structure.get("file_aliases", {}).get(path)
        if explicit:
            candidates = [explicit] if explicit in candidates else []
        if not candidates:
            self.problem("missing_fixed_file", path, "关系指向未核实的原文件或 SHA")
            return None
        actual = sorted(candidates)[0]
        media = dict(self.media[actual], id=self.ident("historical_media", (path, sha)), name=path, resolved_path=actual)
        self.add("media_items", {k: media[k] for k in ("id", "blob_id", "name", "modality", "registered_by")})
        self.add("media_sources", {"media_id": media["id"], "source_id": self.file_sources[actual], "role": "historical_location",
            "citation": {"original_path": path, "sha256": sha, "resolved_path": actual, "storage_evidence_only": True}}, (path, sha))
        self.manifest["preparation"].setdefault("file_aliases", []).append({"original_path": path, "sha256": sha,
            "actual_path": actual, "media_id": media["id"], "storage_evidence_only": True})
        self.alias_media[path, sha] = media
        return media

    def archive(self, key, payload, kind="vsc.legacy-fact/v1"):
        raw = M._json(payload).encode("utf-8")
        return self.add("artifact_versions", {"artifact_key": "legacy.fact:" + key, "version": 1,
            "artifact_type": kind, "stage": "migration", "document": {"utf8": raw.decode()},
            "mime_type": "application/json", "sha256": hashlib.sha256(raw).hexdigest(),
            "project_wide": True, "parser_version": PARSER}, key)

    def prepare_files(self):
        for path, original in self.files.items():
            classified = classify_file(M._safe(self.project, path))
            sha = original["sha256"]
            # Shared blobs use a content identity; project registrations do not.
            blob_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "vsc-blob:" + sha))
            blob = {"id": blob_id, "sha256": sha, "size_bytes": original["size_bytes"], "mime_type": classified["mime_type"]}
            if sha in self.blobs:
                blob = self.blobs[sha]
            else:
                self.blobs[sha] = blob
            blob_ref = self.add("media_blobs", blob)
            object_key = str(Path(self.media_prefix) / sha[:2] / sha) if self.media_prefix is not None else str(Path(self.project.name) / path)
            location_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "vsc-location:" + M._json(["local", object_key])))
            location = self.add("blob_locations", {"id": location_id, "blob_id": blob_id, "storage": "local", "object_key": object_key})
            item_id = self.ident("media", path)
            item = {"id": item_id, "blob_id": blob_id, "name": path, "modality": classified["modality"], "registered_by": self.actor}
            media_ref = self.add("media_items", item)
            self.media[path] = dict(item, sha256=sha, size_bytes=original["size_bytes"])
            provenance = dict(original, **classified, source_authority=self.snapshot["source"]["authority"], content_origin="unknown", rights="unknown")
            raw = M._json(provenance).encode()
            source_id = self.ident("file_sources", path)
            source_ref = self.add("source_versions", {"id": source_id, "source_key": "legacy.file:" + path, "version": 1,
                "kind": "legacy-file-inventory", "sha256": hashlib.sha256(raw).hexdigest(), "document": {"utf8": raw.decode()}, "evidence_uri": path})
            self.file_sources[path] = source_id
            source_link = self.add("media_sources", {"media_id": item_id, "source_id": source_id,
                "role": "legacy_file", "citation": {"path": path, "sha256": sha, "classification": classified["classification"]}}, path)
            self.map("file:" + path, blob_ref, location, media_ref, source_ref, source_link)
            self.manifest["preparation"]["file_inventory"].append(dict(provenance, media_id=item_id, blob_id=blob_id, object_key=object_key))

    def prepare_sources(self):
        for source in self.state.get("sources", []):
            path = source.get("path")
            if not self.fixed(path, source.get("sha256")):
                continue
            ref = self.add("source_versions", {"id": self.ident("sources", source["id"]), "source_key": source["id"],
                "version": 1, "kind": source.get("kind", "document"), "sha256": source["sha256"],
                "document": {"legacy_file": path}, "evidence_uri": source.get("source_path") or path,
                **({"created_at": source["added_at"]} if source.get("added_at") else {})})
            link = self.add("media_sources", {"media_id": self.media[path]["id"], "source_id": ref["key"]["id"], "role": "registered_source",
                "citation": {"legacy_id": source["id"], "rights_statement": source.get("rights", "unknown")}}, source["id"])
            self.map("sources:" + source["id"], ref, link)

    def prepare_objects(self):
        kinds = {}
        for artifact in self.state.get("artifacts", []):
            doc = _document(M._safe(self.project, artifact.get("path", "")))
            self.documents[artifact["id"]] = doc
            if artifact.get("type") == "vsc.asset_bible":
                for entity in doc.get("entities", []) + doc.get("styles", []):
                    kind = LEGACY_ASSET_KINDS.get(entity.get("kind"), entity.get("kind"))
                    if kind in ASSET_KINDS:
                        kinds.setdefault(entity.get("id"), set()).add(kind)
        objects = list(self.objects.values())
        if self.work_code and objects and not any(o["kind"] == "work" for o in objects):
            if self.work_code in self.objects:
                raise M.MigrationError("工程部编号与现有对象冲突")
            container = {"id": self.work_code, "kind": "work", "parent": None,
                         "label": self.state.get("title", self.work_code)}
            self.objects[self.work_code] = container
            objects.insert(0, container)
            self.manifest["preparation"]["technical_containers"].append({"id": self.work_code, "kind": "work", "reason": "explicit_single_work", "actor": self.actor})
        for obj in objects:
            self.ident("objects", obj["id"])
        ordinals = defaultdict(int)
        for obj in objects:
            kind, old = obj["kind"], obj["id"]
            if kind not in SUBTYPES:
                self.problem("unsupported_object", "objects:" + old, "对象类型需要显式关系映射")
                continue
            uid = self.ids["objects:" + old]
            root_ref = self.add("creative_objects", {"id": uid, "kind": kind, "display_code": old, "title": obj.get("label") or old,
                **({"created_at": obj["created_at"]} if obj.get("created_at") else {})})
            typed = {"id": uid}
            if kind == "asset":
                choices = kinds.get(old, set())
                explicit = self.structure.get("asset_kinds", {}).get(old)
                if explicit:
                    choices = {explicit}
                if len(choices) != 1 or next(iter(choices)) not in ASSET_KINDS:
                    self.problem("asset_kind_missing", "objects:" + old, "固定资产文档没有唯一可证明的资产类型")
                    continue
                typed["asset_kind"] = next(iter(choices))
            else:
                parent = obj.get("parent") or obj.get("parent_id")
                if kind == "episode" and not parent:
                    parent = self.work_code
                if kind in PARENTS:
                    parent = self.structure.get("parents", {}).get(old, parent)
                    expected = PARENTS[kind]
                    if not parent or parent not in self.objects or self.objects[parent]["kind"] != expected:
                        self.problem("hierarchy_parent_missing", "objects:" + old, "必须显式提供" + expected + "父级；不能从路径推断")
                        continue
                    typed["parent_id"] = self.ids["objects:" + parent]
                ordinal_key = kind, typed.get("parent_id")
                typed["ordinal"] = ordinals[ordinal_key]
                ordinals[ordinal_key] += 1
            subtype_ref = self.add(SUBTYPES[kind], typed)
            self.map("objects:" + old, root_ref, subtype_ref)

    def prepare_artifacts(self):
        arts = {a["id"]: a for a in self.state.get("artifacts", [])}
        for old in arts:
            self.ident("artifacts", old)
        chains, counts = {}, Counter()
        def chain(old, seen=None):
            seen = set() if seen is None else seen
            if old in seen:
                self.problem("supersedes_cycle", "artifacts:" + old, "原替代关系存在环")
                return old
            parent = arts[old].get("supersedes")
            return chain(parent, seen | {old}) if parent in arts else old
        for old, artifact in arts.items():
            chains[old] = chain(old)
            counts[chains[old]] += 1
            scope = artifact.get("scope", "project")
            path = artifact.get("path")
            if not self.fixed(path, artifact.get("sha256")):
                continue
            row = {"id": self.ids["artifacts:" + old], "artifact_key": chains[old], "version": counts[chains[old]],
                "artifact_type": artifact["type"], "stage": artifact["stage"], "document": {"legacy_file": path},
                "mime_type": classify_file(M._safe(self.project, path))["mime_type"], "sha256": artifact["sha256"],
                "project_wide": scope == "project", "parser_version": PARSER, "registration_note": artifact.get("note", "")}
            if artifact.get("created_at"):
                row["created_at"] = artifact["created_at"]
            previous = artifact.get("supersedes")
            if previous in arts:
                row["supersedes_id"] = self.ids["artifacts:" + previous]
            ref = self.add("artifact_versions", row)
            self.artifacts[old] = self.rows[("artifact_versions", M._json(ref["key"]))]
            self.map("artifacts:" + old, ref)
            self.map("file:" + path, ref)
            if scope != "project":
                object_id = self.ids.get("objects:" + scope)
                if object_id:
                    self.map("artifacts:" + old, self.add("artifact_object_scopes", {"artifact_id": row["id"], "object_id": object_id}))
                else:
                    self.problem("artifact_scope_missing", "artifacts:" + old, "产物范围引用未登记对象")
        for old, artifact in arts.items():
            if old not in self.artifacts:
                continue
            for dependency in artifact.get("depends_on", []):
                if dependency not in self.artifacts:
                    self.problem("dependency_missing", "artifacts:" + old, "原依赖版本不存在")
                    continue
                self.map("artifacts:" + old, self.add("artifact_dependencies", {"artifact_id": self.artifacts[old]["id"], "dependency_id": self.artifacts[dependency]["id"]}))
        # Historical object bindings include every fixed bible revision.
        for obj in self.state.get("objects", []):
            refs = [obj.get("artifact") or obj.get("artifact_id")] + [h.get("artifact") for h in obj.get("binding_history", [])]
            for old in filter(None, refs):
                if old not in self.artifacts:
                    self.problem("object_artifact_missing", "objects:" + obj["id"], "对象引用的固定版本不存在")
                elif obj["kind"] != "asset":
                    self.map("objects:" + obj["id"], self.add("artifact_object_scopes", {"artifact_id": self.artifacts[old]["id"], "object_id": self.ids["objects:" + obj["id"]]}))

    def prepare_decisions(self):
        pending = []
        for event in self.state.get("events", []):
            if event.get("event") == "artifact_decided":
                pending.append(("events:" + str(event["id"]), event.get("artifact_id"), event.get("status"), event.get("by"), NO_REASON, event.get("at")))
        for artifact in self.state.get("artifacts", []):
            detail = artifact.get("decision") or {}
            if detail and artifact.get("status") in {"approved", "rejected"}:
                pending.append(("artifacts:" + artifact["id"], artifact["id"], artifact["status"], detail.get("by"),
                                artifact.get("note") or detail.get("note") or NO_REASON, detail.get("at")))
            elif artifact.get("status") == "approved":
                self.problem("approval_evidence_missing", "artifacts:" + artifact["id"], "已批准状态缺少原操作人决定")
        current = {}
        for key, old, status, actor, reason, at in sorted(pending, key=lambda item: (item[-1] or "", item[0])):
            if old not in self.artifacts or status not in {"approved", "rejected", "revoked"} or not actor:
                self.problem("approval_evidence_missing", key, "原决定缺少固定版本、操作人或结论")
                continue
            self.sequence += 1
            row = {"artifact_id": self.artifacts[old]["id"], "outcome": {"approved": "approve", "rejected": "reject", "revoked": "revoke"}[status],
                   "actor": actor, "reason": reason, "decision_sequence": self.sequence, "based_on_revision": self.snapshot["source"]["revision"]}
            if at:
                row["created_at"] = at
            ref = self.add("artifact_decisions", row, key)
            self.map(key, ref)
            self.manifest["decision_evidence"]["artifact_decisions:" + ref["key"]["id"]] = key
            if status == "approved":
                current[self.artifacts[old]["artifact_key"]] = (old, ref)
        for artifact_key, (old, decision_ref) in current.items():
            original = next(a for a in self.state["artifacts"] if a["id"] == old)
            if original.get("status") == "approved" and not original.get("superseded_by"):
                self.add("current_artifact_versions", {"artifact_key": artifact_key, "artifact_id": self.artifacts[old]["id"], "decision_id": decision_ref["key"]["id"]})

    def prepare_projections(self):
        from vsc.assets.projections import normalize_artifact_payload, SUPPORTED_FORMATS
        from vsc.assets.resource_service import ResourceError
        mapping = {kind: {old: self.ids["objects:" + old] for old, obj in self.objects.items() if obj["kind"] == kind} for kind in SUBTYPES}
        mapping.update(asset_specs={}, script_lines={}, line_texts={})
        original = {a["id"]: a for a in self.state["artifacts"]}
        order = {"vsc.asset_bible": 0, "vsc.screenplay": 1, "vsc.coverage_plan": 2, "vsc.scene_state": 3}
        for old, row in sorted(self.artifacts.items(), key=lambda item: order.get(item[1]["artifact_type"], 4)):
            doc = self.documents[old]
            if doc.get("format") not in SUPPORTED_FORMATS:
                if row["artifact_type"] in {"vsc.timeline", "vsc.selected_takes", "vsc.screenplay", "vsc.asset_bible", "vsc.scene_state", "vsc.coverage_plan"}:
                    self.unindexed(old, "旧文档未具备可验证的正式关系格式")
                continue
            fixed = original[old].get("asset_versions", {})
            local = dict(mapping, asset_specs=dict(mapping["asset_specs"]), _artifact_version_id=row["id"])
            for asset, ref in fixed.items():
                for spec in self.tables.get("asset_spec_versions", []):
                    if spec["asset_id"] == self.ids.get("objects:" + asset) and spec["artifact_id"] == self.ids.get("artifacts:" + ref["id"]):
                        variant = "default" if spec["variant_key"] == "master" else spec["variant_key"]
                        local["asset_specs"][asset + ":" + variant] = spec["id"]
            try:
                projection_doc = doc
                if doc.get("format") == "vsc.screenplay/v1":
                    import copy
                    projection_doc = copy.deepcopy(doc)
                    for scene in projection_doc.get("scenes", []):
                        for line in scene.get("dialogue", []):
                            if line.get("speaker") and line.get("speaker") not in mapping["asset"]:
                                self.manifest["preparation"].setdefault("unresolved_speakers", []).append({"artifact_id": old,
                                    "line_key": line.get("id"), "original_label": line["speaker"], "speaker_id": None})
                                line["speaker"] = None
                projection = normalize_artifact_payload(projection_doc, local)["projections"]
            except (ResourceError, ValueError, KeyError, TypeError) as error:
                self.unindexed(old, "固定文档关系映射缺失：" + str(error))
                continue
            for spec in projection.get("asset_specs", []):
                self.add("asset_spec_versions", dict(spec, artifact_id=row["id"]))
                alias = next(k for k, value in mapping["asset"].items() if value == spec["asset_id"])
                variant = "default" if spec["variant_key"] == "master" else spec["variant_key"]
                mapping["asset_specs"][alias + ":" + variant] = spec["id"]
            # The canonical parser omits style entities; these are real identities.
            if row["artifact_type"] == "vsc.asset_bible":
                for style in doc.get("styles", []):
                    asset_id = mapping["asset"].get(style.get("id"))
                    if asset_id:
                        self.add("asset_spec_versions", {"asset_id": asset_id, "artifact_id": row["id"], "variant_key": "master"}, old + ":" + style["id"])
            for ordinal, line in enumerate(projection.get("script_lines", [])):
                self.add("script_lines", dict(line, ordinal=ordinal, script_version_id=row["id"], source_sha256=row["sha256"]))
                mapping["script_lines"][old + ":" + line["line_key"]] = line["id"]
                mapping["line_texts"][line["id"]] = line["text"]
            for state in projection.get("state_versions", []):
                self.add("state_versions", {k: v for k, v in dict(state, artifact_id=row["id"], source_sha256=row["sha256"]).items() if k != "entities"})
                for entity in state.get("entities", []):
                    self.add("state_entity_refs", dict(entity, state_id=state["id"]))
            for coverage in projection.get("line_coverage", []):
                self.add("shot_line_coverage", dict(coverage, coverage_version_id=row["id"]))
        for old, artifact in original.items():
            for asset, fixed in artifact.get("asset_versions", {}).items():
                specs = [s for s in self.tables.get("asset_spec_versions", []) if s["asset_id"] == self.ids.get("objects:" + asset) and s["artifact_id"] == self.ids.get("artifacts:" + fixed["id"]) and s["variant_key"] == "master"]
                if len(specs) != 1 or self.artifacts.get(fixed["id"], {}).get("sha256") != fixed.get("sha256"):
                    self.problem("asset_versions_unmapped", "artifacts:" + old, "固定资产规格版本缺少可验证唯一master")
                else:
                    self.add("artifact_asset_spec_refs", {"artifact_id": self.artifacts[old]["id"], "asset_id": self.ids["objects:" + asset], "spec_version_id": specs[0]["id"]})

    def unindexed(self, old, message):
        artifact = next(a for a in self.state["artifacts"] if a["id"] == old)
        if artifact.get("status") == "approved":
            self.problem("approved_projection_missing", "artifacts:" + old, message)
            return
        self.artifacts[old]["parser_version"] = "legacy-unindexed/v1"
        self.map("artifacts:" + old, classification="legacy_unindexed")
        self.manifest["preparation"]["legacy_unindexed"].append({"artifact_id": old, "reason": message, "execution_eligible": False})

    def prepare_unknown(self):
        for key, fact in self.facts.items():
            if fact["category"] in {"unknown", "decisions"} and not fact["required_tables"]:
                self.map(key, self.archive(key, fact["payload"]), classification="document")

    def run(self):
        self.prepare_files()
        self.prepare_sources()
        self.prepare_objects()
        self.prepare_artifacts()
        self.prepare_decisions()
        self.prepare_projections()
        self.prepare_unknown()
        from vsc.project.migration_relations import prepare_media_relations
        prepare_media_relations(self)
        from vsc.project.migration_post import prepare_post_relations
        prepare_post_relations(self)
        if self.archive_media:
            self.manifest["preparation"]["media_archive"] = archive_media(self.project, self.manifest)
        self.tables["projects"][0]["decision_sequence"] = self.sequence
        self.manifest["preparation"]["blockers"] = self.blockers
        self.manifest["preparation"]["warnings"] = self.warnings
        gaps = M._coverage(self.manifest, self.snapshot)
        if not gaps and not self.blockers:
            try:
                M.validate_manifest(self.project, self.manifest, self.snapshot)
            except (M.MigrationError, OSError, ValueError) as error:
                self.problem(getattr(error, "code", "manifest_invalid"), "manifest", str(error))
        return {"manifest": self.manifest, "ready": not gaps and not self.blockers,
                "gaps": gaps, "blockers": self.blockers, "warnings": self.warnings,
                "source": self.snapshot["source"], "counts": {"files": len(self.files), "facts": len(self.facts),
                    "tables": {name: len(rows) for name, rows in self.tables.items()},
                    "file_classes": dict(Counter(f["classification"] for f in self.manifest["preparation"]["file_inventory"]))}}


def archive_media(project, manifest):
    """Copy original bytes into controlled content storage; never remove sources.

    Publish with link(2), so a concurrent existing object is never overwritten.
    Reused objects are checked against both size and SHA before acceptance.
    """
    project = Path(project).resolve()
    root = Path(manifest["media_root"])
    if root.is_relative_to(project):
        raise M.MigrationError("受控媒体目录不能置于旧项目内，避免源清单变化")
    if any(path.is_symlink() for path in (root, *root.parents)):
        raise M.MigrationError("受控媒体根目录不能通过符号链接访问")
    root.mkdir(parents=True, exist_ok=True)
    copied, reused, seen = 0, 0, set()
    for item in manifest["preparation"]["file_inventory"]:
        key, expected, size = item["object_key"], item["sha256"], item["size_bytes"]
        if key in seen:
            continue
        seen.add(key)
        source, destination = M._safe(project, item["path"]), M._safe(root, key)
        if not source.is_file():
            raise M.MigrationError("原素材已不存在", "source_changed")
        if destination.exists():
            if not destination.is_file() or destination.stat().st_size != size or M._sha(destination) != expected:
                raise M.MigrationError("已有受控媒体与原 SHA/大小不符", "media_archive_conflict")
            reused += 1
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Check again after creating parents; never follow a planted symlink.
        destination = M._safe(root, key)
        fd, temporary = tempfile.mkstemp(prefix=".vsc-archive-", dir=destination.parent)
        temporary = Path(temporary)
        try:
            digest, measured = hashlib.sha256(), 0
            with source.open("rb") as incoming, os.fdopen(fd, "wb") as outgoing:
                for block in iter(lambda: incoming.read(1024 * 1024), b""):
                    outgoing.write(block)
                    digest.update(block)
                    measured += len(block)
                outgoing.flush()
                os.fsync(outgoing.fileno())
            if measured != size or digest.hexdigest() != expected:
                raise M.MigrationError("媒体转存期间源字节发生变化", "source_changed")
            try:
                os.link(temporary, destination)
                copied += 1
            except FileExistsError:
                destination = M._safe(root, key)
                if not destination.is_file() or destination.stat().st_size != size or M._sha(destination) != expected:
                    raise M.MigrationError("并发发布的受控媒体摘要冲突", "media_archive_conflict")
                reused += 1
            directory_fd = os.open(str(destination.parent), os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            temporary.unlink(missing_ok=True)
    return {"copied": copied, "reused": reused, "unique_objects": len(seen), "verified": True}


def prepare(project, actor, *, work_code=None, structure=None, media_root=None, media_prefix=None, archive_media=False, source_timezone="Asia/Shanghai"):
    """Return a typed manifest and explicit blockers; no freeze/import/cutover."""
    return Preparation(project, actor, work_code, structure, media_root, media_prefix, archive_media, source_timezone).run()
