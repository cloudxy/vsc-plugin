"""Episode management on the original project transaction and object identity."""
from sqlalchemy import select, update, func

from vsc.assets.resource_service import ResourceError
from . import schema as S
from .values import checked_id, clean


class ProductionPlatformRepository:
    def propose_first_production(self, project_id, payload, *, build_preview, **kw):
        from vsc.assets.resource_service import Conflict
        def apply(conn, project):
            preview = build_preview(project_id, payload["request"])
            if preview["preview_sha256"] != payload["preview_sha256"]:
                raise Conflict("输入、候选序号或报价已改变，请重新预览", "production_preview_changed")
            return self._create_artifact(conn, project, preview["artifact"])
        return self._mutate(project_id, "propose_first_production", payload, callback=apply, **kw)

    def get_production_episodes(self, project_id, *, offset=0, limit=100):
        p = checked_id(project_id)
        with self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn:
            project = self._project(conn, p)
            from .project_management import management_project_guard, hidden_object_ids
            management_project_guard(conn, p)
            hidden = hidden_object_ids(conn, p)
            works = list(conn.execute(select(S.works.c.id, S.works.c.ordinal,
                S.creative_objects.c.title).join(S.creative_objects,
                    (S.creative_objects.c.project_id == S.works.c.project_id) &
                    (S.creative_objects.c.id == S.works.c.id)).where(S.works.c.project_id == p)
                .order_by(S.works.c.ordinal, S.works.c.id)).mappings())
            total = conn.execute(select(func.count()).select_from(S.episodes)
                .where(S.episodes.c.project_id == p, S.episodes.c.id.not_in(hidden))).scalar_one()
            query = select(S.episodes.c.id, S.episodes.c.parent_id, S.episodes.c.ordinal,
                S.creative_objects.c.title, S.creative_objects.c.display_code).join(S.creative_objects,
                    (S.creative_objects.c.project_id == S.episodes.c.project_id) &
                    (S.creative_objects.c.id == S.episodes.c.id)).join(S.works,
                    (S.works.c.project_id == S.episodes.c.project_id) & (S.works.c.id == S.episodes.c.parent_id))
            rows = [dict(row) for row in conn.execute(query.where(S.episodes.c.project_id == p, S.episodes.c.id.not_in(hidden))
                .order_by(S.works.c.ordinal, S.episodes.c.ordinal, S.episodes.c.id).offset(offset).limit(limit)).mappings()]
            for row in rows:
                scope = self._descendant_ids(conn, p, row["id"])
                row["scene_count"] = conn.execute(select(func.count()).select_from(S.scenes)
                    .where(S.scenes.c.project_id == p, S.scenes.c.id.in_(scope))).scalar_one()
                row["shot_count"] = conn.execute(select(func.count()).select_from(S.shots)
                    .where(S.shots.c.project_id == p, S.shots.c.id.in_(scope))).scalar_one()
            return clean(dict(project_id=p, revision=project["revision"], works=works,
                items=rows, total=total, offset=offset, limit=limit,
                next_offset=offset + len(rows) if offset + len(rows) < total else None))

    def create_episode_batch(self, project_id, payload, **kw):
        def apply(conn, project):
            p = project["id"]
            parent = payload.get("parent_id")
            if parent:
                parent = self._one(conn, S.works, p, checked_id(parent))["id"]
            else:
                works = list(conn.execute(select(S.works.c.id).where(S.works.c.project_id == p)).scalars())
                if len(works) > 1:
                    raise ResourceError("项目包含多部，请先选择所属部", "work_required")
                parent = works[0] if works else self._create_object(conn, project,
                    dict(kind="work", display_code="WORK", title=project["name"], ordinal=0))["id"]
            start = conn.execute(select(func.max(S.episodes.c.ordinal)).where(
                S.episodes.c.project_id == p, S.episodes.c.parent_id == parent)).scalar_one()
            ordinal = (start if start is not None else -1) + 1
            codes = set(conn.execute(select(S.creative_objects.c.display_code)
                .where(S.creative_objects.c.project_id == p)).scalars())
            number, rows = 1, []
            for title in payload["titles"]:
                while "EP%03d" % number in codes:
                    number += 1
                code = "EP%03d" % number
                codes.add(code)
                rows.append(self._create_object(conn, project, dict(kind="episode",
                    parent_id=parent, display_code=code, title=title.strip(), ordinal=ordinal)))
                ordinal += 1
            return dict(items=rows, parent_id=parent)
        return self._mutate(project_id, "create_episode_batch", payload, callback=apply, **kw)

    def reorder_episodes(self, project_id, payload, **kw):
        def apply(conn, project):
            p, parent = project["id"], checked_id(payload["parent_id"])
            self._one(conn, S.works, p, parent)
            actual = set(conn.execute(select(S.episodes.c.id).where(
                S.episodes.c.project_id == p, S.episodes.c.parent_id == parent)).scalars())
            ids = [checked_id(value) for value in payload["episode_ids"]]
            if set(ids) != actual or len(ids) != len(actual):
                raise ResourceError("排序须包含同一部的全部集，不能移动集的所属或省略新增集", "episode_order_scope")
            maximum = conn.execute(select(func.max(S.episodes.c.ordinal)).where(
                S.episodes.c.project_id == p, S.episodes.c.parent_id == parent)).scalar_one()
            # The existing unique constraint is immediate. Move every sibling to
            # a disjoint range before filling target ordinals, including sparse old orders.
            temporary = max(maximum + 1, len(ids))
            for position, identifier in enumerate(ids):
                conn.execute(update(S.episodes).where(S.episodes.c.project_id == p,
                    S.episodes.c.id == identifier).values(ordinal=temporary + position))
            for ordinal, identifier in enumerate(ids):
                conn.execute(update(S.episodes).where(S.episodes.c.project_id == p,
                    S.episodes.c.id == identifier).values(ordinal=ordinal))
            return dict(parent_id=parent, episode_ids=ids)
        return self._mutate(project_id, "reorder_episodes", payload, callback=apply, **kw)
