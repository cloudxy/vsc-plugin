"""Fixed workspace library over the existing resource graph and blob store."""
from datetime import datetime, timezone
import re

from sqlalchemy import func, insert, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from vsc.assets.resource_service import Conflict, NotFound, ResourceError, required
from . import schema as S
from .values import checked_id, clean, digest, new_id, verify_sha

GAP_MESSAGES = {
    "library_retired": "库项已停止新增使用，已有固定引用仍保留",
    "library_rights_revoked": "当前共享许可已撤回",
    "library_license_expired": "共享许可已到期",
    "library_purpose_not_allowed": "共享许可不包含当前用途",
    "library_source_rights_changed": "原素材的现行权利证据不再允许此用途",
    "library_missing_bytes": "固定媒体字节缺失或摘要不符",
    "storage_unavailable": "受控媒体存储尚未配置",
    "invalid_role": "素材模态或目标类型不适合当前用途",
    "invalid_identity_role": "当前资产身份类型不适合此用途",
    "missing_field": "当前用途尚缺身份、台词覆盖等必要关联",
    "not_found": "目标或固定规格不存在，或不属于当前项目",
    "slot_mismatch": "当前槽位的结构关联已改变，请刷新后重新选择",
    "track_required": "声音用途需要先确定目标音轨",
    "coverage_mismatch": "干声的台词覆盖不属于当前镜头",
    "variant_identity_mismatch": "变体规格与当前资产身份不一致",
    "spec_unapproved": "目标的固定规格尚未批准",
    "revision_conflict": "目标项目已改变，请刷新后重新选择",
    "library_republish_not_supported": "库来源素材及其派生暂不支持再次发布，请直接使用原固定库版",
}


def _expires(value):
    if value is None:
        return None
    result = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if result.tzinfo is None:
        raise ResourceError("许可到期时间需要时区", "invalid_expiry")
    return result


def _scope_allows(scope, purpose):
    return isinstance(scope, list) and (purpose in scope or "*" in scope)


def _imported_ancestor(conn, project_id, media_id):
    # The DB predicate follows only typed, project-local operation/job inputs.
    # UNION makes malformed historical cycles finite; no rights-chain locks or
    # guessed matching by byte digest are introduced.
    return conn.execute(text("SELECT vsc_library_has_imported_ancestor(CAST(:project AS uuid), CAST(:media AS uuid))"),
        {"project": project_id, "media": media_id}).scalar_one()


def _version_gaps(store, conn, version, purpose, *, new_use=False):
    readonly_preview = bool(conn.get_execution_options().get("vsc_readonly_preview"))
    publications = list(conn.execute(select(S.library_reuses).where(
        S.library_reuses.c.library_version_id == version["id"], S.library_reuses.c.reuse_mode == "publish")).mappings())
    # Rights commands lock their source project. Hold the same facts stable
    # through original adoption/freeze; source locks precede entry locks, just
    # as in publication, to avoid an entry/source lock inversion.
    if not readonly_preview:
        for project_id in sorted({row["project_id"] for row in publications}):
            conn.execute(select(S.projects.c.id).where(S.projects.c.id == project_id).with_for_update(read=True)).one()
    entry_query = select(S.library_entries).where(S.library_entries.c.id == version["entry_id"])
    if not readonly_preview:
        entry_query = entry_query.with_for_update(read=True)
    entry = conn.execute(entry_query).mappings().one()
    gaps = []
    if new_use and entry["status"] != "active":
        gaps.append("library_retired")
    if entry["rights_status"] != "active":
        gaps.append("library_rights_revoked")
    if version["expires_at"] and version["expires_at"] <= datetime.now(timezone.utc):
        gaps.append("library_license_expired")
    if not _scope_allows(version["allowed_purposes"], purpose):
        gaps.append("library_purpose_not_allowed")
    # Original rights remain authoritative, while source lifecycle/trash does
    # not invalidate the library's own fixed bytes and evidence snapshot.
    for publication in publications:
        if _imported_ancestor(conn, publication["project_id"], publication["media_id"]):
            # Fail closed for an anomalous/historical republish, too. Valid
            # publication now rejects this shape at both application and DB.
            gaps.append("library_republish_not_supported")
            continue
        rights = store._latest(conn, S.rights_decisions, publication["project_id"], "media_id", publication["media_id"])
        if (not rights or rights["outcome"] not in {"owned", "licensed"}
                or rights["expires_at"] and rights["expires_at"] <= datetime.now(timezone.utc)
                or not _scope_allows(rights["scope"].get("purposes"), purpose)
                or not _scope_allows(rights["scope"].get("purposes"), "library_share")):
            gaps.append("library_source_rights_changed")
    return sorted(set(gaps))


