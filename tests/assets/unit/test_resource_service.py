"""Application boundary checks run without SQL or a configured database."""
import unittest
from unittest.mock import Mock

from support.paths import ROOT
from vsc.assets.resource_service import ResourceError, ResourceService


class ResourceServiceBoundaryTest(unittest.TestCase):
    def test_untrusted_write_never_commits_upload(self):
        storage, store = Mock(), Mock()
        service = ResourceService(store, storage)
        for kw in ({"expected_revision": 1, "idempotency_key": "x"},
                   {"actor": "human", "idempotency_key": "x"},
                   {"actor": "human", "expected_revision": 1}):
            with self.subTest(missing=sorted(kw)):
                with self.assertRaises(ResourceError):
                    service.register_media("project", {"staged_upload": "token"}, **kw)
        storage.commit_upload.assert_not_called()
        store.register_media.assert_not_called()

    def test_client_cannot_supply_decision_actor(self):
        store = Mock()
        service = ResourceService(store)
        with self.assertRaises(ResourceError) as caught:
            service.select_candidate("p", {"candidate_id": "c", "actor": "fake"},
                expected_revision=0, idempotency_key="one", actor="session-human")
        self.assertEqual(caught.exception.code, "untrusted_actor")
        store.select_candidate.assert_not_called()

    def test_pagination_has_bounded_materialization(self):
        store = Mock()
        service = ResourceService(store)
        for offset, limit in ((-1, 50), (0, 0), (0, 201)):
            with self.subTest(offset=offset, limit=limit), self.assertRaises(ResourceError):
                service.list_resources("p", offset=offset, limit=limit)
        store.list_resources.assert_not_called()

    def test_missing_fixed_bytes_become_context_gap_and_block_selection(self):
        store, storage = Mock(), Mock()
        fixed = {"media_id": "m", "sha256": "a" * 64,
                 "locations": [{"storage": "local", "object_key": "blobs/a", "available": True}]}
        store.compile_shot_context.return_value = {"project_id": "p", "shot_id": "s", "revision": 1,
            "media": [fixed], "gaps": [], "ready": True, "sha256": "b" * 64}
        storage.verify.side_effect = ResourceError("字节损坏", "media_unavailable")
        service = ResourceService(store, storage)
        context = service.compile_shot_context("p", "s")
        self.assertFalse(context["ready"])
        self.assertEqual(context["gaps"], [{"code": "media_unavailable", "media_id": "m"}])
        store.get_binding_candidate.return_value = {"media_id": "m"}
        store.get_media.return_value = dict(fixed, id="m")
        with self.assertRaises(ResourceError):
            service.select_candidate("p", {"candidate_id": "c"}, expected_revision=1, idempotency_key="one", actor="human")
        store.select_candidate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
