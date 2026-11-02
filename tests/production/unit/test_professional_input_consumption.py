"""Canonical professional body consumption; no database or provider calls."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from vsc.assets.resource_service import ResourceError
from vsc.adapters.persistence.postgres.professional_inputs import _professional_fragments,prompt_with_conditions,resolve_professional_inputs
from vsc.production.run_authorization import normalize_request


ROOT=Path(__file__).resolve().parents[3]


class ProfessionalInputConsumptionTests(unittest.TestCase):
    def setUp(self):
        self.scope={'id':'shot-2-uuid','sequence_id':'sequence-uuid','scene_id':'scene-uuid',
            'episode_id':'episode-uuid','work_id':'work-uuid'}
        codes={'shot':{'SH-001':'shot-1-uuid','SH-002':self.scope['id'],'SH-OTHER':'other-shot'},
            'scene':{'EP-001-SC-001':self.scope['scene_id'],'OTHER-SC':'other-scene'},
            'sequence':{'SEQ-001':self.scope['sequence_id'],'OTHER-SEQ':'other-sequence'},
            'episode':{'EP-001':self.scope['episode_id'],'EP-002':'other-episode'}}
        self.ids={kind:{**rows,**{identifier:identifier for identifier in rows.values()}} for kind,rows in codes.items()}
        self.ids['shot_scopes']={self.scope['id']:self.scope,
            'shot-1-uuid':dict(self.scope,id='shot-1-uuid'),
            'other-shot':{'id':'other-shot','sequence_id':'other-sequence','scene_id':'other-scene','episode_id':'other-episode'}}

    def template(self,name):
        return json.loads((ROOT/'templates'/name).read_text())

    def test_scene_state_uses_real_baseline_and_all_previous_changes(self):
        document=self.template('scene-state.json');original=deepcopy(document)
        path,fragment=_professional_fragments(document,'scene_state',self.scope,self.ids)[0]
        self.assertEqual(path,'scenes[0].shots[1]')
        self.assertEqual(fragment['entry']['entities']['主角']['pose'],'抬头看向门口')
        self.assertEqual(fragment['entry']['entities']['主角']['holding_hand'],'right')
        self.assertEqual(fragment['exit']['entities']['主角']['pose'],'站起')
        self.assertEqual(fragment['exit']['entities']['信封']['variant'],'信封-已拆')
        self.assertEqual(document,original)
        text=json.dumps(fragment,ensure_ascii=False,sort_keys=True)
        prompt=prompt_with_conditions('原用户提示',{'semantic_inputs':[{'text':text}]})
        self.assertIn('抬头看向门口',prompt);self.assertIn('信封-已拆',prompt)

    def test_continuity_and_shot_plan_keep_original_indices_and_incoming_bridge(self):
        document=self.template('continuity-plan.json')
        for kind in ('continuity','shot_plan'):
            with self.subTest(kind=kind):
                fragments=_professional_fragments(document,kind,self.scope,self.ids)
                self.assertEqual([path for path,_ in fragments],['shots[0].bridge_to_next','shots[1]'])
                self.assertEqual(fragments[0][1]['bridge']['strategy'],'match_action')
                self.assertEqual(fragments[1][1]['entry_state']['characters']['主角']['pose'],'抬头看向门口')

    def test_uuid_and_display_codes_use_same_typed_scope(self):
        document=self.template('continuity-plan.json');document['sequence_id']=self.scope['sequence_id']
        document['shots'][1]['id']=self.scope['id']
        self.assertEqual(_professional_fragments(document,'shot_plan',self.scope,self.ids)[-1][0],'shots[1]')
        self.ids['scene']['SH-002']='unrelated-scene-with-same-code'
        self.assertTrue(_professional_fragments(document,'shot_plan',self.scope,self.ids))

    def test_sequence_links_consume_units_and_real_boundary_content(self):
        document=self.template('sequence-links.json')
        document['units'][0].update(entry_shot='SH-001',exit_shot='SH-002')
        document['units'][1].update(entry_shot='SH-OTHER',exit_shot='SH-OTHER')
        fragments=_professional_fragments(document,'sequence_links',self.scope,self.ids)
        self.assertEqual(fragments[0][0],'links[0]')
        fragment=fragments[0][1]
        self.assertEqual(fragment['shot_boundaries'],['exit'])
        self.assertEqual(fragment['from_unit']['id'],'EP-001')
        self.assertEqual(fragment['link'],document['links'][0])
        prompt=prompt_with_conditions('原用户提示',{'semantic_inputs':[{'text':json.dumps(fragment,ensure_ascii=False)}]})
        self.assertIn(document['links'][0]['audio']['description'],prompt)

    def test_wrong_scope_unknown_format_no_match_and_duplicate_are_explicit_gaps(self):
        state=self.template('scene-state.json');plan=self.template('continuity-plan.json')
        links=self.template('sequence-links.json')
        links['units'][0].update(entry_shot='SH-001',exit_shot='SH-002')
        links['units'][1].update(entry_shot='SH-OTHER',exit_shot='SH-OTHER')
        cases=[]
        wrong=deepcopy(state);wrong['scenes'][0]['id']='OTHER-SC';cases.append(('scene_state',wrong,'professional_input_scope'))
        wrong=deepcopy(plan);wrong['sequence_id']='OTHER-SEQ';cases.append(('shot_plan',wrong,'professional_input_scope'))
        wrong=deepcopy(plan);wrong['scene_ids']=['OTHER-SC'];cases.append(('shot_plan',wrong,'professional_input_scope'))
        wrong=deepcopy(plan);wrong['shots'][1]['entry_state']['scene_id']='OTHER-SC';cases.append(('continuity',wrong,'professional_input_scope'))
        wrong=deepcopy(links);wrong['units'][0]['id']='EP-002';wrong['units'][1]['id']='EP-001';wrong['links'][0].update({'from':'EP-002','to':'EP-001'});cases.append(('sequence_links',wrong,'professional_input_scope'))
        for kind,document in (('scene_state',state),('continuity',plan),('sequence_links',links)):
            wrong=deepcopy(document);wrong['format']='vsc.unknown/v1';cases.append((kind,wrong,'professional_input_incomplete'))
        wrong=deepcopy(plan);wrong['shots']=wrong['shots'][:1];cases.append(('shot_plan',wrong,'professional_input_incomplete'))
        wrong=deepcopy(plan);wrong['shots'].append(deepcopy(wrong['shots'][1]));cases.append(('continuity',wrong,'professional_input_incomplete'))
        wrong=deepcopy(plan);wrong['shots'][1]={'id':'SH-002'};cases.append(('shot_plan',wrong,'professional_input_incomplete'))
        cases.append(('scene_state',{'shots':[{'id':'SH-002'}]},'professional_input_incomplete'))
        cases.append(('sequence_links',{'shots':[{'id':'SH-002'}]},'professional_input_incomplete'))
        for kind,document,code in cases:
            with self.subTest(kind=kind,document=document),self.assertRaises(ResourceError) as error:
                _professional_fragments(document,kind,self.scope,self.ids)
            self.assertEqual(error.exception.code,code)

    def test_interior_shot_cannot_claim_an_unrelated_boundary(self):
        document=self.template('sequence-links.json')
        document['units'][0].update(entry_shot='SH-001',exit_shot='SH-001')
        document['units'][1].update(entry_shot='SH-OTHER',exit_shot='SH-OTHER')
        with self.assertRaises(ResourceError) as error:
            _professional_fragments(document,'sequence_links',self.scope,self.ids)
        self.assertEqual(error.exception.code,'professional_input_incomplete')

    def test_registered_foreign_shots_cannot_contribute_accumulated_state_or_bridge(self):
        state=self.template('scene-state.json');state['scenes'][0]['shots'][0]['id']='SH-OTHER'
        plan=self.template('continuity-plan.json');plan['shots'][0]['id']='SH-OTHER'
        links=self.template('sequence-links.json')
        links['units'][0].update(entry_shot='SH-001',exit_shot='SH-002')
        links['units'][1].update(entry_shot='SH-001',exit_shot='SH-OTHER')
        for kind,document in (('scene_state',state),('continuity',plan),('sequence_links',links)):
            with self.subTest(kind=kind),self.assertRaises(ResourceError) as error:
                _professional_fragments(document,kind,self.scope,self.ids)
            self.assertEqual(error.exception.code,'professional_input_scope')

    def test_resolver_passes_canonical_body_and_fixed_pin_to_actual_prompt_context(self):
        document=self.template('scene-state.json');identifier='10000000-0000-0000-0000-000000000001';sha='a'*64
        row={'id':identifier,'sha256':sha,'artifact_type':'vsc.scene_state','project_wide':False,
            'document':json.dumps(document).encode()}
        source={'id':identifier,'sha256':sha,'kind':'scene_state'}
        conn=SimpleNamespace(execute=lambda statement:SimpleNamespace(scalars=lambda:[self.scope['episode_id']]))
        store=SimpleNamespace(_one=lambda *args:row)
        module='vsc.adapters.persistence.postgres.professional_inputs'
        with patch(module+'.shot_scope',return_value=self.scope),patch(module+'._professional_id_map',return_value=self.ids):
            resolved=resolve_professional_inputs(store,conn,{'id':'project-uuid'},
                {'shot_id':self.scope['id'],'professional_inputs':[source]})
        self.assertEqual(resolved['pins'],[source]);self.assertEqual(resolved['dependency_ids'],[identifier])
        semantic=resolved['semantic_inputs'][0]
        self.assertEqual(semantic['path'],'scenes[0].shots[1]');self.assertEqual(semantic['id'],identifier)
        self.assertEqual(resolved['context']['semantic_inputs'],resolved['semantic_inputs'])
        request=normalize_request({'prompt':prompt_with_conditions('原用户提示',resolved['context'])},
            self.scope['id'],'text_to_video','video')
        self.assertIn('抬头看向门口',request['prompt']);self.assertIn(semantic['text'],request['prompt'])
        self.assertNotIn('approved_inputs',resolved['context'])


if __name__=='__main__':unittest.main()
