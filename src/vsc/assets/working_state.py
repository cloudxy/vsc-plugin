"""Public working-state commands preserve the formal review boundary."""
from vsc.assets.resource_service import ResourceError


class WorkingStateService:
    def save_working_selection(self,p,payload,**kw):
        self._validate_write(payload,**kw)
        if not isinstance(payload,dict) or set(payload)-{'shot_id','output_kind','candidate_id','base_version_id','trim_in_ms','trim_out_ms','event_kind'}:
            raise ResourceError('工作选片字段无效','invalid_working_selection')
        if not {'shot_id','output_kind','candidate_id','base_version_id'}<=set(payload) or payload['output_kind'] not in {'image','video'}:
            raise ResourceError('工作选片需要镜头、输出类型、候选和所见版本','invalid_working_selection')
        if payload.get('event_kind','select' if payload['candidate_id'] else 'clear') not in {'select','clear','trim'}:
            raise ResourceError('工作选择事件无效','invalid_working_selection')
        return self.store.save_working_selection(p,payload,**kw)

    def list_working_selections(self,p,episode_id=None,shot_id=None):
        if not episode_id and not shot_id:raise ResourceError('请限定当前集或镜头','working_scope_required')
        return self.store.list_working_selections(p,episode_id,shot_id)

    def get_classic_draft_inputs(self,p,draft_version_id):
        return self.store.get_classic_draft_inputs(p,draft_version_id)

    def backfill_classic_draft_inputs(self,p,payload,**kw):
        self._validate_write(payload,**kw)
        if set(payload)!={'draft_version_id'}:raise ResourceError('回填须固定一个草稿版本')
        return self.store.backfill_classic_draft_inputs(p,payload,**kw)

    def save_episode_asset(self,p,payload,**kw):
        self._validate_write(payload,**kw)
        if not isinstance(payload,dict) or set(payload)-{'id','episode_id','base_revision','asset_key','name','asset_kind','forms'}:
            raise ResourceError('本集资产字段无效','invalid_episode_asset')
        if not {'episode_id','base_revision','asset_key','name','asset_kind'}<=set(payload) or type(payload['base_revision']) is not int or payload['base_revision']<0:
            raise ResourceError('本集资产需要集、稳定键、名称、类型和版本','invalid_episode_asset')
        if payload['asset_kind'] not in {'character','location','prop','voice','style','costume','object','creature','vehicle','plant'}:
            raise ResourceError('本集资产类型无效','invalid_episode_asset')
        for key in ('name','asset_key'):
            if not isinstance(payload[key],str) or not payload[key].strip() or len(payload[key])>200:
                raise ResourceError('本集资产名称与键须为200字以内非空文本')
        forms=payload.get('forms',[])
        if not isinstance(forms,list) or len(forms)>200:raise ResourceError('形态列表最多200项')
        keys=set()
        for form in forms:
            if not isinstance(form,dict) or set(form)-{'form_key','name','base_version_id','source_asset_id','spec_id','media_id'} or not {'form_key','name','base_version_id'}<=set(form):
                raise ResourceError('形态需要稳定键、名称和所见版本')
            for key in ('form_key','name'):
                if not isinstance(form[key],str) or not form[key].strip() or len(form[key])>200:raise ResourceError('形态名称与键须为200字以内非空文本')
            if form['form_key'] in keys:raise ResourceError('同次保存不能重复形态键')
            keys.add(form['form_key'])
        return self.store.save_episode_asset(p,payload,**kw)

    def list_episode_assets(self,p,episode_id):
        return self.store.list_episode_assets(p,episode_id)