def library_media_gaps(store, conn, project_id, media_id, purpose):
    """Called by _usable, so compilation, submission and post freeze recheck."""
    versions = conn.execute(select(S.library_entry_versions).join(S.library_reuses,
        S.library_entry_versions.c.id == S.library_reuses.c.library_version_id).where(
            S.library_reuses.c.project_id == project_id, S.library_reuses.c.media_id == media_id,
            S.library_reuses.c.reuse_mode.in_(["reference", "derive"]))).mappings()
    return sorted({gap for version in versions for gap in _version_gaps(store, conn, version, purpose)})


def library_project_lock_ids(conn, project_id, anticipated_versions=()):
    """All source projects whose live rights this target can consume.

    The outer resource transaction takes these locks in UUID order *before*
    its target lock, including not-yet-inserted library use edges. This covers
    reciprocal A/B use, rights changes and existing post/submit consumers.
    """
    versions = select(S.library_reuses.c.library_version_id).where(
        S.library_reuses.c.project_id == project_id,
        S.library_reuses.c.reuse_mode.in_(["reference", "derive"]),
        S.library_reuses.c.library_version_id.is_not(None))
    sources = select(S.library_reuses.c.project_id).where(S.library_reuses.c.reuse_mode == "publish",
        or_(S.library_reuses.c.library_version_id.in_(versions),
            S.library_reuses.c.library_version_id.in_(anticipated_versions)))
    return sorted({project_id, *conn.execute(sources).scalars()})


