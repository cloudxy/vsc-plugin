"""Closed official dimensions and the alias map mirrored by migration 0060.

Stored classification lives in the class tables. These constants are the
request allow-list and the vocabulary the migration seeds. ``role_tag`` on
a publication remains the original label.
"""
import re

SCENE_TYPES = ("住宅", "商业", "办公", "医疗", "教育", "餐饮", "其他", "未识别")
SPACES = ("室内", "室外", "半室外", "未识别")
PROP_TYPES = ("武器", "饰品", "服饰配件", "文件/书籍", "通讯/电子", "医疗", "其他")
UNRECOGNIZED = "未识别"

_AGE_GENDER = re.compile(r"^(幼年|少年|青年|中年|老年|壮年)(男|女)$")
_OUTDOOR_OTHER = ("其他", "室外")
_HOME_INDOOR = ("住宅", "室内")

LOCATION_ALIASES = {
    "街巷": _OUTDOOR_OTHER,
    "街巷夜": _OUTDOOR_OTHER,
    "石拱桥": _OUTDOOR_OTHER,
    "山林道": _OUTDOOR_OTHER,
    "夜雨山道": _OUTDOOR_OTHER,
    "市集": _OUTDOOR_OTHER,
    "屋顶天台": _OUTDOOR_OTHER,
    "废墟": _OUTDOOR_OTHER,
    "校园": _OUTDOOR_OTHER,
    "校园夜": _OUTDOOR_OTHER,
    "宅院厅堂": _HOME_INDOOR,
    "宅院厅堂夜": _HOME_INDOOR,
    "客栈大堂": _HOME_INDOOR,
    "客栈大堂夜": _HOME_INDOOR,
    "闺房妆台": _HOME_INDOOR,
    "厨房": _HOME_INDOOR,
    "豪宅客厅": _HOME_INDOOR,
    "卧房": _HOME_INDOOR,
    "卧房夜": _HOME_INDOOR,
    "民居堂屋": _HOME_INDOOR,
    "祠堂": _HOME_INDOOR,
    "祠堂夜": _HOME_INDOOR,
    "洞府": _HOME_INDOOR,
    "医院走廊": ("医疗", "室内"),
    "医院病房": ("医疗", "室内"),
    "实验楼走廊": ("医疗", "室内"),
    "车厢": ("其他", "室内"),
    "牢狱": ("其他", "室内"),
    "学校课堂": ("教育", "室内"),
    "学校礼堂": ("教育", "室内"),
    "办公室": ("办公", "室内"),
    "未标注": (UNRECOGNIZED, UNRECOGNIZED),
    "其他": ("其他", UNRECOGNIZED),
}

PROP_ALIASES = {
    "长枪": "武器",
    "手枪": "武器",
    "长剑": "武器",
    "柳叶刀": "武器",
    "兵器": "武器",
    "中山装": "服饰配件",
    "虎": "其他",
    "飞船": "其他",
}


def character_tags(role_tag):
    """Role-tag chips. A stored age-and-gender label is not a role tag."""
    parts = [part.strip() for part in (role_tag or "").split(" / ") if part.strip()]
    return [part for part in parts if _AGE_GENDER.fullmatch(part) is None]


def classify_location(role_tag):
    text = (role_tag or "").strip()
    parts = [part.strip() for part in text.split(" / ") if part.strip()]
    if len(parts) >= 2 and parts[0] in SCENE_TYPES and parts[1] in SPACES:
        return parts[0], parts[1]
    if text in LOCATION_ALIASES:
        return LOCATION_ALIASES[text]
    return UNRECOGNIZED, UNRECOGNIZED


def classify_prop(role_tag):
    text = (role_tag or "").strip()
    first = text.split(" / ", 1)[0].strip() if text else ""
    for candidate in (text, first):
        if candidate in PROP_TYPES:
            return candidate
        if candidate in PROP_ALIASES:
            return PROP_ALIASES[candidate]
    return "其他"


def presentation(asset_kind, role_tag):
    """Fields added beside the stored publication. They do not replace ``role_tag``."""
    kind = asset_kind or ""
    if kind == "location":
        scene, space = classify_location(role_tag)
        return {"role_tags": [], "scene_type": scene, "space": space, "prop_type": ""}
    if kind == "prop":
        return {"role_tags": [], "scene_type": "", "space": "", "prop_type": classify_prop(role_tag)}
    if kind == "character":
        return {"role_tags": character_tags(role_tag), "scene_type": "", "space": "", "prop_type": ""}
    return {"role_tags": [], "scene_type": "", "space": "", "prop_type": ""}


def _unique_sorted(values):
    return sorted({value for value in values if value})


def character_role_facets(role_tags):
    found = []
    for tag in role_tags:
        found.extend(character_tags(tag))
    return _unique_sorted(found)


def location_facets(role_tags):
    scenes, spaces = [], []
    for tag in role_tags:
        scene, space = classify_location(tag)
        scenes.append(scene)
        spaces.append(space)
    return _unique_sorted(scenes), _unique_sorted(spaces)


def prop_facets(role_tags):
    return _unique_sorted(classify_prop(tag) for tag in role_tags)
