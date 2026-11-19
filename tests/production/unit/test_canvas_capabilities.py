"""Catalogue and execution share local operation semantics and model identities."""
import unittest

from vsc.assets.creative_canvas import normalize_document
from vsc.assets.resource_service import ResourceError
from vsc.production.canvas_capabilities import canvas_capabilities, validate_work_operation


class CanvasCapabilitiesTests(unittest.TestCase):
    def test_catalogue_matches_registered_capabilities_without_remote_aliases(self):
        models = [dict(id='local-image', modality='image', enabled=True, adapter_available=True,
                       capabilities=dict(purposes=['image_edit'], reference_media=True)),
                  dict(id='local-video', modality='video', enabled=True, adapter_available=True,
                       capabilities=dict(first_frame=True, last_frame=False)),
                  dict(id='disabled', modality='image', enabled=False, capabilities={})]
        result = canvas_capabilities(models)
        operations = {op['op_type']: op for op in result['operations']}
        self.assertEqual(len(operations), 55)  # prior catalogue plus audio_to_video and video_edit.
        self.assertEqual(operations['image_three_view']['supported_models'], ['local-image'])
        self.assertFalse(operations['image_upscale']['available'])
        self.assertTrue(operations['single_image_video']['available'])
        self.assertFalse(operations['head_tail_video']['available'])
        self.assertTrue(operations['image_layer_composition']['available'])
        self.assertEqual(operations['image_layer_composition']['consumer'], 'editor')
        self.assertFalse(operations['image_layer_composition']['unavailable_reason'])
        self.assertTrue(operations['image_layer_separation']['available'])
        self.assertEqual(operations['image_layer_separation']['action'], 'layer_separation')
        result['operations'].clear()
        self.assertEqual(len(canvas_capabilities([])['operations']), 55)

    def test_fixed_operation_validates_ports_cardinality_and_node_type(self):
        nodes = {n['id']: n for n in [dict(id='first', type='image'), dict(id='last', type='image'),
            dict(id='v', type='video', params=dict(vsc_operation='head_tail_video'))]}
        edges = [dict(source='first', target='v', port='first_frame'), dict(source='last', target='v', port='last_frame')]
        self.assertEqual(validate_work_operation(nodes['v'], edges, nodes)['mode'], 'first_last')
        for bad in [edges[:1], edges + [edges[0]], [dict(source='first', target='v', port='reference_image')]]:
            with self.subTest(edges=bad), self.assertRaises(ResourceError):
                validate_work_operation(nodes['v'], bad, nodes)
        with self.assertRaises(ResourceError):
            normalize_document(dict(nodes=[dict(id='wrong', type='audio', params=dict(vsc_operation='head_tail_video'))]))
        with self.assertRaises(ResourceError):
            normalize_document(dict(nodes=[dict(id='wrong', type='image', params=dict(vsc_operation='image_three_view'))]))
        self.assertIsNone(validate_work_operation(dict(id='old', type='video', params={}), [], {}))

    def test_editor_and_unavailable_operations_cannot_be_submitted_as_generation(self):
        for operation in ['source_video', 'video_clip', 'seedance_long_video']:
            with self.subTest(operation=operation), self.assertRaises(ResourceError):
                validate_work_operation(dict(id='v', type='video', params=dict(vsc_operation=operation)), [], {})

    def test_model_params_camera_options_and_overrides_match_reference_shape(self):
        models = [
            dict(
                id='ark-seedream-55',
                model_key='doubao-seedream-5-5-261028',
                modality='image',
                enabled=True,
                adapter_available=True,
                capabilities=dict(purposes=['first_frame', 'image_edit'], reference_media=True, max_reference_images=10),
            ),
            dict(
                id='gpt-img-26',
                model_key='gpt-image-2.6-pro_sr',
                modality='image',
                enabled=True,
                adapter_available=True,
                capabilities=dict(purposes=['first_frame', 'image_edit'], reference_media=True, max_reference_images=8),
            ),
            dict(
                id='ark-seedance-25',
                model_key='doubao-seedance-2-5-260628',
                modality='video',
                enabled=True,
                adapter_available=True,
                capabilities=dict(purposes=['text_to_video', 'image_to_video', 'reference_to_video'],
                                  first_frame=True, last_frame=True, reference_media=True, max_reference_images=12),
            ),
        ]
        result = canvas_capabilities(models)
        operations = {op['op_type']: op for op in result['operations']}
        cam = operations['image_generate']['camera_options']
        self.assertIsNotNone(cam)
        self.assertEqual(len(cam['cameras']), 9)
        self.assertEqual(len(cam['lenses']), 10)
        self.assertEqual([f['value'] for f in cam['focal_lengths']], [8, 14, 24, 35, 50, 75, 125])
        self.assertEqual([a['id'] for a in cam['apertures']], ['f/1.4', 'f/4', 'f/11'])

        seedream = result['model_params']['ark-seedream-55']
        self.assertEqual(seedream['show_name'], 'Seedream 5.5')
        self.assertEqual(seedream['resolutions'], ['1.5K', '2K'])
        self.assertNotIn('4:5', seedream['aspect_ratios'])
        self.assertEqual(seedream['backgrounds'], ['auto', 'opaque'])
        self.assertEqual([f['type'] for f in seedream['output_formats']], ['png', 'jpeg', 'webp'])
        self.assertEqual(seedream['counts'], [1, 2, 4])

        gimg = result['model_params']['gpt-img-26']
        self.assertEqual(gimg['show_name'], 'GImage 2.6 Pro')
        self.assertEqual(gimg['resolutions'], ['1K', '2K', '4K'])
        self.assertIn('4:5', gimg['aspect_ratios'])
        self.assertEqual(gimg['backgrounds'], ['auto', 'opaque', 'transparent'])
        self.assertEqual([q['quality'] for q in gimg['qualities']], ['max', 'xhigh', 'high', 'medium', 'low'])
        self.assertEqual([f['type'] for f in gimg['output_formats']], ['png', 'jpeg', 'webp', 'gif'])

        seedance = result['model_params']['ark-seedance-25']
        self.assertEqual(seedance['show_name'], 'Seedance 2.5')
        self.assertEqual(seedance['resolutions'], ['480P', '720P', '1080P', '4K'])
        self.assertIn('adaptive', seedance['aspect_ratios'])
        self.assertEqual(seedance['durations'], list(range(4, 31)))
        self.assertTrue(seedance['generate_audio'])

        overrides = {(row['model_id'], row['op_type']): row for row in result['model_overrides']}
        self.assertIn(('ark-seedream-55', 'image_generate'), overrides)
        ref_port = next(p for p in overrides[('ark-seedream-55', 'image_generate')]['input_ports'] if p['handle'] == 'reference')
        self.assertEqual(ref_port['max_count'], 10)

