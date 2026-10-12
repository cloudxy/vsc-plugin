"""Current-profile state, source and migration regressions (no legacy fixtures)."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from _paths import ROOT


class CurrentState(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name); self.project=self.root/'project'
        self.cli('init',self.project,'--title','synthetic')
    def tearDown(self): self.tmp.cleanup()
    def cli(self,*args,ok=True):
        result=subprocess.run([sys.executable,'-B',str(ROOT/'scripts/vsc_state.py'),*map(str,args)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0 if ok else 1,result.stdout+result.stderr)
        return result.stdout+result.stderr
    def state(self): return json.loads((self.project/'vsc.json').read_text())
    def file(self,name,data):
        p=self.root/name; p.write_text(json.dumps(data) if isinstance(data,dict) else data); return p
    def add(self,kind,stage,data,extra=()):
        return self.cli('artifact','add',self.project,'--type',kind,'--stage',stage,'--file',self.file('input',data),*extra).split()[1]
    def brief(self):
        return {'format':'vsc.creative-brief/v1','audience':'Synthetic viewers','desired_experience':'Follow a choice','decision_owner':'fixture',
                'objectives':[{'id':'O','goal':'clear action','success_evidence':'viewer retells it'}],'nonnegotiables':[], 'conflict_policy':'record human decision'}
    def test_new_init_is_strict_and_text_shells_fail(self):
        self.assertEqual(self.state()['profile_snapshot']['contract_policy'],'production-v2')
        for kind,stage in [('vsc.screenplay','script'),('vsc.animatic','animatic'),('vsc.timeline','post'),('vsc.selected_takes','production'),('vsc.mix','post'),('vsc.delivery_manifest','delivery')]:
            aid=self.add(kind,stage,'x')
            self.assertIn('JSON',self.cli('artifact','decide',self.project,aid,'--status','approved','--by','fixture',ok=False))
    def test_source_snapshot_survives_working_file_and_locator_is_real(self):
        from vsc_sources import source_errors,locator_errors
        working=self.file('source.txt','one\ntwo\n')
        self.cli('source','add',self.project,'--kind','original','--file',working,'--rights','owned')
        source=self.state()['sources'][0]; working.unlink()
        self.assertEqual(source_errors(self.project,source),[])
        fixed=self.project/source['path']
        self.assertEqual(locator_errors(fixed,{'kind':'lines','start':1,'end':2}),[])
        self.assertTrue(locator_errors(fixed,{'kind':'lines','start':99,'end':99}))
        fixed.write_text('changed')
        self.assertTrue(source_errors(self.project,source))
    def test_bundle_is_atomic_and_binds_exact_sha(self):
        aid=self.add('vsc.creative_brief','brief',self.brief()); item=self.state()['artifacts'][0]
        self.cli('artifact','decide-bundle',self.project,'--item',aid+':'+'0'*64,'--status','approved','--by','fixture','--reason','checked',ok=False)
        self.assertEqual(self.state()['artifacts'][0]['status'],'draft')
        self.cli('artifact','decide-bundle',self.project,'--item',aid+':'+item['sha256'],'--status','approved','--by','fixture','--reason','checked')
        self.assertEqual(self.state()['artifacts'][0]['status'],'approved')
    def test_migration_preview_does_not_write_and_stale_preview_fails(self):
        from _paths import freeze_legacy_profile
        freeze_legacy_profile(self.project); original=(self.project/'vsc.json').read_bytes()
        preview=json.loads(self.cli('profile','migrate',self.project,'--profile','vsc.engineered-short'))
        self.assertEqual((self.project/'vsc.json').read_bytes(),original)
        self.cli('object','add',self.project,'--kind','episode','--id','EP1')
        self.cli('profile','migrate',self.project,'--profile','vsc.engineered-short','--apply','--plan-hash',preview['plan_sha256'],'--by','fixture','--reason','checked',ok=False)
        preview=json.loads(self.cli('profile','migrate',self.project,'--profile','vsc.engineered-short'))
        self.cli('profile','migrate',self.project,'--profile','vsc.engineered-short','--apply','--plan-hash',preview['plan_sha256'],'--by','fixture','--reason','checked')
        state=self.state(); self.assertEqual(state['profile_version'],'2.0')
        self.assertTrue((self.project/state['profile_history'][0]['backup']).is_file())
    def test_asset_rebind_preserves_identity_and_history(self):
        first=self.add('vsc.imported_media','design','fixed image bytes')
        self.cli('artifact','decide',self.project,first,'--status','approved','--by','fixture')
        self.cli('object','add',self.project,'--kind','asset','--id','AS1','--artifact',first)
        second=self.add('vsc.imported_media','design','new fixed bytes',('--supersedes',first))
        self.cli('artifact','decide',self.project,second,'--status','approved','--by','fixture')
        self.cli('object','bind',self.project,'--id','AS1','--artifact',second,'--by','fixture','--reason','new reference')
        obj=self.state()['objects'][0]
        self.assertEqual(obj['artifact'],second); self.assertEqual(obj['binding_history'][0]['artifact'],first)
    def test_invention_does_not_need_a_fabricated_source(self):
        from vsc_sources import provenance_errors
        data={'source_units':[], 'screen_units':[{'origin':'invention','source_refs':[],'decision_ref':'self:invention'}]}
        item={'id':'A-1'}; state={'sources':[], 'decisions':[]}
        self.assertTrue(provenance_errors(data,self.project,state,item))
        state['decisions'].append({'id':'D-1','kind':'invention','target':'A-1','outcome':'accepted','by':'synthetic reviewer','reason':'approved new beat'})
        self.assertEqual(provenance_errors(data,self.project,state,item),[])
        self.assertTrue(provenance_errors(data,self.project,state,{'id':'A-2'}))
    def test_dialogue_coverage_requires_a_real_sound_cue(self):
        from test_vsc_handoffs import Fixture
        from vsc_handoffs import project_errors
        (self.root/'fixture').mkdir()
        f=Fixture(self.root/'fixture')
        f.state['profile_snapshot']={'contract_policy':'production-v2'}
        screenplay=f.screenplay_data
        screenplay['scenes'][0]['dialogue']=[{'id':'L1','speaker':'person','text':'Synthetic line','narrative_refs':['N1']}]
        script=f.register('vsc.screenplay',screenplay,[f.adaptation])
        coverage=f.coverage_data; coverage['screenplay']=f.ref(script)
        coverage['scenes'][0]['sequences'][0]['shots'][0]['screenplay_unit_ids'].append('L1')
        owner=f.register('vsc.coverage_plan',coverage,[script,*f.shots,*f.sounds])
        self.assertTrue(any('对白声音Cue' in e for e in project_errors(coverage,f.project,f.state,owner)))
    def test_light_profile_keeps_core_chain_and_is_single_episode(self):
        project=self.root/'light'
        self.cli('init',project,'--title','synthetic light','--profile','vsc.light-short')
        state=json.loads((project/'vsc.json').read_text())
        required={kind for stage in state['profile_snapshot']['stages'] for kind in stage['required']}
        self.assertIn('vsc.coverage_plan',required);self.assertIn('vsc.selected_takes',required)
        self.assertNotIn('vsc.episode_beats',required);self.assertNotIn('vsc.visual_bible',required)
        self.cli('object','add',project,'--kind','episode','--id','EP1')
        self.cli('object','add',project,'--kind','episode','--id','EP2',ok=False)


if __name__=='__main__': unittest.main()
