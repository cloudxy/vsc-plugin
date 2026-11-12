"""Optional organization review lanes reuse original candidate reviews."""

LANES={'character':{'label':'人设参考审核','roles':['identity_face','costume']},'storyboard':{'label':'分镜图审核','roles':['storyboard','composition','first_frame']},'video':{'label':'视频审核','roles':['video_take']}}
class TeamReviewServiceMixin:
    def team_review_queue(self,project_id,lane,*,offset=0,limit=24,status=None,episode_id=None,query=''):
        if lane not in LANES:raise ResourceError('审核线路无效')
        if type(offset)is not int or offset<0 or type(limit)is not int or not 1<=limit<=100 or status not in {None,'unsubmitted','pending','pass','fail','needs_changes'} or not isinstance(query,str) or len(query)>200:raise ResourceError('审核筛选条件无效')
        return self.store.team_review_queue(project_id,lane,offset=offset,limit=limit,status=status,episode_id=episode_id,query=query.strip())
    def submit_team_review(self,project_id,payload,**kw):
        self._validate_write(payload,**kw)
        if not isinstance(payload,dict) or set(payload)-{'candidate_id','lane','supersedes_id','media_id','shot_id','note'} or payload.get('lane') not in LANES:
            raise ResourceError('提交需要原候选、线路及可选前次记录')
        if not payload.get('candidate_id') and not (payload.get('media_id') and payload.get('shot_id')):
            raise ResourceError('提交需要原候选标识或镜头媒体标识')
        return self.store.submit_team_review(project_id,payload,**kw)
    def commit_team_review(self,project_id,payload,**kw):
        self._validate_write(payload,**kw)
        if set(payload)!={'submission_id','outcome','reason'} or payload['outcome'] not in {'pass','fail','needs_changes'} or not isinstance(payload['reason'],str) or not payload['reason'].strip() or len(payload['reason'])>2000:raise ResourceError('填写本次固定候选的审核结论和理由')
        return self.store.commit_team_review(project_id,payload,**kw)
    def batch_commit_team_review(self,project_id,payload,**kw):
        self._validate_write(payload,**kw)
        if not isinstance(payload,dict) or set(payload)!={'submission_ids','outcome','reason'}:
            raise ResourceError('批量审核需要待审记录列表、结论和理由')
        sids=payload.get('submission_ids')
        if not isinstance(sids,list) or not 1<=len(sids)<=50 or len(set(sids))!=len(sids):
            raise ResourceError('单次批量审核支持 1–50 条不重复待审记录')
        if payload['outcome'] not in {'pass','fail','needs_changes'} or not isinstance(payload['reason'],str) or not payload['reason'].strip() or len(payload['reason'])>2000:
            raise ResourceError('填写本次批量审核结论和理由')
        return self.store.batch_commit_team_review(project_id,payload,**kw)
    def mark_team_review_read(self,project_id,payload,**kw):
        self._validate_write(payload,**kw)
        if not isinstance(payload,dict) or set(payload)-{'candidate_id','media_id','shot_id','submission_id','review_id','note'} or (not payload.get('candidate_id') and not payload.get('media_id')):
            raise ResourceError('标记已阅需要对应候选或媒体标识')
        return self.store.mark_team_review_read(project_id,payload,**kw)

from vsc.assets.resource_service import ResourceError
