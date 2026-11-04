import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from vsc.adapters.persistence.legacy_json.panel import CatalogError
from vsc.project.resource_catalog import ResourceCatalog


class ResourceCatalogContentTests(unittest.TestCase):
    def test_tries_later_copy_when_first_has_wrong_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'bad').write_bytes(b'changed')
            (root / 'good').write_bytes(b'original')
            row = {'sha256': hashlib.sha256(b'original').hexdigest(), 'locations': [
                {'storage': 'local', 'object_key': 'bad'},
                {'storage': 'local', 'object_key': 'good'},
            ]}
            catalog = ResourceCatalog(root / 'projects', SimpleNamespace(get_media=lambda *_: row), root)
            self.assertEqual(catalog.content_path('project', 'media'), (root / 'good').resolve())
            row['locations'].pop()
            with self.assertRaises(CatalogError) as error:
                catalog.content_path('project', 'media')
            self.assertEqual(error.exception.code, 'hash_mismatch')


if __name__ == '__main__':
    unittest.main()
