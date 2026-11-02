"""Sequential typed sources must name an earlier node output in this exact turn."""
import unittest
from copy import deepcopy
from vsc.assets.resource_service import ResourceError
from vsc.production.canvas_agent import validate_plan, source_port


def action(kind, text='fixed', **extra):
    return dict(kind=kind,title='test',text=text,source_node_id='',**extra)


class CanvasActionSourceTests(unittest.TestCase):
    def turn(self):return dict(id='turn-a',skill_id='vsc-direct',model_ids=['model'],referenced_nodes=[dict(id='original',type='image',media_id='media')])
    def plan(self):return dict(message='fixed plan',questions=[],actions=[action('append_text'),action('create_video_node',source_action=dict(turn_id='turn-a',action_index=0,node_type='text')),action('prepare_run')])

    def test_typed_previous_text_and_original_node_contract(self):
        result=validate_plan(self.plan(),self.turn())
        self.assertEqual(result['actions'][1]['source_action']['action_index'],0)
        self.assertEqual(source_port('video','text'),'prompt')
        self.assertEqual(source_port('video','image'),'first_frame')
        old=dict(message='old',questions=[],action=dict(action('create_video_node'),source_node_id='original'))
        self.assertEqual(validate_plan(old,self.turn()),old)

    def test_forward_other_turn_wrong_type_and_non_node_outputs_rejected(self):
        cases=[{'turn_id':'other'},{'action_index':1},{'action_index':2},{'action_index':-1},{'action_index':False},{'node_type':'image'}]
        for change in cases:
            with self.subTest(change=change):
                plan=self.plan();plan['actions'][1]['source_action'].update(change)
                with self.assertRaises(ResourceError):validate_plan(plan,self.turn())
        for kind in ['none','prepare_run']:
            with self.subTest(kind=kind):
                plan=self.plan();plan['actions'][0]=action(kind)
                with self.assertRaises(ResourceError):validate_plan(plan,self.turn())
        plan=self.plan();plan['actions'][1]['source_node_id']='original'
        with self.assertRaises(ResourceError):validate_plan(plan,self.turn())
        plan=self.plan();plan['actions'][1]['source_action']['node_type']='script'
        with self.assertRaises(ResourceError):validate_plan(plan,self.turn())

    def test_media_chain_has_compatible_port_and_cannot_reuse_text_as_media(self):
        original=dict(action('reuse_media'),source_node_id='original')
        next_node=action('create_video_node',source_action=dict(turn_id='turn-a',action_index=0,node_type='image'))
        value=validate_plan(dict(message='',questions=[],actions=[original,next_node]),self.turn())
        self.assertEqual(value['actions'][1]['source_action']['node_type'],'image')
        plan=self.plan();plan['actions'][1]['kind']='reuse_media'
        with self.assertRaises(ResourceError):validate_plan(plan,self.turn())
        with self.assertRaises(ResourceError):source_port('audio','image')

    def test_canvas_host_receives_fixed_material_text_once(self):
        import json
        from pathlib import Path
        from types import SimpleNamespace
        from vsc.production.canvas_agent import GrokBuildCanvasAgent
        from vsc.production.role_materials import compile_role_materials
        bundle=compile_role_materials('director','vsc-direct','vsc-direct')
        skill=next(item['text'] for item in bundle['materials'] if item['kind']=='skill')
        captured={}
        def runner(command,**kwargs):
            captured['command']=command
            captured['prompt']=json.loads(Path(command[command.index('--prompt-file')+1]).read_text())
            return SimpleNamespace(returncode=0,stdout=json.dumps(dict(message='fixed',questions=[],actions=[action('none')])))
        turn={**self.turn(),'_materials':bundle,'_media_blocks':[]}
        result=GrokBuildCanvasAgent(runner=runner).generate({'role':{'id':'director'}},turn,skill)
        payload=json.JSONDecoder().raw_decode(captured['prompt'][0]['text'][captured['prompt'][0]['text'].index('{"role_context"'):])[0]
        self.assertEqual(payload['role_materials'],bundle)
        self.assertNotIn('_materials',payload['input'])
        self.assertNotIn('text',payload['skill'])
        self.assertEqual(captured['command'][captured['command'].index('--tools')+1],'')
        self.assertEqual(captured['command'][captured['command'].index('--max-turns')+1],'1')
        self.assertEqual(result['actions'][0]['kind'],'none')
