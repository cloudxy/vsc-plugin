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
        self.assertEqual(len(operations), 53)  # 52 source operations and local single-image video.
        self.assertEqual(operations['image_three_view']['supported_models'], ['local-image'])
        self.assertFalse(operations['image_upscale']['available'])
        self.assertTrue(operations['single_image_video']['available'])
        self.assertFalse(operations['head_tail_video']['available'])
        self.assertFalse(operations['image_layer_composition']['available'])
        self.assertTrue(operations['image_layer_composition']['unavailable_reason'])
        result['operations'].clear()
        self.assertEqual(len(canvas_capabilities([])['operations']), 53)

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
