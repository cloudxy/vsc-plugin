"""Fixed first-cut source/timing and actual renderer request consumers, no DB."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch

from vsc.assets.resource_service import ResourceError
from vsc.post.edit_workspace import FORMAT,FirstCutRenderer,edit_operation,sound_receipt,validate_edit
from vsc.adapters.persistence.postgres.editor_professional import cue_intervals,seed_cue


class EditorProfessionalTests(unittest.TestCase):
    def document(self):
        return dict(format=FORMAT,width=128,height=128,fps=24,clips=[
            dict(id='a',shot_id='shot-a',media_id='video-a',in_frame=24,out_frame=72),
            dict(id='b',shot_id='shot-b',media_id='video-b',in_frame=0,out_frame=24)],audio=[],captions=[])

    def cue(self,document):
        covers=[dict(shot_id='shot-a',start_ms=1000,end_ms=3000),dict(shot_id='shot-b',start_ms=0,end_ms=1000)]
        return dict(id=str(uuid.uuid4()),cue_kind='music',parameters={},covers=covers,intervals=cue_intervals(document,covers))

    def source(self,document,cue,duration=3000):
        class Rows:
            def mappings(self):return self
            def all(self):return [dict(id='fixed-decision',media_id='audio')]
        class Connection:
            def execute(self,*args):return Rows()
        with patch('vsc.adapters.persistence.postgres.workbench_generation.working_media',return_value=(dict(id='audio',modality='audio',duration_ms=duration),[])):
            return seed_cue(None,Connection(),'project',document,cue)

    def test_metadata_survives_edit_commands_and_cue_identity_is_audio_only(self):
        doc=self.document();pin=dict(id=str(uuid.uuid4()),sha256='a'*64,kind='sound_plan')
        doc['professional_inputs']=[pin]
        doc['audio']=[dict(id='sound',media_id='audio',in_frame=0,out_frame=72,cue_id='cue',binding_decision_id='decision')]
        changed=edit_operation(doc,dict(action='split',clip_id='a',frame=48,new_id='a2'))
        self.assertEqual(changed['professional_inputs'],[pin]);self.assertEqual(changed['audio'],doc['audio'])
        self.assertEqual(validate_edit(changed),72)
        for mutate in (lambda d:d['clips'][0].update(cue_id='x',binding_decision_id='y'),
                       lambda d:d['audio'][0].pop('binding_decision_id'),
                       lambda d:d['professional_inputs'][0].update(sha256='bad')):
            wrong=copy.deepcopy(doc);mutate(wrong)
            with self.assertRaises(ValueError):validate_edit(wrong)

    def test_declared_ms_cross_trim_into_one_audio_not_repeat_per_shot(self):
        doc=self.document();cue=self.cue(doc)
        self.assertEqual([(r['start_ms'],r['end_ms']) for r in cue['intervals']],[(0,2000),(2000,3000)])
        audio=self.source(doc,cue)
        self.assertEqual((audio['in_frame'],audio['out_frame'],audio['at_frame']),(0,72,0))
        self.assertEqual((audio['cue_id'],audio['binding_decision_id']),(cue['id'],'fixed-decision'))
        doc['clips'][0]['in_frame']=48;cue=self.cue(doc)
        audio=self.source(doc,cue)
        self.assertEqual((audio['in_frame'],audio['out_frame']),(24,72))

    def test_missing_timing_ambiguous_source_and_internal_cut_are_not_guessed(self):
        doc=self.document();cue=self.cue(doc)
        with self.assertRaises(ResourceError) as missing:self.source(doc,cue,duration=5000)
        self.assertEqual(missing.exception.code,'edit_cue_source_timing_missing')
        cue['parameters']['source_in_ms']=500
        self.assertEqual(self.source(doc,cue,duration=5000)['in_frame'],12)
        doc['clips'][0]['out_frame']=48;cue=self.cue(doc)
        with self.assertRaises(ResourceError) as discontinuous:self.source(doc,cue)
        self.assertEqual(discontinuous.exception.code,'edit_cue_discontinuous')
        cue=self.cue(self.document());cue['covers'][0]['start_ms']=None
        with self.assertRaises(ResourceError) as untimed:self.source(self.document(),cue)
        self.assertEqual(untimed.exception.code,'edit_cue_timing_missing')

    def test_sound_routes_boundaries_and_unknown_alignment_remain_distinct(self):
        doc=self.document();cue=self.cue(doc);audio=self.source(doc,cue);doc['audio']=[audio]
        context=dict(shot_conditions={'shot-a':{'sound_route':'separate'},'shot-b':{'sound_route':'silent'}},
            sound_checks=[dict(cue_id=cue['id'],label='声音桥',kind='music',timing='declared',intervals=cue['intervals'])])
        receipt=sound_receipt(doc,context,{'a':False,'b':False,audio['id']:True})
        self.assertEqual(receipt['stream_and_range_checks'][0]['status'],'covered')
        self.assertEqual(receipt['stream_and_range_checks'][1]['status'],'unexpected_audio')
        self.assertEqual(receipt['boundaries'][0]['status'],'continuous')
        self.assertEqual(receipt['audio_alignment'],'not_verified');self.assertEqual(receipt['status'],'unreviewed')
        doc['audio'][0]['muted']=True
        self.assertEqual(sound_receipt(doc,context,{'a':False,'b':False,audio['id']:True})['boundaries'][0]['status'],'boundary_gap')

    def test_renderer_consumes_rules_and_retains_measurements_without_changing_document(self):
        doc=self.document();doc['captions']=[dict(start_frame=0,end_frame=24,text='固定对白')]
        original=copy.deepcopy(doc);seen=[]
        context={'creative_rules':{'subtitle':{'max_cps':{'value':1,'level':'warning'}}},'script_texts':['固定对白'],
                 'inputs':[dict(id=str(uuid.uuid4()),sha256='a'*64,kind='screenplay')]}
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);font=root/'font.ttf';font.write_bytes(b'fixed-font')
            def run(args,**kwargs):
                if str(args[-1]).endswith('.mp4'):Path(args[-1]).write_bytes(b'captured-local-output')
                return b''
            def layout(path):
                job=json.loads(path.read_text());seen.append(job)
                job['subtitle_checks']['font_layout']='passed'
                for cue in job['cues']:cue.update(png=str(root/'cue.png'),x=0,y=0)
                path.write_text(json.dumps(job))
            with patch.object(FirstCutRenderer,'capabilities',return_value={'available':True}),\
                    patch('vsc.post.edit_workspace._probe',return_value={'format':{'duration':3},'streams':[{'codec_type':'video'},{'codec_type':'audio'}]}),\
                    patch('vsc.post.edit_workspace._run',side_effect=run),\
                    patch('vsc.post.subtitles.resolve_style',return_value=({'font':str(font)},{})),\
                    patch('vsc.post.subtitle_burn.render',side_effect=layout):
                output,receipt=FirstCutRenderer().render(doc,{c['id']:{'path':root/'source.mp4','modality':'video'} for c in doc['clips']},root,professional_context=context)
            self.assertTrue(output.is_file());self.assertEqual(doc,original)
            self.assertEqual(seen[0]['creative_rules'],context['creative_rules']);self.assertEqual(seen[0]['script_texts'],['固定对白'])
            self.assertEqual(receipt['subtitle_checks']['reading_rules'],'warnings')
            self.assertEqual(receipt['subtitle_checks']['text_coverage'],'passed')
            self.assertEqual(receipt['subtitle_checks']['line_binding'],'not_verified')
            self.assertEqual(receipt['subtitle_measurements'][0]['duration_ms'],1000)
            self.assertEqual(receipt['subtitle_measurements'][0]['cps'],4)
            self.assertTrue(receipt['subtitle_warnings'])

