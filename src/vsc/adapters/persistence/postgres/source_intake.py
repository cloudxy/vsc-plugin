"""Source intake transactions; immutable jobs, attempts, extraction and provenance.

Mixin host: ResourceStore project/revision helpers plus ScriptWorkspaceRepository.
Draft hooks are called by the existing save/submit transaction, never afterwards.
"""
import copy
import hashlib

from sqlalchemy import func, insert, select, update

from vsc.assets.resource_service import Conflict, ResourceError, required
from vsc.assets.source_intake import (PARSER_VERSION, SCHEMA_VERSION, extract_source,
    MAX_SOURCE_BYTES, render_structured_body, source_bytes, source_evidence_uri,
    source_format, source_intake_capabilities, structure_proposal)
from . import schema as S
from .values import checked_id, clean, canonical, digest, new_id


class SourceIntakeRepository:
    @staticmethod
    def source_intake_capabilities():
        return source_intake_capabilities()

    def create_source_intake(self, project_id, payload, *, verified_media=None, **kw):
        intent = required(payload, "intent")
        if intent not in ("screenplay", "novel", "outline", "reference"):
            raise ResourceError("来源用途必须明确为 screenplay/novel/outline/reference", "invalid_source_intent")
        evidence_uri = source_evidence_uri(payload.get("evidence_uri"))
        def work(conn, project):
            p, identifier = project["id"], new_id()
            media = None
            if verified_media:
                if not 0 < verified_media.get("size_bytes", 0) <= MAX_SOURCE_BYTES:
                    raise ResourceError("来源文件必须为非空且不超过 10 MiB", "source_size_limit")
                registration = self._register_media(conn, project, dict(verified_media, rights="unknown"), kw.get("actor"))
                media = self._media(conn, p, registration["id"])
            if media:
                fmt = source_format(dict(payload, filename=media["name"]))
                manifest = {"format": "vsc.source-file/v1",
                    "filename": media["name"], "original_sha256": media["sha256"], "size_bytes": media["size_bytes"]}
                raw = canonical(manifest).encode()
            else:
                fmt = source_format(payload)
                if fmt not in ("paste", "txt", "md") or "content_base64" in payload:
                    raise ResourceError("文件来源必须通过受控上传登记", "source_storage_required")
                raw = source_bytes(payload)
            sha = hashlib.sha256(raw).hexdigest()
            title = payload.get("title") or payload.get("filename") or (media["name"] if media else "粘贴文案")
            if not isinstance(title, str) or not title.strip():
                raise ResourceError("来源标题必须为非空文本", "invalid_source_title")
            source_key = payload.get("source_key", identifier)
            version = conn.execute(select(func.coalesce(func.max(S.source_versions.c.version), 0)).where(
                S.source_versions.c.project_id == p, S.source_versions.c.source_key == source_key)).scalar_one() + 1
            conn.execute(insert(S.source_versions).values(project_id=p, id=identifier, source_key=source_key,
                version=version, kind="intake", document=raw, sha256=sha, evidence_uri=evidence_uri))
            conn.execute(insert(S.source_intake_documents).values(project_id=p, source_id=identifier,
                title=title, intent=intent, format=fmt))
            if media:
                conn.execute(insert(S.media_sources).values(project_id=p, id=new_id(), media_id=media["id"],
                    source_id=identifier, role="original_file", citation={}))
            return {"id": identifier, "source_id": identifier, "source_key": source_key, "version": version,
                "sha256": sha, "title": title, "format": fmt, "intent": intent, "size_bytes": media["size_bytes"] if media else len(raw),
                "original_sha256": media["sha256"] if media else sha, "media_id": media["id"] if media else None,
                "registered": True, "parsed": False, "untrusted_material": True}
        return self._mutate(project_id, "create_source_intake", payload, callback=work, **kw)

    def list_source_intake_documents(self, project_id):
        with self.engine.connect() as conn:
            project = self._project(conn, project_id)
            items = [dict(row) for row in conn.execute(select(S.source_intake_documents).where(
                S.source_intake_documents.c.project_id == project["id"]).order_by(
                S.source_intake_documents.c.created_at, S.source_intake_documents.c.source_id)).mappings()]
            return clean({"items": items, "total": len(items), "revision": project["revision"]})

    def create_parse_job(self, project_id, payload, **kw):
        intent = required(payload, "intent")
        if intent not in ("screenplay", "novel", "outline"):
            raise ResourceError("参考资源不进入剧本解析，请使用资源登记", "invalid_source_intent")
        inputs = required(payload, "inputs")
        parameters = payload.get("parameters", {})
        if not isinstance(inputs, list) or not 1 <= len(inputs) <= 30 or not isinstance(parameters, dict):
            raise ResourceError("解析需要 1–30 份固定来源及对象参数", "invalid_payload")

        def work(conn, project):
            p, job_id, fixed = project["id"], new_id(), []
            for ordinal, item in enumerate(inputs):
                source = self._one(conn, S.source_versions, p, required(item, "source_id"))
                if source["sha256"] != required(item, "source_sha256"):
                    raise ResourceError("解析输入必须固定当前所示来源 SHA", "source_sha_mismatch")
                metadata = conn.execute(select(S.source_intake_documents).where(
                    S.source_intake_documents.c.project_id == p,
                    S.source_intake_documents.c.source_id == source["id"])).mappings().first()
                if metadata:
                    if metadata["intent"] != intent:
                        raise ResourceError("解析用途与登记来源用途不一致；请明确登记新的来源语境", "source_intent_mismatch")
                    fmt = metadata["format"]
                    if item.get("format", fmt) != fmt:
                        raise ResourceError("不能用另一格式解释已固定来源", "source_format_mismatch")
                else:
                    if source["kind"] == "intake":
                        raise ResourceError("来源缺少固定登记元数据，停止解析", "source_intake_metadata_required")
                    fmt = required(item, "format")
                fixed.append({"source_id": source["id"], "source_sha256": source["sha256"], "format": fmt,
                              "role": item.get("role", "primary"), "ordinal": ordinal})
            signature = digest({"inputs": fixed, "parameters": parameters, "intent": intent,
                                "parser_version": PARSER_VERSION, "schema_version": SCHEMA_VERSION})
            conn.execute(insert(S.parse_jobs).values(project_id=p, id=job_id, parser_version=PARSER_VERSION,
                schema_version=SCHEMA_VERSION, intent=intent, parameters=parameters,
                signature_sha256=signature, created_by=kw.get("actor") or ""))
            for item in fixed:
                conn.execute(insert(S.parse_job_inputs).values(project_id=p, id=new_id(), job_id=job_id, **item))
            return {"id": job_id, "job_id": job_id, "status": "created", "inputs": fixed,
                    "signature_sha256": signature, "parser_version": PARSER_VERSION, "intent": intent}
        return self._mutate(project_id, "create_parse_job", payload, callback=work, **kw)

    def run_parse_job(self, project_id, payload, *, verified_sources=None, **kw):
        """A new command key explicitly creates one local execution attempt.

        Retry reuses the immutable job parameters. Reparse with other parameters
        creates a new job. Replaying a command key returns its original receipt.
        All extractors are local; there is no uncertain paid submission state.
        """
        def work(conn, project):
            p = project["id"]
            job = self._one(conn, S.parse_jobs, p, required(payload, "job_id"))
            if job["parser_version"] != PARSER_VERSION or job["schema_version"] != SCHEMA_VERSION:
                raise ResourceError("此解析器版本不可执行；创建明确的新解析任务", "parser_version_unavailable")
            attempt_id = new_id()
            number = conn.execute(select(func.coalesce(func.max(S.parse_attempts.c.attempt_no), 0)).where(
                S.parse_attempts.c.project_id == p, S.parse_attempts.c.job_id == job["id"])).scalar_one() + 1
            inputs = list(conn.execute(select(S.parse_job_inputs).where(S.parse_job_inputs.c.project_id == p,
                S.parse_job_inputs.c.job_id == job["id"]).order_by(S.parse_job_inputs.c.ordinal)).mappings())
            outputs, error = [], None
            try:
                for item in inputs:
                    source = self._one(conn, S.source_versions, p, item["source_id"])
                    raw = bytes(source["document"])
                    if hashlib.sha256(raw).hexdigest() != item["source_sha256"]:
                        raise ResourceError("固定来源字节摘要不符", "source_sha_mismatch")
                    media_id = conn.execute(select(S.media_sources.c.media_id).where(
                        S.media_sources.c.project_id == p, S.media_sources.c.source_id == source["id"],
                        S.media_sources.c.role == "original_file")).scalar_one_or_none()
                    if media_id:
                        media = self._media(conn, p, media_id)
                        raw = (verified_sources or {}).get(source["id"])
                        if not isinstance(raw, bytes):
                            raise ResourceError("文件需要从受控存储核验读取", "source_storage_required")
                        if hashlib.sha256(raw).hexdigest() != media["sha256"] or len(raw) != media["size_bytes"]:
                            raise ResourceError("来源原文件字节摘要不符", "source_sha_mismatch")
                    params = dict(job["parameters"])
                    params.update(params.get("per_source", {}).get(item["source_id"], {}))
                    outputs.append((item, extract_source(raw, item["format"], params)))
            except ResourceError as exc:
                error = exc
            except (ValueError, TypeError, KeyError, OverflowError):
                error = ResourceError("文档结构或解析参数无效；请校对后新建解析任务", "invalid_document")
            status = "failed" if error else "succeeded"
            conn.execute(insert(S.parse_attempts).values(project_id=p, id=attempt_id, job_id=job["id"],
                attempt_no=number, status=status, error_code=error.code if error else None,
                error_message=error.message if error else None))
            extraction_ids = []
            # A multi-source attempt succeeds atomically. A failed attempt cannot
            # look complete merely because its first source was readable.
            if not error:
                for item, output in outputs:
                    identifier = new_id()
                    extraction_ids.append(identifier)
                    conn.execute(insert(S.source_extractions).values(project_id=p, id=identifier,
                        attempt_id=attempt_id, source_id=item["source_id"], source_sha256=item["source_sha256"],
                        output_key=str(item["ordinal"]), **{k: output[k] for k in ("text", "text_sha256", "layout", "warnings")}))
                    for anchor in output["anchors"]:
                        conn.execute(insert(S.source_anchors).values(project_id=p, id=new_id(), extraction_id=identifier,
                            source_id=item["source_id"], **{k: anchor[k] for k in ("anchor_key", "start_char", "end_char", "locator")}))
            return {"id": job["id"], "job_id": job["id"], "attempt_id": attempt_id, "attempt_no": number,
                    "status": status, "error_code": error.code if error else None,
                    "error_message": error.message if error else None, "extraction_ids": extraction_ids,
                    "can_import": status == "succeeded" and job["intent"] == "screenplay", "automatic_approval": False}
        return self._mutate(project_id, "run_parse_job", payload, callback=work, **kw)

    def _parse_job(self, conn, project_id, job_id):
        job = self._one(conn, S.parse_jobs, project_id, job_id)
        job["inputs"] = [dict(r) for r in conn.execute(select(S.parse_job_inputs).where(
            S.parse_job_inputs.c.project_id == project_id, S.parse_job_inputs.c.job_id == job["id"])
            .order_by(S.parse_job_inputs.c.ordinal)).mappings()]
        job["attempts"] = [dict(r) for r in conn.execute(select(S.parse_attempts).where(
            S.parse_attempts.c.project_id == project_id, S.parse_attempts.c.job_id == job["id"])
            .order_by(S.parse_attempts.c.attempt_no)).mappings()]
        latest = job["attempts"][-1] if job["attempts"] else None
        job["status"] = latest["status"] if latest else "created"
        job["extractions"] = []
        if latest:
            rows = conn.execute(select(S.source_extractions).where(S.source_extractions.c.project_id == project_id,
                S.source_extractions.c.attempt_id == latest["id"])).mappings()
            by_output = {r["output_key"]: dict(r) for r in rows}
            for item in job["inputs"]:
                extraction = by_output.get(str(item["ordinal"]))
                if not extraction:
                    continue
                anchors = conn.execute(select(S.source_anchors).where(S.source_anchors.c.project_id == project_id,
                    S.source_anchors.c.extraction_id == extraction["id"]).order_by(S.source_anchors.c.start_char)).mappings()
                extraction["anchors"] = [dict(r, text=extraction["text"][r["start_char"]:r["end_char"]]) for r in anchors]
                job["extractions"].append(extraction)
        job["can_import"] = job["status"] == "succeeded" and job["intent"] == "screenplay"
        job["automatic_approval"] = False
        return job

    def get_parse_job(self, project_id, job_id):
        with self.engine.connect() as conn:
            project = self._project(conn, project_id)
            return clean(dict(self._parse_job(conn, project["id"], job_id), revision=project["revision"]))

    def list_parse_jobs(self, project_id):
        with self.engine.connect() as conn:
            project = self._project(conn, project_id)
            identifiers = conn.execute(select(S.parse_jobs.c.id).where(S.parse_jobs.c.project_id == project["id"])
                .order_by(S.parse_jobs.c.created_at.desc(), S.parse_jobs.c.id)).scalars()
            return clean({"revision": project["revision"], "jobs": [
                {k: v for k, v in self._parse_job(conn, project["id"], identifier).items() if k != "extractions"}
                for identifier in identifiers]})

    def preview_parse_job(self, project_id, job_id):
        job = self.get_parse_job(project_id, job_id)
        if job["status"] != "succeeded":
            raise ResourceError("解析尚未成功；保留来源并查看失败记录后重试", "parse_not_succeeded", 409)
        proposal = structure_proposal(job["extractions"])
        return dict(job, proposal=proposal, structure_proposal=proposal,
                    defaults_preview={"work_title": "第一部", "episode_title": "第一集",
                        "sequence_per_scene": True, "creates_shots": False,
                        "duration_ms": None, "requires_confirmation": True},
                    next_step="map_and_correct" if job["can_import"] else "profile_adaptation_required")

    def prepare_parse_import(self, project_id, payload, **kw):
        """Apply a displayed structure proposal only after explicit confirmation.

        Reuse always names a typed stable ID. New identities use job-specific
        display codes, never a name lookup. No shots or approvals are invented.
        Scene durations remain a human input required by import.
        """
        if payload.get("confirmed") is not True:
            raise ResourceError("须明确确认结构提案后创建目录与人物", "structure_confirmation_required")

        def work(conn, project):
            p = project["id"]
            job = self._parse_job(conn, p, required(payload, "job_id"))
            if not job["can_import"]:
                raise ResourceError("仅成功的成型剧本解析可准备导入", "adaptation_required")
            if required(payload, "attempt_id") != job["attempts"][-1]["id"]:
                raise Conflict("解析已更新，请重新确认结构提案", "parse_attempt_conflict")
            proposal = structure_proposal(job["extractions"])
            created, scene_map, speaker_map = [], {}, {}
            prefix = "SRC-" + job["id"][:8] + "-"

            def make(kind, label, parent=None, ordinal=0, code=None):
                result = self._create_object(conn, project, {"kind": kind, "title": label,
                    "display_code": prefix + (code or kind.upper()), "parent_id": parent, "ordinal": ordinal,
                    **({"asset_kind": "character"} if kind == "asset" else {})})
                created.append({"id": result["id"], "kind": kind, "title": label, "system_default": kind in ("work", "episode", "sequence")})
                return result["id"]

            def next_ordinal(table, parent=None):
                query = select(func.coalesce(func.max(table.c.ordinal), -1)).where(table.c.project_id == p)
                if parent:
                    query = query.where(table.c.parent_id == parent)
                return conn.execute(query).scalar_one() + 1

            episode_id = payload.get("episode_id")
            if episode_id:
                episode_id = self._one(conn, S.episodes, p, episode_id)["id"]
            else:
                work_id = payload.get("work_id")
                if work_id:
                    work_id = self._one(conn, S.works, p, work_id)["id"]
                else:
                    work_id = make("work", payload.get("work_title", "第一部"), ordinal=next_ordinal(S.works))
                episode_id = make("episode", payload.get("episode_title", "第一集"), work_id, next_ordinal(S.episodes, work_id))
            scene_ordinal = next_ordinal(S.scenes, episode_id)
            existing_scenes = payload.get("scene_mapping", {})
            for index, scene in enumerate(proposal["scenes"]):
                if not scene["units"]:
                    continue
                if scene["key"] in existing_scenes:
                    row = self._one(conn, S.scenes, p, existing_scenes[scene["key"]])
                    if row["parent_id"] != episode_id:
                        raise ResourceError("复用场次不属于明确选定集", "source_scope_mismatch")
                    scene_id = row["id"]
                else:
                    scene_id = make("scene", scene["source_label"], episode_id, scene_ordinal + index, scene["key"].upper())
                    make("sequence", "默认序列", scene_id, 0, scene["key"].upper() + "-SEQ")
                scene_map[scene["key"]] = scene_id
            if len(set(scene_map.values())) != len(scene_map):
                raise ResourceError("不同来源场次不可自动合并", "duplicate_scene_mapping")
            supplied = payload.get("speaker_mapping", {})
            # A per-unit mapping takes precedence when equal source names mean
            # different people. Shared new identities require an explicit group.
            new_groups = payload.get("new_character_groups", {})
            group_ids = {}
            for scene in proposal["scenes"]:
                for unit in scene["units"]:
                    if unit["kind"] != "dialogue":
                        continue
                    stable_id = supplied.get(unit["key"], supplied.get(unit["speaker_text"]))
                    if stable_id:
                        asset = self._one(conn, S.asset_identities, p, stable_id)
                        if asset["asset_kind"] != "character":
                            raise ResourceError("说话人须为当前项目人物", "invalid_speaker_mapping")
                        speaker_map[unit["key"]] = asset["id"]
                    else:
                        group = new_groups.get(unit["key"], unit["key"])
                        if group not in group_ids:
                            group_ids[group] = make("asset", unit["speaker_text"] or "待命名人物", code="CHAR-" + unit["key"])
                        speaker_map[unit["key"]] = group_ids[group]
            return {"scope_key": episode_id, "episode_id": episode_id, "scene_mapping": scene_map,
                "speaker_mapping": speaker_map, "durations_ms": payload.get("durations_ms", {}),
                "system_created": created, "requires_duration_review": True, "automatic_approval": False}
        return self._mutate(project_id, "prepare_parse_import", payload, callback=work, **kw)

    def get_source_anchor(self, project_id, anchor_id):
        with self.engine.connect() as conn:
            project = self._project(conn, project_id)
            anchor = self._one(conn, S.source_anchors, project["id"], anchor_id)
            extraction = self._one(conn, S.source_extractions, project["id"], anchor["extraction_id"])
            source = self._one(conn, S.source_versions, project["id"], anchor["source_id"])
            title = conn.execute(select(S.source_intake_documents.c.title).where(
                S.source_intake_documents.c.project_id == project["id"],
                S.source_intake_documents.c.source_id == source["id"])).scalar_one_or_none()
            return clean(dict(anchor, text=extraction["text"][anchor["start_char"]:anchor["end_char"]],
                source_sha256=source["sha256"], source_name=title or source["evidence_uri"], untrusted_material=True))

    def import_parse_job(self, project_id, payload, **kw):
        def work(conn, project):
            p = project["id"]
            job = self._parse_job(conn, p, required(payload, "job_id"))
            if not job["can_import"]:
                raise ResourceError("仅成功的成型剧本解析可进入草稿；小说/大纲先走 Profile 改编链", "adaptation_required" if job["intent"] != "screenplay" else "parse_not_succeeded")
            if required(payload, "attempt_id") != job["attempts"][-1]["id"]:
                raise Conflict("解析结果已重试更新；请重新预览并确认映射", "parse_attempt_conflict")
            proposal = structure_proposal(job["extractions"])
            scene_map = required(payload, "scene_mapping")
            speaker_map = payload.get("speaker_mapping", {})
            durations = required(payload, "durations_ms")
            if not all(isinstance(v, dict) for v in (scene_map, speaker_map, durations)):
                raise ResourceError("场、角色、时长映射必须是对象", "invalid_mapping")
            if any(not isinstance(payload.get(key, {}), dict) for key in ("corrections", "narrative_refs", "silence_durations_ms")):
                raise ResourceError("校对、叙事引用及静默时长必须为对象", "invalid_mapping")
            scope = self._scope_key(payload.get("scope_key", ""))
            if scope:
                self._one(conn, S.creative_objects, p, scope)
            parents = self._object_parents(conn, p)
            selected = payload.get("unit_keys")
            available_units = {u["key"] for s in proposal["scenes"] for u in s["units"]}
            if selected is not None and (not isinstance(selected, list) or not selected or not set(selected) <= available_units):
                raise ResourceError("部分采纳须列出当前解析的有效 unit_keys", "invalid_mapping")
            document = {"format": "vsc.screenplay/v1", "project_id": p, "scope": scope or "project",
                "adaptation_refs": copy.deepcopy(payload.get("adaptation_refs", [])), "scenes": [], "structured_source": True}
            refs, mapped_scenes = [], set()
            for proposed in proposal["scenes"]:
                units = [u for u in proposed["units"] if selected is None or u["key"] in selected]
                if not units:
                    continue
                scene_id = checked_id(required(scene_map, proposed["key"]))
                self._one(conn, S.scenes, p, scene_id)
                if scope and scope not in self._ancestor_chain(scene_id, parents):
                    raise ResourceError("场次不属于选定草稿范围", "source_scope_mismatch")
                if scene_id in mapped_scenes:
                    raise ResourceError("多个来源场次不能无声合并；先校对结构后映射", "duplicate_scene_mapping")
                mapped_scenes.add(scene_id)
                duration = required(durations, proposed["key"])
                if type(duration) is not int or duration <= 0:
                    raise ResourceError("场时长必须由校对者明确为正毫秒数", "invalid_mapping")
                scene = {"id": scene_id, "source_label": proposed["source_label"], "estimated_duration_ms": duration,
                         "actions": [], "dialogue": [], "silence": []}
                for order, unit in enumerate(units):
                    key = "src-" + unit["anchor_id"]
                    text = payload.get("corrections", {}).get(unit["key"], unit["text"])
                    if not isinstance(text, str) or not text.strip():
                        raise ResourceError("校对行必须保留非空正文；不采纳的行使用 unit_keys", "invalid_mapping")
                    row = {"id": key, "text": text, "source_order": order,
                           "narrative_refs": payload.get("narrative_refs", {}).get(unit["key"], [])}
                    if unit["kind"] == "dialogue":
                        speaker = checked_id(speaker_map.get(unit["key"], required(speaker_map, unit["speaker_text"]) if unit["speaker_text"] in speaker_map else None))
                        asset = self._one(conn, S.asset_identities, p, speaker)
                        if asset["asset_kind"] != "character":
                            raise ResourceError("说话人必须映射到当前项目人物身份", "invalid_speaker_mapping")
                        row["speaker"] = speaker
                        row["speaker_label"] = unit["speaker_text"]
                        scene["dialogue"].append(row)
                    elif unit["kind"] == "silence":
                        silence_duration = payload.get("silence_durations_ms", {}).get(unit["key"])
                        if type(silence_duration) is not int or silence_duration <= 0:
                            raise ResourceError("静默需要明确的正时长", "invalid_mapping")
                        row.update(duration_ms=silence_duration, purpose=text)
                        scene["silence"].append(row)
                    else:
                        if unit["kind"] == "narration":
                            row["kind"] = "narration"
                        scene["actions"].append(row)
                    refs.append({"scene_key": scene_id, "line_key": key, "anchor_id": unit["anchor_id"], "role": "source"})
                document["scenes"].append(scene)
            if not document["scenes"]:
                raise ResourceError("没有可导入的结构行", "empty_extraction")
            document["body"] = render_structured_body(document)
            draft = self._draft(conn, p, scope, lock=True)
            base = required(payload, "base_draft_revision")
            current = draft["draft_revision"] if draft else 0
            if type(base) is not int or base != current:
                raise Conflict("草稿已更新；请重新校对后导入", "draft_revision_conflict")
            revision = current + 1
            draft_id = draft["id"] if draft else new_id()
            if draft:
                conn.execute(update(S.script_drafts).where(S.script_drafts.c.project_id == p,
                    S.script_drafts.c.id == draft_id).values(content=document, draft_revision=revision,
                    updated_by=kw.get("actor") or "", updated_at=func.now()))
            else:
                conn.execute(insert(S.script_drafts).values(project_id=p, id=draft_id, scope_key=scope,
                    content=document, draft_revision=revision, updated_by=kw.get("actor") or ""))
            for ref in refs:
                conn.execute(insert(S.draft_source_refs).values(project_id=p, id=new_id(), draft_id=draft_id,
                    draft_revision=revision, **ref))
            return {"scope_key": scope, "draft_revision": revision, "draft_id": draft_id, "content": document,
                "source_ref_count": len(refs), "warnings": proposal["warnings"], "automatic_approval": False,
                "next_step": "correct_then_submit_existing_script_draft"}
        return self._mutate(project_id, "import_parse_job", payload, callback=work, **kw)

    @staticmethod
    def _source_draft_content(content):
        if content.get("structured_source"):
            content = copy.deepcopy(content)
            content["body"] = render_structured_body(content)
        return content

    @staticmethod
    def _source_draft_saved(conn, project_id, draft_id, old_revision, new_revision, content):
        """Carry provenance for retained stable units to this exact revision."""
        rows = list(conn.execute(select(S.draft_source_refs).where(S.draft_source_refs.c.project_id == project_id,
            S.draft_source_refs.c.draft_id == draft_id, S.draft_source_refs.c.draft_revision == old_revision)).mappings())
        if not rows:
            return
        units = {(str(s["id"]), str(u["id"])) for s in content.get("scenes", [])
                 for kind in ("actions", "dialogue", "silence") for u in s.get(kind, [])}
        for row in rows:
            if (row["scene_key"], row["line_key"]) in units:
                conn.execute(insert(S.draft_source_refs).values(project_id=project_id, id=new_id(), draft_id=draft_id,
                    draft_revision=new_revision, **{k: row[k] for k in ("scene_key", "line_key", "anchor_id", "role")}))

    @staticmethod
    def _source_draft_submitted(conn, project_id, draft, artifact_id):
        lines = {r["line_key"]: dict(r) for r in conn.execute(select(S.script_lines).where(
            S.script_lines.c.project_id == project_id, S.script_lines.c.script_version_id == artifact_id)).mappings()}
        for ref in conn.execute(select(S.draft_source_refs).where(S.draft_source_refs.c.project_id == project_id,
                S.draft_source_refs.c.draft_id == draft["id"],
                S.draft_source_refs.c.draft_revision == draft["draft_revision"])).mappings():
            line = lines.get(ref["line_key"])
            if not line or str(line["scene_id"]) != ref["scene_key"]:
                raise ResourceError("来源关联与待冻结剧本行不一致，停止提交", "source_projection_mismatch")
            conn.execute(insert(S.script_line_sources).values(project_id=project_id, id=new_id(),
                line_id=line["id"], anchor_id=ref["anchor_id"], role=ref["role"]))

    @staticmethod
    def _source_draft_refs(conn, project_id, draft):
        if not draft:
            return []
        return [clean(dict(row)) for row in conn.execute(select(S.draft_source_refs).where(
            S.draft_source_refs.c.project_id == project_id, S.draft_source_refs.c.draft_id == draft["id"],
            S.draft_source_refs.c.draft_revision == draft["draft_revision"])).mappings()]
