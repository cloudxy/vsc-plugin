"""Readable project and episode asset operations over the original authorities."""
from vsc.assets.resource_service import ResourceError

KINDS = {'character', 'location', 'prop', 'voice', 'style', 'costume', 'object', 'creature', 'vehicle', 'plant'}
ORDER_BY_VALUES = {'name_asc', 'name_desc', 'updated_desc'}


class AssetCardsServiceMixin:
    def _asset_cards(self):
        from vsc.adapters.persistence.postgres.asset_cards import AssetCardsRepository
        return AssetCardsRepository(self.store)

    def list_asset_cards(
        self,
        p,
        query='',
        asset_kind='',
        offset=0,
        limit=24,
        actor=None,
        favorites=False,
        include_object=False,
        include_blocking=False,
        folder_id='',
        order_by='name_asc',
    ):
        if (
            not isinstance(query, str)
            or len(query) > 200
            or asset_kind and asset_kind not in KINDS and not (include_blocking and asset_kind == 'blocking')
            or type(offset) is not int
            or offset < 0
            or type(limit) is not int
            or not 1 <= limit <= 100
            or type(include_object) is not bool
            or include_object and asset_kind != 'prop'
            or type(include_blocking) is not bool
            or not isinstance(folder_id, str)
            or len(folder_id) > 64
            or order_by not in ORDER_BY_VALUES
        ):
            raise ResourceError('资产筛选或分页无效')
        if folder_id and folder_id != 'root':
            from vsc.adapters.persistence.postgres.values import checked_id
            checked_id(folder_id)
        return self._asset_cards().list_asset_cards(
            p,
            query,
            asset_kind,
            offset,
            limit,
            actor,
            favorites,
            include_object,
            include_blocking,
            folder_id=folder_id,
            order_by=order_by,
        )

    def get_asset_card(self, p, asset_id, actor=None):
        return self._asset_cards().get_asset_card(p, asset_id, actor)

    def asset_card_options(self, p):
        from sqlalchemy import select, and_
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.adapters.persistence.postgres.values import clean
        with self.store.engine.connect() as conn:
            voices = [
                dict(r)
                for r in conn.execute(
                    select(
                        S.voice_spec_versions.c.id,
                        S.creative_objects.c.title,
                        S.voice_spec_versions.c.reference_media_id,
                        S.voice_spec_versions.c.diction,
                    )
                    .join(
                        S.creative_objects,
                        and_(
                            S.creative_objects.c.project_id == p,
                            S.creative_objects.c.id == S.voice_spec_versions.c.voice_id,
                        ),
                    )
                    .where(S.voice_spec_versions.c.project_id == p)
                ).mappings()
            ]
            folders = [
                dict(r)
                for r in conn.execute(
                    select(S.management_folders.c.id, S.management_folders.c.title, S.management_folders.c.ordinal)
                    .where(S.management_folders.c.project_id == p, S.management_folders.c.parent_id.is_(None))
                    .order_by(S.management_folders.c.ordinal, S.management_folders.c.id)
                ).mappings()
            ]
        return clean(
            dict(
                voices=voices,
                folders=folders,
                media=self.list_resources(p, limit=200)['items'],
                nodes=self.get_project_tree(p)['nodes'],
                revision=self.get_project(p)['revision'],
            )
        )

    def save_asset_card(self, p, payload, **kw):
        self._validate_write(payload, **kw)
        allowed = {'asset_id', 'name', 'asset_kind', 'base_revision', 'forms', 'folder_id'}
        if not isinstance(payload, dict) or set(payload) - allowed or not {'name', 'asset_kind', 'base_revision', 'forms'} <= set(payload):
            raise ResourceError('资产卡需要名称、类型、版本与形态')
        if (
            payload['asset_kind'] not in KINDS
            or type(payload['base_revision']) is not int
            or payload['base_revision'] < 0
            or not isinstance(payload['name'], str)
            or not 1 <= len(payload['name'].strip()) <= 200
        ):
            raise ResourceError('资产名称、类型或版本无效')
        if payload.get('folder_id') is not None:
            if not isinstance(payload['folder_id'], str) or not payload['folder_id'].strip():
                raise ResourceError('所属文件夹标识无效')
            from vsc.adapters.persistence.postgres.values import checked_id
            checked_id(payload['folder_id'])
        if not isinstance(payload['forms'], list) or not 1 <= len(payload['forms']) <= 50:
            raise ResourceError('请填写1–50个形态')
        keys = set()
        form_allowed = {'form_key', 'name', 'base_version_id', 'description', 'media_id', 'voice_spec_id', 'voice_details'}
        for form in payload['forms']:
            if not isinstance(form, dict) or set(form) - form_allowed or not {'form_key', 'name', 'base_version_id'} <= set(form):
                raise ResourceError('形态字段无效')
            for key in ('form_key', 'name'):
                if not isinstance(form[key], str) or not 1 <= len(form[key].strip()) <= 200:
                    raise ResourceError('形态名称须为1–200字')
            if form['form_key'] in keys:
                raise ResourceError('形态键重复')
            keys.add(form['form_key'])
            if not isinstance(form.get('description', ''), str) or len(form.get('description', '')) > 20000:
                raise ResourceError('形态描述过长')
            if 'voice_details' in form and not isinstance(form['voice_details'], dict):
                raise ResourceError('声线详情格式无效')
        return self._asset_cards().save_asset_card(p, payload, **kw)

    def favorite_asset_card(self, p, payload, **kw):
        self._validate_write(payload, **kw)
        if set(payload) != {'asset_id', 'active'} or type(payload['active']) is not bool:
            raise ResourceError('收藏操作无效')
        return self._asset_cards().favorite_asset_card(p, payload, **kw)

    def reference_asset_card(self, p, payload, **kw):
        self._validate_write(payload, **kw)
        if (
            set(payload) != {'asset_id', 'asset_revision', 'episode_ids'}
            or type(payload['asset_revision']) is not int
            or not isinstance(payload['episode_ids'], list)
            or not 1 <= len(payload['episode_ids']) <= 50
            or len(set(payload['episode_ids'])) != len(payload['episode_ids'])
        ):
            raise ResourceError('请选择1–50个不同剧集和当前资产版本')
        return self._asset_cards().reference_asset_card(p, payload, **kw)

    def copy_asset_card(self, p, payload, **kw):
        self._validate_write(payload, **kw)
        if (
            set(payload) - {'source_project_id', 'source_asset_id', 'form_version_ids', 'name'}
            or not {'source_project_id', 'source_asset_id', 'form_version_ids'} <= set(payload)
            or payload['source_project_id'] == p
        ):
            raise ResourceError('复制需要不同项目及固定源资产')
        ids = payload['form_version_ids']
        if not isinstance(ids, list) or not 1 <= len(ids) <= 50 or len(set(ids)) != len(ids):
            raise ResourceError('请选择不同的固定资产形态')
        self.authorize_access(payload['source_project_id'], 'read')
        return self._asset_cards().copy_asset_card(p, payload, **kw)

    def create_asset_folder(self, p, payload, **kw):
        self._validate_write(payload, **kw)
        if not isinstance(payload, dict) or set(payload) - {'title', 'cover_media_id'} or 'title' not in payload:
            raise ResourceError('新建文件夹需要名称')
        title = payload.get('title')
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 50:
            raise ResourceError('文件夹名称需为1–50字')
        cover_media_id = payload.get('cover_media_id')
        if cover_media_id is not None:
            from vsc.adapters.persistence.postgres.values import checked_id
            checked_id(cover_media_id)
        return self._asset_cards().create_asset_folder(
            p, {'title': title.strip(), 'cover_media_id': cover_media_id}, **kw
        )

    def update_asset_folder(self, p, payload, **kw):
        self._validate_write(payload, **kw)
        if (
            not isinstance(payload, dict)
            or set(payload) - {'folder_id', 'title', 'cover_media_id'}
            or not {'folder_id', 'title'} <= set(payload)
        ):
            raise ResourceError('编辑文件夹需要文件夹标识与名称')
        from vsc.adapters.persistence.postgres.values import checked_id
        checked_id(payload['folder_id'])
        title = payload.get('title')
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 50:
            raise ResourceError('文件夹名称需为1–50字')
        next_payload = {'folder_id': payload['folder_id'], 'title': title.strip()}
        if 'cover_media_id' in payload:
            if payload['cover_media_id'] is not None:
                checked_id(payload['cover_media_id'])
            next_payload['cover_media_id'] = payload['cover_media_id']
        return self._asset_cards().update_asset_folder(p, next_payload, **kw)

    def delete_asset_folder(self, p, payload, **kw):
        self._validate_write(payload, **kw)
        if not isinstance(payload, dict) or set(payload) != {'folder_id'}:
            raise ResourceError('删除文件夹需要文件夹标识')
        from vsc.adapters.persistence.postgres.values import checked_id
        checked_id(payload['folder_id'])
        return self._asset_cards().delete_asset_folder(p, payload, **kw)

    def move_assets_to_folder(self, p, payload, **kw):
        self._validate_write(payload, **kw)
        if not isinstance(payload, dict) or set(payload) - {'asset_ids', 'folder_id', 'source_project_id'} or 'asset_ids' not in payload:
            raise ResourceError('移动资产需要资产列表与目标文件夹')
        if payload.get('source_project_id') and payload['source_project_id'] != p:
            raise ResourceError('跨项目不支持拖拽移动', 'cross_project_move')
        ids = payload['asset_ids']
        if not isinstance(ids, list) or not 1 <= len(ids) <= 100 or any(not isinstance(i, str) for i in ids):
            raise ResourceError('单次最多移动1–100个资产')
        from vsc.adapters.persistence.postgres.values import checked_id
        for aid in ids:
            checked_id(aid)
        folder_id = payload.get('folder_id')
        if folder_id is not None:
            if not isinstance(folder_id, str) or not folder_id.strip():
                raise ResourceError('目标文件夹标识无效')
            checked_id(folder_id)
        return self._asset_cards().move_assets_to_folder(
            p, {'asset_ids': list(dict.fromkeys(ids)), 'folder_id': folder_id}, **kw
        )

    def batch_recycle_assets(self, p, payload, **kw):
        self._validate_write(payload, **kw)
        if not isinstance(payload, dict) or set(payload) - {'asset_ids', 'reason'} or 'asset_ids' not in payload:
            raise ResourceError('批量回收需要资产列表')
        ids = payload['asset_ids']
        if not isinstance(ids, list) or not 1 <= len(ids) <= 100 or any(not isinstance(i, str) for i in ids):
            raise ResourceError('单次最多回收1–100个资产')
        reason = payload.get('reason') or '用户从项目资产工作台批量移入回收站'
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 2000:
            raise ResourceError('回收原因须为1–2000字')
        from vsc.adapters.persistence.postgres.values import checked_id
        for aid in ids:
            checked_id(aid)
        return self._asset_cards().batch_recycle_assets(
            p, {'asset_ids': list(dict.fromkeys(ids)), 'reason': reason.strip()}, **kw
        )

    def save_manifestation_voice(self, p, payload, **kw):
        self._validate_write(payload, **kw)
        if not isinstance(payload, dict):
            raise ResourceError('角色形态音色绑定参数无效')
        allowed = {
            'asset_id',
            'base_revision',
            'form_key',
            'manifestation_id',
            'manifestaion_id',
            'audio_media_id',
            'voice_spec_id',
            'voice_prompt',
            'clear',
        }
        if set(payload) - allowed or 'asset_id' not in payload or 'base_revision' not in payload:
            raise ResourceError('角色形态音色需要资产标识与基线版本')
        from vsc.adapters.persistence.postgres.values import checked_id
        checked_id(payload['asset_id'])
        if type(payload['base_revision']) is not int or payload['base_revision'] < 0:
            raise ResourceError('资产基线版本无效')
        form_ref = payload.get('form_key') or payload.get('manifestation_id') or payload.get('manifestaion_id')
        if not isinstance(form_ref, str) or not 1 <= len(form_ref.strip()) <= 200:
            raise ResourceError('请指定要绑定音色的角色形态')
        voice_prompt = payload.get('voice_prompt', '')
        if not isinstance(voice_prompt, str) or len(voice_prompt) > 200:
            raise ResourceError('音色提示词最多200字')
        clear = bool(payload.get('clear', False))
        audio_media_id = payload.get('audio_media_id')
        voice_spec_id = payload.get('voice_spec_id')
        if audio_media_id is not None:
            checked_id(audio_media_id)
        if voice_spec_id is not None:
            checked_id(voice_spec_id)
        return self._asset_cards().save_manifestation_voice(
            p,
            {
                'asset_id': payload['asset_id'],
                'base_revision': payload['base_revision'],
                'form_ref': form_ref.strip(),
                'audio_media_id': audio_media_id,
                'voice_spec_id': voice_spec_id,
                'voice_prompt': voice_prompt,
                'clear': clear,
            },
            **kw,
        )
