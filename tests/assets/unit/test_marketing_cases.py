"""Full retained metadata, fixed codecs, and pre-case 0.47.30 golden intent."""
from copy import deepcopy
from importlib import resources
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from vsc.assets import marketing_cases as C
from vsc.assets.marketing_studio import _request
from vsc.assets.resource_service import ResourceError, ResourceService


# Captured from the unmodified 0.47.30 implementation (HEAD 21e3357), before
# adding case_ref support. These expectations are not compiled by new helpers.
LEGACY_FIXED_JSON = '{"episode_id":null,"media_ids":[],"method_id":null,"method_sha256":null,"method_version":null,"prompt":"  旧版原始需求🛍\\n"}'
LEGACY_SHA = "5aed26603b8d084949126662607430db194af4f10fea51ee336e7eb101632b62"
LEGACY_CREATE_JSON = '{"document":{"edges":[],"nodes":[{"group":"","id":"marketing-brief","job_id":null,"media_id":null,"params":{"marketing_request_sha256":"5aed26603b8d084949126662607430db194af4f10fea51ee336e7eb101632b62","marketing_role":"brief","skill_id":"vsc-assets"},"text":"  旧版原始需求🛍\\n","title":"营销原始需求","type":"text","x":80.0,"y":80.0}],"viewport":{"x":0.0,"y":0.0,"zoom":1.0}},"episode_id":null,"title":"营销工作室 · 通用需求"}'
LEGACY_RESPONSE_JSON = '{"agent_handoff":{"message":"  旧版原始需求🛍\\n","node_ids":["marketing-brief"],"skill_id":"vsc-assets"},"brief_node_id":"marketing-brief","canvas_id":"33333333-3333-4333-8333-333333333333","canvas_revision":1,"episode_id":null,"id":"33333333-3333-4333-8333-333333333333","material_node_ids":[],"method_node_id":null,"provider_submitted":false,"revision":1}'


