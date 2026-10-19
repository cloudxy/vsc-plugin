"""Stable identity kinds and browse vocabulary, independent of execution support.

Kinds describe business identities. Categories are many-to-many browse labels;
modality and binding purpose retain their own existing authorities.
"""

IDENTITY_KINDS = ("character", "location", "prop", "voice", "style", "costume",
                  "object", "creature", "vehicle", "plant")
BIBLE_KINDS = ("character", "prop", "object", "location", "creature", "vehicle", "plant")
SPECIFICATION_KINDS = ("voice", "style", "costume")
# Existing persisted codes are retained verbatim; there is no prop fallback.
LEGACY_KIND_MAPPING = {kind: kind for kind in IDENTITY_KINDS}

_GROUPS = (
    ("character", "人物与角色", (("identity", "人物身份"), ("face_body", "脸与身体"), ("expression", "表情"),
        ("makeup_hair", "妆发"), ("costume", "服装"), ("action_lipsync", "动作与口型"), ("age_crowd", "年龄与群演"), ("voiceprint", "声纹"))),
    ("environment", "背景环境", (("location", "地点母版"), ("views", "地点多视角"), ("layout", "结构布局地形"),
        ("sky_weather", "天空日夜天气"), ("lighting", "灯光"), ("material_depth", "材质深度蒙版"))),
    ("prop", "道具", (("handheld", "剧情与手持"), ("furniture", "家具"), ("vehicle", "车船"), ("weapon_tool", "武器工具"),
        ("food", "饮食"), ("electronics", "电子"), ("documents", "纸张证件"), ("damage", "破损状态"))),
    ("creature", "生物", (("animal", "动物"), ("insect", "昆虫"), ("pet", "宠物"), ("fantasy", "幻想生物"), ("crowd", "生物群体"))),
    ("plant", "植物", (("tree_flower", "树木花草"), ("vine", "藤蔓"), ("crop", "农作物"), ("fallen", "落叶花瓣"), ("community", "植物群落"))),
    ("sound", "声音", (("voice", "声纹与干声"), ("narration", "旁白"), ("ambience", "环境"), ("sfx", "音效与拟音"),
        ("music", "BGM"), ("impulse_response", "IR混响"), ("phoneme", "音素时码"), ("level", "电平规范"))),
    ("text", "字幕与文字", (("subtitle", "字幕文本"), ("style", "字幕样式"), ("title", "标题片尾"), ("screen", "屏幕文字"),
        ("language", "多语言与词库"), ("font", "字体与授权"))),
    ("vfx", "视觉与动态特效", (("weather", "天气粒子"), ("magic_explosion", "法术爆炸"), ("transition", "转场"),
        ("alpha", "Alpha层"), ("screen", "屏幕画面"), ("sticker", "贴纸"))),
    ("camera_style", "镜头与风格控制", (("camera", "相机运镜构图"), ("style", "视觉风格"), ("lut_grain", "LUT与颗粒"),
        ("prompt", "提示词与负词"), ("model", "模型与LoRA"), ("control", "控制图与蒙版"))),
    ("post", "后期与包装", (("opening_ending", "片头片尾"), ("logo", "Logo水印"), ("graphics", "花字转场包"),
        ("template", "混音渲染模板"), ("cover", "封面海报"), ("delivery", "发布包装"))),
    ("document", "制作文档与规则", (("script", "剧本"), ("storyboard", "分镜"), ("continuity", "场记与连续性"),
        ("bible", "圣经"), ("approval", "批准凭证"), ("rights", "版权凭证"), ("dictionary", "词库与规则"))),
)

CATEGORIES = tuple(row for order, (code, label, children) in enumerate(_GROUPS)
    for row in ({"code": code, "label": label, "parent_code": None, "ordinal": order},
                *({"code": code + "." + child, "label": title, "parent_code": code, "ordinal": n}
                  for n, (child, title) in enumerate(children))))
CATEGORY_BY_CODE = {row["code"]: row for row in CATEGORIES}
TOP_LEVEL_CATEGORIES = tuple(code for code, _, _ in _GROUPS)
KIND_CATEGORIES = {
    "character": ("character",), "location": ("environment",), "prop": ("prop",),
    "object": ("prop",), "creature": ("creature",), "vehicle": ("prop.vehicle",),
    "plant": ("plant",), "voice": ("sound.voice", "character.voiceprint"),
    "style": ("camera_style.style",), "costume": ("character.costume",),
}


def category_descendants(code):
    """Return dictionary codes only; an unknown code never becomes a wildcard."""
    if code not in CATEGORY_BY_CODE:
        raise ValueError("未知资源分类: " + str(code))
    return tuple(row["code"] for row in CATEGORIES if row["code"] == code or row["code"].startswith(code + "."))


def identity_categories(kind):
    if kind not in IDENTITY_KINDS:
        raise ValueError("未知资产身份种类: " + str(kind))
    return KIND_CATEGORIES[kind]
