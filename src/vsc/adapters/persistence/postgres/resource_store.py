"""Transactional PostgreSQL repository for the built-in resource panel.

No legacy fallback and no implicit schema creation. Every mutation locks its
project, checks an expected revision and records an idempotent command receipt.
"""
import hashlib
import json
import uuid
from datetime import datetime, timezone
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import and_, create_engine, delete, func, insert, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DataError, IntegrityError, SQLAlchemyError

from vsc.assets.resource_service import (
    Conflict, INHERITED_REFERENCE_ROLES, NotFound, POST_ROLES, ResourceError,
    ROLE_MATRIX, context_digest, required,
)
from . import schema as S
from .production_store import ProductionRepository
from .preview_store import PreviewRepository
from .budget_store import BudgetRepository
from .source_reader import SourceRepository
from .script_workspace import ScriptWorkspaceRepository
from .values import checked_id, clean, canonical, digest, new_id, verify_sha














class PostgresResourceStore(ProductionRepository, PreviewRepository, BudgetRepository, SourceRepository,
                            ScriptWorkspaceRepository):
    def __init__(self, database_url=None, engine=None):
        if engine is None and not database_url:
            raise ResourceError("PostgreSQL 连接未配置", "database_not_configured", 503)
        if database_url and database_url.startswith("postgresql://"):
            database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
        self.engine = engine or create_engine(database_url, pool_pre_ping=True)
        if self.engine.dialect.name != "postgresql":
            raise ResourceError("资源仓储仅支持 PostgreSQL", "wrong_database")

    def close(self):
        self.engine.dispose()

    def check_schema(self):
        try:
            with self.engine.connect() as conn:
                version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
                if version != "0006_script_workspace":
                    raise ResourceError("PostgreSQL迁移版本不兼容，请先执行显式迁移", "schema_version_mismatch", 503)
                return {"ready": True, "migration": version, "storage_policy": "postgres-series-v1"}
        except SQLAlchemyError as exc:
            raise ResourceError("PostgreSQL不可用或尚未完成显式迁移", "database_unavailable", 503) from exc

    @staticmethod
    def _descendant_ids(conn, p, object_id, include_ancestors=False):
        selected = {checked_id(object_id)}
        parents = []
        for table in (S.episodes, S.scenes, S.sequences, S.shots):
            parents.extend(conn.execute(select(table.c.parent_id, table.c.id).where(table.c.project_id == p)).all())
        changed = True
        while changed:
            before = len(selected)
            selected.update(child for parent, child in parents if parent in selected)
            changed = len(selected) != before
        if include_ancestors:
            parent_by_child = {child: parent for parent, child in parents}
            cursor = checked_id(object_id)
            while cursor in parent_by_child:
                cursor = parent_by_child[cursor]
                selected.add(cursor)
        return selected

    @staticmethod
    def _approval_map(conn, p):
        latest, dependencies = {}, {}
        for row in conn.execute(select(S.artifact_decisions.c.artifact_id, S.artifact_decisions.c.outcome)
                .where(S.artifact_decisions.c.project_id == p)
                .order_by(S.artifact_decisions.c.decision_sequence.desc())).mappings():
            latest.setdefault(row["artifact_id"], row["outcome"])
        for artifact_id, dependency_id in conn.execute(select(S.artifact_dependencies.c.artifact_id,
                S.artifact_dependencies.c.dependency_id).where(S.artifact_dependencies.c.project_id == p)):
            dependencies.setdefault(artifact_id, []).append(dependency_id)
        resolved = {}
        def approved(artifact_id, visiting):
            if artifact_id in resolved:
                return resolved[artifact_id]
            if artifact_id in visiting:
                raise ResourceError("产物依赖出现循环", "dependency_cycle")
            if latest.get(artifact_id) != "approve":
                resolved[artifact_id] = False
            else:
                resolved[artifact_id] = all(approved(d, visiting | {artifact_id}) for d in dependencies.get(artifact_id, []))
            return resolved[artifact_id]
        for artifact_id in latest:
            approved(artifact_id, set())
        return resolved

    @staticmethod
    def _one(conn, table, project_id, row_id):
        row = conn.execute(select(table).where(table.c.project_id == project_id,
                                              table.c.id == checked_id(row_id))).mappings().first()
        if row is None:
            raise NotFound()
        return dict(row)

    @staticmethod
    def _project(conn, project_id, lock=False):
        query = select(S.projects).where(S.projects.c.id == checked_id(project_id))
        if lock:
            query = query.with_for_update()
        row = conn.execute(query).mappings().first()
        if row is None:
            raise NotFound("项目不存在")
        return dict(row)

    def _mutate(self, project_id, action, payload, expected_revision, idempotency_key, actor, callback):
        project_id = checked_id(project_id)
        request_sha = digest({"action": action, "payload": payload, "actor": actor})
        try:
            with self.engine.begin() as conn:
                project = self._project(conn, project_id, lock=True)
                migration_actions = set(conn.execute(select(S.project_revisions.c.action).where(
                    S.project_revisions.c.project_id == project_id,
                    S.project_revisions.c.action.in_(["migration_import", "migration_activate"]))).scalars())
                if "migration_import" in migration_actions and "migration_activate" not in migration_actions:
                    raise Conflict("迁移尚未切换状态权威，PostgreSQL目标保持只读", "migration_pending")
                receipt = conn.execute(select(S.command_receipts).where(
                    S.command_receipts.c.project_id == project_id,
                    S.command_receipts.c.idempotency_key == idempotency_key)).mappings().first()
                if receipt:
                    if receipt["request_sha256"] != request_sha:
                        raise Conflict("同一幂等键已用于不同操作", "idempotency_conflict")
                    return receipt["response"]
                if project["revision"] != expected_revision:
                    raise Conflict()
                response = callback(conn, project)
                revision = project["revision"] + 1
                conn.execute(update(S.projects).where(S.projects.c.id == project_id).values(revision=revision))
                conn.execute(insert(S.project_revisions).values(project_id=project_id, revision=revision,
                    actor=actor, action=action, command_key=idempotency_key))
                response = clean(dict(response, project_id=project_id, revision=revision))
                conn.execute(insert(S.command_receipts).values(project_id=project_id,
                    idempotency_key=idempotency_key, request_sha256=request_sha, response=response))
                return response
        except (IntegrityError, DataError) as exc:
            # Never return SQL parameters/URLs or sensitive JSON in a public error.
            raise ResourceError("关系约束校验失败，检查类型、范围、重复键与固定版本", "constraint_violation") from exc
        except (ValueError, TypeError) as exc:
            raise ResourceError("字段类型、时间或数值格式不正确", "invalid_payload") from exc

    @staticmethod
    def _decision(conn, project, actor, reason):
        if not isinstance(reason, str) or not reason.strip():
            raise ResourceError("人工决定需要说明原因", "reason_required")
        sequence = conn.execute(update(S.projects).where(S.projects.c.id == project["id"])
            .values(decision_sequence=S.projects.c.decision_sequence + 1)
            .returning(S.projects.c.decision_sequence)).scalar_one()
        return {"decision_sequence": sequence, "actor": actor, "reason": reason,
                "based_on_revision": project["revision"]}

    def list_projects(self):
        with self.engine.connect() as conn:
            return clean([dict(r) for r in conn.execute(select(S.projects).order_by(S.projects.c.created_at, S.projects.c.id)).mappings()])

    def get_project(self, project_id):
        with self.engine.connect() as conn:
            return clean(self._project(conn, project_id))

    def create_project(self, payload, actor, **kwargs):
        project_id = checked_id(payload.get("id", new_id()))
        profile = payload.get("profile", "vsc.series-pg")
        snapshot = payload.get("profile_snapshot", {})
        # Creation is an explicit PG operation; never inferred from a directory.
        if payload.get("storage_policy", "postgres-series-v1") != "postgres-series-v1":
            raise ResourceError("创建 PostgreSQL 项目必须显式采用 postgres-series-v1")
        try:
            with self.engine.begin() as conn:
                conn.execute(insert(S.projects).values(id=project_id, name=required(payload, "name"),
                    profile=profile, profile_snapshot=snapshot, storage_policy="postgres-series-v1"))
                return clean(self._project(conn, project_id))
        except IntegrityError as exc:
            raise Conflict("项目 ID 已存在", "project_exists") from exc

    def create_object(self, project_id, payload, **kw):
        def work(conn, project):
            kind = required(payload, "kind")
            tables = {"work": S.works, "episode": S.episodes, "scene": S.scenes,
                      "sequence": S.sequences, "shot": S.shots, "asset": S.asset_identities}
            if kind not in tables:
                raise ResourceError("未知创作对象类型")
            row_id = checked_id(payload.get("id", new_id()))
            conn.execute(insert(S.creative_objects).values(project_id=project["id"], id=row_id,
                kind=kind, display_code=required(payload, "display_code"), title=payload.get("title", payload["display_code"])))
            values = {"project_id": project["id"], "id": row_id, "object_kind": kind}
            if kind == "asset":
                values["asset_kind"] = required(payload, "asset_kind")
            else:
                values["ordinal"] = int(payload.get("ordinal", 0))
                if kind != "work":
                    values["parent_id"] = checked_id(required(payload, "parent_id"))
                if kind == "shot":
                    values["duration_ms"] = payload.get("duration_ms")
            conn.execute(insert(tables[kind]).values(**values))
            return dict(payload, id=row_id)
        return self._mutate(project_id, "create_object", payload, callback=work, **kw)

    def get_project_tree(self, project_id):
        with self.engine.connect() as conn:
            project = self._project(conn, project_id)
            nodes = []
            for table in (S.works, S.episodes, S.scenes, S.sequences, S.shots, S.asset_identities):
                columns = [S.creative_objects.c.id, S.creative_objects.c.kind,
                           S.creative_objects.c.display_code, S.creative_objects.c.title]
                columns += [table.c.parent_id] if "parent_id" in table.c else []
                columns += [table.c.ordinal] if "ordinal" in table.c else []
                if table is S.asset_identities:
                    columns += [table.c.asset_kind]
                query = select(*columns).select_from(S.creative_objects.join(table,
                    and_(table.c.project_id == S.creative_objects.c.project_id, table.c.id == S.creative_objects.c.id)))
                query = query.where(S.creative_objects.c.project_id == project["id"])
                for row in conn.execute(query).mappings():
                    nodes.append(dict({"parent_id": None, "ordinal": 0}, **row))
            rank = {"work": 0, "episode": 1, "scene": 2, "sequence": 3, "shot": 4, "asset": 5}
            nodes.sort(key=lambda n: (rank[n["kind"]], n["parent_id"] or "", n["ordinal"], n["id"]))
            return clean({"project": project, "nodes": nodes, "revision": project["revision"]})

    def create_artifact(self, project_id, payload, **kw):
        return self._mutate(project_id, "create_artifact", payload,
                            callback=lambda conn, project: self._create_artifact(conn, project, payload), **kw)

    def _create_artifact(self, conn, project, payload):
            p, artifact_id = project["id"], checked_id(payload.get("id", new_id()))
            document = required(payload, "document")
            if isinstance(document, (dict, list)):
                raw = canonical(document).encode("utf-8")
            elif isinstance(document, str):
                raw = document.encode("utf-8")
            else:
                raise ResourceError("正文必须是文本或结构化文档")
            if isinstance(document, str):
                try:
                    parsed = json.loads(document)
                    if isinstance(parsed, dict):
                        document = parsed
                except ValueError:
                    pass
            sha = hashlib.sha256(raw).hexdigest()
            if payload.get("sha256", sha) != sha:
                raise ResourceError("产物摘要与正文不符", "sha_mismatch")
            scopes = [checked_id(x) for x in payload.get("object_ids", [])]
            wide = bool(payload.get("project_wide", not scopes))
            if wide == bool(scopes):
                raise ResourceError("项目级范围与对象范围互斥且必须指定其一", "invalid_scope")
            if payload.get("artifact_type") == "vsc.review_delegation":
                from vsc.assets.review_delegation import errors
                if errors(document) or document.get("project_id") != p or wide:
                    raise ResourceError("委托需要有效固定政策与明确项目内对象范围", "invalid_delegation")
            artifact_key = required(payload, "artifact_key")
            supersedes_id = checked_id(payload["supersedes_id"]) if payload.get("supersedes_id") else None
            if supersedes_id:
                previous = self._one(conn, S.artifact_versions, p, supersedes_id)
                previous_scopes = set(conn.execute(select(S.artifact_object_scopes.c.object_id).where(
                    S.artifact_object_scopes.c.project_id == p, S.artifact_object_scopes.c.artifact_id == supersedes_id)).scalars())
                if (previous["artifact_key"] != artifact_key or previous["artifact_type"] != payload["artifact_type"]
                        or previous["stage"] != payload.get("stage", "script") or previous["project_wide"] != wide or previous_scopes != set(scopes)):
                    raise ResourceError("supersedes必须保持同一逻辑产物、类型、阶段与范围", "supersedes_scope_mismatch")
                downstream = {supersedes_id}
                edges = conn.execute(select(S.artifact_dependencies.c.artifact_id, S.artifact_dependencies.c.dependency_id)
                    .where(S.artifact_dependencies.c.project_id == p)).all()
                changed = True
                while changed:
                    before = len(downstream)
                    downstream.update(child for child, parent in edges if parent in downstream)
                    changed = len(downstream) != before
                if downstream & set(payload.get("dependency_ids", [])):
                    raise ResourceError("替代版本不能依赖被替代版本或其下游", "supersedes_dependency_cycle")
            version = conn.execute(select(func.coalesce(func.max(S.artifact_versions.c.version), 0)).where(
                S.artifact_versions.c.project_id == p, S.artifact_versions.c.artifact_key == artifact_key)).scalar_one() + 1
            conn.execute(insert(S.artifact_versions).values(project_id=p, id=artifact_id,
                artifact_key=artifact_key, version=version, artifact_type=required(payload, "artifact_type"),
                stage=payload.get("stage", "script"), document=raw, sha256=sha,
                mime_type=payload.get("mime_type", "application/json" if isinstance(document, (dict, list)) else "text/plain"),
                project_wide=wide, parser_version=payload.get("parser_version", "vsc-resource-v1"), supersedes_id=supersedes_id,
                registration_note=payload.get("registration_note", "")))
            for object_id in scopes:
                conn.execute(insert(S.artifact_object_scopes).values(project_id=p, artifact_id=artifact_id, object_id=object_id))
            for dependency_id in payload.get("dependency_ids", []):
                conn.execute(insert(S.artifact_dependencies).values(project_id=p, artifact_id=artifact_id, dependency_id=checked_id(dependency_id)))
            fixed_specs = self._register_asset_refs(conn, p, artifact_id, payload.get("asset_versions", {}))
            # Projections are generated during the immutable version transaction.
            projection_payload = payload
            generated_projections = False
            derived_keys = set()
            if isinstance(document, dict):
                from vsc.assets.projections import normalize_artifact_payload, SUPPORTED_FORMATS
                if document.get("format") in SUPPORTED_FORMATS:
                    if document.get("project_id") != p:
                        raise ResourceError("原规范文档project_id与登记项目不一致", "document_project_mismatch")
                    mapping = self._projection_id_map(conn, p)
                    for asset_id, fixed in fixed_specs.items():
                        alias = self._one(conn, S.creative_objects, p, asset_id)["display_code"]
                        for spec in conn.execute(select(S.asset_spec_versions).where(S.asset_spec_versions.c.project_id == p,
                                S.asset_spec_versions.c.asset_id == asset_id, S.asset_spec_versions.c.artifact_id == fixed["artifact_id"])).mappings():
                            variant = "default" if spec["variant_key"] == "master" else spec["variant_key"]
                            mapping["asset_specs"][alias + ":" + variant] = spec["id"]
                    mapping["_artifact_version_id"] = artifact_id
                    mapping["declared_dependencies"] = [checked_id(x) for x in payload.get("dependency_ids", [])]
                    if document.get("format") == "vsc.coverage-plan/v1":
                        script_ref = document.get("screenplay", {})
                        script_id = checked_id(required(script_ref, "id"))
                        if script_id not in mapping["declared_dependencies"]:
                            raise ResourceError("覆盖计划必须明确依赖固定剧本版本", "coverage_dependency_missing")
                        fixed_script = self._one(conn, S.artifact_versions, p, script_id)
                        if fixed_script["sha256"] != script_ref.get("sha256"):
                            raise ResourceError("覆盖计划剧本SHA与依赖版本不一致", "coverage_source_mismatch")
                    normalized = normalize_artifact_payload(document, mapping)
                    for key, value in normalized["projections"].items():
                        if key in payload and payload[key] != value:
                            raise ResourceError("原规范投影由服务端解析，不能客户端覆写", "projection_mismatch")
                    projection_payload = dict(payload, **normalized["projections"])
                    derived_keys = set(normalized["projections"])
                    generated_projections = True
            lines = projection_payload.get("script_lines", [])
            if lines and not isinstance(document, dict):
                raise ResourceError("台词投影需要包含同一台词列表的结构化剧本")
            if lines and "script_lines" not in derived_keys and document.get("script_lines") != lines:
                raise ResourceError("台词投影与固定剧本文档不一致", "projection_mismatch")
            for order, line in enumerate(lines):
                conn.execute(insert(S.script_lines).values(project_id=p, id=checked_id(line.get("id", new_id())),
                    script_version_id=artifact_id, scene_id=checked_id(required(line, "scene_id")),
                    speaker_id=checked_id(line["speaker_id"]) if line.get("speaker_id") else None,
                    line_key=required(line, "line_key"), line_kind=line.get("line_kind", "dialogue"),
                    text=required(line, "text"), ordinal=order, source_sha256=sha))
            for spec in projection_payload.get("asset_specs", []):
                if "asset_specs" not in derived_keys and (not isinstance(document, dict) or document.get("asset_specs") != projection_payload["asset_specs"]):
                    raise ResourceError("资产规格投影与固定文档不一致", "projection_mismatch")
                conn.execute(insert(S.asset_spec_versions).values(project_id=p, id=checked_id(spec.get("id", new_id())),
                    asset_id=checked_id(required(spec, "asset_id")), artifact_id=artifact_id,
                    variant_key=spec.get("variant_key", "master")))
            for projection_key in ("state_versions", "line_coverage", "voice_specs", "voice_bindings", "continuity_edges"):
                if projection_key not in derived_keys and projection_payload.get(projection_key) and (not isinstance(document, dict) or document.get(projection_key) != projection_payload[projection_key]):
                    raise ResourceError("关系投影与固定文档不一致: " + projection_key, "projection_mismatch")
            for state in projection_payload.get("state_versions", []):
                state_id = checked_id(state.get("id", new_id()))
                scene_id = checked_id(required(state, "scene_id"))
                shot_id = checked_id(state["shot_id"]) if state.get("shot_id") else None
                if shot_id:
                    shot = self._one(conn, S.shots, p, shot_id)
                    sequence = self._one(conn, S.sequences, p, shot["parent_id"])
                    if sequence["parent_id"] != scene_id:
                        raise ResourceError("逐镜状态与场归属不一致", "state_scene_mismatch")
                location_id = checked_id(state["location_id"]) if state.get("location_id") else None
                if location_id and self._one(conn, S.asset_identities, p, location_id)["asset_kind"] != "location":
                    raise ResourceError("状态地点必须引用地点身份")
                conn.execute(insert(S.state_versions).values(project_id=p, id=state_id, artifact_id=artifact_id,
                    scene_id=scene_id, shot_id=shot_id, location_id=location_id, source_sha256=sha))
                for entity in state.get("entities", []):
                    conn.execute(insert(S.state_entity_refs).values(project_id=p, id=new_id(), state_id=state_id,
                        asset_id=checked_id(required(entity, "asset_id")), spec_version_id=entity.get("spec_version_id"),
                        relation=required(entity, "relation")))
            for coverage in projection_payload.get("line_coverage", []):
                line = self._one(conn, S.script_lines, p, required(coverage, "line_id"))
                start, end = int(coverage.get("start_char", 0)), int(required(coverage, "end_char"))
                if start < 0 or end > len(line["text"]) or end <= start:
                    raise ResourceError("台词覆盖范围超出原文", "coverage_range")
                conn.execute(insert(S.shot_line_coverage).values(project_id=p, id=checked_id(coverage.get("id", new_id())),
                    coverage_version_id=artifact_id, shot_id=checked_id(required(coverage, "shot_id")),
                    line_id=line["id"], start_char=start, end_char=end))
            for voice in projection_payload.get("voice_specs", []):
                identity = self._one(conn, S.asset_identities, p, required(voice, "voice_id"))
                if identity["asset_kind"] != "voice":
                    raise ResourceError("逻辑音色规格必须引用voice身份")
                conn.execute(insert(S.voice_spec_versions).values(project_id=p, id=checked_id(voice.get("id", new_id())),
                    voice_id=identity["id"], artifact_id=artifact_id, reference_media_id=voice.get("reference_media_id"),
                    diction=voice.get("diction", {}), post_chain=voice.get("post_chain", {})))
            for binding in projection_payload.get("voice_bindings", []):
                character = self._one(conn, S.asset_identities, p, required(binding, "character_id"))
                if character["asset_kind"] != "character":
                    raise ResourceError("音色绑定必须引用人物身份")
                conn.execute(insert(S.character_voice_bindings).values(project_id=p, id=new_id(),
                    character_id=character["id"], voice_spec_id=checked_id(required(binding, "voice_spec_id")), scope_version_id=artifact_id))
            for edge in projection_payload.get("continuity_edges", []):
                conn.execute(insert(S.continuity_edges).values(project_id=p, id=checked_id(edge.get("id", new_id())),
                    from_shot_id=checked_id(required(edge, "from_shot_id")), to_shot_id=checked_id(required(edge, "to_shot_id")),
                    exit_state_id=checked_id(required(edge, "exit_state_id")), entry_state_id=checked_id(required(edge, "entry_state_id")),
                    evidence_version_id=artifact_id, strategy=required(edge, "strategy")))
            from .creative_relations import project_relations
            project_relations(self, conn, p, artifact_id, document, payload.get("dependency_ids", []))
            from .quality_relations import project_quality_document
            project_quality_document(self, conn, p, artifact_id, document)
            return {"id": artifact_id, "artifact_key": artifact_key, "version": version, "sha256": sha}

    def _register_asset_refs(self, conn, p, artifact_id, references):
        if not isinstance(references, dict):
            raise ResourceError("asset_versions必须按身份明确固定规格版本", "asset_version_invalid")
        fixed = {}
        for asset_id, reference in references.items():
            asset_id = checked_id(asset_id)
            self._one(conn, S.asset_identities, p, asset_id)
            if not isinstance(reference, dict):
                raise ResourceError("资产版本引用必须包含版本与SHA", "asset_version_invalid")
            if reference.get("spec_version_id"):
                spec = self._one(conn, S.asset_spec_versions, p, reference["spec_version_id"])
            else:
                source_id = checked_id(required(reference, "id"))
                rows = conn.execute(select(S.asset_spec_versions).where(S.asset_spec_versions.c.project_id == p,
                    S.asset_spec_versions.c.asset_id == asset_id, S.asset_spec_versions.c.artifact_id == source_id,
                    S.asset_spec_versions.c.variant_key == "master")).mappings().all()
                if len(rows) != 1:
                    raise ResourceError("固定资产文档未提供唯一master规格，请明确spec_version_id", "asset_version_ambiguous")
                spec = dict(rows[0])
            source = self._one(conn, S.artifact_versions, p, spec["artifact_id"])
            if spec["asset_id"] != asset_id or source["sha256"] != reference.get("sha256"):
                raise ResourceError("资产身份、固定规格与源SHA不一致", "asset_version_mismatch")
            conn.execute(insert(S.artifact_asset_spec_refs).values(project_id=p, artifact_id=artifact_id,
                asset_id=asset_id, spec_version_id=spec["id"]))
            fixed[asset_id] = spec
        return fixed

    def _projection_id_map(self, conn, p):
        result = {kind: {} for kind in ("work", "episode", "scene", "sequence", "shot", "asset")}
        objects = [dict(r) for r in conn.execute(select(S.creative_objects).where(S.creative_objects.c.project_id == p)).mappings()]
        display_by_id = {row["id"]: row["display_code"] for row in objects}
        for row in objects:
            result[row["kind"]][row["display_code"]] = row["id"]
            result[row["kind"]][row["id"]] = row["id"]
        current = set(conn.execute(select(S.current_artifact_versions.c.artifact_id).where(S.current_artifact_versions.c.project_id == p)).scalars())
        result["asset_specs"], result["script_lines"], result["line_texts"] = {}, {}, {}
        for row in conn.execute(select(S.asset_spec_versions).where(S.asset_spec_versions.c.project_id == p,
                S.asset_spec_versions.c.artifact_id.in_(current))).mappings():
            variant = "default" if row["variant_key"] == "master" else row["variant_key"]
            result["asset_specs"][display_by_id[row["asset_id"]] + ":" + variant] = row["id"]
        for row in conn.execute(select(S.script_lines, S.artifact_versions.c.artifact_key).select_from(S.script_lines.join(S.artifact_versions,
                and_(S.script_lines.c.project_id == S.artifact_versions.c.project_id, S.script_lines.c.script_version_id == S.artifact_versions.c.id)))
                .where(S.script_lines.c.project_id == p)).mappings():
            result["script_lines"][row["script_version_id"] + ":" + row["line_key"]] = row["id"]
            result["line_texts"][row["id"]] = row["text"]
            if row["script_version_id"] in current:
                result["script_lines"][row["artifact_key"] + ":" + row["line_key"]] = row["id"]
                result["script_lines"].setdefault(row["line_key"], row["id"])
        return result

    def get_projection_id_map(self, project_id):
        with self.engine.connect() as conn:
            project = self._project(conn, project_id)
            return self._projection_id_map(conn, project["id"])

    def decide_artifact(self, project_id, payload, actor, **kw):
        def work(conn, project):
            p = project["id"]
            artifact = self._one(conn, S.artifact_versions, p, required(payload, "artifact_id"))
            outcome = payload.get("outcome", "approve")
            if artifact["artifact_type"] == "vsc.review_delegation":
                from vsc.assets.review_delegation import document, errors
                policy = document(artifact["document"])
                if errors(policy) or actor != policy["grantor_actor"] or actor == policy["delegate_actor"]:
                    raise ResourceError("委托政策只能由固定的真实委托人批准或撤销", "delegation_grantor_required")
            if outcome == "approve":
                if artifact["supersedes_id"]:
                    current = conn.execute(select(S.current_artifact_versions.c.artifact_id).where(
                        S.current_artifact_versions.c.project_id == p, S.current_artifact_versions.c.artifact_key == artifact["artifact_key"])).scalar_one_or_none()
                    if current != artifact["supersedes_id"]:
                        raise Conflict("被替代版本已不是当前版本，须重新审查此草稿", "supersedes_stale")
                for dependency in conn.execute(select(S.artifact_dependencies.c.dependency_id).where(
                        S.artifact_dependencies.c.project_id == p, S.artifact_dependencies.c.artifact_id == artifact["id"])).scalars():
                    if not self._artifact_approved(conn, p, dependency):
                        raise ResourceError("上游版本尚未获得有效人工批准", "dependency_unapproved")
                for spec_id in conn.execute(select(S.artifact_asset_spec_refs.c.spec_version_id).where(
                        S.artifact_asset_spec_refs.c.project_id == p, S.artifact_asset_spec_refs.c.artifact_id == artifact["id"])).scalars():
                    spec = self._one(conn, S.asset_spec_versions, p, spec_id)
                    if not self._artifact_approved(conn, p, spec["artifact_id"]):
                        raise ResourceError("固定资产规格尚未获批准", "asset_spec_unapproved")
            row_id = new_id()
            conn.execute(insert(S.artifact_decisions).values(project_id=p, id=row_id,
                artifact_id=artifact["id"], outcome=outcome, **self._decision(conn, project, actor, required(payload, "reason"))))
            if outcome == "approve":
                conn.execute(pg_insert(S.current_artifact_versions).values(project_id=p, artifact_key=artifact["artifact_key"],
                    artifact_id=artifact["id"], decision_id=row_id).on_conflict_do_update(
                        index_elements=[S.current_artifact_versions.c.project_id, S.current_artifact_versions.c.artifact_key],
                        set_={"artifact_id": artifact["id"], "decision_id": row_id}))
            else:
                conn.execute(delete(S.current_artifact_versions).where(S.current_artifact_versions.c.project_id == p,
                    S.current_artifact_versions.c.artifact_id == artifact["id"]))
            return {"id": row_id, "artifact_id": artifact["id"], "outcome": outcome}
        return self._mutate(project_id, "decide_artifact", payload, actor=actor, callback=work, **kw)

    @staticmethod
    def _latest(conn, table, p, field, row_id):
        return conn.execute(select(table).where(table.c.project_id == p, table.c[field] == row_id)
            .order_by(table.c.decision_sequence.desc()).limit(1)).mappings().first()

    def _artifact_approved(self, conn, p, artifact_id, seen=None):
        seen = set() if seen is None else seen
        if artifact_id in seen:
            raise ResourceError("产物依赖出现循环", "dependency_cycle")
        seen.add(artifact_id)
        decision = self._latest(conn, S.artifact_decisions, p, "artifact_id", artifact_id)
        if not decision or decision["outcome"] != "approve":
            return False
        for parent_id in conn.execute(select(S.artifact_dependencies.c.dependency_id).where(
                S.artifact_dependencies.c.project_id == p, S.artifact_dependencies.c.artifact_id == artifact_id)).scalars():
            if not self._artifact_approved(conn, p, parent_id, set(seen)):
                return False
        return True

    def get_artifact_version(self, project_id, artifact_id):
        with self.engine.connect() as conn:
            project = self._project(conn, project_id)
            row = self._one(conn, S.artifact_versions, project["id"], artifact_id)
            row["approved"] = self._artifact_approved(conn, project["id"], row["id"])
            row["decisions"] = [dict(r) for r in conn.execute(select(S.artifact_decisions).where(
                S.artifact_decisions.c.project_id == project["id"], S.artifact_decisions.c.artifact_id == row["id"])
                .order_by(S.artifact_decisions.c.decision_sequence)).mappings()]
            row["script_lines"] = [dict(r) for r in conn.execute(select(S.script_lines).where(
                S.script_lines.c.project_id == project["id"], S.script_lines.c.script_version_id == row["id"])
                .order_by(S.script_lines.c.ordinal)).mappings()]
            row["revision"] = project["revision"]
            row["content"] = clean(row["document"])
            row["object_ids"] = list(conn.execute(select(S.artifact_object_scopes.c.object_id).where(
                S.artifact_object_scopes.c.project_id == project["id"], S.artifact_object_scopes.c.artifact_id == row["id"])).scalars())
            row["dependency_ids"] = list(conn.execute(select(S.artifact_dependencies.c.dependency_id).where(
                S.artifact_dependencies.c.project_id == project["id"], S.artifact_dependencies.c.artifact_id == row["id"])).scalars())
            row["asset_versions"] = [dict(r) for r in conn.execute(select(S.artifact_asset_spec_refs).where(
                S.artifact_asset_spec_refs.c.project_id == project["id"], S.artifact_asset_spec_refs.c.artifact_id == row["id"])).mappings()]
            return clean(row)

    def list_sources(self, project_id):
        with self.engine.connect() as conn:
            project = self._project(conn, project_id)
            columns = [c for c in S.source_versions.c if c.name != "document"]
            rows = [dict(r) for r in conn.execute(select(*columns).where(S.source_versions.c.project_id == project["id"])
                .order_by(S.source_versions.c.source_key, S.source_versions.c.version)).mappings()]
            return clean({"items": rows, "total": len(rows), "revision": project["revision"]})

    def list_artifacts(self, project_id, object_id=None):
        with self.engine.connect() as conn:
            project = self._project(conn, project_id)
            p = project["id"]
            query = select(*[c for c in S.artifact_versions.c if c.name != "document"]).where(S.artifact_versions.c.project_id == p)
            if object_id:
                self._one(conn, S.creative_objects, p, object_id)
                scoped_objects = self._descendant_ids(conn, p, object_id, include_ancestors=True)
                query = query.where(or_(S.artifact_versions.c.project_wide.is_(True), S.artifact_versions.c.id.in_(
                    select(S.artifact_object_scopes.c.artifact_id).where(S.artifact_object_scopes.c.project_id == p,
                        S.artifact_object_scopes.c.object_id.in_(scoped_objects)))))
            rows = [dict(r) for r in conn.execute(query.order_by(S.artifact_versions.c.artifact_key, S.artifact_versions.c.version)).mappings()]
            current = set(conn.execute(select(S.current_artifact_versions.c.artifact_id).where(
                S.current_artifact_versions.c.project_id == p)).scalars())
            approvals = self._approval_map(conn, p)
            for row in rows:
                row["approved"] = approvals.get(row["id"], False)
                row["current"] = row["id"] in current
            return clean({"items": rows, "total": len(rows), "revision": project["revision"]})

    def register_media(self, project_id, payload, actor, **kw):
        def work(conn, project):
            p = project["id"]
            sha = verify_sha(required(payload, "sha256"))
            size = required(payload, "size_bytes")
            if not isinstance(size, int) or size < 0:
                raise ResourceError("size_bytes 必须是非负整数")
            storage, key = required(payload, "storage"), required(payload, "object_key")
            if (not isinstance(key, str) or storage not in {"local", "s3", "minio"}
                    or ".." in key.split("/") or "\\" in key or key.startswith("/")):
                raise ResourceError("媒体位置必须是受控存储中的相对对象键", "unsafe_location")
            proposed_blob_id = new_id()
            conn.execute(pg_insert(S.media_blobs).values(id=proposed_blob_id, sha256=sha,
                size_bytes=size, mime_type=required(payload, "mime_type"),
                **{k: payload.get(k) for k in ("width", "height", "duration_ms", "sample_rate")}, probe=payload.get("probe", {}))
                .on_conflict_do_nothing(index_elements=[S.media_blobs.c.sha256]))
            blob = conn.execute(select(S.media_blobs).where(S.media_blobs.c.sha256 == sha)).mappings().one()
            if blob["size_bytes"] != size or blob["mime_type"] != payload["mime_type"]:
                raise Conflict("相同摘要的文件信息不一致", "blob_mismatch")
            conn.execute(pg_insert(S.blob_locations).values(id=new_id(), blob_id=blob["id"], storage=storage, object_key=key)
                .on_conflict_do_nothing(index_elements=[S.blob_locations.c.blob_id, S.blob_locations.c.storage, S.blob_locations.c.object_key]))
            media_id = checked_id(payload.get("id", new_id()))
            conn.execute(insert(S.media_items).values(project_id=p, id=media_id, blob_id=blob["id"],
                name=required(payload, "name"), modality=required(payload, "modality"), registered_by=actor))
            source = payload.get("source")
            source_id = None
            if source:
                source_id = self._insert_source(conn, p, source)
                conn.execute(insert(S.media_sources).values(project_id=p, id=new_id(), media_id=media_id,
                    source_id=source_id, role=source.get("role", "origin"), citation=source.get("citation", {})))
            rights = payload.get("rights", "unknown")
            if rights in {"owned", "licensed"} and not source_id:
                raise ResourceError("已知权利判定必须绑定来源证据", "rights_evidence_required")
            if rights == "licensed" and not payload.get("rights_scope"):
                raise ResourceError("授权素材需要明确适用用途范围", "rights_scope_required")
            scope = payload.get("rights_scope", {"purposes": ["*"] if rights == "owned" else []})
            if not isinstance(scope, dict) or not isinstance(scope.get("purposes"), list):
                raise ResourceError("权利范围必须包含 purposes 列表", "invalid_rights_scope")
            conn.execute(insert(S.rights_decisions).values(project_id=p, id=new_id(), media_id=media_id,
                source_id=source_id, outcome=rights, scope=scope,
                **self._decision(conn, project, actor, payload.get("rights_reason", "登记时明确的权利状态"))))
            return {"id": media_id, "sha256": sha, "blob_id": blob["id"], "rights": rights}
        return self._mutate(project_id, "register_media", payload, actor=actor, callback=work, **kw)

    @staticmethod
    def _insert_source(conn, p, source):
        source_id = checked_id(source.get("id", new_id()))
        content = source.get("content", "")
        raw = (canonical(content) if not isinstance(content, str) else content).encode("utf-8")
        sha = hashlib.sha256(raw).hexdigest()
        if source.get("sha256", sha) != sha:
            raise ResourceError("来源证据摘要不符", "source_sha_mismatch")
        conn.execute(insert(S.source_versions).values(project_id=p, id=source_id,
            source_key=source.get("source_key", source_id), version=int(source.get("version", 1)),
            kind=required(source, "kind"), sha256=sha, document=raw, evidence_uri=source.get("evidence_uri")))
        return source_id

    @staticmethod
    def _media_query(p):
        return select(S.media_items, *[c for c in S.media_blobs.c if c.name not in {"id", "created_at"}]).select_from(
            S.media_items.join(S.media_blobs, S.media_items.c.blob_id == S.media_blobs.c.id)).where(S.media_items.c.project_id == p)

    def _media(self, conn, p, media_id):
        row = conn.execute(self._media_query(p).where(S.media_items.c.id == checked_id(media_id))).mappings().first()
        if row is None:
            raise NotFound("素材不存在")
        result = dict(row)
        result["locations"] = [dict(r) for r in conn.execute(select(S.blob_locations).where(
            S.blob_locations.c.blob_id == result["blob_id"])).mappings()]
        return result

    def get_media(self, project_id, media_id):
        with self.engine.connect() as conn:
            project = self._project(conn, project_id)
            p = project["id"]
            row = self._media(conn, p, media_id)
            row["rights"] = clean(dict(self._latest(conn, S.rights_decisions, p, "media_id", row["id"]) or {}))
            lifecycle = self._latest(conn, S.media_lifecycle_decisions, p, "media_id", row["id"])
            row["deprecated"] = bool(lifecycle and lifecycle["outcome"] == "deprecate")
            row["sources"] = [dict(r) for r in conn.execute(select(S.media_sources, S.source_versions.c.kind,
                S.source_versions.c.evidence_uri, S.source_versions.c.sha256).select_from(S.media_sources.join(S.source_versions,
                and_(S.media_sources.c.project_id == S.source_versions.c.project_id, S.media_sources.c.source_id == S.source_versions.c.id)))
                .where(S.media_sources.c.project_id == p, S.media_sources.c.media_id == row["id"])).mappings()]
            row["candidates"] = [dict(r) for r in conn.execute(select(S.binding_candidates).where(
                S.binding_candidates.c.project_id == p, S.binding_candidates.c.media_id == row["id"])).mappings()]
            candidate_ids = [c["id"] for c in row["candidates"]]
            row["reviews"], row["decisions"], row["bindings"] = [], [], []
            if candidate_ids:
                row["reviews"] = [dict(r) for r in conn.execute(select(S.media_reviews).where(
                    S.media_reviews.c.project_id == p, S.media_reviews.c.candidate_id.in_(candidate_ids))
                    .order_by(S.media_reviews.c.project_revision, S.media_reviews.c.id)).mappings()]
                row["decisions"] = [dict(r) for r in conn.execute(select(S.binding_decisions).where(
                    S.binding_decisions.c.project_id == p, S.binding_decisions.c.candidate_id.in_(candidate_ids))
                    .order_by(S.binding_decisions.c.decision_sequence)).mappings()]
                row["bindings"] = [dict(r) for r in conn.execute(select(S.binding_slots, S.current_bindings.c.candidate_id,
                    S.current_bindings.c.decision_id).select_from(S.binding_slots.join(S.current_bindings,
                    and_(S.binding_slots.c.project_id == S.current_bindings.c.project_id, S.binding_slots.c.id == S.current_bindings.c.slot_id)))
                    .where(S.binding_slots.c.project_id == p, S.current_bindings.c.candidate_id.in_(candidate_ids))).mappings()]
            row["checks"] = [dict(r) for r in conn.execute(select(S.media_checks).where(
                S.media_checks.c.project_id == p, S.media_checks.c.media_id == row["id"])).mappings()]
            row["renditions"] = self._renditions(conn, p, [row["id"]])
            row["preview_jobs"] = [dict(r) for r in conn.execute(select(S.preview_jobs).where(
                S.preview_jobs.c.project_id == p, S.preview_jobs.c.media_id == row["id"])).mappings()]
            row["revision"] = project["revision"]
            return clean(row)

    def get_binding_candidate(self, project_id, candidate_id):
        with self.engine.connect() as conn:
            project = self._project(conn, project_id)
            return clean(self._one(conn, S.binding_candidates, project["id"], candidate_id))

    def get_timeline_media(self, project_id, timeline_id):
        with self.engine.connect() as conn:
            project = self._project(conn, project_id)
            timeline = self._one(conn, S.timeline_versions, project["id"], timeline_id)
            items = select(S.timeline_items.c.id).where(S.timeline_items.c.project_id == project["id"],
                S.timeline_items.c.timeline_id == timeline["id"])
            return clean([dict(r) for r in conn.execute(select(S.timeline_item_media).where(
                S.timeline_item_media.c.project_id == project["id"], S.timeline_item_media.c.item_id.in_(items))).mappings()])

    def get_timeline(self, project_id, timeline_id):
        with self.engine.connect() as conn:
            project = self._project(conn, project_id)
            p = project["id"]
            timeline = self._one(conn, S.timeline_versions, p, timeline_id)
            artifact = self._one(conn, S.artifact_versions, p, timeline["artifact_id"])
            items = [dict(r) for r in conn.execute(select(S.timeline_items).where(S.timeline_items.c.project_id == p,
                S.timeline_items.c.timeline_id == timeline["id"]).order_by(S.timeline_items.c.ordinal)).mappings()]
            sources = [dict(r) for r in conn.execute(select(S.timeline_item_media, S.media_blobs.c.mime_type).select_from(
                S.timeline_item_media.join(S.media_blobs, S.timeline_item_media.c.blob_id == S.media_blobs.c.id)).where(
                S.timeline_item_media.c.project_id == p, S.timeline_item_media.c.item_id.in_([item["id"] for item in items]))).mappings()]
            locations = {}
            for location in conn.execute(select(S.blob_locations).where(S.blob_locations.c.blob_id.in_([s["blob_id"] for s in sources]))).mappings():
                locations.setdefault(location["blob_id"], []).append(dict(location))
            by_item = {}
            for source in sources:
                source["locations"] = locations.get(source["blob_id"], [])
                by_item.setdefault(source["item_id"], []).append(source)
            for item in items:
                item["media"] = by_item.get(item["id"], [])
            return clean(dict(timeline, artifact=artifact, items=items, revision=project["revision"]))

    def list_resources(self, project_id, object_id=None, offset=0, limit=50, modality=None, **filters):
        with self.engine.connect() as conn:
            project = self._project(conn, project_id)
            p = project["id"]
            query = self._media_query(p)
            if object_id:
                self._one(conn, S.creative_objects, p, object_id)
                scoped_objects = self._descendant_ids(conn, p, object_id)
                ids = select(S.binding_candidates.c.media_id).select_from(S.binding_candidates.join(S.binding_slots,
                    and_(S.binding_candidates.c.project_id == S.binding_slots.c.project_id, S.binding_candidates.c.slot_id == S.binding_slots.c.id)))
                ids = ids.where(S.binding_slots.c.project_id == p, S.binding_slots.c.target_object_id.in_(scoped_objects))
                query = query.where(S.media_items.c.id.in_(ids))
            if modality:
                query = query.where(S.media_items.c.modality == modality)
            if filters.get("role"):
                ids = select(S.binding_candidates.c.media_id).select_from(S.binding_candidates.join(S.binding_slots,
                    and_(S.binding_candidates.c.project_id == S.binding_slots.c.project_id, S.binding_candidates.c.slot_id == S.binding_slots.c.id)))
                ids = ids.where(S.binding_slots.c.project_id == p, S.binding_slots.c.role == filters["role"])
                query = query.where(S.media_items.c.id.in_(ids))
            if filters.get("status") in {"selected", "unselected"}:
                selected_ids = select(S.binding_candidates.c.media_id).select_from(S.binding_candidates.join(S.current_bindings,
                    and_(S.binding_candidates.c.project_id == S.current_bindings.c.project_id,
                         S.binding_candidates.c.id == S.current_bindings.c.candidate_id))).where(S.binding_candidates.c.project_id == p)
                selected = S.media_items.c.id.in_(selected_ids)
                query = query.where(selected if filters["status"] == "selected" else ~selected)
            ranked_lifecycle = select(S.media_lifecycle_decisions.c.media_id, S.media_lifecycle_decisions.c.outcome,
                func.row_number().over(partition_by=S.media_lifecycle_decisions.c.media_id,
                    order_by=S.media_lifecycle_decisions.c.decision_sequence.desc()).label("decision_rank"))
            ranked_lifecycle = ranked_lifecycle.where(S.media_lifecycle_decisions.c.project_id == p).subquery()
            latest_lifecycle = select(ranked_lifecycle.c.media_id, ranked_lifecycle.c.outcome).where(
                ranked_lifecycle.c.decision_rank == 1).subquery()
            deprecated_ids = select(latest_lifecycle.c.media_id).where(latest_lifecycle.c.outcome == "deprecate")
            if filters.get("status") in {"deprecated", "active"}:
                deprecated = S.media_items.c.id.in_(deprecated_ids)
                query = query.where(deprecated if filters["status"] == "deprecated" else ~deprecated)
            query_text = filters.get("q") or filters.get("query")
            if query_text:
                query = query.where(S.media_items.c.name.ilike("%" + str(query_text).replace("%", "\\%").replace("_", "\\_") + "%"))
            if filters.get("registration") == "unregistered":
                query = query.where(text("FALSE"))
            total = conn.execute(select(func.count()).select_from(query.subquery())).scalar_one()
            rows = [dict(r) for r in conn.execute(query.order_by(S.media_items.c.created_at, S.media_items.c.id).offset(offset).limit(limit)).mappings()]
            # One batched location query rather than one request/query per card.
            blob_ids = [r["blob_id"] for r in rows]
            locations = {}
            if blob_ids:
                for row in conn.execute(select(S.blob_locations).where(S.blob_locations.c.blob_id.in_(blob_ids))).mappings():
                    locations.setdefault(row["blob_id"], []).append(dict(row))
            for row in rows:
                row["locations"] = locations.get(row["blob_id"], [])
            renditions = {}
            if rows:
                for rendition in self._renditions(conn, p, [r["id"] for r in rows]):
                    renditions.setdefault(rendition["media_id"], []).append(rendition)
            for row in rows:
                row["renditions"] = renditions.get(row["id"], [])
            deprecated = set(conn.execute(deprecated_ids.where(latest_lifecycle.c.media_id.in_([r["id"] for r in rows]))).scalars()) if rows else set()
            for row in rows:
                row["deprecated"] = row["id"] in deprecated
            return clean({"items": rows, "total": total, "offset": offset, "limit": limit, "revision": project["revision"]})

    def propose_binding(self, project_id, payload, actor, **kw):
        def work(conn, project):
            p = project["id"]
            target = self._one(conn, S.creative_objects, p, required(payload, "target_object_id"))
            media = self._media(conn, p, required(payload, "media_id"))
            role = required(payload, "role")
            if role not in ROLE_MATRIX or target["kind"] not in ROLE_MATRIX[role][0] or media["modality"] not in ROLE_MATRIX[role][1]:
                raise ResourceError("用途与对象类型或素材模态不匹配", "invalid_role")
            if role in {"identity_face", "costume", "location_master", "location_view", "voice_sample", "style_reference"}:
                identity_id = target["id"] if target["kind"] == "asset" else required(payload, "identity_asset_id")
                identity = self._one(conn, S.asset_identities, p, identity_id)
                allowed = {"identity_face": {"character"}, "costume": {"character", "costume"},
                           "location_master": {"location"}, "location_view": {"location"},
                           "voice_sample": {"character", "voice"}, "style_reference": {"style"}}
                if identity["asset_kind"] not in allowed[role]:
                    raise ResourceError("用途与资产身份种类不匹配", "invalid_identity_role")
            if payload.get("variant_spec_id"):
                variant = self._one(conn, S.asset_spec_versions, p, payload["variant_spec_id"])
                expected_asset = target["id"] if target["kind"] == "asset" else payload.get("identity_asset_id")
                if variant["asset_id"] != expected_asset:
                    raise ResourceError("变体规格与用途身份不一致", "variant_identity_mismatch")
            coverage_id = payload.get("line_coverage_id")
            if role == "dialogue_dry":
                coverage = self._one(conn, S.shot_line_coverage, p, required(payload, "line_coverage_id"))
                if coverage["shot_id"] != target["id"]:
                    raise ResourceError("干声必须绑定本镜头的台词覆盖", "coverage_mismatch")
            slot_key = payload.get("slot_key", "line:" + coverage_id if coverage_id else "main")
            if not isinstance(slot_key, str) or not slot_key:
                raise ResourceError("slot_key 不能为空")
            if role in {"ambience", "music", "sfx"} and not payload.get("track_key"):
                raise ResourceError("混音用途需要独立 track_key", "track_required")
            existing = conn.execute(select(S.binding_slots).where(S.binding_slots.c.project_id == p,
                S.binding_slots.c.target_object_id == target["id"], S.binding_slots.c.role == role,
                S.binding_slots.c.slot_key == slot_key)).mappings().first()
            if existing:
                slot_id = existing["id"]
                for field in ("variant_spec_id", "line_coverage_id", "track_key", "identity_asset_id"):
                    if existing[field] != payload.get(field):
                        raise Conflict("槽位的结构引用不一致", "slot_mismatch")
            else:
                slot_id = new_id()
                conn.execute(insert(S.binding_slots).values(project_id=p, id=slot_id,
                    target_object_id=target["id"], role=role, slot_key=slot_key,
                    variant_spec_id=payload.get("variant_spec_id"), line_coverage_id=coverage_id,
                    track_key=payload.get("track_key"), identity_asset_id=payload.get("identity_asset_id")))
            candidate_id = new_id()
            conn.execute(insert(S.binding_candidates).values(project_id=p, id=candidate_id, slot_id=slot_id,
                media_id=media["id"], spec_version_id=payload.get("spec_version_id"),
                context_sha256=payload.get("context_sha256"), proposer=actor))
            return {"id": candidate_id, "candidate_id": candidate_id, "slot_id": slot_id, "media_id": media["id"]}
        return self._mutate(project_id, "propose_binding", payload, actor=actor, callback=work, **kw)

    def record_review(self, project_id, payload, actor, **kw):
        def work(conn, project):
            candidate = self._one(conn, S.binding_candidates, project["id"], required(payload, "candidate_id"))
            row_id = new_id()
            conn.execute(insert(S.media_reviews).values(project_id=project["id"], id=row_id,
                candidate_id=candidate["id"], check_id=payload.get("check_id"), reviewer=actor,
                reviewer_type=payload.get("reviewer_type", "human"), criteria_version=payload.get("criteria_version", "manual-v1"),
                context_sha256=payload.get("context_sha256"), outcome=required(payload, "outcome"),
                reason=required(payload, "reason"), evidence=payload.get("evidence", {}), project_revision=project["revision"] + 1))
            return {"id": row_id, "candidate_id": candidate["id"]}
        return self._mutate(project_id, "record_review", payload, actor=actor, callback=work, **kw)

    def _usable(self, conn, p, media_id, purpose):
        media = self._media(conn, p, media_id)
        gaps = []
        if not any(x["available"] for x in media["locations"]):
            gaps.append("missing_bytes")
        rights = self._latest(conn, S.rights_decisions, p, "media_id", media_id)
        if not rights or rights["outcome"] not in {"owned", "licensed"}:
            gaps.append("rights_unknown_or_restricted")
        elif rights["expires_at"] and rights["expires_at"] <= datetime.now(timezone.utc):
            gaps.append("rights_expired")
        elif purpose not in rights["scope"].get("purposes", []) and "*" not in rights["scope"].get("purposes", []):
            gaps.append("rights_scope_mismatch")
        lifecycle = self._latest(conn, S.media_lifecycle_decisions, p, "media_id", media_id)
        if lifecycle and lifecycle["outcome"] == "deprecate":
            gaps.append("media_deprecated")
        checks = conn.execute(select(S.media_checks).where(S.media_checks.c.project_id == p,
            S.media_checks.c.media_id == media_id).order_by(S.media_checks.c.project_revision.desc(), S.media_checks.c.id)).mappings().all()
        # An absent inspection remains a visible production gap; UI browsing is allowed.
        if not checks:
            gaps.append("technical_check_missing")
        else:
            latest_checks = {}
            for check in checks:
                latest_checks.setdefault((check["checker"], check["criteria_version"]), check)
            if any(check["outcome"] != "pass" for check in latest_checks.values()):
                gaps.append("technical_check_failed")
        return media, gaps

    def select_candidate(self, project_id, payload, actor, **kw):
        def work(conn, project):
            p = project["id"]
            candidate = self._one(conn, S.binding_candidates, p, required(payload, "candidate_id"))
            slot = self._one(conn, S.binding_slots, p, candidate["slot_id"])
            _, gaps = self._usable(conn, p, candidate["media_id"], slot["role"])
            if candidate["spec_version_id"] and not self._artifact_approved(conn, p, candidate["spec_version_id"]):
                gaps.append("spec_unapproved")
            if gaps:
                raise ResourceError("素材尚不可正式选择: " + ", ".join(gaps), "unusable_media")
            review = conn.execute(select(S.media_reviews).where(S.media_reviews.c.project_id == p,
                S.media_reviews.c.candidate_id == candidate["id"], S.media_reviews.c.reviewer_type == "human")
                .order_by(S.media_reviews.c.project_revision.desc(), S.media_reviews.c.id.desc()).limit(1)).mappings().first()
            delegation = None
            if payload.get("delegation_artifact_id"):
                if review and review["outcome"] != "pass":
                    raise ResourceError("委托不能覆盖人工拒绝或修改要求", "human_review_veto")
                delegation = self._delegated_selection(conn, p, candidate, slot, payload, actor)
            elif payload.get("review_id"):
                raise ResourceError("指定AI审查必须同时指定委托政策", "delegation_required")
            elif not review or review["outcome"] != "pass":
                raise ResourceError("选择前需要本用途的人工审查通过", "human_review_required")
            from .production_guard import validate_adoption
            trial_adoptions = validate_adoption(self, conn, project, candidate, slot, payload)
            row_id = new_id()
            reason = required(payload, "reason")
            if trial_adoptions:
                reason += "\n试片正式采用：" + payload["trial_adoption"]["reason"].strip()
            conn.execute(insert(S.binding_decisions).values(project_id=p, id=row_id, slot_id=slot["id"],
                candidate_id=candidate["id"], outcome="select", **self._decision(conn, project, actor, reason)))
            for adoption in trial_adoptions:
                conn.execute(insert(S.binding_trial_adoptions).values(project_id=p, decision_id=row_id, **adoption))
            if delegation:
                conn.execute(insert(S.binding_selection_delegations).values(project_id=p, decision_id=row_id,
                    slot_id=slot["id"], candidate_id=candidate["id"], **delegation))
            conn.execute(pg_insert(S.current_bindings).values(project_id=p, slot_id=slot["id"], candidate_id=candidate["id"], decision_id=row_id)
                .on_conflict_do_update(index_elements=[S.current_bindings.c.project_id, S.current_bindings.c.slot_id],
                    set_={"candidate_id": candidate["id"], "decision_id": row_id}))
            return {"id": row_id, "decision_id": row_id, "slot_id": slot["id"], "candidate_id": candidate["id"], "outcome": "select"}
        return self._mutate(project_id, "select_candidate", payload, actor=actor, callback=work, **kw)

    def _delegated_selection(self, conn, p, candidate, slot, payload, actor):
        from vsc.assets.review_delegation import TYPE, document, errors
        artifact = self._one(conn, S.artifact_versions, p, required(payload, "delegation_artifact_id"))
        if artifact["artifact_type"] != TYPE:
            raise ResourceError("固定委托政策类型无效", "invalid_delegation")
        policy = document(artifact["document"])
        if errors(policy) or policy["project_id"] != p:
            raise ResourceError("固定委托政策无效", "invalid_delegation")
        approval = self._latest(conn, S.artifact_decisions, p, "artifact_id", artifact["id"])
        if (not approval or approval["outcome"] != "approve" or approval["actor"] != policy["grantor_actor"]
                or not self._artifact_approved(conn, p, artifact["id"])):
            raise ResourceError("委托政策未获得有效委托人批准", "delegation_unapproved")
        if policy["delegate_actor"] != actor or actor == policy["grantor_actor"]:
            raise ResourceError("操作人不是固定受托人", "delegation_actor_mismatch")
        if datetime.fromisoformat(policy["expires_at"].replace("Z", "+00:00")) <= datetime.now(timezone.utc):
            raise ResourceError("委托已经到期", "delegation_expired")
        scopes = conn.execute(select(S.artifact_object_scopes.c.object_id).where(
            S.artifact_object_scopes.c.project_id == p, S.artifact_object_scopes.c.artifact_id == artifact["id"])).scalars()
        allowed_objects = set()
        for scope in scopes:
            allowed_objects.update(self._descendant_ids(conn, p, scope))
        if artifact["project_wide"] or slot["target_object_id"] not in allowed_objects or slot["role"] not in policy["allowed_roles"]:
            raise ResourceError("用途或对象超出委托范围", "delegation_scope_mismatch")
        review = self._one(conn, S.media_reviews, p, required(payload, "review_id"))
        latest = conn.execute(select(S.media_reviews).where(S.media_reviews.c.project_id == p,
            S.media_reviews.c.candidate_id == candidate["id"], S.media_reviews.c.reviewer == actor,
            S.media_reviews.c.reviewer_type == "ai").order_by(S.media_reviews.c.project_revision.desc(),
                S.media_reviews.c.id.desc()).limit(1)).mappings().first()
        if (review["candidate_id"] != candidate["id"] or review["reviewer"] != actor
                or review["reviewer_type"] != "ai" or review["outcome"] != "pass"
                or not latest or latest["id"] != review["id"]
                or review["context_sha256"] != candidate["context_sha256"]):
            raise ResourceError("委托选择需要本人对同一固定候选的最新AI审查通过", "delegation_review_mismatch")
        return {"review_id": review["id"], "delegation_artifact_id": artifact["id"], "approval_decision_id": approval["id"]}

    def reject_candidate(self, project_id, payload, actor, **kw):
        def work(conn, project):
            p = project["id"]
            candidate = self._one(conn, S.binding_candidates, p, required(payload, "candidate_id"))
            current = conn.execute(select(S.current_bindings).where(S.current_bindings.c.project_id == p,
                S.current_bindings.c.slot_id == candidate["slot_id"])).mappings().first()
            if current and current["candidate_id"] == candidate["id"]:
                raise Conflict("当前选择应使用退役操作", "candidate_current")
            row_id = new_id()
            conn.execute(insert(S.binding_decisions).values(project_id=p, id=row_id, slot_id=candidate["slot_id"],
                candidate_id=candidate["id"], outcome="reject", **self._decision(conn, project, actor, required(payload, "reason"))))
            return {"id": row_id, "candidate_id": candidate["id"], "outcome": "reject"}
        return self._mutate(project_id, "reject_candidate", payload, actor=actor, callback=work, **kw)

    def retire_binding(self, project_id, payload, actor, **kw):
        def work(conn, project):
            p, slot_id = project["id"], checked_id(required(payload, "slot_id"))
            self._one(conn, S.binding_slots, p, slot_id)
            current = conn.execute(select(S.current_bindings).where(S.current_bindings.c.project_id == p,
                S.current_bindings.c.slot_id == slot_id)).mappings().first()
            if not current:
                raise Conflict("槽位没有当前选择", "binding_not_current")
            row_id = new_id()
            conn.execute(insert(S.binding_decisions).values(project_id=p, id=row_id, slot_id=slot_id,
                candidate_id=current["candidate_id"], outcome="retire", **self._decision(conn, project, actor, required(payload, "reason"))))
            conn.execute(delete(S.current_bindings).where(S.current_bindings.c.project_id == p, S.current_bindings.c.slot_id == slot_id))
            return {"id": row_id, "slot_id": slot_id, "outcome": "retire"}
        return self._mutate(project_id, "retire_binding", payload, actor=actor, callback=work, **kw)

    def decide_media_lifecycle(self, project_id, payload, actor, **kw):
        def work(conn, project):
            media = self._one(conn, S.media_items, project["id"], required(payload, "media_id"))
            row_id = new_id()
            conn.execute(insert(S.media_lifecycle_decisions).values(project_id=project["id"], id=row_id,
                media_id=media["id"], outcome=required(payload, "outcome"),
                **self._decision(conn, project, actor, required(payload, "reason"))))
            return {"id": row_id, "media_id": media["id"], "outcome": payload["outcome"]}
        return self._mutate(project_id, "decide_media_lifecycle", payload, actor=actor, callback=work, **kw)

    def decide_rights(self, project_id, payload, actor, **kw):
        def work(conn, project):
            p = project["id"]
            media = self._one(conn, S.media_items, p, required(payload, "media_id"))
            source_id = payload.get("source_id")
            outcome = required(payload, "outcome")
            if outcome in {"owned", "licensed"}:
                self._one(conn, S.source_versions, p, required(payload, "source_id"))
            row_id = new_id()
            expires = datetime.fromisoformat(payload["expires_at"]) if payload.get("expires_at") else None
            if expires and expires.tzinfo is None:
                raise ResourceError("授权到期时间需要时区")
            scope = payload.get("scope", {"purposes": []})
            if not isinstance(scope, dict) or not isinstance(scope.get("purposes"), list):
                raise ResourceError("权利范围必须包含 purposes 列表", "invalid_rights_scope")
            conn.execute(insert(S.rights_decisions).values(project_id=p, id=row_id, media_id=media["id"], source_id=source_id,
                outcome=outcome, scope=scope, expires_at=expires,
                **self._decision(conn, project, actor, required(payload, "reason"))))
            return {"id": row_id, "media_id": media["id"], "outcome": outcome}
        return self._mutate(project_id, "decide_rights", payload, actor=actor, callback=work, **kw)

    def record_media_check(self, project_id, payload, **kw):
        def work(conn, project):
            media = self._media(conn, project["id"], required(payload, "media_id"))
            if payload.get("blob_sha256", media["sha256"]) != media["sha256"]:
                raise ResourceError("检查不属于当前固定字节", "check_sha_mismatch")
            row_id = new_id()
            conn.execute(insert(S.media_checks).values(project_id=project["id"], id=row_id, media_id=media["id"],
                blob_id=media["blob_id"], blob_sha256=media["sha256"], checker=required(payload, "checker"),
                criteria_version=required(payload, "criteria_version"), outcome=required(payload, "outcome"), report=payload.get("report", {}),
                project_revision=project["revision"] + 1))
            return {"id": row_id, "media_id": media["id"]}
        return self._mutate(project_id, "record_media_check", payload, callback=work, **kw)

    def create_media_operation(self, project_id, payload, **kw):
        def work(conn, project):
            p, operation_id = project["id"], checked_id(payload.get("id", new_id()))
            inputs, outputs = required(payload, "inputs"), required(payload, "outputs")
            input_ids = {checked_id(required(item, "media_id")) for item in inputs}
            output_ids = {checked_id(required(item, "media_id")) for item in outputs}
            if not inputs or not outputs or input_ids & output_ids:
                raise ResourceError("加工需要非空输入输出且不能引用自身", "operation_cycle")
            # Project FOR UPDATE in _mutate serializes concurrent graph writes.
            edges = conn.execute(select(S.operation_inputs.c.media_id.label("parent"), S.operation_outputs.c.media_id.label("child"))
                .select_from(S.operation_inputs.join(S.operation_outputs, and_(
                    S.operation_inputs.c.project_id == S.operation_outputs.c.project_id,
                    S.operation_inputs.c.operation_id == S.operation_outputs.c.operation_id)))
                .where(S.operation_inputs.c.project_id == p)).all()
            children = {}
            for parent, child in edges:
                children.setdefault(parent, set()).add(child)
            for output_id in output_ids:
                pending, seen = [output_id], set()
                while pending:
                    item = pending.pop()
                    if item in input_ids:
                        raise ResourceError("素材加工图出现循环", "operation_cycle")
                    if item not in seen:
                        seen.add(item)
                        pending.extend(children.get(item, ()))
            conn.execute(insert(S.media_operations).values(project_id=p, id=operation_id,
                operation_type=required(payload, "operation_type"), recipe_version=required(payload, "recipe_version"),
                tool=required(payload, "tool"), tool_version=required(payload, "tool_version"), parameters=payload.get("parameters", {}),
                status="created", execution=payload.get("execution", {})))
            for order, item in enumerate(inputs):
                self._one(conn, S.media_items, p, item["media_id"])
                conn.execute(insert(S.operation_inputs).values(project_id=p, id=checked_id(item.get("id", new_id())),
                    operation_id=operation_id, media_id=checked_id(item["media_id"]), role=item.get("role", "layer"),
                    layer_order=item.get("layer_order", order), start_ms=item.get("start_ms"), end_ms=item.get("end_ms"),
                    transform=item.get("transform", {}), opacity=item.get("opacity", 1), mask_input_id=item.get("mask_input_id")))
            for order, item in enumerate(outputs):
                media = self._media(conn, p, item["media_id"])
                if not any(location["available"] for location in media["locations"]):
                    raise ResourceError("加工输出字节未完成入库", "output_bytes_missing")
                conn.execute(insert(S.operation_outputs).values(project_id=p, id=new_id(), operation_id=operation_id,
                    media_id=media["id"], role=item.get("role", "composite"), ordinal=order))
            conn.execute(update(S.media_operations).where(S.media_operations.c.project_id == p,
                S.media_operations.c.id == operation_id).values(status="succeeded"))
            return {"id": operation_id, "status": "succeeded"}
        return self._mutate(project_id, "create_media_operation", payload, callback=work, **kw)

    def get_media_lineage(self, project_id, media_id, max_nodes=1000, max_depth=32):
        if not 1 <= max_nodes <= 5000 or not 1 <= max_depth <= 100:
            raise ResourceError("来源图查询范围无效")
        with self.engine.connect() as conn:
            project = self._project(conn, project_id)
            p, media_id = project["id"], checked_id(media_id)
            self._media(conn, p, media_id)
            pending, seen, operations, edges, truncated = [(media_id, 0)], set(), {}, [], False
            while pending:
                current, depth = pending.pop()
                if current in seen:
                    continue
                if depth > max_depth or len(seen) >= max_nodes or len(edges) >= max_nodes:
                    truncated = True
                    continue
                seen.add(current)
                operation_ids = conn.execute(select(S.operation_outputs.c.operation_id).where(
                    S.operation_outputs.c.project_id == p, S.operation_outputs.c.media_id == current)).scalars().all()
                for op_id in operation_ids:
                    if op_id not in operations:
                        operations[op_id] = self._one(conn, S.media_operations, p, op_id)
                    inputs = conn.execute(select(S.operation_inputs).where(S.operation_inputs.c.project_id == p,
                        S.operation_inputs.c.operation_id == op_id).order_by(S.operation_inputs.c.layer_order, S.operation_inputs.c.id)
                        .limit(max_nodes - len(edges) + 1)).mappings()
                    for row in inputs:
                        if len(edges) >= max_nodes:
                            truncated = True
                            break
                        edges.append(dict(row, output_media_id=current))
                        pending.append((row["media_id"], depth + 1))
            return clean({"media_id": media_id, "operations": list(operations.values()), "inputs": edges,
                          "source_media_ids": sorted(seen), "revision": project["revision"],
                          "truncated": truncated, "max_nodes": max_nodes, "max_depth": max_depth})

    def get_media_usage(self, project_id, media_id, offset=0, limit=200):
        if offset < 0 or not 1 <= limit <= 1000:
            raise ResourceError("用途查询分页范围无效")
        with self.engine.connect() as conn:
            project = self._project(conn, project_id)
            p, media_id = project["id"], checked_id(media_id)
            self._media(conn, p, media_id)
            candidate_query = (select(S.binding_candidates, S.binding_slots.c.target_object_id,
                S.binding_slots.c.role, S.binding_slots.c.slot_key).select_from(S.binding_candidates.join(S.binding_slots,
                and_(S.binding_candidates.c.project_id == S.binding_slots.c.project_id, S.binding_candidates.c.slot_id == S.binding_slots.c.id)))
                .where(S.binding_candidates.c.project_id == p, S.binding_candidates.c.media_id == media_id))
            candidates = [dict(r) for r in conn.execute(candidate_query.order_by(S.binding_candidates.c.id).offset(offset).limit(limit)).mappings()]
            current_query = select(S.current_bindings).select_from(S.current_bindings.join(S.binding_candidates,
                and_(S.current_bindings.c.project_id == S.binding_candidates.c.project_id,
                     S.current_bindings.c.candidate_id == S.binding_candidates.c.id))).where(
                S.current_bindings.c.project_id == p, S.binding_candidates.c.media_id == media_id)
            current = [dict(r) for r in conn.execute(current_query.order_by(S.current_bindings.c.slot_id).offset(offset).limit(limit)).mappings()]
            result = {"media_id": media_id, "candidates": candidates, "current_bindings": current,
                      "revision": project["revision"], "offset": offset, "limit": limit, "totals": {
                          "candidates": conn.execute(select(func.count()).select_from(candidate_query.subquery())).scalar_one(),
                          "current_bindings": conn.execute(select(func.count()).select_from(current_query.subquery())).scalar_one()}}
            delegation_query = select(S.binding_selection_delegations, S.media_reviews.c.reviewer,
                S.media_reviews.c.reviewer_type).select_from(S.binding_selection_delegations.join(S.binding_candidates,
                    and_(S.binding_selection_delegations.c.project_id == S.binding_candidates.c.project_id,
                         S.binding_selection_delegations.c.candidate_id == S.binding_candidates.c.id)).join(S.media_reviews,
                    and_(S.binding_selection_delegations.c.project_id == S.media_reviews.c.project_id,
                         S.binding_selection_delegations.c.review_id == S.media_reviews.c.id))).where(
                    S.binding_selection_delegations.c.project_id == p, S.binding_candidates.c.media_id == media_id)
            result["totals"]["selection_delegations"] = conn.execute(select(func.count()).select_from(delegation_query.subquery())).scalar_one()
            result["selection_delegations"] = [dict(r) for r in conn.execute(delegation_query.order_by(
                S.binding_selection_delegations.c.decision_id).offset(offset).limit(limit)).mappings()]
            from .production_guard import trial_sources
            origins = trial_sources(conn, p, media_id)
            result["totals"]["trial_sources"] = len(origins)
            result["trial_sources"] = origins[offset:offset + limit]
            for label, table in (("operation_inputs", S.operation_inputs), ("job_inputs", S.job_input_media),
                    ("job_outputs", S.job_outputs), ("timeline_items", S.timeline_item_media),
                    ("render_inputs", S.render_inputs), ("render_outputs", S.render_outputs)):
                query = select(table).where(table.c.project_id == p, table.c.media_id == media_id)
                result["totals"][label] = conn.execute(select(func.count()).select_from(query.subquery())).scalar_one()
                result[label] = [dict(r) for r in conn.execute(query.order_by(table.c.id).offset(offset).limit(limit)).mappings()]
            descendants = conn.execute(text("""WITH RECURSIVE edges(parent_id, child_id) AS (
                SELECT i.media_id, o.media_id FROM operation_inputs i JOIN operation_outputs o
                ON i.project_id=o.project_id AND i.operation_id=o.operation_id WHERE i.project_id=:project
            ), descendants(id) AS (
                SELECT child_id FROM edges WHERE parent_id=:media
                UNION SELECT e.child_id FROM edges e JOIN descendants d ON e.parent_id=d.id
            ) SELECT id FROM descendants ORDER BY id"""), {"project": p, "media": media_id}).scalars().all()
            result["totals"]["derived_media_ids"] = len(descendants)
            result["derived_media_ids"] = descendants[offset:offset + limit]
            result["indirect_current_bindings"] = []
            if descendants:
                result["indirect_current_bindings"] = [dict(r) for r in conn.execute(select(
                    S.current_bindings, S.binding_candidates.c.media_id).select_from(S.current_bindings.join(S.binding_candidates,
                    and_(S.current_bindings.c.project_id == S.binding_candidates.c.project_id,
                         S.current_bindings.c.candidate_id == S.binding_candidates.c.id)))
                    .where(S.current_bindings.c.project_id == p, S.binding_candidates.c.media_id.in_(descendants))
                    .order_by(S.current_bindings.c.slot_id).offset(offset).limit(limit)).mappings()]
            result["truncated"] = any(total > offset + limit for total in result["totals"].values())
            return clean(result)

    def create_preview_job(self, project_id, payload, **kw):
        def work(conn, project):
            media = self._media(conn, project["id"], required(payload, "media_id"))
            purpose = required(payload, "purpose")
            if purpose not in {"thumbnail", "poster", "proxy_video", "waveform", "document_pages"}:
                raise ResourceError("未知预览用途")
            sha = digest({"sha256": media["sha256"], "purpose": purpose, "recipe_version": required(payload, "recipe_version")})
            existing = conn.execute(select(S.preview_jobs).where(S.preview_jobs.c.project_id == project["id"],
                S.preview_jobs.c.media_id == media["id"], S.preview_jobs.c.purpose == purpose,
                S.preview_jobs.c.request_sha256 == sha)).mappings().first()
            if existing:
                return dict(existing)
            row_id = new_id()
            conn.execute(insert(S.preview_jobs).values(project_id=project["id"], id=row_id, media_id=media["id"],
                purpose=purpose, recipe_version=payload["recipe_version"], request_sha256=sha, status="created"))
            return {"id": row_id, "status": "created", "request_sha256": sha}
        return self._mutate(project_id, "create_preview_job", payload, callback=work, **kw)

    def compile_shot_context(self, project_id, shot_id, purpose=None):
        with self.engine.connect() as conn:
            project = self._project(conn, project_id)
            return clean(self._compile_context(conn, project, checked_id(shot_id), purpose))

    def compile_asset_context(self, project_id, asset_id, purpose="asset_ref"):
        with self.engine.connect() as conn:
            project = self._project(conn, project_id)
            return clean(self._compile_asset_context(conn, project, checked_id(asset_id), purpose))

    def _compile_asset_context(self, conn, project, asset_id, purpose):
        p = project["id"]
        identity = self._one(conn, S.asset_identities, p, asset_id)
        if identity["asset_kind"] == "voice":
            raise ResourceError("声音复刻尚无Provider能力，不允许资产图像任务代替", "asset_generation_unsupported")
        specs = [dict(r) for r in conn.execute(select(S.asset_spec_versions).where(
            S.asset_spec_versions.c.project_id == p, S.asset_spec_versions.c.asset_id == asset_id,
            S.asset_spec_versions.c.variant_key == "master", S.asset_spec_versions.c.artifact_id.in_(
                select(S.current_artifact_versions.c.artifact_id).where(S.current_artifact_versions.c.project_id == p)))).mappings()
            if self._artifact_approved(conn, p, r["artifact_id"])]
        gaps = []
        if len(specs) != 1:
            gaps.append({"code": "identity_spec_missing" if not specs else "identity_spec_conflict", "asset_id": asset_id})
        artifacts = {s["artifact_id"]: self._one(conn, S.artifact_versions, p, s["artifact_id"]) for s in specs}
        media_inputs = []
        slots = conn.execute(select(S.binding_slots).where(S.binding_slots.c.project_id == p,
            S.binding_slots.c.target_object_id == asset_id, S.binding_slots.c.role.in_(INHERITED_REFERENCE_ROLES))).mappings()
        for slot in slots:
            current = conn.execute(select(S.current_bindings).where(S.current_bindings.c.project_id == p,
                S.current_bindings.c.slot_id == slot["id"])).mappings().first()
            # A first reference does not require a previously selected reference.
            if not current:
                continue
            candidate = self._one(conn, S.binding_candidates, p, current["candidate_id"])
            media, reasons = self._usable(conn, p, candidate["media_id"], slot["role"])
            if candidate["spec_version_id"]:
                if not self._artifact_approved(conn, p, candidate["spec_version_id"]):
                    reasons.append("spec_unapproved")
                else:
                    artifacts[candidate["spec_version_id"]] = self._one(conn, S.artifact_versions, p, candidate["spec_version_id"])
            if reasons:
                gaps.append({"code": "binding_unusable", "slot_id": slot["id"], "reasons": reasons})
                continue
            media_inputs.append({"media_id": media["id"], "blob_id": media["blob_id"], "sha256": media["sha256"],
                "role": slot["role"], "slot_id": slot["id"], "candidate_id": candidate["id"],
                "binding_decision_id": current["decision_id"], "target_object_id": asset_id,
                "inherited": False, "locations": media["locations"]})
        ordered = [artifacts[k] for k in sorted(artifacts)]
        context = {"project_id": p, "revision": project["revision"], "shot_id": None, "asset_id": asset_id,
            "purpose": purpose, "ancestors": [asset_id], "artifacts": [{"id": a["id"], "artifact_type": a["artifact_type"],
                "sha256": a["sha256"], "document": clean(a["document"])} for a in ordered],
            "state": None, "state_entity_refs": [], "script_lines": [], "voices": [],
            "media": sorted(media_inputs, key=lambda m: (m["role"], m["slot_id"])), "gaps": gaps, "ready": not gaps}
        context["semantic_inputs"] = self._semantic_inputs(conn, p, None, None, purpose,
            ordered, {asset_id}, {s["asset_id"]: s["id"] for s in specs}, [], [])
        context["sha256"] = context_digest(clean(context))
        return context

    @staticmethod
    def _context_plan_applies(artifact, object_keys):
        """Honor explicit plan ownership in migrated project-wide artifacts."""
        try:
            document = json.loads(artifact["document"])
        except (ValueError, UnicodeDecodeError):
            return True
        if not isinstance(document, dict) or document.get("format") not in {
                "vsc.continuity-plan/v1", "vsc.sound-cue-sheet/v1"}:
            return True
        for kind in ("scene", "sequence"):
            owner = document.get(kind + "_id")
            if owner and owner not in object_keys[kind]:
                return False
        if document.get("format") == "vsc.continuity-plan/v1" and isinstance(document.get("shots"), list):
            return any(row.get("id") in object_keys["shot"] for row in document["shots"] if isinstance(row, dict))
        return True

    def _compatible_context_specs(self, conn, p, first, second):
        """Compare approved bible revisions without replacing either fixed pin."""
        if first["asset_id"] != second["asset_id"]:
            return False
        if first["artifact_id"] == second["artifact_id"]:
            return True
        artifacts = [self._one(conn, S.artifact_versions, p, spec["artifact_id"]) for spec in (first, second)]
        if artifacts[0]["artifact_key"] != artifacts[1]["artifact_key"]:
            return False
        old, new = sorted(artifacts, key=lambda row: row["version"])
        alias = self._one(conn, S.creative_objects, p, first["asset_id"])["display_code"]
        rows = []
        for artifact in (old, new):
            try:
                document = json.loads(artifact["document"])
            except (ValueError, UnicodeDecodeError):
                return False
            if not isinstance(document, dict) or document.get("format") != "vsc.asset-bible/v1":
                return False
            matches = [row for key in ("entities", "styles", "sounds") for row in document.get(key, [])
                       if isinstance(row, dict) and row.get("id") in {first["asset_id"], alias}]
            if len(matches) != 1:
                return False
            rows.append(matches[0])
        from vsc.project.artifacts import _same_identity
        return _same_identity(*rows)

    def _compile_context(self, conn, project, shot_id, purpose=None):
        p = project["id"]
        shot = self._one(conn, S.shots, p, shot_id)
        sequence = self._one(conn, S.sequences, p, shot["parent_id"])
        scene = self._one(conn, S.scenes, p, sequence["parent_id"])
        episode = self._one(conn, S.episodes, p, scene["parent_id"])
        work = self._one(conn, S.works, p, episode["parent_id"])
        ancestor_ids = [work["id"], episode["id"], scene["id"], sequence["id"], shot_id]
        artifacts = conn.execute(select(S.artifact_versions).where(S.artifact_versions.c.project_id == p,
            S.artifact_versions.c.artifact_type.in_({
                "vsc.creative_brief", "vsc.adaptation_plan", "vsc.episode_beats", "vsc.screenplay",
                "vsc.coverage_plan", "vsc.shot_plan", "vsc.continuity_plan", "vsc.scene_state",
                "vsc.asset_bible", "vsc.visual_bible", "vsc.animatic", "vsc.sequence_links",
                "creative-relations", "vsc.sound_plan", "vsc.sound_cue_sheet", "shot_plan", "shot-plan", "shot_design", "shot-design",
                "scene-state", "scene_state", "asset-bible", "asset_bible", "screenplay", "coverage-plan",
                "coverage_plan", "voice-spec", "voice_spec", "voice-bindings", "continuity-plan", "animatic", "visual-bible"}),
            S.artifact_versions.c.id.in_(select(S.current_artifact_versions.c.artifact_id).where(S.current_artifact_versions.c.project_id == p)),
            or_(S.artifact_versions.c.project_wide.is_(True), S.artifact_versions.c.id.in_(
                select(S.artifact_object_scopes.c.artifact_id).where(S.artifact_object_scopes.c.project_id == p,
                    S.artifact_object_scopes.c.object_id.in_(ancestor_ids)))))).mappings().all()
        object_keys = {kind: {row["id"], self._one(conn, S.creative_objects, p, row["id"])["display_code"]}
                       for kind, row in (("scene", scene), ("sequence", sequence), ("shot", shot))}
        approved = [dict(a) for a in artifacts if self._context_plan_applies(a, object_keys)
                    and self._artifact_approved(conn, p, a["id"])]
        gaps, selected_artifacts = [], []
        by_key = {}
        for artifact in approved:
            by_key.setdefault(artifact["artifact_key"], []).append(artifact)
        for key, versions in by_key.items():
            # Multiple independently approved versions are a gap, never "newer wins".
            if len(versions) != 1:
                gaps.append({"code": "artifact_conflict", "artifact_key": key, "ids": [v["id"] for v in versions]})
            else:
                selected_artifacts.append(versions[0])
        artifact_ids = [a["id"] for a in selected_artifacts]
        coverage_rows = conn.execute(select(S.shot_line_coverage, S.script_lines.c.text,
            S.script_lines.c.line_key, S.script_lines.c.speaker_id, S.script_lines.c.script_version_id)
            .select_from(S.shot_line_coverage.join(S.script_lines,
                and_(S.shot_line_coverage.c.project_id == S.script_lines.c.project_id,
                     S.shot_line_coverage.c.line_id == S.script_lines.c.id)))
            .where(S.shot_line_coverage.c.project_id == p, S.shot_line_coverage.c.shot_id == shot_id,
                   S.shot_line_coverage.c.coverage_version_id.in_(artifact_ids))
            .order_by(S.script_lines.c.ordinal, S.shot_line_coverage.c.start_char)).mappings().all()
        lines, voices = [], []
        for coverage in coverage_rows:
            if not self._artifact_approved(conn, p, coverage["script_version_id"]):
                gaps.append({"code": "script_unapproved", "line_id": coverage["line_id"]})
                continue
            line = dict(coverage)
            line["spoken_text"] = line["text"][line["start_char"]:line["end_char"]]
            lines.append(line)
        if purpose in {"tts", "dialogue_dry", "dialogue"} and not lines:
            gaps.append({"code": "dialogue_coverage_missing"})
        for speaker in sorted({r["speaker_id"] for r in lines if r["speaker_id"]}):
            voice_rows = conn.execute(select(S.voice_spec_versions, S.character_voice_bindings.c.scope_version_id)
                .select_from(S.voice_spec_versions.join(S.character_voice_bindings,
                    and_(S.voice_spec_versions.c.project_id == S.character_voice_bindings.c.project_id,
                         S.voice_spec_versions.c.id == S.character_voice_bindings.c.voice_spec_id)))
                .where(S.voice_spec_versions.c.project_id == p, S.character_voice_bindings.c.character_id == speaker,
                       S.character_voice_bindings.c.scope_version_id.in_(artifact_ids))).mappings().all()
            voice_rows = [dict(v) for v in voice_rows if self._artifact_approved(conn, p, v["artifact_id"])]
            if len(voice_rows) == 1:
                voices.append(dict(voice_rows[0], character_id=speaker))
            elif purpose in {"tts", "dialogue_dry", "dialogue"}:
                gaps.append({"code": "voice_missing" if not voice_rows else "voice_conflict", "character_id": speaker})
        if not any(a["artifact_type"] in {"vsc.shot_plan", "shot_plan", "shot-plan", "shot_design", "shot-design"} for a in selected_artifacts):
            gaps.append({"code": "shot_spec_missing"})
        states = conn.execute(select(S.state_versions).where(S.state_versions.c.project_id == p,
            S.state_versions.c.artifact_id.in_(artifact_ids),
            S.state_versions.c.scene_id == scene["id"], or_(S.state_versions.c.shot_id == shot_id, S.state_versions.c.shot_id.is_(None)))).mappings().all()
        states = [dict(s) for s in states if self._artifact_approved(conn, p, s["artifact_id"])]
        explicit = [s for s in states if s["shot_id"] == shot_id]
        state_candidates = explicit or [s for s in states if s["shot_id"] is None]
        state = state_candidates[0] if len(state_candidates) == 1 else None
        if len(state_candidates) > 1:
            gaps.append({"code": "state_conflict"})
        entity_refs = []
        asset_ids = set()
        dialogue_only = purpose in {"tts", "dialogue_dry", "dialogue"}
        if state:
            entity_refs = [dict(r) for r in conn.execute(select(S.state_entity_refs).where(
                S.state_entity_refs.c.project_id == p, S.state_entity_refs.c.state_id == state["id"])).mappings()]
            if not dialogue_only:
                asset_ids.update(r["asset_id"] for r in entity_refs if r["relation"] in {"in_frame", "held", "costume"})
            if state["location_id"] and not dialogue_only:
                asset_ids.add(state["location_id"])
        elif not states:
            gaps.append({"code": "state_missing"})
        if dialogue_only:
            asset_ids.update(v["voice_id"] for v in voices)
        # Preserve exact state-specified identity/voice evidence even when its
        # artifact is scoped to an asset rather than the shot's ancestor chain.
        extra_artifact_ids = {v["artifact_id"] for v in voices}
        for entity in entity_refs:
            if entity["spec_version_id"]:
                spec = self._one(conn, S.asset_spec_versions, p, entity["spec_version_id"])
                if spec["asset_id"] != entity["asset_id"]:
                    gaps.append({"code": "state_spec_identity_mismatch", "asset_id": entity["asset_id"]})
                extra_artifact_ids.add(spec["artifact_id"])
        slots = conn.execute(select(S.binding_slots).where(S.binding_slots.c.project_id == p,
            S.binding_slots.c.target_object_id.in_([shot_id] + sorted(asset_ids)),
            S.binding_slots.c.role.in_(tuple(ROLE_MATRIX)))).mappings().all()
        spec_by_identity = {r["asset_id"]: r["spec_version_id"] for r in entity_refs if r["spec_version_id"]}
        fixed_asset_refs = {}
        references = conn.execute(select(S.artifact_asset_spec_refs, S.artifact_versions.c.version)
            .select_from(S.artifact_asset_spec_refs.join(S.asset_spec_versions, and_(
                S.artifact_asset_spec_refs.c.project_id == S.asset_spec_versions.c.project_id,
                S.artifact_asset_spec_refs.c.spec_version_id == S.asset_spec_versions.c.id)).join(S.artifact_versions, and_(
                S.asset_spec_versions.c.project_id == S.artifact_versions.c.project_id,
                S.asset_spec_versions.c.artifact_id == S.artifact_versions.c.id)))
            .where(S.artifact_asset_spec_refs.c.project_id == p,
                   S.artifact_asset_spec_refs.c.artifact_id.in_(artifact_ids),
                   S.artifact_asset_spec_refs.c.asset_id.in_(sorted(asset_ids)))
            .order_by(S.artifact_versions.c.version, S.artifact_asset_spec_refs.c.spec_version_id)).mappings()
        conflicted_assets = set()
        for ref in references:
            spec = self._one(conn, S.asset_spec_versions, p, ref["spec_version_id"])
            previous = fixed_asset_refs.setdefault(ref["asset_id"], spec)
            if not self._compatible_context_specs(conn, p, previous, spec):
                conflicted_assets.add(ref["asset_id"])
            extra_artifact_ids.add(spec["artifact_id"])
        for asset_id, fixed in fixed_asset_refs.items():
            existing = self._one(conn, S.asset_spec_versions, p, spec_by_identity[asset_id]) if asset_id in spec_by_identity else None
            if existing and not self._compatible_context_specs(conn, p, existing, fixed):
                conflicted_assets.add(asset_id)
            else:
                spec_by_identity.setdefault(asset_id, fixed["id"])
                if existing:
                    fixed_asset_refs[asset_id] = existing
        gaps.extend({"code": "asset_version_conflict", "asset_id": asset_id} for asset_id in sorted(conflicted_assets))
        ranked_slots = {}
        for slot in slots:
            if slot["role"] in POST_ROLES:
                continue
            identity_id = slot["identity_asset_id"] or (slot["target_object_id"] if slot["target_object_id"] != shot_id else None)
            if slot["role"] in INHERITED_REFERENCE_ROLES and identity_id:
                key = (identity_id, slot["role"])
                if slot["target_object_id"] == shot_id:
                    rank = 0
                elif slot["variant_spec_id"]:
                    if spec_by_identity.get(identity_id) != slot["variant_spec_id"]:
                        continue
                    rank = 1
                else:
                    rank = 2
            else:
                key, rank = (shot_id, slot["role"], slot["slot_key"]), 0
            previous = ranked_slots.get(key)
            if not previous or rank < previous[0]:
                ranked_slots[key] = (rank, [slot])
            elif rank == previous[0]:
                previous[1].append(slot)
        slots = []
        for _, alternatives in ranked_slots.values():
            if len(alternatives) > 1:
                gaps.append({"code": "binding_conflict", "slot_ids": [s["id"] for s in alternatives]})
            else:
                slots.append(alternatives[0])
        media_inputs = []
        for slot in slots:
            inherited = slot["target_object_id"] != shot_id
            if slot["role"] in POST_ROLES or (inherited and slot["role"] not in INHERITED_REFERENCE_ROLES):
                continue
            if purpose in {"shot_keyframe", "keyframe", "ref"} and slot["role"] in {"first_frame", "last_frame"}:
                continue
            current = conn.execute(select(S.current_bindings).where(S.current_bindings.c.project_id == p,
                S.current_bindings.c.slot_id == slot["id"])).mappings().first()
            if not current:
                gaps.append({"code": "binding_missing", "slot_id": slot["id"], "role": slot["role"]})
                continue
            candidate = self._one(conn, S.binding_candidates, p, current["candidate_id"])
            if candidate["spec_version_id"]:
                extra_artifact_ids.add(candidate["spec_version_id"])
            media, reasons = self._usable(conn, p, candidate["media_id"], slot["role"])
            if candidate["spec_version_id"] and not self._artifact_approved(conn, p, candidate["spec_version_id"]):
                reasons.append("spec_unapproved")
            if reasons:
                gaps.append({"code": "binding_unusable", "slot_id": slot["id"], "reasons": reasons})
                continue
            media_inputs.append({"media_id": media["id"], "blob_id": media["blob_id"], "sha256": media["sha256"],
                "role": slot["role"], "slot_id": slot["id"], "candidate_id": candidate["id"],
                "binding_decision_id": current["decision_id"], "target_object_id": slot["target_object_id"],
                "inherited": inherited, "locations": media["locations"]})
        if purpose in {"video_clip", "image_to_video", "i2v"} and not any(m["role"] == "first_frame" for m in media_inputs):
            gaps.append({"code": "first_frame_missing"})
        for identity_id in sorted(asset_ids):
            identity = self._one(conn, S.asset_identities, p, identity_id)
            required_roles = {"character": {"identity_face"}, "location": {"location_master", "location_view"},
                              "prop": {"prop"}, "voice": {"voice_sample"}, "style": {"style_reference"},
                              "costume": {"costume"}}.get(identity["asset_kind"], set())
            if required_roles and not any(m["role"] in required_roles and
                    (m["target_object_id"] == identity_id or any(s["id"] == m["slot_id"] and s["identity_asset_id"] == identity_id for s in slots))
                    for m in media_inputs):
                gaps.append({"code": "identity_reference_missing", "asset_id": identity_id, "roles": sorted(required_roles)})
        selected_ids = {a["id"] for a in selected_artifacts}
        for artifact_id in sorted(extra_artifact_ids - selected_ids):
            if not self._artifact_approved(conn, p, artifact_id):
                gaps.append({"code": "identity_spec_unapproved", "artifact_id": artifact_id})
            else:
                selected_artifacts.append(self._one(conn, S.artifact_versions, p, artifact_id))
        selected_artifacts.sort(key=lambda a: a["id"])
        media_inputs.sort(key=lambda m: (m["role"], m["slot_id"]))
        context = {"project_id": p, "revision": project["revision"], "shot_id": shot_id, "purpose": purpose,
            "ancestors": ancestor_ids, "artifacts": [{"id": a["id"], "artifact_type": a["artifact_type"],
                "sha256": a["sha256"], "document": clean(a["document"])} for a in selected_artifacts],
            "state": state, "state_entity_refs": entity_refs, "script_lines": lines, "voices": voices,
            "media": media_inputs, "gaps": gaps, "ready": not gaps}
        context["semantic_inputs"] = self._semantic_inputs(conn, p, shot_id, scene["id"], purpose,
            selected_artifacts, asset_ids, spec_by_identity, lines, voices,
            {key: value["artifact_id"] for key, value in fixed_asset_refs.items()})
        context["sha256"] = context_digest(clean(context))
        return context

    def _semantic_inputs(self, conn, p, shot_id, scene_id, purpose, artifacts, asset_ids, specs, lines, voices, fixed_asset_artifacts=None):
        objects = {r["id"]: r["display_code"] for r in conn.execute(select(S.creative_objects.c.id, S.creative_objects.c.display_code)
            .where(S.creative_objects.c.project_id == p, S.creative_objects.c.id.in_(list(asset_ids) + [shot_id, scene_id]))).mappings()}
        shot_keys = {shot_id, objects[shot_id]} if shot_id else set()
        scene_keys = {scene_id, objects[scene_id]} if scene_id else set()
        asset_keys = set(asset_ids) | {objects[k] for k in asset_ids}
        variants = {}
        for asset_id, spec_id in specs.items():
            spec = self._one(conn, S.asset_spec_versions, p, spec_id)
            variants[objects.get(asset_id, asset_id)] = "default" if spec["variant_key"] == "master" else spec["variant_key"]
        line_keys = {line["line_key"] for line in lines}
        audio = purpose in {"tts", "dialogue_dry", "dialogue"}
        def sanitized(value):
            ignored = {"path", "url", "uri", "local_uri", "original_uri", "evidence_uri", "filename", "name", "title",
                       "references", "created_at", "updated_at", "source_sha256", "spec_version_id", "artifact_id"}
            if isinstance(value, dict):
                return {k: sanitized(v) for k, v in value.items() if k not in ignored}
            if isinstance(value, list):
                return [sanitized(v) for v in value]
            return value
        values = {}
        for artifact in artifacts:
            try:
                doc = json.loads(artifact["document"])
            except (ValueError, UnicodeDecodeError):
                doc = clean(artifact["document"])
            fmt = doc.get("format") if isinstance(doc, dict) else None
            kind = artifact["artifact_type"]
            fragment = doc
            if fmt == "vsc.creative-relations/v1":
                uses = [u for u in doc.get("instances", []) if u.get("shot_id") == shot_id or (not u.get("shot_id") and u.get("scene_id") == scene_id)]
                keys = {u["key"] for u in uses}
                fragment = {"instances": uses, "interactions": [x for x in doc.get("interactions", []) if x.get("subject") in keys or x.get("object") in keys],
                    "performances": [x for x in doc.get("performances", []) if shot_id in x.get("shot_ids", []) and (audio or x.get("domain") != "voice")]}
                if audio:
                    fragment["cues"] = [x for x in doc.get("cues", []) if any(c.get("shot_id") == shot_id for c in x.get("shots", []))]
                if not any(fragment.values()):
                    continue
            elif fmt == "vsc.asset-bible/v1":
                entities = []
                for entity in doc.get("entities", []):
                    if entity["id"] not in asset_keys:
                        continue
                    entity_id = next((key for key in asset_ids if entity["id"] in {key, objects[key]}), None)
                    fixed_artifact = (fixed_asset_artifacts or {}).get(entity_id)
                    if fixed_artifact and fixed_artifact != artifact["id"]:
                        continue
                    selected = {k: v for k, v in entity.items() if k not in {"references", "variants", "voice", "sound"}}
                    variant = variants.get(entity["id"], "default")
                    selected["variants"] = {variant: entity.get("variants", {}).get(variant)}
                    if audio:
                        selected.update({k: entity[k] for k in ("voice", "sound") if k in entity})
                    entities.append(selected)
                if not entities:
                    continue
                fragment = {"entities": entities}
            elif fmt == "vsc.scene-state/v1":
                from vsc.story.consistency import derive
                snapshots = derive(doc)
                fragment = next((copy for key, copy in snapshots.items() if key in shot_keys), {})
                if isinstance(fragment, dict):
                    fragment = json.loads(json.dumps(fragment))
                    for moment in ("entry", "exit"):
                        if moment in fragment:
                            fragment[moment]["entities"] = {k: v for k, v in fragment[moment].get("entities", {}).items() if k in asset_keys}
            elif fmt == "vsc.continuity-plan/v1" or (isinstance(doc, dict) and "shots" in doc):
                fragment = [s for s in doc.get("shots", []) if s.get("id") in shot_keys]
            elif fmt == "vsc.screenplay/v1":
                fragment = [{k: s[k] for k in ("id",) if k in s} | {"units": [u for group in ("actions", "dialogue", "silence")
                    for u in s.get(group, []) if not line_keys or u.get("id") in line_keys]}
                    for s in doc.get("scenes", []) if s.get("id") in scene_keys]
            elif fmt == "vsc.coverage-plan/v1":
                fragment = [s for scene in doc.get("scenes", []) for seq in scene.get("sequences", [])
                            for s in seq.get("shots", []) if s.get("id") in shot_keys]
            elif isinstance(doc, dict) and "state_versions" in doc:
                fragment = [{k: v for k, v in state.items() if k != "id"} for state in doc["state_versions"]
                            if state.get("scene_id") == scene_id and state.get("shot_id", shot_id) == shot_id]
            elif isinstance(doc, dict) and ("voice_specs" in doc or "voice_bindings" in doc):
                voice_ids = {voice["voice_id"] for voice in voices}
                speaker_ids = {voice["character_id"] for voice in voices}
                fragment = {"voice_specs": [{k: v for k, v in item.items() if k != "id"} for item in doc.get("voice_specs", []) if item.get("voice_id") in voice_ids],
                            "voice_bindings": [{k: v for k, v in item.items() if k != "voice_spec_id"} for item in doc.get("voice_bindings", []) if item.get("character_id") in speaker_ids]}
            fragment = sanitized(fragment)
            key = digest({"type": kind, "fragment": fragment})
            values[key] = {"artifact_type": kind, "content": fragment}
        return [values[key] for key in sorted(values)]



    def freeze_timeline(self, project_id, payload, **kw):
        def work(conn, project):
            p, timeline_id = project["id"], checked_id(payload.get("id", new_id()))
            artifact = self._one(conn, S.artifact_versions, p, required(payload, "artifact_id"))
            if not self._artifact_approved(conn, p, artifact["id"]):
                raise ResourceError("时间线产物未批准", "timeline_unapproved")
            try:
                document = json.loads(artifact["document"].decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                raise ResourceError("固定时间线必须是可解析结构文档", "timeline_document_invalid")
            if isinstance(document, dict) and document.get("format") == "vsc.timeline/v1":
                items, fps_num, fps_den = self._timeline_projection(conn, project, artifact, document, payload)
            else:
                if not isinstance(document, dict) or document.get("items") != payload.get("items"):
                    raise ResourceError("时间线关系投影与批准正文不一致", "projection_mismatch")
                items, fps_num, fps_den = required(payload, "items"), payload.get("fps_num", 24), payload.get("fps_den", 1)
            conn.execute(insert(S.timeline_versions).values(project_id=p, id=timeline_id, artifact_id=artifact["id"],
                episode_id=checked_id(required(payload, "episode_id")), fps_num=fps_num, fps_den=fps_den))
            for ordinal, item in enumerate(items):
                item_id = new_id()
                conn.execute(insert(S.timeline_items).values(project_id=p, id=item_id, timeline_id=timeline_id,
                    shot_id=item.get("shot_id"), track_key=required(item, "track_key"), ordinal=item.get("ordinal", ordinal),
                    offset_frame=required(item, "offset_frame"), duration_frames=required(item, "duration_frames"), envelope=item.get("envelope", {})))
                for source in required(item, "media"):
                    media = self._media(conn, p, required(source, "media_id"))
                    decision = self._one(conn, S.binding_decisions, p, required(source, "binding_decision_id"))
                    self._validate_fixed_decision(conn, p, decision, media["id"], item.get("shot_id"))
                    conn.execute(insert(S.timeline_item_media).values(project_id=p, id=new_id(), item_id=item_id,
                        media_id=media["id"], binding_decision_id=decision["id"], blob_id=media["blob_id"], blob_sha256=media["sha256"],
                        role=required(source, "role"), source_in_frame=source.get("source_in_frame", 0),
                        source_out_frame=required(source, "source_out_frame")))
            return {"id": timeline_id, "artifact_id": artifact["id"]}
        return self._mutate(project_id, "freeze_timeline", payload, callback=work, **kw)

    def _timeline_projection(self, conn, project, artifact, document, payload):
        p = project["id"]
        ref = required(document, "selected_takes")
        selected = self._one(conn, S.artifact_versions, p, required(ref, "id"))
        dependencies = set(conn.execute(select(S.artifact_dependencies.c.dependency_id).where(
            S.artifact_dependencies.c.project_id == p, S.artifact_dependencies.c.artifact_id == artifact["id"])).scalars())
        if selected["id"] not in dependencies or selected["sha256"] != ref.get("sha256") or not self._artifact_approved(conn, p, selected["id"]):
            raise ResourceError("时间线必须固定批准的selected_takes依赖", "selected_takes_mismatch")
        if selected["artifact_type"] not in {"vsc.selected_takes", "selected-takes"}:
            raise ResourceError("selected_takes依赖类型错误", "selected_takes_mismatch")
        choices = {item["id"]: item for item in json.loads(selected["document"]).get("items", [])}
        bindings = {item["segment_id"]: item for item in document.get("bindings", [])}
        mappings = payload.get("selected_media", {})
        if not isinstance(mappings, dict):
            raise ResourceError("selected_media必须明确映射selected item至media与决定", "selected_media_mapping_required")
        object_map = self._projection_id_map(conn, p)["shot"]
        plan, items = required(document, "render_plan"), []
        for segment_ordinal, segment in enumerate(plan.get("segments", [])):
            if segment.get("kind") not in {"video", "image", "audio"}:
                continue
            binding = bindings.get(segment["id"])
            if not binding or binding.get("selected_item_id") not in choices:
                raise ResourceError("媒体segment必须明确绑定selected item", "timeline_binding_missing")
            choice = choices[binding["selected_item_id"]]
            mapping = mappings.get(choice["id"])
            if not isinstance(mapping, dict):
                raise ResourceError("不得按SHA猜素材身份，请提供selected_media映射", "selected_media_mapping_required")
            media = self._media(conn, p, required(mapping, "media_id"))
            decision = self._one(conn, S.binding_decisions, p, required(mapping, "binding_decision_id"))
            source = choice.get("media", {})
            if (media["sha256"] != source.get("sha256") or binding.get("sha256") != media["sha256"]
                    or segment.get("source") != source.get("path") or binding.get("purpose") != choice.get("purpose")
                    or binding.get("usage_rights") != choice.get("usage_rights")):
                raise ResourceError("时间线、获选文案与固定素材不一致", "selected_takes_mismatch")
            shot_id = object_map.get(choice.get("shot_id"))
            if segment.get("kind") in {"video", "image"} and (not shot_id or object_map.get(segment.get("source_shot_id")) != shot_id):
                raise ResourceError("时间线segment与获选镜头归属不一致", "selected_take_mismatch")
            self._validate_fixed_decision(conn, p, decision, media["id"], shot_id)
            slot = self._one(conn, S.binding_slots, p, decision["slot_id"])
            if choice.get("purpose") == "visual" and slot["role"] not in {"video_take", "composition", "first_frame", "last_frame"}:
                raise ResourceError("视觉选片没有批准的镜头用途", "selected_take_mismatch")
            duration = required(segment, "duration_in_frames")
            source_in = segment.get("source_in_frame", 0)
            items.append({"shot_id": shot_id, "ordinal": segment_ordinal, "track_key": segment.get("track_key", segment["kind"]),
                "offset_frame": required(segment, "from_frame"), "duration_frames": duration,
                "envelope": {k: segment[k] for k in ("volume", "muted", "fade_in_frames", "fade_out_frames", "audio_envelope") if k in segment},
                "media": [{"media_id": media["id"], "binding_decision_id": decision["id"], "role": slot["role"],
                           "source_in_frame": source_in, "source_out_frame": source_in + duration}]})
        if not items:
            raise ResourceError("时间线没有可冻结的媒体片段", "timeline_empty")
        fps = plan["composition"]["fps"]
        if type(fps) is not int or fps <= 0:
            raise ResourceError("原规范时间线fps必须为正整数")
        return items, fps, 1

    def _validate_fixed_decision(self, conn, p, decision, media_id, shot_id=None):
        candidate = self._one(conn, S.binding_candidates, p, decision["candidate_id"])
        slot = self._one(conn, S.binding_slots, p, decision["slot_id"])
        if decision["outcome"] != "select" or candidate["media_id"] != media_id:
            raise ResourceError("固定选择决定与用料不匹配", "decision_media_mismatch")
        current = conn.execute(select(S.current_bindings).where(S.current_bindings.c.project_id == p,
            S.current_bindings.c.slot_id == decision["slot_id"], S.current_bindings.c.decision_id == decision["id"])).mappings().first()
        if not current:
            raise Conflict("新时间线必须采用当前正式选择", "selected_take_not_current")
        _, gaps = self._usable(conn, p, media_id, slot["role"])
        if gaps:
            raise ResourceError("时间线用料不可用: " + ", ".join(gaps), "timeline_media_unusable")
        if shot_id and slot["role"] in {"video_take", "dialogue_dry"} and slot["target_object_id"] != shot_id:
            raise ResourceError("选片与镜头归属不一致", "selected_take_mismatch")

    def freeze_render(self, project_id, payload, **kw):
        def work(conn, project):
            p, row_id = project["id"], checked_id(payload.get("id", new_id()))
            timeline = self._one(conn, S.timeline_versions, p, required(payload, "timeline_id"))
            artifact = self._one(conn, S.artifact_versions, p, required(payload, "artifact_id"))
            if not self._artifact_approved(conn, p, artifact["id"]):
                raise ResourceError("渲染规格未批准", "render_unapproved")
            for key in ("subtitle_version_id", "style_version_id"):
                if payload.get(key) and not self._artifact_approved(conn, p, payload[key]):
                    raise ResourceError("字幕或样式规格未批准", "render_dependency_unapproved")
            conn.execute(insert(S.render_versions).values(project_id=p, id=row_id, timeline_id=timeline["id"], artifact_id=artifact["id"],
                subtitle_version_id=payload.get("subtitle_version_id"), style_version_id=payload.get("style_version_id"),
                tool=required(payload, "tool"), tool_version=required(payload, "tool_version"), parameters=payload.get("parameters", {})))
            items = select(S.timeline_items.c.id).where(S.timeline_items.c.project_id == p, S.timeline_items.c.timeline_id == timeline["id"])
            for source in conn.execute(select(S.timeline_item_media).where(S.timeline_item_media.c.project_id == p,
                    S.timeline_item_media.c.item_id.in_(items))).mappings():
                conn.execute(insert(S.render_inputs).values(project_id=p, id=new_id(), render_id=row_id,
                    media_id=source["media_id"], binding_decision_id=source["binding_decision_id"], blob_id=source["blob_id"],
                    blob_sha256=source["blob_sha256"], role=source["role"]))
            for output in payload.get("outputs", []):
                self._media(conn, p, required(output, "media_id"))
                conn.execute(insert(S.render_outputs).values(project_id=p, id=new_id(), render_id=row_id,
                    media_id=output["media_id"], role=output.get("role", "delivery")))
            return {"id": row_id, "timeline_id": timeline["id"], "artifact_id": artifact["id"]}
        return self._mutate(project_id, "freeze_render", payload, callback=work, **kw)
