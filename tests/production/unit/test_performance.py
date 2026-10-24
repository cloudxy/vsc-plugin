import copy
import unittest
from vsc.production.performance import FIELDS, execution_problems, prompt_fragment, participant_problems


def parameters(domain):
    value = {key: 'explicit observable ' + key for key in FIELDS[domain]}
    value.update(purpose='observable intention', acceptance='fixed tolerance', fallback='edit to reaction', route='generation')
    if domain == 'combat':
        value['phases'] = [{'phase': key, 'actor_role': 'attacker', 'counterpart_role': 'defender', 'action': 'fixed action'}
                           for key in ('preparation', 'initiation', 'contact', 'reaction', 'recovery')]
    if domain == 'dance':
        value['beats'] = [{'seconds': 0, 'pose': 'open'}, {'seconds': 1.5, 'pose': 'close'}]
    if domain == 'vfx':
        value['layers'] = [{'name': 'light', 'purpose': 'contact glow', 'occlusion': 'behind hand'}]
    if domain == 'voice':
        value.update(delivery='whisper', target_seconds=2.5)
    return value


class PerformanceTests(unittest.TestCase):
    def test_three_people_chain_uses_identity_not_shared_role_and_checks_causality(self):
        p=parameters('combat')
        def node(key, actor, other, after):
            return dict(id=key,actor_instance=actor,counterpart_instance=other,after=after,
                        phases=[dict(phase=phase,action='observable '+phase) for phase in
                                ('preparation','initiation','contact','reaction','recovery')])
        p['chain']=[node('one','a','b',[]),node('two','c','a',['one'])]
        people=[dict(instance=x,role='fighter') for x in ('a','b','c')]
        self.assertEqual(execution_problems('combat',p),[])
        self.assertEqual(participant_problems('combat',p,people),[])
        self.assertIn('counterpart_instance',prompt_fragment('combat',p))
        for kind in ('cycle','missing','phase','self','duplicate'):
            bad=copy.deepcopy(p)
            if kind=='cycle':bad['chain'][0]['after']=['two']
            if kind=='missing':bad['chain'][1]['after']=['lost']
            if kind=='phase':bad['chain'][1]['phases'].reverse()
            if kind=='self':bad['chain'][1]['counterpart_instance']='c'
            if kind=='duplicate':bad['chain'][1]['id']='one'
            with self.subTest(kind=kind):self.assertTrue(execution_problems('combat',bad))
        bad=copy.deepcopy(p);bad['chain'][1]['actor_instance']='outside'
        self.assertTrue(participant_problems('combat',bad,people))
        self.assertTrue(participant_problems('combat',p,people+[people[0]]))

    def test_same_voice_different_delivery_requires_actual_supported_control(self):
        from vsc.production.performance import voice_control_problems
        p = parameters('voice')
        p.update(delivery='speech', controls=[{'field': 'rate', 'model_default': 'speech_rate', 'expected': 0}])
        model = {'capabilities': {'performance_controls': {'rate': 'speech_rate'}}, 'default_params': {'speech_rate': 0}}
        self.assertEqual(voice_control_problems(p, model, 'stable', [{'id': 'stable'}]), [])
        for delivery in ('whisper', 'shout'):
            p['delivery'] = delivery
            self.assertTrue(voice_control_problems(p, model, 'stable', [{'id': 'stable'}]))
        p['delivery'] = 'speech'
        self.assertTrue(voice_control_problems(p, model, 'changed', [{'id': 'stable'}]))
        model['default_params']['speech_rate'] = 30
        self.assertTrue(voice_control_problems(p, model, 'stable', [{'id': 'stable'}]))

    def test_professional_specs_compile_and_missing_decisions_block(self):
        for domain in FIELDS:
            p = parameters(domain)
            self.assertEqual(execution_problems(domain, p), [])
            self.assertIn('acceptance', prompt_fragment(domain, p))
            for field in FIELDS[domain]:
                bad = copy.deepcopy(p)
                bad.pop(field)
                self.assertTrue(execution_problems(domain, bad), (domain, field))

    def test_unknown_phase_music_timing_layers_and_voice_duration_block(self):
        mutations = [('combat', 'phases', []), ('dance', 'beats', [{'seconds': float('nan'), 'pose': 'a'}]),
                     ('vfx', 'layers', []), ('voice', 'target_seconds', None)]
        for domain, field, value in mutations:
            p = parameters(domain)
            p[field] = value
            with self.assertRaises(ValueError):
                prompt_fragment(domain, p)