class SharedLibraryRepository:
    def __init__(self, store, storage=None):
        self.store, self.storage = store, storage

    @staticmethod
    def _lock_key(conn, key):
        # Covers absent entries and absent import keys as well as existing rows.
        conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": "vsc-library:" + key})

    @staticmethod
    def _description(payload):
        allowed = {"library_key", "title", "category", "description", "specification", "allowed_purposes", "license", "expires_at"}
        value = {key: payload[key] for key in allowed if key in payload}
        for key in ("library_key", "title", "category", "description"):
            if not isinstance(required(value, key), str):
                raise ResourceError("库展示字段必须是文本", "invalid_library_description")
        if payload.get("visibility", "workspace") != "workspace":
            raise ResourceError("当前只支持工作区共享", "library_visibility_denied", 403)
        if not isinstance(value.get("specification", {}), dict):
            raise ResourceError("库规格必须为对象", "invalid_library_specification")
        purposes = required(value, "allowed_purposes")
        if not isinstance(purposes, list) or not purposes or any(not isinstance(x, str) or not x for x in purposes):
            raise ResourceError("库许可需要明确用途", "library_rights_required")
        license = required(value, "license")
        if (not isinstance(license, dict) or license.get("outcome") not in {"owned", "licensed"}
                or license.get("allow_workspace_reuse") is not True
                or not isinstance(license.get("evidence"), str) or not license["evidence"].strip()):
            raise ResourceError("需要允许工作区复用的许可与脱敏证据", "library_rights_required")
        value["specification"] = value.get("specification", {})
        value["license"] = {key: license[key] for key in ("outcome", "allow_workspace_reuse", "evidence", "name", "attribution", "uri") if key in license}
        value["expires_at"] = _expires(value.get("expires_at"))
        if value["expires_at"] and value["expires_at"] <= datetime.now(timezone.utc):
            raise ResourceError("库许可已到期", "library_license_expired")
        return value

    def _verify(self, member):
        if self.storage is None:
            raise ResourceError("库媒体需核验受控存储", "storage_unavailable")
        for location in member.get("locations", []):
            if location["storage"] == "local" and location["available"]:
                try:
                    return self.storage.verify(location["object_key"], member["sha256"])
                except (OSError, ResourceError):
                    continue
        raise ResourceError("库固定字节缺失或摘要不符", "library_missing_bytes")

    @staticmethod
    def _members(conn, version_id):
        members = []
        version_ids = version_id if isinstance(version_id, (list, tuple)) else [version_id]
        query = select(S.library_version_media, *[c for c in S.media_blobs.c if c.name != "id"]).join(
            S.media_blobs, S.media_blobs.c.id == S.library_version_media.c.blob_id).where(
                S.library_version_media.c.library_version_id.in_(version_ids)).order_by(S.library_version_media.c.ordinal)
        rows = list(conn.execute(query).mappings())
        locations = {}
        for item in conn.execute(select(S.blob_locations).where(
                S.blob_locations.c.blob_id.in_({row["blob_id"] for row in rows}))).mappings():
            locations.setdefault(item["blob_id"], []).append(dict(item))
        for row in rows:
            member = dict(row)
            member["locations"] = locations.get(member["blob_id"], [])
            members.append(member)
        return members

    @staticmethod
    def _public_member(member):
        value = {key: clean(member.get(key)) for key in ("member_key", "role", "ordinal", "modality", "mime_type", "sha256", "size_bytes", "width", "height", "duration_ms")}
        from urllib.parse import quote
        value["preview_url"] = "/api/v1/library/versions/" + member["library_version_id"] + "/members/" + quote(member["member_key"], safe="") + "/content"
        return value

    def _detail(self, conn, version_id):
        rows = self._details(conn, [checked_id(version_id)])
        if not rows:
            raise NotFound("库固定版本不存在")
        return rows[0]

    def _details(self, conn, version_ids):
        versions = {row["id"]: row for row in conn.execute(select(S.library_entry_versions).where(
            S.library_entry_versions.c.id.in_(version_ids))).mappings()}
        entries = {row["id"]: row for row in conn.execute(select(S.library_entries).where(
            S.library_entries.c.id.in_({row["entry_id"] for row in versions.values()}),
            S.library_entries.c.visibility == "workspace")).mappings()}
        members = {}
        for member in self._members(conn, version_ids):
            members.setdefault(member["library_version_id"], []).append(self._public_member(member))
        results = []
        for version_id in version_ids:
            version = versions.get(version_id)
            if not version or version["entry_id"] not in entries:
                continue
            entry = entries[version["entry_id"]]
            result = {key: entry[key] for key in ("id", "library_key", "title", "category", "status", "rights_status", "current_version_id")}
            result.update({key: version[key] for key in ("version", "title", "category", "description", "specification", "sha256", "license", "allowed_purposes", "expires_at")})
            result.update(version_id=version_id, library_version_id=version_id, members=members.get(version_id, []))
            results.append(clean(result))
        return results

    def detail(self, version_id):
        with self.store.engine.connect() as conn:
            return self._detail(conn, version_id)

    def search(self, query="", category=None, offset=0, limit=24, include_retired=False):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise ResourceError("库分页范围不合法", "invalid_page")
        if not isinstance(query, str) or len(query) > 200:
            raise ResourceError("检索文字过长", "invalid_query")
        with self.store.engine.connect() as conn:
            statement = select(S.library_entries.c.current_version_id).join(S.library_entry_versions,
                S.library_entries.c.current_version_id == S.library_entry_versions.c.id).where(S.library_entries.c.visibility == "workspace")
            if not include_retired:
                statement = statement.where(S.library_entries.c.status == "active", S.library_entries.c.rights_status == "active")
            if category:
                statement = statement.where(S.library_entries.c.category == category)
            if query:
                pattern = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
                statement = statement.where(or_(S.library_entries.c.title.ilike(pattern, escape="\\"),
                    S.library_entry_versions.c.description.ilike(pattern, escape="\\")))
            total = conn.execute(select(func.count()).select_from(statement.subquery())).scalar_one()
            ids = list(conn.execute(statement.order_by(S.library_entries.c.title, S.library_entries.c.id).offset(offset).limit(limit)).scalars())
            return {"items": self._details(conn, ids), "total": total, "offset": offset, "limit": limit}

    def content(self, version_id, member_key):
        with self.store.engine.connect() as conn:
            self._detail(conn, version_id)
            member = next((m for m in self._members(conn, version_id) if m["member_key"] == member_key), None)
            if member is None:
                raise NotFound("库媒体成员不存在")
            return self._verify(member), member["mime_type"]

    def _create_version(self, conn, description, members, actor, request_sha, import_key=None):
        key = description["library_key"]
        member_keys = [member["member_key"] for member in members]
        if (not 1 <= len(key) <= 200 or any(not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", value) for value in member_keys)
                or len(set(member_keys)) != len(member_keys)):
            raise ResourceError("库标识或媒体成员标识不合法或重复", "invalid_library_members")
        self._lock_key(conn, "entry:" + key)
        entry = conn.execute(select(S.library_entries).where(S.library_entries.c.library_key == key).with_for_update()).mappings().first()
        if entry is None:
            entry_id, version = new_id(), 1
            conn.execute(insert(S.library_entries).values(id=entry_id, library_key=key,
                title=description["title"], category=description["category"], created_by=actor))
        else:
            if entry["status"] != "active" or entry["rights_status"] != "active":
                raise ResourceError("停用库项不可新增版本", "library_retired")
            if entry["created_by"] != actor:
                raise ResourceError("只有库项维护人可发布新版", "library_owner_required", 403)
            entry_id = entry["id"]
            version = conn.execute(select(func.max(S.library_entry_versions.c.version)).where(S.library_entry_versions.c.entry_id == entry_id)).scalar_one() + 1
        version_id = new_id()
        sha = digest({"description": description, "members": [{k: member[k] for k in ("member_key", "blob_id", "modality", "role")} for member in members]})
        conn.execute(insert(S.library_entry_versions).values(id=version_id, entry_id=entry_id, version=version,
            title=description["title"], category=description["category"],
            description=description["description"], specification=description["specification"],
            member_count=len(members), sha256=sha,
            import_key=import_key, request_sha256=request_sha, license=description["license"],
            allowed_purposes=description["allowed_purposes"], expires_at=description["expires_at"], published_by=actor))
        for ordinal, member in enumerate(members):
            conn.execute(insert(S.library_version_media).values(library_version_id=version_id,
                member_key=member["member_key"], blob_id=member["blob_id"], modality=member["modality"],
                role=member.get("role", "reference"), ordinal=ordinal))
        conn.execute(update(S.library_entries).where(S.library_entries.c.id == entry_id).values(
            current_version_id=version_id, title=description["title"], category=description["category"]))
        return {"entry_id": entry_id, "library_version_id": version_id, "version_id": version_id, "version": version, "sha256": sha}

    def publish(self, project_id, payload, actor, **kw):
        description = self._description(payload)
        members = required(payload, "members")
        if not isinstance(members, list) or not 1 <= len(members) <= 32:
            raise ResourceError("一次发布1至32项媒体", "invalid_library_members")
        def work(conn, project):
            prepared = []
            for item in members:
                member = self.store._media(conn, project["id"], required(item, "media_id"))
                if _imported_ancestor(conn, project["id"], member["id"]):
                    raise ResourceError(GAP_MESSAGES["library_republish_not_supported"],
                        "library_republish_not_supported", 409)
                self._verify(member)
                rights = self.store._latest(conn, S.rights_decisions, project["id"], "media_id", member["id"])
                if (not rights or rights["outcome"] not in {"owned", "licensed"} or not rights["source_id"]
                        or not _scope_allows(rights["scope"].get("purposes"), "library_share")):
                    raise ResourceError("原素材没有工作区共享许可", "library_publish_rights_required", 403)
                if rights["expires_at"] and (description["expires_at"] is None or description["expires_at"] > rights["expires_at"]):
                    raise ResourceError("共享期限不得超过原许可", "library_rights_scope_mismatch")
                if rights["outcome"] == "licensed" and description["license"]["outcome"] != "licensed":
                    raise ResourceError("共享许可不能把已授权素材改称自有", "library_rights_scope_mismatch")
                if any(not _scope_allows(rights["scope"].get("purposes"), purpose) for purpose in description["allowed_purposes"]):
                    raise ResourceError("共享用途超过原许可", "library_rights_scope_mismatch")
                for purpose in description["allowed_purposes"]:
                    _, gaps = self.store._usable(conn, project["id"], member["id"], purpose)
                    if gaps:
                        raise ResourceError("原素材当前不可共享: " + ", ".join(gaps), "library_publish_blocked")
                prepared.append(dict(member, member_key=required(item, "member_key"), role=item.get("role", "reference"), rights=rights))
            result = self._create_version(conn, description, prepared, actor, digest(payload))
            for member in prepared:
                conn.execute(insert(S.library_reuses).values(project_id=project["id"], id=new_id(), media_id=member["id"],
                    source_id=member["rights"]["source_id"], rights_decision_id=member["rights"]["id"],
                    library_key=description["library_key"], library_version=str(result["version"]), reuse_mode="publish",
                    library_version_id=result["library_version_id"], member_key=member["member_key"], blob_id=member["blob_id"]))
            return result
        return self.store._mutate(project_id, "publish_library", payload, actor=actor, callback=work, **kw)

    def import_entry(self, payload, actor):
        description = self._description(payload)
        import_key = required(payload, "import_key")
        if not isinstance(import_key, str) or not 1 <= len(import_key) <= 200:
            raise ResourceError("导入标识无效", "invalid_import_key")
        request_sha = digest({"payload": payload, "actor": actor})
        try:
            with self.store.engine.begin() as conn:
                self._lock_key(conn, "import:" + import_key)
                existing = conn.execute(select(S.library_entry_versions).where(S.library_entry_versions.c.import_key == import_key)).mappings().first()
                if existing:
                    if existing["request_sha256"] != request_sha:
                        raise Conflict("导入标识已用于其他内容", "idempotency_conflict")
                    return {"entry_id": existing["entry_id"], "library_version_id": existing["id"], "version_id": existing["id"], "version": existing["version"], "sha256": existing["sha256"]}
                prepared = []
                for member in payload["members"]:
                    self._verify(dict(member, locations=[dict(member, available=True)]))
                    sha = verify_sha(member["sha256"])
                    conn.execute(pg_insert(S.media_blobs).values(id=new_id(), sha256=sha, size_bytes=member["size_bytes"],
                        mime_type=member["mime_type"], **{key: member.get(key) for key in ("width", "height", "duration_ms", "sample_rate")},
                        probe=member.get("probe", {})).on_conflict_do_nothing(index_elements=[S.media_blobs.c.sha256]))
                    blob = conn.execute(select(S.media_blobs).where(S.media_blobs.c.sha256 == sha)).mappings().one()
                    if blob["size_bytes"] != member["size_bytes"] or blob["mime_type"] != member["mime_type"]:
                        raise Conflict("固定字节探测不一致", "blob_mismatch")
                    conn.execute(pg_insert(S.blob_locations).values(id=new_id(), blob_id=blob["id"], storage=member["storage"],
                        object_key=member["object_key"]).on_conflict_do_nothing(index_elements=[S.blob_locations.c.blob_id, S.blob_locations.c.storage, S.blob_locations.c.object_key]))
                    prepared.append(dict(member, blob_id=blob["id"]))
                return self._create_version(conn, description, prepared, actor, request_sha, import_key)
        except IntegrityError as exc:
            raise ResourceError("共享库关系不合法", "constraint_violation") from exc

    def _preflight(self, conn, project, payload):
        version_id = checked_id(required(payload, "library_version_id"))
        version = conn.execute(select(S.library_entry_versions).where(S.library_entry_versions.c.id == version_id)).mappings().first()
        if version is None:
            raise NotFound("库固定版本不存在")
        member = next((m for m in self._members(conn, version_id) if m["member_key"] == required(payload, "member_key")), None)
        if member is None:
            raise NotFound("库媒体成员不存在")
        role = required(payload, "role")
        gaps = _version_gaps(self.store, conn, version, role, new_use=True)
        try:
            self.store._binding_intent(conn, project["id"], payload, member["modality"])
            if payload.get("select") is True and payload.get("spec_version_id") and not self.store._artifact_approved(conn, project["id"], payload["spec_version_id"]):
                gaps.append("spec_unapproved")
        except ResourceError as error:
            gaps.append(error.code)
        try:
            self._verify(member)
        except ResourceError as error:
            gaps.append(error.code)
        return version, member, sorted(set(gaps))

    def preview_use(self, project_id, payload):
        with self.store.engine.connect() as conn:
            project = self.store._project(conn, project_id)
            _, member, gaps = self._preflight(conn, project, payload)
            if "expected_revision" in payload and payload["expected_revision"] != project["revision"]:
                gaps.append("revision_conflict")
            return {"available": not gaps, "gaps": [{"code": code, "message": GAP_MESSAGES.get(code, code)} for code in gaps],
                "revision": project["revision"], "library_version_id": payload["library_version_id"],
                "member_key": member["member_key"], "target_object_id": payload["target_object_id"], "role": payload["role"],
                "member": self._public_member(member), "would_select": payload.get("select") is True}

    def use(self, project_id, payload, actor, **kw):
        if "select" in payload and type(payload["select"]) is not bool:
            raise ResourceError("选择意图必须明确", "invalid_selection_intent")
        def work(conn, project):
            version, member, gaps = self._preflight(conn, project, payload)
            if gaps:
                raise ResourceError("库素材不能用于目标: " + "；".join(GAP_MESSAGES.get(code, code) for code in gaps), "library_use_blocked")
            entry = conn.execute(select(S.library_entries).where(S.library_entries.c.id == version["entry_id"])).mappings().one()
            location = next(item for item in member["locations"] if item["storage"] == "local" and item["available"])
            source = {"kind": "workspace-library", "content": {"library_version_id": version["id"], "member_key": member["member_key"],
                "sha256": member["sha256"], "license": version["license"], "allowed_purposes": version["allowed_purposes"]}}
            registered = self.store._register_media(conn, project, dict(member, name=entry["title"], source=source,
                rights="licensed", rights_scope={"purposes": version["allowed_purposes"]}, storage=location["storage"],
                object_key=location["object_key"]), actor)
            rights = self.store._latest(conn, S.rights_decisions, project["id"], "media_id", registered["id"])
            reuse_id = new_id()
            conn.execute(insert(S.library_reuses).values(project_id=project["id"], id=reuse_id, media_id=registered["id"],
                source_id=rights["source_id"], rights_decision_id=rights["id"], library_key=entry["library_key"],
                library_version=str(version["version"]), reuse_mode="reference", library_version_id=version["id"],
                member_key=member["member_key"], blob_id=member["blob_id"]))
            internal = {"actor": actor, "expected_revision": project["revision"], "idempotency_key": "library-internal", "_transaction": (conn, project)}
            self.store.record_media_check(project["id"], {"media_id": registered["id"], "checker": "library-byte-verification",
                "criteria_version": "sha256-controlled-storage/v1", "outcome": "pass", "report": {"sha256": member["sha256"]}}, **internal)
            binding = {key: payload[key] for key in ("target_object_id", "role", "slot_key", "identity_asset_id", "variant_spec_id", "spec_version_id", "line_coverage_id", "track_key", "context_sha256") if key in payload}
            candidate = self.store.propose_binding(project["id"], dict(binding, media_id=registered["id"]), **internal)
            decision = None
            if payload.get("select") is True:
                reason = payload.get("reason", "用户明确将此库固定版本用于当前目标")
                self.store.record_review(project["id"], {"candidate_id": candidate["candidate_id"], "reviewer_type": "human",
                    "outcome": "pass", "reason": reason, "evidence": {"library_version_id": version["id"], "member_key": member["member_key"]}}, **internal)
                selection = {key: payload[key] for key in ("trial_adoption",) if key in payload}
                decision = self.store.select_candidate(project["id"], dict(selection, candidate_id=candidate["candidate_id"], reason=reason), **internal)
            return dict(candidate, media_id=registered["id"], source_id=rights["source_id"], reuse_id=reuse_id,
                library_version_id=version["id"], member_key=member["member_key"], selected=decision is not None,
                decision_id=decision["decision_id"] if decision else None)
        return self.store._mutate(project_id, "use_library", payload, actor=actor, callback=work,
            _library_versions=(checked_id(required(payload, "library_version_id")),), **kw)

    def retire(self, entry_id, payload, actor):
        if not isinstance(payload, dict) or payload.get("outcome", "retire") not in {"retire", "revoke_rights"} or not payload.get("reason"):
            raise ResourceError("停用需要明确结果和原因", "invalid_library_retirement")
        with self.store.engine.begin() as conn:
            entry = conn.execute(select(S.library_entries).where(S.library_entries.c.id == checked_id(entry_id)).with_for_update()).mappings().first()
            if entry is None:
                raise NotFound("库项不存在")
            if entry["created_by"] != actor:
                raise ResourceError("只有库项维护人可停用", "library_owner_required", 403)
            key = required(payload, "idempotency_key")
            if not isinstance(key, str) or not 1 <= len(key) <= 200:
                raise ResourceError("停用需要有效操作标识", "idempotency_required")
            request_sha = digest({"payload": payload, "actor": actor})
            existing = conn.execute(select(S.library_entry_decisions).where(
                S.library_entry_decisions.c.entry_id == entry["id"],
                S.library_entry_decisions.c.idempotency_key == key)).mappings().first()
            if existing and existing["request_sha256"] != request_sha:
                raise Conflict("停用标识已用于其他操作", "idempotency_conflict")
            if not existing:
                conn.execute(insert(S.library_entry_decisions).values(id=new_id(), entry_id=entry["id"],
                    outcome=payload.get("outcome", "retire"), reason=payload["reason"], actor=actor,
                    idempotency_key=key, request_sha256=request_sha))
            values = {"rights_status": "revoked"} if payload.get("outcome") == "revoke_rights" else {"status": "retired"}
            conn.execute(update(S.library_entries).where(S.library_entries.c.id == entry["id"]).values(**values))
            return {"entry_id": entry["id"], "status": values.get("status", entry["status"]), "rights_status": values.get("rights_status", entry["rights_status"])}
