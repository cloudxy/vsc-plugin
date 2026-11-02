"""Original workflow and ready/blocked batch fixtures shared by production tests."""
from datetime import datetime, timedelta, timezone


class IntelligentBatchSetup:
    def detail(self):return self.service.get_intelligent_workflow(self.p,self.flow)
    def save(self,state):
        current=self.detail();request=dict(workflow_id=self.flow,base_version_id=current['version']['id'],state=state)
        preview=self.service.preview_intelligent_change(self.p,request)
        return self.write('save_intelligent_workflow',dict(request,impact_sha256=preview['sha256']))
    def unit(self,key,shot):
        return dict(unit_key=key,kind='shot',title=key,description='角色走近门边',duration_ms=5000,segments=[dict(start_ms=0,end_ms=5000,text='角色向门边走两步')],shot_id=shot,
            professional=dict(narrative_purpose='建立门外威胁',entry_state='角色在门左侧，面向门',exit_state='角色停在门左侧一步处',bridge='保留门外敲击声接下一镜',sound_route='separate'))
    def prepared(self,blocked=False,duplicate=False):
        from vsc.production.resource_settings import ResourceSettings,PRESETS
        preset=next(row for row in PRESETS if row['id']=='xai-grok-imagine-video')
        self.model=ResourceSettings(self.store).save({**{k:v for k,v in preset.items() if k not in {'id','label'}},'enabled':True,'model_version':'isolated-episode-batch'},'test-human')
        second=self.write('create_object',dict(kind='shot',display_code='SHOT-B',parent_id=self.objects['sequence'],ordinal=1))['id']
        image=self.media('本批真实身份引用');state=self.detail()['state'];state['units']=[self.unit('one',self.objects['shot']),self.unit('two',self.objects['shot'] if duplicate else second)]
        selections={}
        for shot in {u['shot_id'] for u in state['units']}:
            candidate=self.write('propose_binding',dict(target_object_id=shot,media_id=image,role='first_frame',slot_key='workbench'))
            selections[shot]=self.write('save_working_selection',dict(shot_id=shot,output_kind='image',candidate_id=candidate['candidate_id'],base_version_id=None))['selection_version_id']
        if blocked:state['units'].append(self.unit('missing',None))
        state['media']=[dict(unit_key=u['unit_key'],purpose='first_frame',media_id=image,decision_id=None,working_selection_version_id=selections[u['shot_id']]) for u in state['units'] if u['shot_id']]
        self.save(state);now=datetime.now(timezone.utc)
        fixed=dict(workflow_id=self.flow,version_id=self.detail()['version']['id'],unit_keys=[u['unit_key'] for u in state['units']],purpose='video')
        preparation=dict(model_id=self.model['id']);saved=self.write('prepare_intelligent_drafts',dict(fixed,**preparation))
        request=dict(fixed,preparation=preparation,items=[dict(unit_key=i['unit_key'],draft_artifact_id=i['draft_artifact_id']) for i in saved['items'] if not i['gaps']],auto_first_cut=False,
            execution_policy=dict(version='bounded-v1',first_draft_due_at=(now+timedelta(minutes=10)).isoformat(),stop_submitting_at=(now+timedelta(minutes=30)).isoformat(),max_attempts_per_purpose=2,max_repair_rounds=1,authorization=dict(mode='new_batch',reason='明确确认本集固定测试批次')))
        return request
