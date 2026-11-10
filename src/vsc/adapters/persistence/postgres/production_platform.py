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
                scope = self._descendant_ids(conn, p, row["id"]) - hidden
                row["scene_count"] = conn.execute(select(func.count()).select_from(S.scenes)
                    .where(S.scenes.c.project_id == p, S.scenes.c.id.in_(scope))).scalar_one()
                row["shot_count"] = conn.execute(select(func.count()).select_from(S.shots)
                    .where(S.shots.c.project_id == p, S.shots.c.id.in_(scope))).scalar_one()
            return clean(dict(project_id=p, revision=project["revision"], works=works,
                items=rows, total=total, offset=offset, limit=limit,
                next_offset=offset + len(rows) if offset + len(rows) < total else None))

    def _episode_editor_snapshot(self, conn, project, episode_id=None, parent_id=None):
        from .project_management import hidden_object_ids, management_object_guard, management_project_guard
        p=project['id'];management_project_guard(conn,p);hidden=hidden_object_ids(conn,p)
        works=[dict(row) for row in conn.execute(select(S.works.c.id,S.creative_objects.c.title)
            .join(S.creative_objects,(S.creative_objects.c.project_id==S.works.c.project_id)&(S.creative_objects.c.id==S.works.c.id))
            .where(S.works.c.project_id==p,S.works.c.id.not_in(hidden)).order_by(S.works.c.ordinal,S.works.c.id)).mappings()]
        episode=None
        if episode_id:
            management_object_guard(conn,p,episode_id)
            episode=self._one(conn,S.episodes,p,checked_id(episode_id));parent_id=episode['parent_id']
            episode['title']=self._one(conn,S.creative_objects,p,episode_id)['title']
            scope=self._descendant_ids(conn,p,episode_id)-hidden
            episode['shot_count']=conn.execute(select(func.count()).select_from(S.shots).where(
                S.shots.c.project_id==p,S.shots.c.id.in_(scope))).scalar_one()
        elif parent_id:
            self._one(conn,S.works,p,checked_id(parent_id));management_object_guard(conn,p,parent_id)
        elif len(works)==1:
            parent_id=works[0]['id']
        elif not works and conn.execute(select(S.works.c.id).where(S.works.c.project_id==p).limit(1)).first():
            raise ResourceError('请先恢复所属部，再创建剧集','object_recycled',409)
        siblings=list(conn.execute(select(S.episodes.c.id).where(S.episodes.c.project_id==p,
            S.episodes.c.parent_id==parent_id,S.episodes.c.id.not_in(hidden)).order_by(S.episodes.c.ordinal,S.episodes.c.id)).scalars()) if parent_id else []
        if episode:episode['position']=siblings.index(episode_id)+1
        return dict(project_id=p,revision=project['revision'],episode=episode,parent_id=parent_id,works=works,
            sibling_count=len(siblings),max_position=len(siblings)+(0 if episode else 1),needs_parent=not parent_id and len(works)>1)

    def get_episode_editor(self, project_id, episode_id=None, parent_id=None):
        with self.engine.connect().execution_options(isolation_level='REPEATABLE READ') as conn:
            project=self._project(conn,checked_id(project_id));self._access_require(conn,project['id'],'read')
            return clean(self._episode_editor_snapshot(conn,project,episode_id,parent_id))

    def get_episode_entry(self, project_id, episode_id, actor):
        from .project_management import management_object_guard, inactive_canvas_ids
        with self.engine.connect().execution_options(isolation_level='REPEATABLE READ') as conn:
            project=self._project(conn,checked_id(project_id));p=project['id'];self._access_require(conn,p,'read')
            self._one(conn,S.episodes,p,checked_id(episode_id));management_object_guard(conn,p,episode_id)
            episode=self._one(conn,S.creative_objects,p,episode_id)
            canvas=conn.execute(select(S.creative_canvases.c.id,S.creative_canvas_versions.c.title,
                S.creative_canvas_versions.c.created_at.label('updated_at')).join(S.creative_canvas_versions,
                    (S.creative_canvas_versions.c.project_id==S.creative_canvases.c.project_id)&
                    (S.creative_canvas_versions.c.id==S.creative_canvases.c.current_version_id)).where(
                        S.creative_canvases.c.project_id==p,S.creative_canvases.c.episode_id==episode_id,
                        S.creative_canvases.c.created_by==actor,S.creative_canvases.c.id.not_in(inactive_canvas_ids(p))).order_by(
                            S.creative_canvas_versions.c.created_at.desc(),S.creative_canvases.c.id.desc()).limit(1)).mappings().first()
            return clean(dict(project_id=p,episode_id=episode_id,title=episode['title'],revision=project['revision'],canvas=dict(canvas) if canvas else None))

    def save_episode(self, project_id, payload, **kw):
        def apply(conn, project):
            from .project_management import hidden_object_ids
            p=project['id'];episode_id=payload.get('episode_id')
            baseline=self._episode_editor_snapshot(conn,project,episode_id,payload.get('parent_id'))
            if baseline['needs_parent']:raise ResourceError('项目包含多部，请先选择所属部','work_required')
            position=payload.get('position')
            if position is not None and not 1<=position<=baseline['max_position']:
                raise ResourceError('排序位置不在当前所属部范围内','episode_order_scope')
            count=payload['shot_count'];episode=baseline['episode'];parent=baseline['parent_id']
            if episode:
                if count<episode['shot_count']:
                    raise ResourceError('减少分镜数需要明确选择要回收的镜头；当前编辑不会删除镜头','episode_shot_reduction')
                if count>episode['shot_count']:
                    self._append_episode_shots(conn,project,episode_id,count-episode['shot_count'],episode['shot_count'])
                conn.execute(update(S.creative_objects).where(S.creative_objects.c.project_id==p,
                    S.creative_objects.c.id==episode_id).values(title=payload['title'].strip()))
            else:
                created=self._create_episode_batch(conn,project,dict(titles=[payload['title']],parent_id=parent,initial_shot_count=count))
                episode_id=created['items'][0]['id'];parent=created['parent_id']
            hidden=hidden_object_ids(conn,p)
            if position is not None:
                original=list(conn.execute(select(S.episodes.c.id).where(S.episodes.c.project_id==p,
                    S.episodes.c.parent_id==parent).order_by(S.episodes.c.ordinal,S.episodes.c.id)).scalars())
                visible=[identifier for identifier in original if identifier not in hidden]
                visible.remove(episode_id);visible.insert(position-1,episode_id);ordered=iter(visible)
                self._set_episode_order(conn,p,parent,[identifier if identifier in hidden else next(ordered) for identifier in original])
            result=self._episode_editor_snapshot(conn,project,episode_id)
            all_ids=list(conn.execute(select(S.episodes.c.id).join(S.works,
                (S.works.c.project_id==S.episodes.c.project_id)&(S.works.c.id==S.episodes.c.parent_id)).where(
                    S.episodes.c.project_id==p,S.episodes.c.id.not_in(hidden)).order_by(S.works.c.ordinal,S.episodes.c.ordinal,S.episodes.c.id)).scalars())
            result.update(episode_id=episode_id,episode_index=all_ids.index(episode_id))
            return result
        return self._mutate(project_id,'save_episode',payload,callback=apply,**kw)

    def _append_episode_shots(self, conn, project, episode_id, count, previous_count):
        from .project_management import hidden_object_ids
        from .values import new_id
        p=project['id'];hidden=hidden_object_ids(conn,p)
        sequence=conn.execute(select(S.sequences.c.id).join(S.scenes,
            (S.scenes.c.project_id==S.sequences.c.project_id)&(S.scenes.c.id==S.sequences.c.parent_id)).where(
                S.sequences.c.project_id==p,S.scenes.c.parent_id==episode_id,S.sequences.c.id.not_in(hidden)).order_by(
                    S.scenes.c.ordinal.desc(),S.sequences.c.ordinal.desc(),S.sequences.c.id.desc()).limit(1)).scalar_one_or_none()
        if sequence is None:
            scene=conn.execute(select(S.scenes.c.id).where(S.scenes.c.project_id==p,S.scenes.c.parent_id==episode_id,
                S.scenes.c.id.not_in(hidden)).order_by(S.scenes.c.ordinal.desc(),S.scenes.c.id.desc()).limit(1)).scalar_one_or_none()
            if scene is None:
                ordinal=conn.execute(select(func.max(S.scenes.c.ordinal)).where(S.scenes.c.project_id==p,S.scenes.c.parent_id==episode_id)).scalar_one()
                scene=self._create_object(conn,project,dict(kind='scene',parent_id=episode_id,display_code='SC-'+new_id()[:8],
                    title='场景1',ordinal=(ordinal if ordinal is not None else -1)+1))['id']
            ordinal=conn.execute(select(func.max(S.sequences.c.ordinal)).where(S.sequences.c.project_id==p,S.sequences.c.parent_id==scene)).scalar_one()
            sequence=self._create_object(conn,project,dict(kind='sequence',parent_id=scene,display_code='SQ-'+new_id()[:8],
                title='镜组1',ordinal=(ordinal if ordinal is not None else -1)+1))['id']
        ordinal=conn.execute(select(func.max(S.shots.c.ordinal)).where(S.shots.c.project_id==p,S.shots.c.parent_id==sequence)).scalar_one()
        start=(ordinal if ordinal is not None else -1)+1
        for index in range(count):self._create_object(conn,project,dict(kind='shot',parent_id=sequence,
            display_code='SH-'+new_id()[:8],title='分镜'+str(previous_count+index+1),ordinal=start+index))

    def create_episode_batch(self, project_id, payload, **kw):
        return self._mutate(project_id, "create_episode_batch", payload,
            callback=lambda conn, project: self._create_episode_batch(conn, project, payload), **kw)

    def _create_episode_batch(self, conn, project, payload):
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
        siblings=list(conn.execute(select(S.episodes.c.id).where(S.episodes.c.project_id==p,S.episodes.c.parent_id==parent).order_by(S.episodes.c.ordinal,S.episodes.c.id)).scalars())
        anchor=payload.get('insert_before_id') or payload.get('insert_after_id')
        if anchor and anchor not in siblings:raise ResourceError('插入位置不属于所选部','episode_order_scope')
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
            episode=rows[-1]
            count=payload.get('initial_shot_count',0)
            if count:
                from .values import new_id
                scene=self._create_object(conn,project,dict(kind='scene',parent_id=episode['id'],display_code='SC-'+new_id()[:8],title='场景1',ordinal=0))
                sequence=self._create_object(conn,project,dict(kind='sequence',parent_id=scene['id'],display_code='SQ-'+new_id()[:8],title='镜组1',ordinal=0))
                for index in range(count):self._create_object(conn,project,dict(kind='shot',parent_id=sequence['id'],display_code='SH-'+new_id()[:8],title='分镜'+str(index+1),ordinal=index))
            ordinal += 1
        if anchor:
            position=siblings.index(anchor)+(1 if payload.get('insert_after_id') else 0)
            self._set_episode_order(conn,p,parent,siblings[:position]+[r['id'] for r in rows]+siblings[position:])
        return dict(items=rows, parent_id=parent)

    def reorder_episodes(self, project_id, payload, **kw):
        def apply(conn, project):
            p=project['id']
            if 'episode_id' in payload:
                episode=self._one(conn,S.episodes,p,checked_id(payload['episode_id']));parent=episode['parent_id']
                ids=list(conn.execute(select(S.episodes.c.id).where(S.episodes.c.project_id==p,S.episodes.c.parent_id==parent).order_by(S.episodes.c.ordinal,S.episodes.c.id)).scalars())
                index=ids.index(episode['id']);target=index+(-1 if payload['direction']=='up' else 1)
                if 0<=target<len(ids):ids[index],ids[target]=ids[target],ids[index]
                self._set_episode_order(conn,p,parent,ids)
                return dict(parent_id=parent,episode_ids=ids)
            parent=checked_id(payload['parent_id'])
            self._one(conn, S.works, p, parent)
            actual = set(conn.execute(select(S.episodes.c.id).where(
                S.episodes.c.project_id == p, S.episodes.c.parent_id == parent)).scalars())
            ids = [checked_id(value) for value in payload["episode_ids"]]
            if set(ids) != actual or len(ids) != len(actual):
                raise ResourceError("排序须包含同一部的全部集，不能移动集的所属或省略新增集", "episode_order_scope")
            self._set_episode_order(conn,p,parent,ids)
            return dict(parent_id=parent, episode_ids=ids)
        return self._mutate(project_id, "reorder_episodes", payload, callback=apply, **kw)

    def _set_episode_order(self,conn,p,parent,ids):
        maximum=conn.execute(select(func.max(S.episodes.c.ordinal)).where(S.episodes.c.project_id==p,S.episodes.c.parent_id==parent)).scalar_one()
        temporary=max((maximum or 0)+1,len(ids))
        for index,identifier in enumerate(ids):conn.execute(update(S.episodes).where(S.episodes.c.project_id==p,S.episodes.c.id==identifier).values(ordinal=temporary+index))
        for index,identifier in enumerate(ids):conn.execute(update(S.episodes).where(S.episodes.c.project_id==p,S.episodes.c.id==identifier).values(ordinal=index))