class MarketingCaseTests(unittest.TestCase):
    def first(self):
        return C.list_cases()["items"][0]["examples"][0]

    def test_complete_counts_pagination_and_all_detail_projections(self):
        first = C.list_cases()
        self.assertEqual(first["catalog_sha256"], "3574def15e6793d988c9c788ff1c3814ad879ab96677abeae84f7493e11becd9")
        self.assertEqual(first["source_reported_total"], 114)
        self.assertEqual([c["available_group_count"] for c in first["categories"]], [6, 27, 10, 28, 13, 5, 9, 10, 2, 2, 2])
        pages = [C.list_cases(page=i, catalog_sha256=first["catalog_sha256"]) for i in range(1, 7)]
        self.assertEqual([len(page["items"]) for page in pages], [20, 20, 20, 20, 20, 14])
        self.assertEqual([page["next_page"] for page in pages], [2, 3, 4, 5, 6, None])
        cases = [case for page in pages for group in page["items"] for case in group["examples"]]
        self.assertEqual(len({case["id"] for case in cases}), 114)
        self.assertEqual(cases[0]["sha256"], "25dd8536d74c328802001d91cf1181d782ef288275c72369f4f511940605bd99")
        observed = []
        for case in cases:
            with self.subTest(case=case["id"]):
                detail = C.get_case({key: case[key] for key in ("id", "version", "sha256")})
                self.assertEqual(detail["case"], case)
                self.assertEqual(set(case), set(C.CASE_FIELDS))
                self.assertEqual((case["width"], case["height"]), (720, 1280))
                if detail["detail_coverage"]["observed_source_detail"]:
                    observed.append(case["template_key"])
        self.assertEqual(observed, ["approved_7135edbbae7c4181"])

    def test_local_filters_stale_catalog_and_invalid_queries(self):
        for category in C.list_cases()["categories"]:
            with self.subTest(category=category["category_name"]):
                page = C.list_cases(category_name=category["category_name"])
                self.assertEqual(page["total_available"], category["available_group_count"])
                self.assertTrue(all(g["category_name"] == category["category_name"] for g in page["items"]))
        self.assertEqual(C.list_cases(keyword="  屏幕里的复古时装广告  ")["items"][0]["examples"][0], self.first())
        self.assertEqual(C.list_cases(keyword="not-a-real-retained-case")["total_available"], 0)
        self.assertEqual(C.list_cases(keyword="not-a-real-retained-case")["source_reported_total"], 114)
        for args in (dict(page=True), dict(page=0), dict(page_size=21), dict(category_name="unknown"), dict(keyword=[])):
            with self.subTest(args=args), self.assertRaises(ResourceError):
                C.list_cases(**args)
        with self.assertRaises(ResourceError) as changed:
            C.list_cases(catalog_sha256="0" * 64)
        self.assertEqual(changed.exception.code, "marketing_catalog_changed")

    def test_fixed_scalar_codec_without_live_catalog_and_rejects_bad_params(self):
        case = self.first()
        params = C.case_spec_to_params(case)
        with patch.object(C, "load_catalog", side_effect=AssertionError("fixed codec must be offline")):
            self.assertEqual(C.case_spec_from_params(dict(params, marketing_role="brief")), case)
            self.assertIsNone(C.case_spec_from_params({"marketing_role": "brief"}))
            self.assertEqual(C.case_spec_to_params(None), {})
            self.assertEqual(C.validate_case_ref({k: case[k] for k in ("id", "version", "sha256")})["id"], case["id"])
        for changed in (dict(params, marketing_case_width=True), dict(params, marketing_case_extra="forged"),
                {"marketing_case_id": case["id"]}, dict(params, marketing_case_sha256="0" * 64),
                dict(params, marketing_case_group_description="changed")):
            with self.subTest(changed=changed), self.assertRaises(ResourceError):
                C.case_spec_from_params(changed)
        ref = {key: case[key] for key in ("id", "version", "sha256")}
        for bad in (dict(ref, version=True), dict(ref, id="skyproduction:../bad"), case):
            with self.subTest(bad=bad), self.assertRaises(ResourceError):
                C.validate_case_ref(bad)
        for ref, status in ((dict(ref, id="skyproduction:unknown"), 404), (dict(ref, version=2), 409)):
            with self.subTest(status=status), self.assertRaises(ResourceError) as failed:
                C.resolve_case(ref)
            self.assertEqual(failed.exception.status_code, status)

    def test_legacy_omitted_and_null_intent_document_and_receipt_match_030_goldens(self):
        for extra in ({}, {"case_ref": None}):
            with self.subTest(extra=extra):
                payload = dict(prompt="  旧版原始需求🛍\n", **extra)
                fixed, _, sha = _request(payload)
                self.assertEqual(json.dumps(fixed, ensure_ascii=False, sort_keys=True, separators=(",", ":")), LEGACY_FIXED_JSON)
                self.assertEqual(sha, LEGACY_SHA)
                store = Mock()
                store.get_operation_receipt.return_value = dict(found=False, response=None)
                store.create_creative_canvas.return_value = dict(id="33333333-3333-4333-8333-333333333333", canvas_revision=1, revision=1)
                with patch.object(C, "load_catalog", side_effect=AssertionError("legacy must not load catalog")):
                    response = ResourceService(store).create_marketing_canvas("11111111-1111-4111-8111-111111111111", payload,
                        actor="test-human", expected_revision=0, idempotency_key="legacy-before-case")
                self.assertEqual(json.dumps(store.create_creative_canvas.call_args.args[1], ensure_ascii=False, sort_keys=True, separators=(",", ":")), LEGACY_CREATE_JSON)
                self.assertEqual(json.dumps(response, ensure_ascii=False, sort_keys=True, separators=(",", ":")), LEGACY_RESPONSE_JSON)

    def test_packaged_resource_does_not_follow_workflow_root_or_working_directory(self):
        expected = C.load_catalog()["catalog_sha256"]
        raw = resources.files("vsc.assets").joinpath("marketing-cases.json").read_text(encoding="utf-8")
        for private in (".vsc-local", "/private/", "/Users/", "authorization", "cookie", "request_headers"):
            self.assertNotIn(private, raw.lower() if private == private.lower() else raw)
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"VSC_WORKFLOW_ROOT": directory}):
            original = Path.cwd()
            try:
                os.chdir(directory)
                Path("marketing-cases.json").write_text("{}")
                self.assertEqual(C.load_catalog()["catalog_sha256"], expected)
            finally:
                os.chdir(original)
        first = C.load_catalog()
        first["metadata"]["groups"].clear()
        self.assertEqual(len(C.load_catalog()["metadata"]["groups"]), 114)

    def test_synthetic_multi_example_identity_is_not_forced_to_group_key(self):
        catalog = C.load_catalog()
        group = catalog["metadata"]["groups"][0]
        second = deepcopy(group["examples"][0])
        second["template_key"] = "synthetic_second_example"
        group["examples"].append(second)
        catalog["case_versions"][second["template_key"]] = 1
        examples = C._groups(catalog)[0]["examples"]
        self.assertEqual(len(examples), 2)
        self.assertEqual(examples[1]["group_key"], examples[0]["group_key"])
        self.assertNotEqual(examples[1]["id"], examples[0]["id"])
