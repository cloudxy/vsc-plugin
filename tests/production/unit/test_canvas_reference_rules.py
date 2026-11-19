"""Source/generator params, model input limits and local prompt optimize."""
import unittest

from vsc.assets.resource_service import ResourceError
from vsc.assets.creative_canvas import CreativeCanvasService, normalize_document
from vsc.production.canvas_capabilities import canvas_capabilities, input_validation_for
from vsc.production.text_tool_host import OUTPUT_FIELDS


class CanvasReferenceRulesTests(unittest.TestCase):
    def test_node_kind_stays_inside_params(self):
        document = normalize_document(dict(
            nodes=[dict(id='n1', type='image', title='素材', x=0, y=0, text='', params=dict(vsc_node_kind='source'))],
            edges=[],
        ))
        self.assertEqual(document['nodes'][0]['params']['vsc_node_kind'], 'source')
        with self.assertRaises(ResourceError):
            normalize_document(dict(nodes=[dict(id='n1', type='image', title='素材', x=0, y=0, text='', params={}, node_kind='source')]))

    def test_input_validation_follows_model_family(self):
        seedance = input_validation_for(dict(id='doubao-seedance-2-5-260628', model_key='doubao-seedance-2-5-260628', modality='video'))
        self.assertEqual(seedance['family'], 'seedance_2_5')
        self.assertEqual(seedance['image_aspect_max'], 2.5)
        self.assertEqual(seedance['video_duration_max'], 30)
        older = input_validation_for(dict(id='doubao-seedance-2-0-pro', model_key='doubao-seedance-2-0-pro', modality='video'))
        self.assertEqual(older['family'], 'seedance_2_0')
        self.assertEqual(older['video_duration_max'], 15)
        kling = input_validation_for(dict(id='kling-v2', model_key='kling-v2', modality='image', capabilities=dict(max_reference_images=4)))
        self.assertEqual(kling['family'], 'kling_4')
        self.assertEqual(kling['image_short_edge_min'], 300)
        wan = input_validation_for(dict(model_key='wan2.6-i2v-plus', modality='video'))
        self.assertEqual(wan['family'], 'wan_3_0')
        self.assertLess(wan['image_aspect_min'], 0.34)
        counted = input_validation_for(dict(id='seedream', model_key='doubao-seedream-5-5-261028', capabilities=dict(max_reference_images=10)))
        self.assertEqual(counted, dict(family='reference_count', max_reference_images=10))
        self.assertIsNone(input_validation_for(dict(id='plain-image', model_key='gpt-image-2', modality='image')))
        catalogue = canvas_capabilities([dict(
            id='kling-x', model_key='kling-v2', modality='image', enabled=True, adapter_available=True,
            capabilities=dict(max_reference_images=4, purposes=['image_edit'], reference_media=True),
        )])
        self.assertEqual(catalogue['model_params']['kling-x']['input_validation']['family'], 'kling_4')
        self.assertEqual(catalogue['model_params']['doubao-seedance-2-5-260628']['input_validation']['family'], 'seedance_2_5')

    def test_optimize_uses_text_host_and_keeps_translate_reason(self):
        self.assertEqual(OUTPUT_FIELDS['optimize'], ['body'])
        service = CreativeCanvasService.__new__(CreativeCanvasService)
        service.get_project = lambda project_id: {'id': project_id}
        service.get_creative_canvas = lambda project_id, canvas_id: {'id': canvas_id}

        class Host:
            name = 'fake-text-tools'

            def __init__(self, available=True, body='优化后的雪夜'):
                self._available = available
                self._body = body
                self.seen = None

            def available(self):
                return self._available

            def generate(self, tool, action, document, references):
                self.seen = (tool, action, document, references)
                return {'body': self._body}

        host = Host()
        service.text_tool_host = host
        result = service.optimize_canvas_prompt('p1', {'canvas_id': 'c1', 'node_id': 'n1', 'text': '雪夜'})
        self.assertEqual(result['text'], '优化后的雪夜')
        self.assertEqual(host.seen[0], 'canvas')
        self.assertEqual(host.seen[1], 'optimize')
        self.assertIn('不编造事实', host.seen[2]['instruction'])

        down = Host(available=False)
        service.text_tool_host = down
        status = service.canvas_prompt_assist_status()
        self.assertIn('翻译不可用', status['unavailable_reason'])
        self.assertNotIn('提示词优化', status['unavailable_reason'])
        self.assertFalse(status['optimize_available'])
        self.assertIn('提示词优化不可用', status['optimize_unavailable_reason'])
        with self.assertRaises(ResourceError) as blocked:
            service.optimize_canvas_prompt('p1', {'text': '雪夜'})
        self.assertEqual(blocked.exception.status_code, 503)

        service.text_tool_host = Host(body='  ')
        with self.assertRaises(ResourceError) as invalid:
            service.optimize_canvas_prompt('p1', {'text': '雪夜'})
        self.assertEqual(invalid.exception.status_code, 502)
        with self.assertRaises(ResourceError):
            service.optimize_canvas_prompt('p1', {'text': '   '})
