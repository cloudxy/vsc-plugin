"""Packaged external case metadata; pure fixed-spec codecs never read a catalog."""
from collections import Counter
from copy import deepcopy
import hashlib
from importlib import resources
import json
import re
from urllib.parse import urlsplit

from vsc.assets.resource_service import ResourceError


CASE_FIELDS = ("schema", "id", "version", "sha256", "source_origin", "template_key", "group_key", "category_name",
    "category_label", "group_name", "group_description", "video_name", "cover_url", "video_url", "width", "height",
    "evidence_id", "evidence_body_sha256")
CASE_PREFIX = "marketing_case_"
METADATA_SHA256 = "e4adaf87308d379755295f25ed558941a58d221f3b9677f4359fe90b3851af99"


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _fail(message="案例引用格式或固定摘要不符", code="invalid_marketing_case", status=422):
    raise ResourceError(message, code, status)


def _sha(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def validate_case_ref(ref):
    if ref is None:
        return None
    if (not isinstance(ref, dict) or set(ref) != {"id", "version", "sha256"} or
            not isinstance(ref["id"], str) or len(ref["id"]) > 2000 or
            re.fullmatch(r"skyproduction:[A-Za-z0-9_-]+", ref["id"]) is None or
            type(ref["version"]) is not int or ref["version"] < 1 or not _sha(ref["sha256"])):
        _fail()
    return deepcopy(ref)


def validate_case_spec(spec):
    if not isinstance(spec, dict) or set(spec) != set(CASE_FIELDS):
        _fail()
    validate_case_ref({key: spec[key] for key in ("id", "version", "sha256")})
    for key, value in spec.items():
        if key in {"version", "width", "height"}:
            if type(value) is not int or value < 1:
                _fail()
        elif not isinstance(value, str) or len(value) > 2000:
            _fail()
    if (spec["schema"] != "vsc.marketing-case/v1" or spec["id"] != "skyproduction:" + spec["template_key"] or
            not _sha(spec["evidence_body_sha256"]) or _digest({k: v for k, v in spec.items() if k != "sha256"}) != spec["sha256"]):
        _fail()
    for key in ("source_origin", "cover_url", "video_url"):
        if not spec[key] and key != "source_origin":
            continue
        try:
            url = urlsplit(spec[key])
        except ValueError:
            _fail()
        if url.scheme not in {"https", "http"} or not url.hostname or url.username or url.password:
            _fail()
        if key == "source_origin" and (url.path or url.query or url.fragment):
            _fail()
    return deepcopy(spec)


def case_spec_to_params(spec):
    return {} if spec is None else {CASE_PREFIX + key: value for key, value in validate_case_spec(spec).items()}


def case_spec_from_params(params):
    if not isinstance(params, dict) or any(not isinstance(key, str) for key in params):
        _fail()
    fixed = {key[len(CASE_PREFIX):]: value for key, value in params.items() if key.startswith(CASE_PREFIX)}
    return validate_case_spec(fixed) if fixed else None


def _groups(catalog):
    pages = {page["page"]: page["response_body_text_utf8_sha256"] for page in catalog["pages"]}
    result = []
    for group in catalog["metadata"]["groups"]:
        examples = []
        for example in group["examples"]:
            spec = dict(schema="vsc.marketing-case/v1", id="skyproduction:" + example["template_key"],
                version=catalog["case_versions"][example["template_key"]], source_origin=catalog["source_origin"],
                **{key: group[key] for key in ("group_key", "category_name", "category_label", "group_name", "group_description")},
                **{key: example[key] for key in ("template_key", "video_name", "cover_url", "video_url", "width", "height")},
                evidence_id=catalog["provenance"]["evidence_id"],
                evidence_body_sha256=pages[catalog["group_sources"][group["group_key"]]])
            spec["sha256"] = _digest(spec)
            examples.append(validate_case_spec(spec))
        result.append(dict({key: group[key] for key in ("group_key", "category_name", "category_label", "group_name", "group_description")}, examples=examples))
    return result


def load_catalog():
    """Read only this package's bytes, independent of cwd or workflow roots."""
    try:
        catalog = json.loads(resources.files("vsc.assets").joinpath("marketing-cases.json").read_text(encoding="utf-8"))
        expected = {"format", "catalog_version", "metadata", "metadata_sha256", "case_versions", "source_origin", "provenance",
                    "pages", "group_sources", "coverage", "observed_detail_keys", "catalog_sha256"}
        if (set(catalog) != expected or catalog["format"] != "vsc.marketing-case-catalog/v1" or
                catalog["metadata_sha256"] != METADATA_SHA256 or _digest(catalog["metadata"]) != METADATA_SHA256 or
                _digest({k: v for k, v in catalog.items() if k != "catalog_sha256"}) != catalog["catalog_sha256"]):
            _fail("包内营销目录摘要不符", "marketing_catalog_integrity", 409)
        categories, groups = catalog["metadata"]["categories"], catalog["metadata"]["groups"]
        if (set(catalog["provenance"]) != {"evidence_id", "har_sha256", "observation_window", "body_digest_scope"} or
                not _sha(catalog["provenance"]["har_sha256"]) or
                set(catalog["provenance"]["observation_window"]) != {"first", "last"}):
            _fail()
        names = [item["category_name"] for item in categories]
        group_keys = [item["group_key"] for item in groups]
        keys = [example["template_key"] for group in groups for example in group["examples"]]
        if (len(names) != len(set(names)) or len(group_keys) != len(set(group_keys)) or len(keys) != len(set(keys)) or
                set(catalog["case_versions"]) != set(keys) or set(catalog["group_sources"]) != set(group_keys)):
            _fail("包内营销目录身份不唯一", "marketing_catalog_integrity", 409)
        counts = Counter(group["category_name"] for group in groups)
        if set(counts) != set(names) or any(type(c["template_count"]) is not int or c["template_count"] != counts[c["category_name"]] for c in categories):
            _fail("包内营销分类数量不符", "marketing_catalog_integrity", 409)
        pages = catalog["pages"]
        if [p["page"] for p in pages] != list(range(1, len(pages) + 1)):
            _fail()
        page_counts = Counter(catalog["group_sources"].values())
        if set(page_counts) != {p["page"] for p in pages} or any(not _sha(p["response_body_text_utf8_sha256"]) or
                p["returned_group_count"] != page_counts[p["page"]] for p in pages):
            _fail()
        coverage = catalog["coverage"]
        if (coverage["available_group_count"] != len(groups) or coverage["available_example_count"] != len(keys) or
                coverage["category_count"] != len(categories) or coverage["detail_sample_count"] != len(catalog["observed_detail_keys"]) or
                not set(catalog["observed_detail_keys"]) <= set(keys)):
            _fail()
        _groups(catalog)
        return catalog
    except (KeyError, TypeError, ValueError, OSError) as error:
        raise ResourceError("包内营销目录格式不符", "marketing_catalog_integrity", 409) from error


def _resolve(catalog, ref):
    ref = validate_case_ref(ref)
    if ref is None:
        _fail()
    spec = next((case for group in _groups(catalog) for case in group["examples"] if case["id"] == ref["id"]), None)
    if spec is None:
        _fail("营销案例不存在", "marketing_case_not_found", 404)
    if any(spec[key] != ref[key] for key in ("version", "sha256")):
        _fail("营销案例版本或摘要已改变", "marketing_case_changed", 409)
    return spec


def resolve_case(ref):
    return _resolve(load_catalog(), ref)


def list_cases(category_name=None, keyword="", page=1, page_size=20, catalog_sha256=None):
    if type(page) is not int or page < 1 or type(page_size) is not int or not 1 <= page_size <= 20 or not isinstance(keyword, str) or len(keyword) > 2000:
        _fail("目录页码、页长或关键词无效")
    catalog = load_catalog()
    if catalog_sha256 is not None and catalog_sha256 != catalog["catalog_sha256"]:
        _fail("营销目录已更新，请重载首页", "marketing_catalog_changed", 409)
    categories = catalog["metadata"]["categories"]
    if category_name not in (None, "") and category_name not in [c["category_name"] for c in categories]:
        _fail("营销类别不存在")
    keyword = keyword.strip().casefold()
    groups = [g for g in _groups(catalog) if (not category_name or g["category_name"] == category_name) and
        (not keyword or any(keyword in value.casefold() for value in [g["group_name"], g["group_description"], g["category_label"],
             *[example["video_name"] for example in g["examples"]]]))]
    counts = Counter(g["category_name"] for g in catalog["metadata"]["groups"])
    return dict(catalog_version=catalog["catalog_version"], catalog_sha256=catalog["catalog_sha256"], coverage=deepcopy(catalog["coverage"]),
        source_reported_total=catalog["coverage"]["source_reported_total"], total_available=len(groups), page=page, page_size=page_size,
        next_page=page + 1 if page * page_size < len(groups) else None,
        categories=[dict(category_name=c["category_name"], category_label=c["category_label"], source_template_count=c["template_count"],
            available_group_count=counts[c["category_name"]]) for c in categories], items=groups[(page - 1) * page_size:page * page_size])


def get_case(ref):
    catalog = load_catalog()
    spec = _resolve(catalog, ref)
    return dict(catalog_version=catalog["catalog_version"], catalog_sha256=catalog["catalog_sha256"], case=spec,
        detail_coverage=dict(basis="list_projection", observed_source_detail=spec["template_key"] in catalog["observed_detail_keys"]))
