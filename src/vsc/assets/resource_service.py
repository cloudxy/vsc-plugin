"""Provider-neutral resource use cases shared by CLI, web and AI callers.

No SQL, HTTP or provider SDK is imported here. A repository owns the transaction
including revision checks, immutable decisions and materialized current bindings.
"""
import hashlib
import json


class ResourceError(Exception):
    def __init__(self, message, code="invalid_resource", status_code=422):
        super().__init__(message)
        self.message, self.code, self.status_code = message, code, status_code


class Conflict(ResourceError):
    def __init__(self, message="项目已发生变化，请刷新后重试", code="revision_conflict"):
        super().__init__(message, code, 409)


class NotFound(ResourceError):
    def __init__(self, message="资源不存在"):
        super().__init__(message, "not_found", 404)


ROLE_MATRIX = {
    "identity_face": ({"asset", "shot"}, {"image"}),
    "costume": ({"asset", "shot"}, {"image"}),
    "location_master": ({"asset", "shot"}, {"image"}),
    "location_view": ({"asset", "shot"}, {"image"}),
    "composition": ({"shot"}, {"image"}),
    "storyboard": ({"shot"}, {"image"}),
    "subtitle_style": ({"work", "episode", "scene", "shot", "asset"}, {"text", "document"}),
    "font": ({"work", "episode", "scene", "shot", "asset"}, {"document", "other"}),
    "lut": ({"work", "episode", "scene", "shot", "asset"}, {"document", "other"}),
    "post_mask": ({"work", "episode", "scene", "shot", "asset"}, {"image"}),
    "first_frame": ({"shot"}, {"image"}),
    "last_frame": ({"shot"}, {"image"}),
    "reference_audio": ({"shot"}, {"audio"}),
    "prop": ({"asset", "shot"}, {"image"}),
    "video_take": ({"shot"}, {"video"}),
    "dialogue_dry": ({"shot"}, {"audio"}),
    "voice_sample": ({"asset", "shot"}, {"audio"}),
    "ambience": ({"scene", "shot"}, {"audio"}),
    "music": ({"work", "episode", "scene", "shot"}, {"audio"}),
    "sfx": ({"scene", "shot"}, {"audio"}),
    "style_reference": ({"asset", "shot"}, {"image"}),
}
INHERITED_REFERENCE_ROLES = frozenset({
    "identity_face", "costume", "location_master", "location_view", "prop",
    "voice_sample", "style_reference",
})
POST_ROLES = frozenset({"video_take", "dialogue_dry", "ambience", "music", "sfx",
                        "subtitle_style", "font", "lut", "post_mask"})


def context_digest(context):
    """Hash fixed creative inputs, excluding revision and availability displays."""
    if "semantic_inputs" in context:
        value = {k: context.get(k) for k in ("project_id", "shot_id", "purpose", "ancestors", "semantic_inputs")}
        if context.get("asset_id"):
            value["asset_id"] = context["asset_id"]
        value["media"] = [{k: item[k] for k in ("media_id", "sha256", "role", "target_object_id")}
                          for item in context.get("media", [])]
        return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
            separators=(",", ":"), default=str).encode("utf-8")).hexdigest()
    value = {k: v for k, v in context.items() if k not in {"revision", "gaps", "ready", "sha256"}}
    value["artifacts"] = [{k: a[k] for k in ("id", "artifact_type", "sha256")} for a in context.get("artifacts", [])]
    value["media"] = [{k: v for k, v in item.items() if k != "locations"} for item in context.get("media", [])]
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def required(payload, name):
    if not isinstance(payload, dict):
        raise ResourceError("输入必须是对象", "invalid_payload")
    value = payload.get(name)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ResourceError("缺少字段: " + name, "missing_field")
    return value


def artifact_stage(profile, artifact_type, fallback=None):
    """Resolve ownership from the immutable Profile, never caller stage labels."""
    owners = [stage["id"] for stage in profile.get("stages", []) if artifact_type in stage.get("required", [])]
    if len(owners) > 1:
        raise ResourceError("固定 Profile 中产物类型归属不唯一: " + artifact_type, "invalid_profile")
    return owners[0] if owners else fallback


