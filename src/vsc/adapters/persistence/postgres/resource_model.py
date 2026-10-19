"""Typed resource projections and browse queries over immutable VSC facts.

The artifact transaction calls ``_project_resource_model`` once. No method edits
design/location/requirement projections; current satisfaction is derived from
the existing selection and rights authorities.
"""
import json
import uuid

from sqlalchemy import and_, exists, literal, or_, select, union_all
from sqlalchemy.dialects.postgresql import insert as pg_insert

from vsc.assets.resource_model import projection_content, projection_rows, projection_text
from vsc.assets.resource_service import ResourceError, required
from vsc.assets.taxonomy import CATEGORY_BY_CODE, KIND_CATEGORIES, category_descendants
from . import schema as S
from .values import checked_id, clean


class ResourceModelRepository:
    def _project_resource_model(self, conn, project, artifact_id, document, dependency_ids=()):
        """Append deterministic typed projections in the artifact transaction."""
        if not isinstance(document, dict):
            return
        fields = {"design_units", "scene_locations", "resource_requirements"}
        bible = document.get("format") == "vsc.asset-bible/v1"
        if not fields.intersection(document) and not bible:
            return
        p = project["id"]
        if document.get("project_id", p) != p:
            raise ResourceError("资源正文项目不一致", "document_project_mismatch")
        artifact = self._one(conn, S.artifact_versions, p, artifact_id)
        if json.loads(artifact["document"]) != document:
            raise ResourceError("资源投影必须来自固定产物正文", "projection_mismatch")
        deps = set(dependency_ids)
        mapping = self._projection_id_map(conn, p)
        if bible:
            from vsc.assets.taxonomy import BIBLE_KINDS
            for entity in projection_rows(document, "entities"):
                asset = mapping["asset"].get(entity.get("id"), entity.get("id"))
                identity = self._one(conn, S.asset_identities, p, checked_id(asset))
                if entity.get("kind") not in BIBLE_KINDS or identity["asset_kind"] != entity["kind"]:
                    raise ResourceError("资产圣经与登记身份种类不一致", "asset_kind_mismatch")
        declared = self._artifact_scopes(conn, p, artifact_id)
        allowed = set(declared)
        for identifier in declared:
            allowed.update(self._descendant_ids(conn, p, identifier))

        def identifier(group, key):
            return str(uuid.uuid5(uuid.UUID(artifact_id), "resource-model:" + group + ":" + str(key)))

        def scoped(value):
            if not artifact["project_wide"] and value not in allowed:
                raise ResourceError("资源关系超出产物范围", "resource_scope_mismatch")

        def ref(table, value, *, kind=None, optional=False):
            if value is None and optional:
                return None
            value = mapping.get(kind, {}).get(value, value) if kind else value
            row = self._one(conn, table, p, checked_id(value))
            owner = row.get("artifact_id") or row.get("script_version_id")
            if owner and owner != artifact_id and owner not in deps:
                raise ResourceError("资源引用须声明固定产物依赖: " + owner, "resource_dependency_missing")
            return row["id"]

        def scene_for(shot_id):
            shot = self._one(conn, S.shots, p, shot_id)
            return self._one(conn, S.sequences, p, shot["parent_id"])["parent_id"]

        def scope(row, *, optional=True):
            shot = ref(S.shots, row.get("shot_id"), kind="shot", optional=True)
            scene = ref(S.scenes, row.get("scene_id"), kind="scene", optional=optional)
            if shot:
                actual = scene_for(shot)
                if scene and actual != scene:
                    raise ResourceError("资源场镜归属不一致", "resource_scene_mismatch")
                scene = actual
            if scene:
                scoped(shot or scene)
            return scene, shot

        def fixed_spec(row, asset):
            spec = ref(S.asset_spec_versions, row.get("spec_version_id"), optional=True)
            if spec and (not asset or self._one(conn, S.asset_spec_versions, p, spec)["asset_id"] != asset):
                raise ResourceError("资源身份与固定规格不一致", "resource_spec_mismatch")
            return spec

        def add(table, key, **values):
            row = dict(values, project_id=p, id=identifier(table.name, key))
            conn.execute(pg_insert(table).values(**row).on_conflict_do_nothing(index_elements=["project_id", "id"]))
            return row["id"]

        def line_refs(table, parent_field, parent_id, lines, scene=None):
            if not isinstance(lines, list):
                raise ResourceError("line_ids必须为固定剧本行ID数组", "invalid_resource_projection")
            for line in dict.fromkeys(lines):
                line_id = ref(S.script_lines, line)
                if scene and self._one(conn, S.script_lines, p, line_id)["scene_id"] != scene:
                    raise ResourceError("资源引用的剧本行不属于该场", "resource_scene_mismatch")
                conn.execute(pg_insert(table).values(project_id=p, **{parent_field: parent_id}, line_id=line_id).on_conflict_do_nothing())

        design_keys = set()
        for order, item in enumerate(projection_rows(document, "design_units")):
            key = projection_text(item, "design_key")
            if key in design_keys:
                raise ResourceError("设计design_key不得重复", "duplicate_design_key")
            design_keys.add(key)
            scene = ref(S.scenes, item.get("scene_id"), kind="scene", optional=True)
            if scene:
                scoped(scene)
            content = projection_content(item, {"design_key", "scene_id", "shots", "panels", "line_ids"})
            if "duration_ms" in content and (type(content["duration_ms"]) is not int or content["duration_ms"] <= 0):
                raise ResourceError("设计duration_ms必须为正整数", "invalid_resource_projection")
            unit = add(S.shot_design_units, key, artifact_id=artifact_id, source_sha256=artifact["sha256"],
                scene_id=scene, design_key=key, ordinal=order, content=content)
            shots = item.get("shots", [])
            if not isinstance(shots, list):
                raise ResourceError("设计shots必须为对象数组", "invalid_resource_projection")
            for n, target in enumerate(shots):
                if not isinstance(target, dict):
                    raise ResourceError("设计镜头映射须含shot_id、purpose、role", "invalid_resource_projection")
                shot = ref(S.shots, required(target, "shot_id"), kind="shot")
                shot_scene = scene_for(shot)
                scoped(shot)
                if scene and scene != shot_scene:
                    raise ResourceError("设计单元与映射镜头不在同场", "resource_scene_mismatch")
                add(S.shot_design_shots, key + ":" + str(n), artifact_id=artifact_id, design_unit_id=unit,
                    shot_id=shot, scene_id=shot_scene, purpose=target.get("purpose", "*"),
                    role=target.get("role", "primary"), ordinal=n)
            panel_keys = set()
            for n, panel in enumerate(projection_rows(item, "panels")):
                panel_key = projection_text(panel, "panel_key")
                if panel_key in panel_keys:
                    raise ResourceError("面板panel_key不得重复", "duplicate_panel_key")
                panel_keys.add(panel_key)
                media = ref(S.media_items, panel.get("media_id"), optional=True)
                if media and self._one(conn, S.media_items, p, media)["modality"] != "image":
                    raise ResourceError("分镜面板须引用图片媒体", "invalid_design_panel")
                add(S.shot_design_panels, key + ":" + panel_key, design_unit_id=unit, panel_key=panel_key,
                    media_id=media, ordinal=n, content=projection_content(panel, {"panel_key", "media_id"}))
            line_refs(S.shot_design_line_refs, "design_unit_id", unit, item.get("line_ids", []), scene)

        for n, item in enumerate(projection_rows(document, "scene_locations")):
            scene, shot = scope(item, optional=False)
            location = ref(S.asset_identities, required(item, "location_id"), kind="asset")
            if self._one(conn, S.asset_identities, p, location)["asset_kind"] != "location":
                raise ResourceError("场景地点须引用location身份", "invalid_location_kind")
            add(S.scene_location_refs, str(n), artifact_id=artifact_id, source_sha256=artifact["sha256"],
                scene_id=scene, shot_id=shot, location_id=location, spec_version_id=fixed_spec(item, location),
                role=item.get("role", "primary"), ordinal=item.get("ordinal", n))

        requirement_keys = set()
        for item in projection_rows(document, "resource_requirements"):
            key = projection_text(item, "requirement_key")
            if key in requirement_keys:
                raise ResourceError("需求requirement_key不得重复", "duplicate_requirement_key")
            requirement_keys.add(key)
            category = projection_text(item, "category_code")
            if category not in CATEGORY_BY_CODE:
                raise ResourceError("未知资源分类", "unknown_category")
            scene, shot = scope(item)
            asset = ref(S.asset_identities, item.get("asset_id"), kind="asset", optional=True)
            instance = ref(S.asset_use_instances, item.get("instance_id"), optional=True)
            if instance:
                use = self._one(conn, S.asset_use_instances, p, instance)
                if asset and asset != use["asset_id"] or scene and use["scene_id"] != scene or shot and use["shot_id"] not in {None, shot}:
                    raise ResourceError("需求实例与身份或场镜范围不符", "resource_instance_mismatch")
                asset = asset or use["asset_id"]
            req = add(S.asset_requirements, key, artifact_id=artifact_id, source_sha256=artifact["sha256"],
                requirement_key=key, category_code=category, purpose=projection_text(item, "purpose"),
                description=projection_text(item, "description"), scene_id=scene, shot_id=shot, asset_id=asset,
                spec_version_id=fixed_spec(item, asset), instance_id=instance)
            line_refs(S.requirement_line_refs, "requirement_id", req, item.get("line_ids", []), scene)
            for slot_ref in projection_rows(item, "slots"):
                slot_id = ref(S.binding_slots, required(slot_ref, "slot_id"))
                slot = self._one(conn, S.binding_slots, p, slot_id)
                valid_targets = {asset, shot, scene}
                if not any(valid_targets) or slot["target_object_id"] not in valid_targets:
                    raise ResourceError("需求槽位不属于该资源或场镜", "resource_slot_mismatch")
                if asset and slot["identity_asset_id"] and slot["identity_asset_id"] != asset:
                    raise ResourceError("需求与槽位身份不一致", "resource_slot_mismatch")
                conn.execute(pg_insert(S.requirement_slots).values(project_id=p, requirement_id=req,
                    slot_id=slot_id, role=slot_ref.get("role", "fulfills")).on_conflict_do_nothing())

    def get_resource_taxonomy(self, project_id):
        with self.engine.connect() as conn:
            project = self._project(conn, checked_id(project_id))
            rows = [dict(row) for row in conn.execute(select(S.asset_categories)
                .order_by(S.asset_categories.c.parent_code.nullsfirst(), S.asset_categories.c.ordinal)).mappings()]
            return {"project_id": project["id"], "revision": project["revision"], "categories": rows,
                "identity_kinds": list(KIND_CATEGORIES), "execution_authority": "provider_models"}

    def classify_resource(self, project_id, payload, **kw):
        targets = {"identity": (S.asset_identities, S.identity_category_links, "asset_id"),
            "media": (S.media_items, S.media_category_links, "media_id"),
            "artifact": (S.artifact_versions, S.artifact_category_links, "artifact_id")}
        def work(conn, project):
            target_type = required(payload, "target_type")
            if target_type not in targets:
                raise ResourceError("未知分类对象类型", "invalid_category_target")
            category = projection_text(payload, "category_code")
            if category not in CATEGORY_BY_CODE:
                raise ResourceError("未知资源分类", "unknown_category")
            target, links, field = targets[target_type]
            target_id = self._one(conn, target, project["id"], checked_id(required(payload, "target_id")))["id"]
            conn.execute(pg_insert(links).values(project_id=project["id"], **{field: target_id},
                category_code=category, registered_by=kw.get("actor") or "").on_conflict_do_nothing())
            return {"target_type": target_type, "target_id": target_id, "category_code": category}
        return self._mutate(project_id, "classify_resource", payload, callback=work, **kw)

    def _resource_object_scope(self, conn, p, object_id):
        if not object_id:
            return None
        identifier = self._one(conn, S.creative_objects, p, checked_id(object_id))["id"]
        return sorted({identifier, *self._descendant_ids(conn, p, identifier)})

    def browse_resources(self, project_id, category=None, target_type=None, query="", limit=100, offset=0, object_id=None):
        if type(limit) is not int or not 1 <= limit <= 200 or type(offset) is not int or offset < 0:
            raise ResourceError("分页要求offset>=0，1<=limit<=200", "invalid_page")
        if target_type not in {None, "identity", "media", "artifact"}:
            raise ResourceError("未知资源对象类型", "invalid_category_target")
        if not isinstance(query, str) or len(query) > 500:
            raise ResourceError("检索词须为不超过500字的文本", "invalid_query")
        try:
            codes = category_descendants(category) if category else None
        except ValueError as error:
            raise ResourceError(str(error), "unknown_category")
        p = checked_id(project_id)
        with self.engine.connect() as conn:
            project = self._project(conn, p)
            object_ids = self._resource_object_scope(conn, p, object_id)
            branches = []
            specs = (
                ("identity", S.asset_identities, S.identity_category_links, "asset_id", S.creative_objects.c.title,
                 S.asset_identities.c.asset_kind, literal(None), S.asset_identities.join(S.creative_objects,
                    and_(S.asset_identities.c.project_id == S.creative_objects.c.project_id, S.asset_identities.c.id == S.creative_objects.c.id))),
                ("media", S.media_items, S.media_category_links, "media_id", S.media_items.c.name,
                 S.media_items.c.modality, S.media_blobs.c.sha256, S.media_items.join(S.media_blobs, S.media_items.c.blob_id == S.media_blobs.c.id)),
                ("artifact", S.artifact_versions, S.artifact_category_links, "artifact_id", S.artifact_versions.c.artifact_key,
                 S.artifact_versions.c.artifact_type, S.artifact_versions.c.sha256, S.artifact_versions),
            )
            for typ, table, links, field, title, kind, sha, source in specs:
                if target_type and typ != target_type:
                    continue
                statement = select(literal(typ).label("target_type"), table.c.id.label("target_id"),
                    title.label("title"), kind.label("kind"), sha.label("sha256")).select_from(source).where(table.c.project_id == p)
                if object_ids is not None:
                    scoped_slots = select(S.binding_slots.c.id).where(S.binding_slots.c.project_id == p,
                        S.binding_slots.c.target_object_id.in_(object_ids))
                    if typ == "identity":
                        used = select(S.asset_use_instances.c.asset_id).where(S.asset_use_instances.c.project_id == p,
                            or_(S.asset_use_instances.c.scene_id.in_(object_ids), S.asset_use_instances.c.shot_id.in_(object_ids)))
                        locations = select(S.scene_location_refs.c.location_id).where(S.scene_location_refs.c.project_id == p,
                            or_(S.scene_location_refs.c.scene_id.in_(object_ids), S.scene_location_refs.c.shot_id.in_(object_ids)))
                        requirements = select(S.asset_requirements.c.asset_id).where(S.asset_requirements.c.project_id == p,
                            or_(S.asset_requirements.c.scene_id.in_(object_ids), S.asset_requirements.c.shot_id.in_(object_ids)))
                        bound = select(S.binding_slots.c.identity_asset_id).where(S.binding_slots.c.project_id == p,
                            S.binding_slots.c.target_object_id.in_(object_ids))
                        state_assets = select(S.state_entity_refs.c.asset_id).join(S.state_versions,
                            and_(S.state_entity_refs.c.project_id == S.state_versions.c.project_id,
                                S.state_entity_refs.c.state_id == S.state_versions.c.id)).where(S.state_versions.c.project_id == p,
                                    or_(S.state_versions.c.scene_id.in_(object_ids), S.state_versions.c.shot_id.in_(object_ids)))
                        statement = statement.where(or_(table.c.id.in_(object_ids), table.c.id.in_(used), table.c.id.in_(locations),
                            table.c.id.in_(requirements), table.c.id.in_(bound), table.c.id.in_(state_assets)))
                    elif typ == "media":
                        candidates = select(S.binding_candidates.c.media_id).where(S.binding_candidates.c.project_id == p,
                            S.binding_candidates.c.slot_id.in_(scoped_slots))
                        output_jobs = select(S.generation_jobs.c.id).where(S.generation_jobs.c.project_id == p,
                            or_(S.generation_jobs.c.shot_id.in_(object_ids), S.generation_jobs.c.asset_id.in_(object_ids)))
                        outputs = select(S.job_outputs.c.media_id).where(S.job_outputs.c.project_id == p,
                            S.job_outputs.c.job_id.in_(output_jobs))
                        designs = select(S.shot_design_shots.c.design_unit_id).where(S.shot_design_shots.c.project_id == p,
                            S.shot_design_shots.c.shot_id.in_(object_ids))
                        panels = select(S.shot_design_panels.c.media_id).where(S.shot_design_panels.c.project_id == p,
                            S.shot_design_panels.c.design_unit_id.in_(designs))
                        timeline = select(S.timeline_item_media.c.media_id).join(S.timeline_items,
                            and_(S.timeline_item_media.c.project_id == S.timeline_items.c.project_id,
                                S.timeline_item_media.c.item_id == S.timeline_items.c.id)).where(
                                    S.timeline_items.c.project_id == p, S.timeline_items.c.shot_id.in_(object_ids))
                        statement = statement.where(or_(table.c.id.in_(candidates), table.c.id.in_(outputs),
                            table.c.id.in_(panels), table.c.id.in_(timeline)))
                    else:
                        scopes = select(S.artifact_object_scopes.c.artifact_id).where(S.artifact_object_scopes.c.project_id == p,
                            S.artifact_object_scopes.c.object_id.in_(object_ids))
                        statement = statement.where(or_(table.c.project_wide.is_(True), table.c.id.in_(scopes)))
                if query:
                    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                    statement = statement.where(title.ilike("%" + escaped + "%", escape="\\"))
                if codes:
                    classified = exists(select(1).where(links.c.project_id == p, links.c[field] == table.c.id,
                        links.c.category_code.in_(codes)))
                    if typ == "identity":
                        implicit = [key for key, values in KIND_CATEGORIES.items() if any(value in codes for value in values)]
                        classified = or_(classified, table.c.asset_kind.in_(implicit))
                    statement = statement.where(classified)
                branches.append(statement)
            combined = union_all(*branches).subquery()
            from sqlalchemy import func
            total = conn.execute(select(func.count()).select_from(combined)).scalar_one()
            rows = [dict(row) for row in conn.execute(select(combined).order_by(combined.c.target_type,
                combined.c.title, combined.c.target_id).offset(offset).limit(limit)).mappings()]
            for typ, _, links, field, *_ in specs:
                found = {row["target_id"]: row for row in rows if row["target_type"] == typ}
                for row in found.values():
                    row["category_codes"] = list(KIND_CATEGORIES[row["kind"]]) if typ == "identity" else []
                    row["capabilities"] = ["registered"]
                    if typ == "artifact":
                        row["capabilities"].append("read")
                    elif typ == "media" and row["kind"] in {"image", "video", "audio", "text", "document"}:
                        row["capabilities"].append("preview")
                    row["execution_available"] = False
                if found:
                    for link in conn.execute(select(links).where(links.c.project_id == p, links.c[field].in_(list(found)))).mappings():
                        values = found[link[field]]["category_codes"]
                        if link["category_code"] not in values:
                            values.append(link["category_code"])
                for row in found.values():
                    row["category_codes"].sort()
            return clean({"project_id": p, "revision": project["revision"], "items": rows, "total": total,
                "offset": offset, "limit": limit, "next_offset": offset + len(rows) if offset + len(rows) < total else None})

    def _design_rows(self, conn, p, *, shot_id=None, artifact_ids=None, object_ids=None):
        statement = select(S.shot_design_units).where(S.shot_design_units.c.project_id == p)
        if artifact_ids is not None:
            statement = statement.where(S.shot_design_units.c.artifact_id.in_(artifact_ids))
        if shot_id:
            statement = statement.where(S.shot_design_units.c.id.in_(select(S.shot_design_shots.c.design_unit_id)
                .where(S.shot_design_shots.c.project_id == p, S.shot_design_shots.c.shot_id == shot_id)))
        if object_ids is not None:
            statement = statement.where(or_(S.shot_design_units.c.scene_id.in_(object_ids),
                S.shot_design_units.c.id.in_(select(S.shot_design_shots.c.design_unit_id).where(
                    S.shot_design_shots.c.project_id == p, S.shot_design_shots.c.shot_id.in_(object_ids)))))
        rows = [dict(row) for row in conn.execute(statement.order_by(S.shot_design_units.c.artifact_id, S.shot_design_units.c.ordinal)).mappings()]
        for row in rows:
            row["shots"] = [dict(item) for item in conn.execute(select(S.shot_design_shots).where(
                S.shot_design_shots.c.project_id == p, S.shot_design_shots.c.design_unit_id == row["id"])
                .order_by(S.shot_design_shots.c.ordinal)).mappings()]
            row["panels"] = [dict(item) for item in conn.execute(select(S.shot_design_panels).where(
                S.shot_design_panels.c.project_id == p, S.shot_design_panels.c.design_unit_id == row["id"])
                .order_by(S.shot_design_panels.c.ordinal)).mappings()]
            row["line_ids"] = list(conn.execute(select(S.shot_design_line_refs.c.line_id).where(
                S.shot_design_line_refs.c.project_id == p, S.shot_design_line_refs.c.design_unit_id == row["id"])).scalars())
        return rows

    def get_shot_designs(self, project_id, shot_id=None, artifact_id=None, object_id=None):
        p = checked_id(project_id)
        with self.engine.connect() as conn:
            project = self._project(conn, p)
            if shot_id:
                shot_id = self._one(conn, S.shots, p, checked_id(shot_id))["id"]
            if artifact_id:
                artifact_id = self._one(conn, S.artifact_versions, p, checked_id(artifact_id))["id"]
            rows = self._design_rows(conn, p, shot_id=shot_id, artifact_ids=[artifact_id] if artifact_id else None,
                object_ids=self._resource_object_scope(conn, p, object_id))
            for row in rows:
                row["artifact"] = self._artifact_state(conn, p, row["artifact_id"])
                linked_shots = [item["shot_id"] for item in row["shots"]]
                jobs = select(S.generation_jobs.c.id, S.generation_jobs.c.shot_id, S.generation_jobs.c.purpose,
                    S.generation_jobs.c.modality, S.generation_jobs.c.candidate_no, S.generation_jobs.c.attempt,
                    S.generation_jobs.c.status).where(S.generation_jobs.c.project_id == p,
                    S.generation_jobs.c.shot_id.in_(linked_shots), S.generation_jobs.c.id.in_(
                        select(S.job_input_versions.c.job_id).where(S.job_input_versions.c.project_id == p,
                            S.job_input_versions.c.artifact_id == row["artifact_id"])))
                row["jobs"] = [dict(item) for item in conn.execute(jobs.order_by(S.generation_jobs.c.created_at)).mappings()]
                for job in row["jobs"]:
                    job["outputs"] = [dict(item) for item in conn.execute(select(S.job_outputs.c.media_id,
                        S.job_outputs.c.asset_type).where(S.job_outputs.c.project_id == p,
                            S.job_outputs.c.job_id == job["id"])).mappings()]
            return clean({"project_id": p, "revision": project["revision"], "units": rows})

    def _requirement_rows(self, conn, p, *, artifact_ids=None, scene_id=None, shot_id=None, object_ids=None):
        statement = select(S.asset_requirements).where(S.asset_requirements.c.project_id == p)
        if artifact_ids is not None:
            statement = statement.where(S.asset_requirements.c.artifact_id.in_(artifact_ids))
        if scene_id:
            statement = statement.where(S.asset_requirements.c.scene_id == scene_id)
        if shot_id:
            statement = statement.where(or_(S.asset_requirements.c.shot_id == shot_id,
                S.asset_requirements.c.shot_id.is_(None)))
        if object_ids is not None:
            statement = statement.where(or_(S.asset_requirements.c.scene_id.in_(object_ids),
                S.asset_requirements.c.shot_id.in_(object_ids), S.asset_requirements.c.asset_id.in_(object_ids)))
        rows = [dict(row) for row in conn.execute(statement.order_by(S.asset_requirements.c.artifact_id,
            S.asset_requirements.c.requirement_key)).mappings()]
        for row in rows:
            row["line_ids"] = list(conn.execute(select(S.requirement_line_refs.c.line_id).where(
                S.requirement_line_refs.c.project_id == p, S.requirement_line_refs.c.requirement_id == row["id"])).scalars())
            row["slots"] = []
            for link in conn.execute(select(S.requirement_slots).where(S.requirement_slots.c.project_id == p,
                    S.requirement_slots.c.requirement_id == row["id"])).mappings():
                slot = self._one(conn, S.binding_slots, p, link["slot_id"])
                current = conn.execute(select(S.current_bindings).where(S.current_bindings.c.project_id == p,
                    S.current_bindings.c.slot_id == slot["id"])).mappings().first()
                selected, reasons = None, ["binding_missing"]
                if current:
                    candidate = self._one(conn, S.binding_candidates, p, current["candidate_id"])
                    _, reasons = self._usable(conn, p, candidate["media_id"], slot["role"])
                    if candidate["spec_version_id"] and not self._artifact_approved(conn, p, candidate["spec_version_id"]):
                        reasons.append("spec_unapproved")
                    selected = {"candidate_id": candidate["id"], "media_id": candidate["media_id"],
                        "binding_decision_id": current["decision_id"]}
                row["slots"].append({"slot_id": slot["id"], "role": link["role"], "purpose": slot["role"],
                    "selected": selected, "usable": not reasons, "reasons": reasons})
            fulfilling = [slot for slot in row["slots"] if slot["role"] in {"fulfills", "post"}]
            row["status"] = "satisfied" if fulfilling and all(slot["usable"] for slot in fulfilling) else "unmet"
        return rows

    def get_resource_requirements(self, project_id, artifact_id=None, scene_id=None, shot_id=None, object_id=None):
        p = checked_id(project_id)
        with self.engine.connect() as conn:
            project = self._project(conn, p)
            if artifact_id:
                artifact_id = self._one(conn, S.artifact_versions, p, checked_id(artifact_id))["id"]
            if shot_id:
                shot = self._one(conn, S.shots, p, checked_id(shot_id))
                actual = self._one(conn, S.sequences, p, shot["parent_id"])["parent_id"]
                if scene_id and checked_id(scene_id) != actual:
                    raise ResourceError("场镜范围不一致", "resource_scene_mismatch")
                scene_id = actual
            if scene_id:
                scene_id = self._one(conn, S.scenes, p, checked_id(scene_id))["id"]
            rows = self._requirement_rows(conn, p, artifact_ids=[artifact_id] if artifact_id else None,
                scene_id=scene_id, shot_id=shot_id, object_ids=self._resource_object_scope(conn, p, object_id))
            return clean({"project_id": p, "revision": project["revision"], "requirements": rows,
                "has_requirements": bool(rows), "unmet_count": sum(row["status"] == "unmet" for row in rows)})

    def _location_rows(self, conn, p, *, scene_id=None, shot_id=None, artifact_ids=None, object_ids=None):
        statement = select(S.scene_location_refs).where(S.scene_location_refs.c.project_id == p)
        if scene_id:
            statement = statement.where(S.scene_location_refs.c.scene_id == scene_id)
        if artifact_ids is not None:
            statement = statement.where(S.scene_location_refs.c.artifact_id.in_(artifact_ids))
        if shot_id:
            statement = statement.where(or_(S.scene_location_refs.c.shot_id == shot_id, S.scene_location_refs.c.shot_id.is_(None)))
        if object_ids is not None:
            statement = statement.where(or_(S.scene_location_refs.c.scene_id.in_(object_ids), S.scene_location_refs.c.shot_id.in_(object_ids)))
        rows = [dict(row) for row in conn.execute(statement.order_by(S.scene_location_refs.c.artifact_id,
            S.scene_location_refs.c.scene_id, S.scene_location_refs.c.ordinal)).mappings()]
        overrides = {row["artifact_id"] for row in rows if row["shot_id"] == shot_id and row["role"] == "primary"} if shot_id else set()
        for row in rows:
            row["effective"] = not (shot_id and row["shot_id"] is None and row["role"] == "primary" and row["artifact_id"] in overrides)
        return rows

    def get_scene_locations(self, project_id, scene_id=None, shot_id=None, object_id=None):
        p = checked_id(project_id)
        with self.engine.connect() as conn:
            project = self._project(conn, p)
            if shot_id:
                shot_id = self._one(conn, S.shots, p, checked_id(shot_id))["id"]
                actual = self._one(conn, S.sequences, p, self._one(conn, S.shots, p, shot_id)["parent_id"])["parent_id"]
                if scene_id and checked_id(scene_id) != actual:
                    raise ResourceError("场镜范围不一致", "resource_scene_mismatch")
                scene_id = actual
            if scene_id:
                scene_id = self._one(conn, S.scenes, p, checked_id(scene_id))["id"]
            return clean({"project_id": p, "revision": project["revision"],
                "locations": self._location_rows(conn, p, scene_id=scene_id, shot_id=shot_id,
                    object_ids=self._resource_object_scope(conn, p, object_id))})

    def get_asset_usage(self, project_id, asset_id):
        p, asset = checked_id(project_id), checked_id(asset_id)
        with self.engine.connect() as conn:
            project = self._project(conn, p)
            self._one(conn, S.asset_identities, p, asset)
            data = {"project_id": p, "revision": project["revision"], "asset_id": asset}
            for key, table, field in (("specifications", S.asset_spec_versions, "asset_id"),
                    ("instances", S.asset_use_instances, "asset_id"), ("locations", S.scene_location_refs, "location_id"),
                    ("requirements", S.asset_requirements, "asset_id"), ("state_references", S.state_entity_refs, "asset_id"),
                    ("fixed_artifacts", S.artifact_asset_spec_refs, "asset_id")):
                data[key] = [dict(row) for row in conn.execute(select(table).where(table.c.project_id == p,
                    table.c[field] == asset)).mappings()]
            data["slots"] = [dict(row) for row in conn.execute(select(S.binding_slots).where(S.binding_slots.c.project_id == p,
                or_(S.binding_slots.c.identity_asset_id == asset, S.binding_slots.c.target_object_id == asset))).mappings()]
            return clean(data)

    def _resource_context_asset_refs(self, conn, project, *, shot_id, scene_id, purpose, artifact_ids):
        """Typed input identities before the ordinary binding/spec compiler runs.

        The caller merges these IDs/specs with state-owned references, reporting
        conflicting fixed specs rather than choosing a newer version.
        """
        p = project["id"]
        refs = []
        if purpose not in {"tts", "dialogue_dry", "dialogue"}:
            for row in self._location_rows(conn, p, scene_id=scene_id, shot_id=shot_id, artifact_ids=artifact_ids):
                if row["effective"]:
                    refs.append({"asset_id": row["location_id"], "spec_version_id": row["spec_version_id"],
                        "source": "scene_location", "source_id": row["id"], "artifact_id": row["artifact_id"],
                        "role": row["role"], "shot_id": row["shot_id"]})
        rows = conn.execute(select(S.asset_requirements).where(S.asset_requirements.c.project_id == p,
            S.asset_requirements.c.artifact_id.in_(artifact_ids), S.asset_requirements.c.scene_id == scene_id,
            or_(S.asset_requirements.c.shot_id == shot_id, S.asset_requirements.c.shot_id.is_(None)),
            S.asset_requirements.c.purpose.in_(["*", purpose] if purpose else ["*"]))).mappings()
        from vsc.assets.resource_service import POST_ROLES
        for row in rows:
            if row["asset_id"] and row["purpose"] not in POST_ROLES:
                refs.append({"asset_id": row["asset_id"], "spec_version_id": row["spec_version_id"],
                    "source": "resource_requirement", "source_id": row["id"], "artifact_id": row["artifact_id"]})
        return refs

    def _resource_slot_instances(self, conn, p, *, artifact_ids, shot_id, scene_id):
        """Only typed requirement evidence may distinguish physical uses in slots."""
        statement = select(S.requirement_slots.c.slot_id, S.asset_requirements.c.instance_id).join(
            S.asset_requirements, and_(S.requirement_slots.c.project_id == S.asset_requirements.c.project_id,
                S.requirement_slots.c.requirement_id == S.asset_requirements.c.id)).where(
                    S.asset_requirements.c.project_id == p, S.asset_requirements.c.artifact_id.in_(artifact_ids),
                    S.asset_requirements.c.scene_id == scene_id, S.asset_requirements.c.instance_id.is_not(None),
                    or_(S.asset_requirements.c.shot_id == shot_id, S.asset_requirements.c.shot_id.is_(None)))
        result = {}
        for row in conn.execute(statement).mappings():
            result.setdefault(row["slot_id"], set()).add(row["instance_id"])
        return {key: tuple(sorted(values)) for key, values in result.items()}

    def _extend_resource_context(self, conn, project, context, *, artifacts, scene_id):
        """Compile only approved, applicable fixed design/location/requirement rows.

        Call after semantic_inputs exists and before context_digest. Submitted jobs
        still pin their artifact IDs/SHA via existing job_input_versions.
        """
        p, shot, purpose = project["id"], context["shot_id"], context.get("purpose")
        ids = [row["id"] for row in artifacts]
        for ref in self._resource_context_asset_refs(conn, project, shot_id=shot, scene_id=scene_id,
                purpose=purpose, artifact_ids=ids):
            pinned = ref["spec_version_id"] or conn.execute(select(S.artifact_asset_spec_refs.c.spec_version_id).where(
                S.artifact_asset_spec_refs.c.project_id == p, S.artifact_asset_spec_refs.c.artifact_id == ref["artifact_id"],
                S.artifact_asset_spec_refs.c.asset_id == ref["asset_id"])).scalar_one_or_none()
            if not pinned:
                context["gaps"].append({"code": "resource_spec_missing", "asset_id": ref["asset_id"], "source_id": ref["source_id"]})
        audio = purpose in {"tts", "dialogue_dry", "dialogue"}
        units = [] if audio else self._design_rows(conn, p, shot_id=shot, artifact_ids=ids)
        matching = []
        for unit in units:
            links = [link for link in unit["shots"] if link["shot_id"] == shot and link["purpose"] in {"*", purpose}]
            if any(link["role"] == "primary" for link in links):
                matching.append(unit)
        if len(matching) > 1:
            context["gaps"].append({"code": "shot_design_conflict", "design_unit_ids": [row["id"] for row in matching]})
        for unit in matching:
            for panel in unit["panels"]:
                if not panel["media_id"]:
                    continue
                media, reasons = self._usable(conn, p, panel["media_id"], "storyboard")
                if reasons:
                    context["gaps"].append({"code": "design_panel_unusable", "panel_id": panel["id"], "reasons": reasons})
                    continue
                if not any(row["media_id"] == media["id"] and row["role"] == "storyboard" for row in context["media"]):
                    context["media"].append({"media_id": media["id"], "blob_id": media["blob_id"], "sha256": media["sha256"],
                        "role": "storyboard", "slot_id": None, "candidate_id": None, "binding_decision_id": None,
                        "target_object_id": shot, "inherited": False, "locations": media["locations"]})
        locations = [] if audio else [row for row in self._location_rows(conn, p, scene_id=scene_id,
            shot_id=shot, artifact_ids=ids) if row["effective"]]
        primary_locations = {row["location_id"] for row in locations if row["role"] == "primary"}
        if len(primary_locations) > 1:
            context["gaps"].append({"code": "scene_location_conflict", "location_ids": sorted(primary_locations)})
        requirements = self._requirement_rows(conn, p, artifact_ids=ids, scene_id=scene_id, shot_id=shot)
        active_requirements = [row for row in requirements if row["purpose"] in {"*", purpose}]
        # Only actual generation-reference roles enter a production context. Post
        # and browse classification remain queryable without changing its SHA.
        from vsc.assets.resource_service import POST_ROLES
        active_requirements = [row for row in active_requirements if row["purpose"] not in POST_ROLES]
        for row in active_requirements:
            if row["status"] == "unmet":
                context["gaps"].append({"code": "resource_requirement_unmet", "requirement_id": row["id"]})
        context["shot_designs"] = matching
        context["scene_locations"] = locations
        context["resource_requirements"] = active_requirements
        extra = {"shot_designs": [{key: row[key] for key in ("id", "artifact_id", "source_sha256", "design_key", "content", "panels", "line_ids")}
                for row in matching], "scene_locations": locations,
            "resource_requirements": [{key: row[key] for key in ("id", "artifact_id", "source_sha256", "requirement_key",
                "category_code", "purpose", "description", "asset_id", "spec_version_id", "instance_id", "line_ids")} for row in active_requirements]}
        if matching or locations or active_requirements:
            # _semantic_inputs is a list so append one typed domain fragment.
            context["semantic_inputs"].append({"artifact_type": "vsc.resource_model", "content": extra})
        context["ready"] = not context["gaps"]
