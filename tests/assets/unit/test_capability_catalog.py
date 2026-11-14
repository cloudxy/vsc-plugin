"""Registered identities, meaningful projections and bounded plain-text reads."""
from collections import Counter
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import support.paths
from vsc.assets.capability_catalog import CapabilityCatalog, DOCUMENT_LIMIT, SOURCES, identity
from vsc.assets.resource_service import ResourceError


class CapabilityCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='vsc-capabilities-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'repository'
        self.vendor = self.root / 'vendor'
        self.root.mkdir()
        self.vendor.mkdir()
        self.tutorials = {'canvas': ('画布教程', 'docs/guide/canvas.md')}
        self.routes = {'adapt': [('inkos', 'methods/shared/SKILL.md', 'guide', '改编方法')],
                       'script': [('inkos', 'methods/shared/SKILL.md', 'guide', '剧本方法')],
                       'sound': [('openmontage', 'methods/audio/SKILL.md', 'runtime: tool', '声音方法')],
                       'architecture': [('inkos', 'private/SKILL.md', 'guide', '非生产方法')]}
        self.put('docs/guide/canvas.md', '# 画布教程\n真实正文\n')
        self.put('vendor/inkos/methods/shared/SKILL.md', '---\nname: same-name\ndescription: |\n  正文描述\n---\n方法正文\n')
        self.put('vendor/openmontage/methods/audio/SKILL.md', '---\nname: same-name\nversion: 1.2\n---\n声音正文\n')
        self.catalog = CapabilityCatalog(self.root, self.vendor, skills={}, tutorials=self.tutorials,
                                         vendor_routes=self.routes)

    def put(self, path, content):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode('utf-8') if isinstance(content, str) else content)
        return target

    def error(self, document_id, code, status):
        with self.assertRaises(ResourceError) as caught:
            self.catalog.document(document_id)
        self.assertEqual((caught.exception.code, caught.exception.status_code), (code, status))
        self.assertNotIn(str(self.root), str(caught.exception))

    def test_identity_dedup_stage_mapping_and_reference_boundaries(self):
        payload = self.catalog.capabilities()
        methods = [item for item in payload['items'] if item['kind'] == 'external_method']
        self.assertEqual(len(methods), 2)
        self.assertEqual(len({item['id'] for item in methods}), 2)  # Same name, distinct sources.
        first = next(item for item in methods if item['source'] == 'vendor:inkos')
        self.assertEqual(first['origin_stages'], ['adapt', 'script'])
        self.assertEqual(first['stages'], ['adapt', 'script'])
        sound = next(item for item in methods if item['source'] == 'vendor:openmontage')
        self.assertEqual(sound['origin_stages'], ['sound'])
        self.assertEqual(sound['stages'], ['produce'])
        self.assertEqual(sound['version'], '1.2')
        self.assertIsNone(first['version'])
        for item in methods:
            self.assertEqual(item['status'], 'reference')
            self.assertEqual(item['action']['type'], 'read')
            self.assertIsNone(item['action']['target'])
            self.assertFalse(item['action']['requires_project'])
            self.assertEqual(item['installation'], {'state': 'unknown', 'document': 'present'})
            self.assertNotEqual(item['task'], '|')
        self.assertNotIn('private', repr(payload))
        self.assertEqual(first['id'], 'cap_' + sha256(('vendor:inkos\0' + first['path']).encode()).hexdigest())

    def test_canvas_shared_source_skill_retains_distinct_id_and_missing_fields(self):
        self.put('skills/vsc-assets/SKILL.md', '# 素材方法')
        self.catalog.skills = {
            'asset-extraction': {'name': '同名', 'source_skill': 'vsc-assets', 'version': '3.0'},
            'asset-matching': {'name': '同名', 'source_skill': 'vsc-assets'},
            'unknown-new': {'name': '未知元数据', 'source_skill': 'missing'},
        }
        rows = self.catalog.capabilities('canvas')['items']
        self.assertEqual(len({item['id'] for item in rows}), 3)
        self.assertEqual(rows[0]['sha256'], rows[1]['sha256'])
        self.assertTrue(rows[0]['inputs'] and rows[0]['outputs'] and rows[0]['suitable'])
        self.assertEqual(rows[1]['version'], None)
        self.assertEqual(rows[2]['inputs'], [])
        self.assertEqual(rows[2]['outputs'], [])
        self.assertEqual(rows[2]['status'], 'dependency_required')
        self.assertEqual(rows[2]['installation']['document'], 'missing')
        self.assertEqual(rows[0]['action']['target']['params']['skill'], 'asset-extraction')

    def test_real_registered_snapshot_metadata_routes_and_three_tutorials(self):
        from vsc.bootstrap import repository_root
        real = CapabilityCatalog()
        payload = real.capabilities()
        self.assertEqual(payload['status'], 'ok')
        self.assertEqual(Counter(i['kind'] for i in payload['items']),
                         {'canvas_skill': 16, 'builtin_tool': 14, 'tutorial': 3, 'external_method': 22})
        self.assertEqual(len({i['id'] for i in payload['items']}), 55)
        self.assertEqual(len([i for i in payload['items'] if i['source'] == 'vendor:remotion']), 5)
        required = {'id', 'source', 'path', 'name', 'kind', 'stages', 'origin_stages', 'task', 'version',
                    'sha256', 'inputs', 'outputs', 'suitable', 'unsuitable', 'dependencies', 'installation',
                    'status', 'status_reason', 'action', 'related_documents'}
        targets = set()
        for item in payload['items']:
            self.assertEqual(set(item), required)
            for field in ('inputs', 'outputs', 'suitable', 'unsuitable'):
                self.assertTrue(item[field], (item['name'], field))
            self.assertNotEqual(item['task'], '|')
            self.assertNotIn(str(repository_root()), repr(item))
            if item['action']['type'] == 'navigate':
                self.assertTrue(item['action']['requires_project'])
                target = item['action']['target']
                if item['source'] == 'builtin':
                    self.assertIn('在能力中心自动创建', item['unsuitable'][0])
                    self.assertNotIn('在首页自动创建', item['unsuitable'][0])
                    targets.add((target['page'], tuple(target['params'].items())))
                else:
                    self.assertEqual(target['page'], 'creative-canvas')
            else:
                if item['source'] == 'tutorial':
                    self.assertEqual(item['installation']['document'], 'present')
                if item['installation']['document'] == 'present':
                    doc = real.document(item['action']['document_id'])
                    self.assertEqual(doc['title'], item['name'])
                    self.assertEqual(doc['sha256'], item['sha256'])
                    self.assertTrue(doc['content'].strip())
                    self.assertEqual(doc['format'], 'text/plain')
                else:
                    self.assertEqual(item['status'], 'dependency_required')
                    self.assertIsNone(item['sha256'])
                    with self.assertRaises(ResourceError) as missing_doc:
                        real.document(item['action']['document_id'])
                    self.assertEqual((missing_doc.exception.code, missing_doc.exception.status_code), ('document_not_found', 404))
        expected = {('text-tools', (('tool', key),)) for key in ('novel', 'translation', 'scoring', 'breakdown', 'qc', 'overseas')}
        expected |= {('classic-production', (('kind', key),)) for key in ('image', 'video')}
        expected |= {(p, ()) for p in ('intelligent-creation', 'marketing-studio', 'editing', 'delivery')}
        expected |= {('creative-tools', (('tool', key),)) for key in ('segment_remake', 'breakdown')}
        self.assertEqual(targets, expected)
        video = next(i for i in payload['items'] if i['path'] == 'page/text-tools?tool=breakdown')
        self.assertEqual(video['name'], '视频拉片')
        self.assertIn('视频', video['inputs'][0])
        self.assertNotIn('剧本', video['inputs'][0])

    def test_bad_vendor_source_isolated_and_empty_is_success(self):
        # Both sources participate in the same original stage.
        self.routes['script'].append(('openmontage', 'methods/audio/SKILL.md', 'runtime: tool', '同阶段方法'))
        before = self.catalog.capabilities()
        good_ids = {i['id'] for i in before['items'] if i['source'] != 'vendor:inkos'}
        self.put('vendor/inkos/methods/shared/SKILL.md', b'\xff')
        after = self.catalog.capabilities()
        self.assertEqual(after['status'], 'partial')
        self.assertEqual(good_ids, {i['id'] for i in after['items']})
        self.assertEqual(next(s for s in after['sources'] if s['id'] == 'vendor:inkos')['status'], 'error')
        self.assertEqual(self.catalog.capabilities('vendor:inkos')['status'], 'unavailable')
        self.assertEqual(self.catalog.capabilities('vendor:remotion'), dict(schema_version=1, status='ok',
            sources=[dict(id='vendor:remotion', status='ok', error=None)], items=[]))
        with self.assertRaises(ResourceError) as caught:
            self.catalog.capabilities('vendor:anywhere')
        self.assertEqual((caught.exception.code, caught.exception.status_code), ('invalid_capability_source', 422))

    def test_document_bytes_identity_and_plain_text(self):
        path = 'docs/guide/canvas.md'
        body = '# 画布\r\n<script>alert(1)</script>\n[链接](file:///etc/passwd)\n'
        self.put(path, body)
        doc_id = identity('doc_', 'tutorial', path)
        row = self.catalog.document(doc_id)
        self.assertEqual(row, dict(schema_version=1, id=doc_id, title='画布教程', source='tutorial',
            path=path, format='text/plain', content=body, sha256=sha256(body.encode()).hexdigest()))
        self.assertEqual(self.catalog.document(doc_id), row)  # Repeated reads have no state.

    def test_unknown_illegal_ids_never_accept_paths(self):
        for value in ('../config/.env', '/etc/passwd', 'doc_' + 'a' * 63, 'doc_' + 'A' * 64,
                      'doc_' + 'f' * 64, 'doc_' + '0' * 64 + '?path=config/.env'):
            with self.subTest(value=value):
                self.error(value, 'document_not_found', 404)

    def test_missing_empty_non_utf8_io_error_and_size_boundary(self):
        path = 'docs/guide/canvas.md'
        doc_id = identity('doc_', 'tutorial', path)
        (self.root / path).unlink()
        self.error(doc_id, 'document_not_found', 404)
        for content in ('', ' \n\t', b'\xff\xfe'):
            with self.subTest(content=content):
                self.put(path, content)
                self.error(doc_id, 'document_unavailable', 503)
        self.put(path, b'a' * DOCUMENT_LIMIT)
        self.assertEqual(len(self.catalog.document(doc_id)['content']), DOCUMENT_LIMIT)
        self.put(path, b'a' * (DOCUMENT_LIMIT + 1))
        self.error(doc_id, 'document_too_large', 413)
        with patch.object(Path, 'open', side_effect=PermissionError('private path')):
            self.error(doc_id, 'document_unavailable', 503)

    def test_registered_traversal_absolute_path_source_and_file_symlinks_are_forbidden(self):
        for path in ('../outside.md', '/etc/passwd', 'docs/guide/../secret.md', 'docs\\guide\\secret.md'):
            self.catalog.tutorials = {'unsafe': ('秘密', path)}
            self.error(identity('doc_', 'tutorial', path), 'document_forbidden', 403)
        self.catalog.tutorials = self.tutorials
        outside = self.root.parent / 'outside'
        outside.mkdir()
        (outside / 'SKILL.md').write_text('private data', encoding='utf-8')
        # A declared source may not be a symlink outside the controlled vendor root.
        source = self.vendor / 'openwrite'
        source.symlink_to(outside, target_is_directory=True)
        self.routes['script'].append(('openwrite', 'SKILL.md', 'guide', '越界'))
        self.error(identity('doc_', 'vendor:openwrite', 'openwrite/SKILL.md'), 'document_forbidden', 403)
        payload = self.catalog.capabilities()
        self.assertEqual(payload['status'], 'partial')
        self.assertTrue(any(i['source'] == 'vendor:inkos' for i in payload['items']))
        # Nor may a registered file escape its own source into another source.
        escape = self.vendor / 'inkos/escape/SKILL.md'
        escape.parent.mkdir()
        escape.symlink_to(self.vendor / 'openmontage/methods/audio/SKILL.md')
        self.routes['direct'] = [('inkos', 'escape/SKILL.md', 'guide', '越界')]
        self.error(identity('doc_', 'vendor:inkos', 'inkos/escape/SKILL.md'), 'document_forbidden', 403)
        tutorial_link = self.put('docs/guide/link.md', 'placeholder')
        tutorial_link.unlink()
        tutorial_link.symlink_to(outside / 'SKILL.md')
        self.catalog.tutorials = {'link': ('越界教程', 'docs/guide/link.md')}
        self.error(identity('doc_', 'tutorial', 'docs/guide/link.md'), 'document_forbidden', 403)

    def test_registered_vendor_traversal_and_source_mount_rechecked_each_read(self):
        self.routes['post'] = [('inkos', '../openmontage/methods/audio/SKILL.md', 'guide', '非法登记')]
        path = 'inkos/../openmontage/methods/audio/SKILL.md'
        self.error(identity('doc_', 'vendor:inkos', path), 'document_forbidden', 403)
        doc_id = identity('doc_', 'vendor:inkos', 'inkos/methods/shared/SKILL.md')
        self.assertTrue(self.catalog.document(doc_id)['content'])
        target = self.vendor / 'inkos/methods/shared/SKILL.md'
        target.unlink()
        target.symlink_to(self.vendor / 'openmontage/methods/audio/SKILL.md')
        self.error(doc_id, 'document_forbidden', 403)


if __name__ == '__main__':
    unittest.main()
