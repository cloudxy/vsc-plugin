"""Transactional settings over the authoritative provider/model/route tables."""
import uuid
from contextlib import contextmanager
from sqlalchemy import insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from vsc.assets.resource_service import Conflict, NotFound, ResourceError
from . import schema as S
from .values import checked_id, clean


class ResourceSettingsRepository:
    def __init__(self, engine):
        self.engine = engine

    def _row(self, conn, model_id, lock=False, current=False):
        query = select(S.provider_models).where(S.provider_models.c.id == checked_id(model_id))
        if lock:
            query = query.with_for_update()
        model = conn.execute(query).mappings().first()
        if model is None:
            raise NotFound("资源配置不存在")
        if current and conn.execute(select(S.provider_configurations.c.provider_id).where(
                S.provider_configurations.c.previous_model_id == model_id)).first():
            raise Conflict("配置已更新，请刷新后使用新版本", "configuration_version_conflict")
        provider = conn.execute(select(S.providers).where(S.providers.c.id == model["provider_id"])).mappings().one()
        identity = conn.execute(select(S.provider_configurations).where(S.provider_configurations.c.provider_id == provider["id"])).mappings().first()
        if identity:
            fields = {key: identity[key] for key in ("supplier", "product", "plan", "region", "execution", "tool_id", "previous_model_id")}
        else:
            # Existing registry rows stay visible; only the original Ark identity is recognized.
            ark = provider["id"] == "volc_ark"
            fields = {"supplier": "volcengine" if ark else "unknown", "product": "ark" if ark else "unknown",
                      "plan": "agent-plan" if ark else "unknown", "region": "cn-beijing" if ark else "unknown",
                      "execution": "api", "tool_id": None, "previous_model_id": None}
        return clean(dict(fields, id=model["id"], provider_id=provider["id"], name=provider["name"],
            modality=model["modality"], model_key=model["model_key"], model_version=model["model_version"],
            capabilities=model["capabilities"], default_params=model["default_params"],
            base_url=provider["base_url"], auth_ref=provider["auth_ref"], enabled=bool(provider["enabled"] and model["enabled"])))

    def get(self, model_id):
        with self.engine.connect() as conn:
            return self._row(conn, model_id)

    def _defaults(self, conn):
        rows = conn.execute(select(S.provider_routes).where(S.provider_routes.c.enabled,
            S.provider_routes.c.preferred_model_id.is_not(None)).order_by(S.provider_routes.c.priority, S.provider_routes.c.id)).mappings()
        defaults = {}
        for row in rows:
            defaults.setdefault(row["purpose"], str(row["preferred_model_id"]))
        return defaults

    def list(self):
        with self.engine.connect() as conn:
            replaced = select(S.provider_configurations.c.previous_model_id).where(S.provider_configurations.c.previous_model_id.is_not(None))
            models = conn.execute(select(S.provider_models.c.id).where(S.provider_models.c.id.not_in(replaced)).order_by(S.provider_models.c.id)).scalars()
            rows = [self._row(conn, str(model)) for model in models]
            return rows, self._defaults(conn)

    def save(self, payload, actor):
        if not actor:
            raise ResourceError("配置写入需要真实操作人", "actor_required")
        provider_id, model_id = "config-" + uuid.uuid4().hex, str(uuid.uuid4())
        previous = payload.get("id")
        try:
            with self.engine.begin() as conn:
                if previous:
                    self._row(conn, previous, lock=True, current=True)
                conn.execute(insert(S.providers).values(id=provider_id, name=payload["name"], modality=payload["modality"],
                    base_url=payload["base_url"], auth_ref=payload["auth_ref"], enabled=payload["enabled"], rate_limit={}))
                conn.execute(insert(S.provider_models).values(id=model_id, provider_id=provider_id, model_key=payload["model_key"],
                    model_version=payload["model_version"], modality=payload["modality"], capabilities=payload["capabilities"],
                    default_params=payload["default_params"], cost_rule={}, enabled=payload["enabled"]))
                conn.execute(insert(S.provider_configurations).values(provider_id=provider_id, previous_model_id=previous, actor=actor,
                    **{key: payload.get(key) for key in ("supplier", "product", "plan", "region", "execution", "tool_id")}))
                if previous:
                    conn.execute(update(S.provider_models).where(S.provider_models.c.id == previous).values(enabled=False))
                    # An edited connection does not silently replace an explicit default choice.
                    conn.execute(update(S.provider_routes).where(S.provider_routes.c.preferred_model_id == previous).values(enabled=False))
                return self._row(conn, model_id)
        except IntegrityError as exc:
            raise Conflict("配置版本已改变或关联无效，请刷新后重试", "configuration_version_conflict") from exc

    def enabled(self, model_id, enabled):
        with self.engine.begin() as conn:
            row = self._row(conn, model_id, lock=True, current=True)
            if enabled:
                from vsc.production.resource_settings import adapter_available
                if not adapter_available(row) or not row["capabilities"].get("purposes"):
                    raise ResourceError("配置能力或执行路线不可用", "adapter_unavailable")
                provider = conn.execute(select(S.providers).where(S.providers.c.id == row["provider_id"]).with_for_update()).mappings().one()
                identity = conn.execute(select(S.provider_configurations.c.provider_id).where(
                    S.provider_configurations.c.provider_id == row["provider_id"])).first()
                if not provider["enabled"] and not identity:
                    raise ResourceError("旧供应商已全局停用；请编辑保存为独立配置再启用，避免同时启用其他模型", "shared_provider_disabled")
                conn.execute(update(S.providers).where(S.providers.c.id == row["provider_id"]).values(enabled=True))
            conn.execute(update(S.provider_models).where(S.provider_models.c.id == model_id).values(enabled=enabled))
            if not enabled:
                conn.execute(update(S.provider_routes).where(S.provider_routes.c.preferred_model_id == model_id).values(enabled=False))
            return self._row(conn, model_id)

    def bind_default(self, purpose, model_id):
        with self.engine.begin() as conn:
            row = self._row(conn, model_id, lock=True, current=True)
            if not row["enabled"] or purpose not in row["capabilities"].get("purposes", []):
                raise ResourceError("配置已停用或不支持该用途", "model_capability_mismatch")
            route_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "vsc:route:%s:%s:0" % (row["modality"], purpose)))
            values = dict(id=route_id, modality=row["modality"], purpose=purpose, priority=0, enabled=True,
                preferred_provider=row["provider_id"], preferred_model_id=model_id, preferred_model_version=row["model_version"], fallback_provider=None)
            conn.execute(pg_insert(S.provider_routes).values(**values).on_conflict_do_update(index_elements=[S.provider_routes.c.id],
                set_={key: value for key, value in values.items() if key != "id"}))
            return self._defaults(conn)

    def clear_default(self, purpose):
        with self.engine.begin() as conn:
            conn.execute(update(S.provider_routes).where(S.provider_routes.c.purpose == purpose,
                S.provider_routes.c.preferred_model_id.is_not(None)).values(enabled=False))
            return self._defaults(conn)

    @contextmanager
    def execution_guard(self):
        with self.engine.begin() as conn:
            conn.execute(text("SELECT pg_advisory_xact_lock(867530916)"))
            yield

    def active_jobs(self, tool_id=None):
        with self.engine.connect() as conn:
            # Until separate execution environments exist, conservatively block
            # switching tools for any created, running or unknown submission.
            return conn.execute(select(S.generation_jobs.c.id).where(
                S.generation_jobs.c.status.in_(["created", "submitted", "running", "submission_unknown"])).limit(1)).first() is not None