def dependency_requirements(profile, artifact_type):
    explicit = profile.get("dependency_requirements", {}).get(artifact_type)
    if explicit is not None:
        return explicit, None
    stages = profile.get("stages", [])
    owner = artifact_stage(profile, artifact_type)
    index = next((i for i, stage in enumerate(stages) if stage["id"] == owner), None)
    if profile.get("dependency_policy") == "previous_stage" and index:
        return stages[index - 1].get("required", []), stages[index - 1]["id"]
    return [], None


from vsc.assets.role_memory import RoleMemoryService
from vsc.assets.source_resource import SourceResourceService
from vsc.assets.resource_model import ResourceModelService
from vsc.assets.feedback import ReviewService
from vsc.assets.media_recycle import MediaRecycleService
from vsc.assets.edit_preview import EditPreviewService


class ResourceService(RoleMemoryService, SourceResourceService, ResourceModelService, ReviewService,
                      MediaRecycleService, EditPreviewService):
    def __init__(self, store, storage=None, script_suggester=None):
        self.store, self.storage = store, storage
        self.script_suggester = script_suggester

    def list_projects(self):
        return self.store.list_projects()

    def check_schema(self, *, read_only=False):
        return self.store.check_schema(read_only=True) if read_only else self.store.check_schema()

    def create_project(self, payload, actor=None, **kwargs):
        self._actor(actor)
        required(payload, "name")
        payload = dict(payload)
        if "profile_snapshot" not in payload:
            from vsc.project.state import profile_for
            payload["profile_snapshot"] = profile_for(payload.get("profile", "vsc.series-pg"))
        snapshot = payload["profile_snapshot"]
        if (not isinstance(snapshot, dict) or not isinstance(snapshot.get("profile_id"), str) or not snapshot["profile_id"]
                or not isinstance(snapshot.get("version"), str) or not snapshot["version"] or not isinstance(snapshot.get("stages"), list)):
            raise ResourceError("固定Profile需要profile_id、version与stages", "invalid_profile_snapshot")
        if payload.get("profile", snapshot["profile_id"]) != snapshot["profile_id"]:
            raise ResourceError("Profile名称与固定快照不一致", "invalid_profile_snapshot")
        if snapshot.get("storage_policy", "postgres-series-v1") != "postgres-series-v1":
            raise ResourceError("新PostgreSQL项目需要匹配的存储策略Profile", "invalid_profile_snapshot")
        payload["profile"] = snapshot["profile_id"]
        return self.store.create_project(payload, actor=actor, **kwargs)

    def get_project(self, project_id):
        return self.store.get_project(project_id)

    def get_operation_receipt(self, project_id, key, actor=None):
        self._actor(actor)
        return self.store.get_operation_receipt(project_id, key, actor)

    def get_project_tree(self, project_id):
        return self.store.get_project_tree(project_id)

    def list_resources(self, project_id, object_id=None, offset=0, limit=50, modality=None, **filters):
        if not isinstance(offset, int) or not isinstance(limit, int) or offset < 0 or not 1 <= limit <= 200:
            raise ResourceError("分页要求 offset >= 0，1 <= limit <= 200", "invalid_page")
        return self.store.list_resources(project_id, object_id=object_id, offset=offset,
                                         limit=limit, modality=modality, **filters)

    def get_media(self, project_id, media_id):
        value = self.store.get_media(project_id, media_id)
        value["review_history"] = self.get_review_history(project_id, media_id=media_id)
        value["review_targets"] = self._reviews().targets(project_id, media_id=media_id)
        return value

    def get_artifact_version(self, project_id, artifact_id):
        value = self.store.get_artifact_version(project_id, artifact_id)
        value["review_history"] = self.get_review_history(project_id, artifact_id=artifact_id)
        value["review_targets"] = self._reviews().targets(project_id, artifact_id=artifact_id)
        return value

    def get_source_version(self, project_id, source_id):
        return self.store.get_source_version(project_id, source_id)

    def list_artifacts(self, project_id, object_id=None):
        return self.store.list_artifacts(project_id, object_id=object_id)

    def list_sources(self, project_id):
        return self.store.list_sources(project_id)

    def get_timeline(self, project_id, timeline_id):
        return self.store.get_timeline(project_id, timeline_id)

    def get_projection_id_map(self, project_id):
        return self.store.get_projection_id_map(project_id)

    def compile_asset_context(self, project_id, asset_id, purpose="asset_ref"):
        context = self.store.compile_asset_context(project_id, asset_id, purpose=purpose)
        if self.storage is not None:
            for item in context.get("media", []):
                try:
                    self._verify_media(project_id, item["media_id"], expected_sha=item["sha256"], snapshot=item)
                except ResourceError as error:
                    context.setdefault("gaps", []).append({"code": error.code, "media_id": item["media_id"]})
            context["ready"] = not context.get("gaps")
            context["sha256"] = context_digest(context)
        return context

    def get_media_lineage(self, project_id, media_id):
        return self.store.get_media_lineage(project_id, media_id)

    def get_media_usage(self, project_id, media_id):
        return self.store.get_media_usage(project_id, media_id)

    def compile_shot_context(self, project_id, shot_id, purpose=None):
        context = self.store.compile_shot_context(project_id, shot_id, purpose=purpose)
        if self.storage is not None:
            for item in context.get("media", []):
                try:
                    self._verify_media(project_id, item["media_id"], expected_sha=item["sha256"], snapshot=item)
                except ResourceError as error:
                    context.setdefault("gaps", []).append({"code": error.code, "media_id": item["media_id"]})
            context["ready"] = not context.get("gaps")
            context["sha256"] = context_digest(context)
        return context

    def _verify_media(self, project_id, media_id, expected_sha=None, snapshot=None):
        if self.storage is None:
            return
        media = snapshot if snapshot is not None else self.store.get_media(project_id, media_id)
        sha = expected_sha or media["sha256"]
        if media["sha256"] != sha:
            raise ResourceError("固定媒体摘要已改变", "media_sha_mismatch")
        locations = [l for l in media.get("locations", []) if l.get("available") and l.get("storage") == "local"]
        last = None
        for location in locations:
            try:
                self.storage.verify(location["object_key"], sha)
                return
            except (OSError, ResourceError) as error:
                last = error
        if isinstance(last, ResourceError):
            raise last
        raise ResourceError("正式消费所需的固定字节不可读取", "media_unavailable")

    @staticmethod
    def _actor(actor):
        if not isinstance(actor, str) or not actor.strip():
            raise ResourceError("写操作需要可信操作会话的身份", "actor_required", 403)

    def _validate_write(self, payload, expected_revision=None, idempotency_key=None, actor=None):
        self._actor(actor)
        if not isinstance(payload, dict):
            raise ResourceError("输入必须是对象", "invalid_payload")
        if not isinstance(expected_revision, int) or isinstance(expected_revision, bool) or expected_revision < 0:
            raise ResourceError("写操作需要 expected_revision", "revision_required")
        if not isinstance(idempotency_key, str) or not idempotency_key.strip() or len(idempotency_key) > 200:
            raise ResourceError("写操作需要不超过 200 字符的 idempotency_key", "idempotency_required")
        if "actor" in payload or "approved_by" in payload:
            raise ResourceError("操作身份由可信会话提供", "untrusted_actor")

    def _write(self, method, project_id, payload, expected_revision=None, idempotency_key=None, actor=None):
        self._validate_write(payload, expected_revision=expected_revision, idempotency_key=idempotency_key, actor=actor)
        return getattr(self.store, method)(project_id, payload, expected_revision=expected_revision,
                                           idempotency_key=idempotency_key, actor=actor)

    def create_object(self, project_id, payload, **kw):
        return self._write("create_object", project_id, payload, **kw)

    def create_artifact(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        artifact_type = required(payload, "artifact_type")
        project = self.store.get_project(project_id)
        if isinstance(artifact_type, str) and artifact_type.startswith("vsc."):
            from vsc.project.pg_workflow import validate_contract
            errors = validate_contract(required(payload, "document"), artifact_type,
                project["profile_snapshot"].get("contract_policy", "production-v2"))
            if errors:
                raise ResourceError("产物违反固定契约: " + "; ".join(errors), "invalid_contract")
        return self._write("create_artifact", project_id, payload, **kw)

    # ---------- 剧本工作区（Q1：工作副本、批注、提交确认） ----------

    def get_script_draft(self, project_id, scope_key=""):
        from vsc.assets.script_inputs import editor_inputs
        value = editor_inputs(self, project_id, self.store.get_script_draft(project_id, scope_key))
        value["suggestion_runs"] = self.store.list_script_suggestion_runs(project_id, scope_key)
        for note in value.get("notes", []):
            note["review_history"] = self.get_review_history(project_id, script_note_id=note["id"])["items"][0]
        return value

    def resume_script_suggestions(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        run_id = required(payload, "run_id")
        run = self.store.get_script_suggestion_run(project_id, run_id)
        if run["status"] == "running" and run["result"] is not None:
            return self.store.finish_script_suggestion_run(project_id, {"run_id": run_id}, actor=kw["actor"],
                expected_revision=kw["expected_revision"], idempotency_key="script-ai-finish:" + run_id)
        return {"id": run_id, "status": run["status"], "result": run["result"],
                "revision": self.get_project(project_id)["revision"]}

    def save_script_draft(self, project_id, payload, actor=None, **_):
        self._actor(actor)
        if not isinstance(payload, dict) or "actor" in payload:
            raise ResourceError("输入必须是对象，操作身份由可信会话提供", "invalid_payload")
        return self.store.save_script_draft(project_id, payload, actor=actor)

    def submit_script_draft(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        # The repository normalizes trusted project/scope fields and validates
        # those exact frozen bytes under the same draft lock and transaction.
        required(payload, "artifact_type")
        return self._write("submit_script_draft", project_id, payload, **kw)

    def add_script_note(self, project_id, payload, **kw):
        return self._write("add_script_note", project_id, payload, **kw)

    def decide_script_note(self, project_id, payload, **kw):
        return self._write("decide_script_note", project_id, payload, **kw)

    def add_script_suggestion(self, project_id, payload, **kw):
        return self._write("add_script_suggestion", project_id, payload, **kw)

    def generate_script_suggestions(self, project_id, payload, **kw):
        from vsc.assets.script_ai import GrokBuildSuggestions, generate_suggestions
        return generate_suggestions(self, project_id, payload,
            self.script_suggester if self.script_suggester is not None else GrokBuildSuggestions(), **kw)

    def preview_local_production(self, project_id, payload):
        from vsc.assets.local_production import LocalProduction
        return LocalProduction(self).preview(project_id, payload)

    def local_production_options(self, project_id, action, entity_id):
        from vsc.assets.local_production import LocalProduction
        return LocalProduction(self).options(project_id, action, entity_id)

    def propose_local_production(self, project_id, payload, **kw):
        from vsc.assets.local_production import LocalProduction
        return LocalProduction(self).propose(project_id, payload, **kw)

    def enqueue_local_production(self, project_id, payload, **kw):
        from vsc.assets.local_production import LocalProduction
        return LocalProduction(self).enqueue(project_id, payload, **kw)

    def decide_script_suggestion(self, project_id, payload, **kw):
        return self._write("decide_script_suggestion", project_id, payload, **kw)

    def script_revision_impact(self, project_id, scope_key=""):
        return self.store.script_revision_impact(project_id, scope_key)

    def compare_script_draft(self, project_id, scope_key="", base_artifact_id=None):
        from vsc.assets.script_diff import compare_documents
        draft = self.store.get_script_draft(project_id, scope_key)
        base = draft.get("base") or {}
        base_id = base_artifact_id or base.get("id")
        if base_id is None:
            # F08：基线按精确范围选取——项目级稿只认项目级剧本，分集稿只认项目级或覆盖该集的剧本。
            project = self.store.get_project(project_id)
            stages = project["profile_snapshot"].get("stages", [])
            script_types = {kind for stage in stages for kind in stage.get("required", []) if "screenplay" in kind}
            if script_types:
                for row in self.list_artifacts(project_id)["items"]:
                    if row.get("artifact_type") not in script_types or not row.get("current") or not row.get("approved"):
                        continue
                    if scope_key:
                        if row.get("project_wide") or scope_key in (row.get("object_ids") or []):
                            base_id, base = row["id"], {"id": row["id"], "version": row.get("version"),
                                                        "sha256": row.get("sha256")}
                            break
                    elif row.get("project_wide"):
                        base_id, base = row["id"], {"id": row["id"], "version": row.get("version"),
                                                    "sha256": row.get("sha256")}
                        break
        baseline = self.get_artifact_version(project_id, base_id).get("content") if base_id else None
        if isinstance(baseline, str):
            import json
            try:
                baseline = json.loads(baseline)
            except ValueError:
                baseline = None
        current = draft.get("content")
        # These two fields are owned by the server at freeze time, not by an
        # editor. Compare the same trusted document on both sides.
        if isinstance(current, dict):
            current = dict(current, project_id=project_id, scope=draft["scope_key"] or "project")
        if isinstance(baseline, dict):
            baseline = dict(baseline, project_id=project_id, scope=draft["scope_key"] or "project")
        return {"scope_key": draft["scope_key"], "phase": draft["phase"],
                "base_artifact_id": base_id, "base": base or None,
                "changes": compare_documents(baseline, current)}

    def decide_artifact(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        if payload.get("outcome", "approve") == "approve":
            artifact = self.store.get_artifact_version(project_id, required(payload, "artifact_id"))
            if artifact["artifact_type"].startswith("vsc."):
                from vsc.project.pg_workflow import validate_contract
                project = self.store.get_project(project_id)
                errors = validate_contract(artifact["document"], artifact["artifact_type"],
                    project["profile_snapshot"].get("contract_policy", "production-v2"))
                if errors:
                    raise ResourceError("不能批准违反固定契约的产物: " + "; ".join(errors), "invalid_contract")
                self._check_dependencies(project, artifact)
        return self._write("decide_artifact", project_id, payload, **kw)

    def _check_dependencies(self, project, artifact):
        profile = project["profile_snapshot"]
        explicit, expected_stage = dependency_requirements(profile, artifact["artifact_type"])
        if not explicit:
            return
        dependencies = [self.store.get_artifact_version(project["id"], row_id) for row_id in artifact.get("dependency_ids", [])]
        parents = {node["id"]: node["parent_id"] for node in self.get_project_tree(project["id"])["nodes"] if node.get("parent_id")}
        def covers(dep):
            if dep["project_wide"]:
                return True
            if artifact["project_wide"]:
                return False
            for scope in artifact.get("object_ids", []):
                chain, cursor = {scope}, scope
                while cursor in parents:
                    cursor = parents[cursor]
                    chain.add(cursor)
                if not chain.intersection(dep.get("object_ids", [])):
                    return False
            return True
        for kind in explicit:
            if not any(dep["artifact_type"] == kind and (expected_stage is None or
                       artifact_stage(profile, dep["artifact_type"], dep["stage"]) == expected_stage) and covers(dep) for dep in dependencies):
                raise ResourceError("缺少同范围前置产物的明确固定依赖: " + kind, "artifact_dependency_required")

    def register_media(self, project_id, payload, **kw):
        """Register verified bytes already in a controlled storage adapter.

        HTTP never accepts arbitrary server paths. Adapters may provide sha256,
        probe and location after staging/hash validation; unknown rights remain
        unknown and cannot be selected for production.
        """
        self._validate_write(payload, **kw)
        if self.storage is not None and "staged_upload" in payload:
            payload = dict(payload)
            display_name = payload.get("name")
            verified = self.storage.commit_upload(payload.pop("staged_upload"))
            payload.update(verified)
            # The caller may name its project registration. Byte identity,
            # modality, probe and storage location still come only from staging.
            if display_name is not None:
                payload["name"] = display_name
        return self._write("register_media", project_id, payload, **kw)

    def propose_binding(self, project_id, payload, **kw):
        return self._write("propose_binding", project_id, payload, **kw)

    def record_review(self, project_id, payload, **kw):
        return self._write("record_review", project_id, payload, **kw)

    def select_candidate(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        if payload.get("delegation_artifact_id") and self.storage is None:
            raise ResourceError("委托选择必须核验受控存储实际字节", "delegation_storage_required")
        if self.storage is not None:
            candidate = self.store.get_binding_candidate(project_id, required(payload, "candidate_id"))
            self._verify_media(project_id, candidate["media_id"])
        return self._write("select_candidate", project_id, payload, **kw)

    def reject_candidate(self, project_id, payload, **kw):
        return self._write("reject_candidate", project_id, payload, **kw)

    def retire_binding(self, project_id, payload, **kw):
        return self._write("retire_binding", project_id, payload, **kw)

    def decide_media_lifecycle(self, project_id, payload, **kw):
        return self._write("decide_media_lifecycle", project_id, payload, **kw)

    def deprecate_media(self, project_id, payload, **kw):
        return self.decide_media_lifecycle(project_id, dict(payload, outcome="deprecate"), **kw)

    def decide_rights(self, project_id, payload, **kw):
        return self._write("decide_rights", project_id, payload, **kw)

    def record_media_check(self, project_id, payload, **kw):
        return self._write("record_media_check", project_id, payload, **kw)

    def create_media_operation(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        if self.storage is not None:
            for item in list(required(payload, "inputs")) + list(required(payload, "outputs")):
                self._verify_media(project_id, required(item, "media_id"))
        return self._write("create_media_operation", project_id, payload, **kw)

    def create_preview_job(self, project_id, payload, **kw):
        return self._write("create_preview_job", project_id, payload, **kw)

    def list_preview_jobs(self, project_id, media_id=None):
        return self.store.list_preview_jobs(project_id, media_id=media_id)

    def get_media_rendition(self, project_id, media_id, purpose=None):
        return self.store.get_media_rendition(project_id, media_id, purpose=purpose)

    def claim_preview_job(self, project_id=None, retry_failed=False, stale_after_seconds=300):
        return self.store.claim_preview_job(project_id=project_id, retry_failed=retry_failed, stale_after_seconds=stale_after_seconds)

    def finish_preview_job(self, project_id, job_id, attempt, result):
        if self.storage is not None:
            if result.get("storage") != "local":
                raise ResourceError("预览结果没有可校验本地存储", "storage_unavailable")
            self.storage.verify(required(result, "object_key"), required(result, "sha256"))
        return self.store.finish_preview_job(project_id, job_id, attempt, result)

    def fail_preview_job(self, project_id, job_id, attempt, error):
        return self.store.fail_preview_job(project_id, job_id, attempt, error)

    def retry_preview_job(self, project_id, payload, **kw):
        return self._write("retry_preview_job", project_id, payload, **kw)

    def create_generation_job(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        self._preflight_generation_job(project_id, payload)
        return self._write("create_generation_job", project_id, payload, **kw)

    def _preflight_generation_job(self, project_id, payload):
        from vsc.production.video_operations import verify_operation_source
        verify_operation_source(self, project_id, payload.get("request_payload", {}))
        project = self.store.get_project(project_id)
        gated = any(stage.get("id") == "animatic" for stage in project.get("profile_snapshot", {}).get("stages", []))
        if self.storage is not None or gated:
            asset = payload.get("asset_id")
            context = (self.compile_asset_context(project_id, asset, purpose=payload.get("purpose")) if asset else
                self.compile_shot_context(project_id, required(payload, "shot_id"), purpose=payload.get("purpose")))
            if not context["ready"]:
                raise ResourceError("固定输入实物或上下文有缺口，不能生成", "context_gaps")
            if gated:
                from vsc.project.pg_workflow import check_gate
                run = self.store.get_artifact_version(project_id, required(payload, "run_version_id"))
                try:
                    trial = json.loads(run["document"]).get("phase") == "trial"
                except (ValueError, TypeError, AttributeError) as exc:
                    raise ResourceError("运行包必须是固定结构文档", "invalid_production_run") from exc
                gate = check_gate(self, project_id, "script" if asset or trial else "animatic",
                    scope=payload.get("episode_id") if asset else context["ancestors"][1])
                if not gate["passed"]:
                    raise ResourceError("正式制作前序Gate尚未通过", "production_gate_failed")
    def register_provider(self, payload, actor=None):
        self._actor(actor)
        return self.store.register_provider(payload, actor=actor)

    def register_model(self, payload, actor=None):
        self._actor(actor)
        return self.store.register_model(payload, actor=actor)

    def register_route(self, payload, actor=None):
        self._actor(actor)
        return self.store.register_route(payload, actor=actor)

    def configure_budget(self, project_id, payload, **kw):
        return self._write("configure_budget", project_id, payload, **kw)

    def budget_status(self, project_id):
        return self.store.budget_status(project_id)

    def list_models(self, modality=None):
        return self.store.list_models(modality=modality)

    def list_routes(self):
        return self.store.list_routes()

    def get_generation_job(self, project_id, job_id):
        return self.store.get_generation_job(project_id, job_id)

    def list_generation_jobs(self, project_id, status=None, offset=0, limit=50):
        if offset < 0 or not 1 <= limit <= 200:
            raise ResourceError("任务分页范围不正确")
        return self.store.list_generation_jobs(project_id, status=status, offset=offset, limit=limit)

    def claim_generation_job(self, worker_id, project_id=None, lease_seconds=300, statuses=("created",),
                             job_id=None, recovery=False, serialize=False, managed_only=False,
                             resume_storage=False):
        self._actor(worker_id)
        return self.store.claim_generation_job(worker_id=worker_id, project_id=project_id,
            lease_seconds=lease_seconds, statuses=statuses, job_id=job_id,
            recovery=recovery, serialize=serialize, managed_only=managed_only,
            resume_storage=resume_storage)

    def renew_generation_job_lease(self, project_id, job_id, worker_id, claim_epoch, lease_seconds=300):
        return self.store.renew_generation_job_lease(project_id, job_id, worker_id, claim_epoch,
                                                    lease_seconds=lease_seconds)

    def release_generation_job_lease(self, project_id, job_id, worker_id, claim_epoch,
                                     retry_seconds=0, error_code=None):
        return self.store.release_generation_job_lease(project_id, job_id, worker_id, claim_epoch,
                                                       retry_seconds=retry_seconds, error_code=error_code)

    def recover_generation_job(self, project_id, payload, *, human_decision=None, **kw):
        from vsc.assets.generation_recovery import require_generation_recovery
        require_generation_recovery(human_decision, kw.get("actor"))
        self._validate_write(payload, **kw)
        if self.storage is not None and payload.get("status") == "succeeded":
            for item in payload.get("outputs", []):
                self._verify_media(project_id, required(item, "media_id"))
        return self.store.recover_generation_job(project_id, payload,
            confirmation_id=human_decision.confirmation_id, **kw)

    def mark_submission_started(self, project_id, payload, **kw):
        return self._write("mark_submission_started", project_id, payload, **kw)

    def record_submission_result(self, project_id, payload, **kw):
        return self._write("record_submission_result", project_id, payload, **kw)

    def update_generation_job(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        if self.storage is not None and payload.get("status") == "succeeded":
            for item in payload.get("outputs", []):
                self._verify_media(project_id, required(item, "media_id"))
        return self._write("update_generation_job", project_id, payload, **kw)

    def freeze_timeline(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        if self.storage is not None:
            if "items" in payload:
                for item in required(payload, "items"):
                    for media in required(item, "media"):
                        self._verify_media(project_id, required(media, "media_id"))
            else:
                for mapping in required(payload, "selected_media").values():
                    self._verify_media(project_id, required(mapping, "media_id"))
        return self._write("freeze_timeline", project_id, payload, **kw)

    def freeze_render(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        if self.storage is not None:
            for media in self.store.get_timeline_media(project_id, required(payload, "timeline_id")):
                self._verify_media(project_id, media["media_id"], expected_sha=media["blob_sha256"])
            for media in payload.get("outputs", []) + payload.get("caption_inputs", []):
                self._verify_media(project_id, required(media, "media_id"))
        return self._write("freeze_render", project_id, payload, **kw)
