"""Optional organization review lanes reuse original candidate reviews."""

LANES={'character':{'label':'人设参考审核','roles':['identity_face','costume']},'storyboard':{'label':'分镜图审核','roles':['storyboard','composition']},'video':{'label':'视频审核','roles':['video_take']}}
class TeamReviewServiceMixin:
    def team_review_queue(self,project_id,lane):
        if lane not in LANES:raise ResourceError('审核线路无效')
        return self.store.team_review_queue(project_id,lane)
    def submit_team_review(self,project_id,payload,**kw):
        self._validate_write(payload,**kw)
        if set(payload)-{'candidate_id','lane','supersedes_id'} or payload.get('lane') not in LANES:raise ResourceError('提交需要原候选、线路及可选前次记录')
        return self.store.submit_team_review(project_id,payload,**kw)
    def commit_team_review(self,project_id,payload,**kw):
        self._validate_write(payload,**kw)
        if set(payload)!={'submission_id','outcome','reason'} or payload['outcome'] not in {'pass','fail','needs_changes'} or not isinstance(payload['reason'],str) or not payload['reason'].strip() or len(payload['reason'])>2000:raise ResourceError('填写本次固定候选的审核结论和理由')
        return self.store.commit_team_review(project_id,payload,**kw)

from vsc.assets.resource_service import ResourceError
