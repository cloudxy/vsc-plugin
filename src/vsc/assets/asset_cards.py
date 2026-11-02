"""Readable project and episode asset operations over the original authorities."""
from vsc.assets.resource_service import ResourceError
KINDS={'character','location','prop','voice','style','costume','object','creature','vehicle','plant'}
class AssetCardsServiceMixin:
    def _asset_cards(self):
        from vsc.adapters.persistence.postgres.asset_cards import AssetCardsRepository
        return AssetCardsRepository(self.store)
    def list_asset_cards(self,p,query='',asset_kind='',offset=0,limit=24,actor=None,favorites=False):
        if not isinstance(query,str) or len(query)>200 or asset_kind and asset_kind not in KINDS or type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=100:raise ResourceError('资产筛选或分页无效')
        return self._asset_cards().list_asset_cards(p,query,asset_kind,offset,limit,actor,favorites)
    def get_asset_card(self,p,asset_id,actor=None):return self._asset_cards().get_asset_card(p,asset_id,actor)
    def asset_card_options(self,p):
        from sqlalchemy import select,and_
        from vsc.adapters.persistence.postgres import schema as S
        with self.store.engine.connect() as conn:
            voices=[dict(r) for r in conn.execute(select(S.voice_spec_versions.c.id,S.creative_objects.c.title,S.voice_spec_versions.c.reference_media_id).join(S.creative_objects,and_(S.creative_objects.c.project_id==p,S.creative_objects.c.id==S.voice_spec_versions.c.voice_id)).where(S.voice_spec_versions.c.project_id==p)).mappings()]
        return dict(voices=voices,media=self.list_resources(p,limit=200)['items'],nodes=self.get_project_tree(p)['nodes'],revision=self.get_project(p)['revision'])
    def save_asset_card(self,p,payload,**kw):
        self._validate_write(payload,**kw)
        if not isinstance(payload,dict) or set(payload)-{'asset_id','name','asset_kind','base_revision','forms'} or not {'name','asset_kind','base_revision','forms'}<=set(payload):raise ResourceError('资产卡需要名称、类型、版本与形态')
        if payload['asset_kind'] not in KINDS or type(payload['base_revision']) is not int or payload['base_revision']<0 or not isinstance(payload['name'],str) or not 1<=len(payload['name'].strip())<=200:raise ResourceError('资产名称、类型或版本无效')
        if not isinstance(payload['forms'],list) or not 1<=len(payload['forms'])<=50:raise ResourceError('请填写1–50个形态')
        keys=set()
        for form in payload['forms']:
            if not isinstance(form,dict) or set(form)-{'form_key','name','base_version_id','description','media_id','voice_spec_id'} or not {'form_key','name','base_version_id'}<=set(form):raise ResourceError('形态字段无效')
            for key in ('form_key','name'):
                if not isinstance(form[key],str) or not 1<=len(form[key].strip())<=200:raise ResourceError('形态名称须为1–200字')
            if form['form_key'] in keys:raise ResourceError('形态键重复')
            keys.add(form['form_key'])
            if not isinstance(form.get('description',''),str) or len(form.get('description',''))>20000:raise ResourceError('形态描述过长')
        return self._asset_cards().save_asset_card(p,payload,**kw)
    def favorite_asset_card(self,p,payload,**kw):
        self._validate_write(payload,**kw)
        if set(payload)!={'asset_id','active'} or type(payload['active']) is not bool:raise ResourceError('收藏操作无效')
        return self._asset_cards().favorite_asset_card(p,payload,**kw)
    def reference_asset_card(self,p,payload,**kw):
        self._validate_write(payload,**kw)
        if set(payload)!={'asset_id','asset_revision','episode_ids'} or type(payload['asset_revision']) is not int or not isinstance(payload['episode_ids'],list) or not 1<=len(payload['episode_ids'])<=50 or len(set(payload['episode_ids']))!=len(payload['episode_ids']):raise ResourceError('请选择1–50个不同剧集和当前资产版本')
        return self._asset_cards().reference_asset_card(p,payload,**kw)
    def copy_asset_card(self,p,payload,**kw):
        self._validate_write(payload,**kw)
        if set(payload)-{'source_project_id','source_asset_id','form_version_ids','name'} or not {'source_project_id','source_asset_id','form_version_ids'}<=set(payload) or payload['source_project_id']==p:raise ResourceError('复制需要不同项目及固定源资产')
        ids=payload['form_version_ids']
        if not isinstance(ids,list) or not 1<=len(ids)<=50 or len(set(ids))!=len(ids):raise ResourceError('请选择不同的固定资产形态')
        self.authorize_access(payload['source_project_id'],'read')
        return self._asset_cards().copy_asset_card(p,payload,**kw)
