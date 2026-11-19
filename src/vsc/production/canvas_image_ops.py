"""Deterministic local pixel operations for Canvas in-place image tooling."""
from __future__ import annotations

import io
import json
import math
import re
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from vsc.assets.resource_service import ResourceError

FILTER_PRESETS = {
    "original": {"hue": 0, "sat": 0, "bri": 0, "con": 0, "tint": (1.0, 1.0, 1.0)},
    "natural_enhance": {"hue": 0, "sat": 8, "bri": 2, "con": 5, "tint": (1.0, 1.0, 1.0)},
    "vivid": {"hue": 0, "sat": 28, "bri": 3, "con": 10, "tint": (1.02, 1.0, 0.98)},
    "anime_crisp": {"hue": -4, "sat": 22, "bri": 5, "con": 18, "tint": (1.0, 1.01, 1.03)},
    "teal_orange": {"hue": -8, "sat": 14, "bri": -2, "con": 16, "tint": (1.06, 0.99, 0.94)},
    "cinema_dark": {"hue": -6, "sat": -14, "bri": -14, "con": 20, "tint": (0.96, 0.98, 1.04)},
    "black_gold": {"hue": 12, "sat": -18, "bri": -10, "con": 24, "tint": (1.08, 1.02, 0.88)},
    "cyberpunk": {"hue": -28, "sat": 34, "bri": 2, "con": 22, "tint": (1.05, 0.92, 1.12)},
    "warm_film": {"hue": 10, "sat": 10, "bri": 4, "con": 8, "tint": (1.06, 1.01, 0.92)},
    "cyan_film": {"hue": -14, "sat": -6, "bri": 2, "con": 10, "tint": (0.93, 1.03, 1.04)},
    "vintage_fade": {"hue": 8, "sat": -22, "bri": 6, "con": -10, "tint": (1.04, 1.01, 0.93)},
    "polaroid": {"hue": 6, "sat": -8, "bri": 8, "con": 6, "tint": (1.03, 1.02, 0.95)},
    "jp_fresh": {"hue": -4, "sat": -10, "bri": 12, "con": -6, "tint": (0.97, 1.02, 1.05)},
    "cream_sun": {"hue": 10, "sat": -6, "bri": 10, "con": -4, "tint": (1.05, 1.02, 0.94)},
    "cool_clear": {"hue": -10, "sat": -8, "bri": 12, "con": 6, "tint": (0.95, 1.01, 1.06)},
    "classic_bw": {"hue": 0, "sat": -100, "bri": 0, "con": 12, "tint": (1.0, 1.0, 1.0)},
    "high_contrast_bw": {"hue": 0, "sat": -100, "bri": -4, "con": 38, "tint": (1.0, 1.0, 1.0)},
    "sepia_retro": {"hue": 24, "sat": -45, "bri": 2, "con": 10, "tint": (1.10, 1.00, 0.84)},
    "night_blue": {"hue": -22, "sat": 12, "bri": -8, "con": 14, "tint": (0.90, 0.97, 1.12)},
    "forest": {"hue": -12, "sat": 10, "bri": -2, "con": 8, "tint": (0.94, 1.06, 0.95)},
    "autumn_orange": {"hue": 16, "sat": 18, "bri": 4, "con": 10, "tint": (1.08, 1.00, 0.90)},
}

FILTER_ALIASES = {
    "none": "original",
    "natural": "natural_enhance",
    "comic": "anime_crisp",
    "moody": "cinema_dark",
    "cyber": "cyberpunk",
    "green_film": "cyan_film",
    "faded": "vintage_fade",
    "instant": "polaroid",
    "cream": "cream_sun",
    "cool_white": "cool_clear",
    "bw": "classic_bw",
    "bw_hard": "high_contrast_bw",
    "sepia": "sepia_retro",
    "night": "night_blue",
    "autumn": "autumn_orange",
    "bright": "vivid",
    "warm": "warm_film",
    "cool": "cool_clear",
}


def resolve_filter_id(filter_id):
    key = str(filter_id or "original").strip() or "original"
    key = FILTER_ALIASES.get(key, key)
    if key not in FILTER_PRESETS:
        raise ResourceError("未知的调色滤镜标识", "invalid_canvas_color_adjust")
    return key


def _open_rgba(content: bytes) -> Image.Image:
    try:
        with Image.open(io.BytesIO(content)) as raw:
            raw.load()
            oriented = ImageOps.exif_transpose(raw)
            return oriented.convert("RGBA")
    except Exception as exc:
        raise ResourceError("源图片无法完整解码", "invalid_canvas_image_bytes") from exc


def _encode_png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def crop_image_bytes(content: bytes, x: float, y: float, w: float, h: float) -> bytes:
    for val in (x, y, w, h):
        if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(val):
            raise ResourceError("裁剪坐标必须为有限数值", "invalid_canvas_crop")
    if not (0.0 <= x < 1.0 and 0.0 <= y < 1.0 and 0.01 <= w <= 1.0 and 0.01 <= h <= 1.0):
        raise ResourceError("裁剪区域超出有效比例范围", "invalid_canvas_crop")
    img = _open_rgba(content)
    width, height = img.size
    left = max(0, min(width - 1, int(round(x * width))))
    top = max(0, min(height - 1, int(round(y * height))))
    right = max(left + 1, min(width, int(round((x + w) * width))))
    bottom = max(top + 1, min(height, int(round((y + h) * height))))
    return _encode_png(img.crop((left, top, right, bottom)))


def rotate_flip_image_bytes(content: bytes, degrees: float = 0.0, flip_x: bool = False, flip_y: bool = False) -> bytes:
    if isinstance(degrees, bool) or not isinstance(degrees, (int, float)) or not -360.0 <= degrees <= 360.0:
        raise ResourceError("旋转角度须在 -360 至 360 度之间", "invalid_canvas_rotate")
    if not isinstance(flip_x, bool) or not isinstance(flip_y, bool):
        raise ResourceError("翻转参数须为布尔值", "invalid_canvas_rotate")
    img = _open_rgba(content)
    if flip_x:
        img = ImageOps.mirror(img)
    if flip_y:
        img = ImageOps.flip(img)
    if abs(float(degrees)) > 1e-4:
        img = img.rotate(-float(degrees), resample=Image.Resampling.BICUBIC, expand=True)
    return _encode_png(img)


def color_adjust_image_bytes(
    content: bytes,
    filter_id: str = "original",
    strength: int = 100,
    hue: int = 0,
    saturation: int = 0,
    brightness: int = 0,
    contrast: int = 0,
) -> bytes:
    filter_id = resolve_filter_id(filter_id)
    for val, low, high in ((strength, 0, 100), (hue, -180, 180), (saturation, -100, 100), (brightness, -100, 100), (contrast, -100, 100)):
        if isinstance(val, bool) or not isinstance(val, (int, float)) or not low <= val <= high:
            raise ResourceError("调色滑杆数值超出允许区间", "invalid_canvas_color_adjust")
    preset = FILTER_PRESETS[filter_id]
    ratio = float(strength) / 100.0
    total_hue = float(preset["hue"]) * ratio + float(hue)
    total_sat = float(preset["sat"]) * ratio + float(saturation)
    total_bri = float(preset["bri"]) * ratio + float(brightness)
    total_con = float(preset["con"]) * ratio + float(contrast)

    rgba = _open_rgba(content)
    alpha = rgba.getchannel("A")
    rgb = rgba.convert("RGB")

    if abs(total_hue) >= 0.5:
        hsv = rgb.convert("HSV")
        h_ch, s_ch, v_ch = hsv.split()
        shift = int(round((total_hue / 360.0) * 255.0)) % 256
        h_ch = h_ch.point(lambda p: (p + shift) & 255)
        rgb = Image.merge("HSV", (h_ch, s_ch, v_ch)).convert("RGB")

    tr, tg, tb = preset["tint"]
    if ratio > 0 and (tr != 1.0 or tg != 1.0 or tb != 1.0):
        mr = 1.0 + (tr - 1.0) * ratio
        mg = 1.0 + (tg - 1.0) * ratio
        mb = 1.0 + (tb - 1.0) * ratio
        r_ch, g_ch, b_ch = rgb.split()
        r_ch = r_ch.point(lambda p: max(0, min(255, int(round(p * mr)))))
        g_ch = g_ch.point(lambda p: max(0, min(255, int(round(p * mg)))))
        b_ch = b_ch.point(lambda p: max(0, min(255, int(round(p * mb)))))
        rgb = Image.merge("RGB", (r_ch, g_ch, b_ch))

    if abs(total_sat) >= 0.5:
        rgb = ImageEnhance.Color(rgb).enhance(max(0.0, 1.0 + total_sat / 100.0))
    if abs(total_bri) >= 0.5:
        rgb = ImageEnhance.Brightness(rgb).enhance(max(0.1, 1.0 + total_bri / 100.0))
    if abs(total_con) >= 0.5:
        rgb = ImageEnhance.Contrast(rgb).enhance(max(0.1, 1.0 + total_con / 100.0))

    out = rgb.convert("RGBA")
    out.putalpha(alpha)
    return _encode_png(out)


def _stroke_geometry(stroke, width, height, code):
    if not isinstance(stroke, dict):
        raise ResourceError("涂鸦笔触格式无效", code)
    tool = str(stroke.get("tool") or "brush")
    if tool not in {"brush", "arrow", "rect", "text", "eraser"}:
        raise ResourceError("涂鸦工具无效", code)
    color = str(stroke.get("color", "#ff3b30"))
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        raise ResourceError("涂鸦颜色须为十六进制 RGB", code)
    stroke_w = stroke.get("width", 6)
    if isinstance(stroke_w, bool) or not isinstance(stroke_w, (int, float)) or not 1 <= stroke_w <= 64:
        raise ResourceError("涂鸦笔刷宽度超出范围", code)
    pts = stroke.get("points", [])
    if not isinstance(pts, list) or not 1 <= len(pts) <= 2000:
        raise ResourceError("涂鸦笔触坐标点数须在 1..2000 之间", code)
    coords = []
    for pt in pts:
        if not isinstance(pt, (list, tuple)) or len(pt) != 2:
            raise ResourceError("涂鸦坐标点无效", code)
        px, py = pt
        if isinstance(px, bool) or isinstance(py, bool) or not isinstance(px, (int, float)) or not isinstance(py, (int, float)):
            raise ResourceError("涂鸦坐标点须为数值", code)
        coords.append((max(0.0, min(1.0, float(px))) * width, max(0.0, min(1.0, float(py))) * height))
    if tool in {"arrow", "rect"} and len(coords) < 2:
        raise ResourceError("箭头和矩形至少需要两个坐标点", code)
    text = str(stroke.get("text") or "")
    if tool == "text" and (not text or len(text) > 80):
        raise ResourceError("文字涂鸦需要 1 到 80 个字符", code)
    scale = max(1.0, min(width, height) / 400.0)
    return tool, color, max(1, int(round(float(stroke_w) * scale))), coords, text[:80]


def _paint_positive(draw, tool, color, px_width, coords, text):
    if tool == "text":
        draw.text(coords[0], text, fill=color, font=ImageFont.load_default())
        return
    if tool == "rect":
        xs = [point[0] for point in coords]
        ys = [point[1] for point in coords]
        draw.rectangle((min(xs), min(ys), max(xs), max(ys)), outline=color, width=px_width)
        return
    if tool == "arrow":
        start, end = coords[0], coords[-1]
        draw.line((start, end), fill=color, width=px_width)
        angle = math.atan2(end[1] - start[1], end[0] - start[0])
        length = max(8.0, px_width * 3)
        head = [
            end,
            (end[0] + length * math.cos(angle + math.radians(150)), end[1] + length * math.sin(angle + math.radians(150))),
            (end[0] + length * math.cos(angle - math.radians(150)), end[1] + length * math.sin(angle - math.radians(150))),
        ]
        draw.polygon(head, fill=color)
        return
    if len(coords) == 1:
        cx, cy = coords[0]
        radius = px_width / 2.0
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=color)
    else:
        draw.line(coords, fill=color, width=px_width, joint="curve")


def _erase_overlay(overlay, px_width, coords):
    mask = Image.new("L", overlay.size, 0)
    _paint_positive(ImageDraw.Draw(mask), "brush", 255, px_width, coords, "")
    overlay.putalpha(ImageChops.multiply(overlay.getchannel("A"), ImageOps.invert(mask)))


def doodle_overlay_image_bytes(content: bytes, strokes: list) -> bytes:
    if not isinstance(strokes, list) or not 1 <= len(strokes) <= 500:
        raise ResourceError("涂鸦至少需要一笔有效笔触（上限 500 笔）", "invalid_canvas_doodle")
    img = _open_rgba(content)
    width, height = img.size
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    drawn_strokes = 0
    for stroke in strokes:
        tool, color, px_width, coords, text = _stroke_geometry(stroke, width, height, "invalid_canvas_doodle")
        if tool == "eraser":
            _erase_overlay(overlay, px_width, coords)
            draw = ImageDraw.Draw(overlay)
        else:
            _paint_positive(draw, tool, color, px_width, coords, text)
        drawn_strokes += 1
    if drawn_strokes < 1:
        raise ResourceError("涂鸦至少需要一笔有效笔触（上限 500 笔）", "invalid_canvas_doodle")
    return _encode_png(Image.alpha_composite(img, overlay))


def mask_image_bytes(content: bytes, strokes: list) -> bytes:
    if not isinstance(strokes, list) or not strokes:
        raise ResourceError("请先涂抹需要重绘的区域", "invalid_canvas_mask")
    img = _open_rgba(content)
    width, height = img.size
    mask = Image.new("RGBA", (width, height), (0, 0, 0, 255))
    draw = ImageDraw.Draw(mask)
    for stroke in strokes:
        tool, _color, px_width, coords, text = _stroke_geometry(stroke, width, height, "invalid_canvas_mask")
        if tool == "eraser":
            _paint_positive(draw, "brush", "#000000", px_width, coords, "")
        else:
            _paint_positive(draw, "brush" if tool == "eraser" else tool, "#ffffff", px_width, coords, text or " ")
    return _encode_png(mask)


def build_grid_storyboard_node_fields(cell, index, rows, columns, label):
    if not isinstance(cell, dict) or type(index) is not int or index < 1:
        raise ResourceError("宫格分镜切片无效", "invalid_canvas_grid")
    name = str(label or "宫格分镜组")[:100]
    payload = {
        "kind": "grid_storyboard_group",
        "version": 1,
        "rows": int(rows),
        "columns": int(columns),
        "row": int(cell["row"]),
        "column": int(cell["column"]),
        "index": index,
        "label": name,
    }
    return {
        "title": "宫格切片 %s" % index,
        "group": name,
        "text": "",
        "params": {"grid_storyboard_group": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))},
    }


def _render_equirect_perspective(src_rgb: Image.Image, yaw_deg: float, pitch_deg: float, fov_deg: float, out_w: int, out_h: int) -> bytes:
    sw, sh = src_rgb.size
    src_px = src_rgb.load()
    out = Image.new("RGB", (out_w, out_h))
    out_px = out.load()

    yaw = math.radians(yaw_deg)
    pitch = math.radians(pitch_deg)
    fov = math.radians(max(30.0, min(120.0, fov_deg)))
    half_tan = math.tan(fov / 2.0)
    aspect = out_w / max(1.0, float(out_h))

    cy, sy = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)

    x_cam = [((2.0 * (ix + 0.5) / out_w) - 1.0) * aspect * half_tan for ix in range(out_w)]
    two_pi = 2.0 * math.pi
    for iy in range(out_h):
        yc = (1.0 - (2.0 * (iy + 0.5) / out_h)) * half_tan
        # Pitch around X: y1 = yc*cp + 1*sp, z1 = -yc*sp + 1*cp (camera looks along +Z, +Y up)
        y1 = yc * cp + sp
        z1 = -yc * sp + cp
        for ix, xc in enumerate(x_cam):
            inv_len = 1.0 / math.sqrt(xc * xc + y1 * y1 + z1 * z1)
            rx = (xc * cy + z1 * sy) * inv_len
            ry = y1 * inv_len
            rz = (-xc * sy + z1 * cy) * inv_len
            lon = math.atan2(rx, rz)  # -pi .. pi
            lat = math.asin(max(-1.0, min(1.0, ry)))  # -pi/2 .. pi/2
            u = ((lon + math.pi) / two_pi) % 1.0
            v = 0.5 - (lat / math.pi)
            sx_i = min(sw - 1, max(0, int(u * sw)))
            sy_i = min(sh - 1, max(0, int(v * sh)))
            out_px[ix, iy] = src_px[sx_i, sy_i]
    return _encode_png(out)


PANORAMA_HD_WIDTH = 1280
PANORAMA_HD_HEIGHT = 720
MAX_LAYER_SELECTIONS = 16


def panorama_view_specs(mode: str, base_yaw: float, base_pitch: float) -> list[tuple]:
    """Views are offsets from the current base yaw and pitch, not absolute zeros."""
    if mode not in {"current", "four", "twelve"}:
        raise ResourceError("全景截图模式须为当前视角、4大视角或12大视角", "invalid_canvas_panorama_capture")
    yaw = float(base_yaw)
    pitch = float(base_pitch)
    if mode == "current":
        return [(yaw, pitch, "全景当前截图", 0.0)]
    if mode == "four":
        offsets = ((0.0, "正前", "0°"), (180.0, "正后", "180°"), (-90.0, "左侧", "-90°"), (90.0, "右侧", "+90°"))
        return [(yaw + off, pitch, "全景 4视角 · %s %s" % (name, text), off) for off, name, text in offsets]
    return [(yaw + idx * 30.0, pitch, "全景 12视角 · %s°" % (idx * 30), float(idx * 30)) for idx in range(12)]


def _project_equirect(sw, sh, yaw_deg, pitch_deg, fov_deg, out_w, out_h, px, py):
    yaw = math.radians(yaw_deg)
    pitch = math.radians(pitch_deg)
    fov = math.radians(max(30.0, min(120.0, fov_deg)))
    half_tan = math.tan(fov / 2.0)
    aspect = out_w / max(1.0, float(out_h))
    cy, sy = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)
    xc = ((2.0 * px / out_w) - 1.0) * aspect * half_tan
    yc = (1.0 - (2.0 * py / out_h)) * half_tan
    y1 = yc * cp + sp
    z1 = -yc * sp + cp
    inv_len = 1.0 / math.sqrt(xc * xc + y1 * y1 + z1 * z1)
    rx = (xc * cy + z1 * sy) * inv_len
    ry = y1 * inv_len
    rz = (-xc * sy + z1 * cy) * inv_len
    lon = math.atan2(rx, rz)
    lat = math.asin(max(-1.0, min(1.0, ry)))
    u = ((lon + math.pi) / (2.0 * math.pi)) % 1.0
    v = 0.5 - (lat / math.pi)
    return u * sw, max(0.0, min(sh - 1.0, v * sh))


def _render_equirect_perspective_mesh(src_rgb: Image.Image, yaw_deg: float, pitch_deg: float, fov_deg: float, out_w: int, out_h: int) -> bytes:
    """Bilinear mesh of the same projection, so HD views stay local and fast."""
    sw, sh = src_rgb.size
    wide = Image.new("RGB", (sw * 2, sh))
    wide.paste(src_rgb, (0, 0))
    wide.paste(src_rgb, (sw, 0))
    tiles_x = max(1, min(48, max(1, out_w // 16)))
    tiles_y = max(1, min(27, max(1, out_h // 16)))
    mesh = []
    for ty in range(tiles_y):
        y0 = ty * out_h // tiles_y
        y1 = (ty + 1) * out_h // tiles_y
        if y1 <= y0:
            continue
        for tx in range(tiles_x):
            x0 = tx * out_w // tiles_x
            x1 = (tx + 1) * out_w // tiles_x
            if x1 <= x0:
                continue
            corners = ((x0, y0), (x0, y1), (x1, y1), (x1, y0))
            raw = [_project_equirect(sw, sh, yaw_deg, pitch_deg, fov_deg, out_w, out_h, px, py) for px, py in corners]
            base = raw[0][0]
            unwrapped = []
            for sx, sy in raw:
                if sx - base > sw / 2.0:
                    sx -= sw
                elif sx - base < -sw / 2.0:
                    sx += sw
                unwrapped.append((sx, sy))
            if any(sx < 0 for sx, _sy in unwrapped):
                unwrapped = [(sx + sw, sy) for sx, sy in unwrapped]
            quad = []
            for sx, sy in unwrapped:
                quad.extend((sx, sy))
            mesh.append(((x0, y0, x1, y1), tuple(quad)))
    resample = getattr(getattr(Image, "Resampling", Image), "BILINEAR")
    mesh_op = getattr(getattr(Image, "Transform", Image), "MESH")
    out = wide.transform((out_w, out_h), mesh_op, mesh, resample=resample)
    return _encode_png(out)


def capture_panorama_views(
    content: bytes,
    mode: str = "current",
    yaw_deg: float = 0.0,
    pitch_deg: float = 0.0,
    fov_deg: float = 75.0,
    out_width: int = PANORAMA_HD_WIDTH,
    out_height: int = PANORAMA_HD_HEIGHT,
) -> list[dict]:
    if mode not in {"current", "four", "twelve"}:
        raise ResourceError("全景截图模式须为当前视角、4大视角或12大视角", "invalid_canvas_panorama_capture")
    for val, low, high in ((yaw_deg, -720.0, 720.0), (pitch_deg, -89.0, 89.0), (fov_deg, 30.0, 120.0)):
        if isinstance(val, bool) or not isinstance(val, (int, float)) or not low <= val <= high:
            raise ResourceError("全景视角参数超出有效范围", "invalid_canvas_panorama_capture")
    if isinstance(out_width, bool) or isinstance(out_height, bool) or type(out_width) is not int or type(out_height) is not int:
        raise ResourceError("全景输出尺寸无效", "invalid_canvas_panorama_capture")
    if out_width < 16 or out_height < 16 or out_width > 3840 or out_height > 2160:
        raise ResourceError("全景输出尺寸超出范围", "invalid_canvas_panorama_capture")
    src = _open_rgba(content).convert("RGB")
    results = []
    for y_deg, p_deg, label, offset in panorama_view_specs(mode, yaw_deg, pitch_deg):
        png = _render_equirect_perspective_mesh(src, y_deg, p_deg, float(fov_deg), out_width, out_height)
        results.append({
            "yaw": y_deg,
            "pitch": p_deg,
            "fov": float(fov_deg),
            "offset": offset,
            "label": label,
            "width": out_width,
            "height": out_height,
            "bytes": png,
        })
    return results


def _selection_box(width, height, bbox):
    x, y, w, h = bbox["x"], bbox["y"], bbox["w"], bbox["h"]
    left = max(0, min(width - 1, int(round(x * width))))
    top = max(0, min(height - 1, int(round(y * height))))
    right = max(left + 1, min(width, int(round((x + w) * width))))
    bottom = max(top + 1, min(height, int(round((y + h) * height))))
    return left, top, right, bottom


def normalize_layer_selections(selections):
    if not isinstance(selections, list) or not selections:
        raise ResourceError("请至少框选一个图层区域", "invalid_canvas_layer_separation")
    if len(selections) > MAX_LAYER_SELECTIONS:
        raise ResourceError("图层分离最多框选 16 个区域", "invalid_canvas_layer_separation")
    normalized = []
    seen = set()
    for index, item in enumerate(selections):
        if not isinstance(item, dict):
            raise ResourceError("图层区域格式无效", "invalid_canvas_layer_separation")
        ident = str(item.get("id") or ("sel-%s" % (index + 1))).strip()[:40]
        if not ident or ident in seen:
            raise ResourceError("图层区域标识无效或重复", "invalid_canvas_layer_separation")
        seen.add(ident)
        description = item.get("description", "")
        if not isinstance(description, str) or len(description) > 200:
            raise ResourceError("区域描述最长 200 字", "invalid_canvas_layer_separation")
        bbox = item.get("bbox")
        if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            x, y, w, h = bbox
        elif isinstance(bbox, dict):
            x, y = bbox.get("x"), bbox.get("y")
            w, h = bbox.get("w", bbox.get("width")), bbox.get("h", bbox.get("height"))
        else:
            raise ResourceError("图层区域缺少 bbox", "invalid_canvas_layer_separation")
        for val in (x, y, w, h):
            if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(float(val)):
                raise ResourceError("图层区域坐标无效", "invalid_canvas_layer_separation")
        x, y, w, h = float(x), float(y), float(w), float(h)
        if not (0.0 <= x < 1.0 and 0.0 <= y < 1.0 and 0.01 <= w <= 1.0 and 0.01 <= h <= 1.0 and x + w <= 1.001 and y + h <= 1.001):
            raise ResourceError("图层区域超出画面", "invalid_canvas_layer_separation")
        normalized.append({"id": ident, "description": description, "bbox": {"x": round(x, 4), "y": round(y, 4), "w": round(w, 4), "h": round(h, 4)}})
    return normalized


def _inpaint_boxes(img: Image.Image, boxes) -> Image.Image:
    filled = img.convert("RGBA")
    blurred = filled.filter(ImageFilter.GaussianBlur(radius=18))
    for left, top, right, bottom in boxes:
        patch = blurred.crop((left, top, right, bottom))
        filled.paste(patch, (left, top))
    return filled


def separate_image_layers(content: bytes, selections) -> dict:
    chosen = normalize_layer_selections(selections)
    img = _open_rgba(content)
    width, height = img.size
    boxes = [_selection_box(width, height, item["bbox"]) for item in chosen]
    background = _inpaint_boxes(img, boxes)
    foregrounds = []
    for item, box in zip(chosen, boxes):
        layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        crop = img.crop(box)
        layer.paste(crop, (box[0], box[1]))
        alpha = layer.getchannel("A")
        mask = Image.new("L", (width, height), 0)
        ImageDraw.Draw(mask).rectangle((box[0], box[1], box[2] - 1, box[3] - 1), fill=255)
        layer.putalpha(ImageChops.multiply(alpha, mask) if alpha.getextrema() != (255, 255) else mask)
        foregrounds.append({"id": item["id"], "description": item["description"], "bbox": item["bbox"], "bytes": _encode_png(layer)})
    snapshot = {
        "kind": "layer_separation",
        "selections": chosen,
        "foreground_count": len(foregrounds),
        "background": "local_inpaint",
        "credits": 0,
    }
    return {
        "foregrounds": foregrounds,
        "background": {"id": "background", "description": "背景修补", "bytes": _encode_png(background)},
        "snapshot": snapshot,
    }


def _layer_number(value, low, high, code="invalid_canvas_layer_composition"):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or not low <= float(value) <= high:
        raise ResourceError("图层位置或缩放超出范围", code)
    return float(value)


def compose_image_layers(layers, width=None, height=None) -> bytes:
    if not isinstance(layers, list) or not 1 <= len(layers) <= 32:
        raise ResourceError("请选择 1 至 32 个图层进行免费合成", "invalid_canvas_layer_composition")
    decoded = []
    for item in layers:
        if not isinstance(item, dict) or not isinstance(item.get("bytes"), (bytes, bytearray)):
            raise ResourceError("图层缺少图片字节", "invalid_canvas_layer_composition")
        visible = item.get("visible", True)
        if type(visible) is not bool:
            raise ResourceError("图层显隐须为布尔值", "invalid_canvas_layer_composition")
        scale = _layer_number(item.get("scale", 1), 0.05, 8)
        x = _layer_number(item.get("x", 0), -8000, 8000)
        y = _layer_number(item.get("y", 0), -8000, 8000)
        z = item.get("z", 0)
        if isinstance(z, bool) or not isinstance(z, (int, float)):
            raise ResourceError("图层顺序无效", "invalid_canvas_layer_composition")
        img = _open_rgba(bytes(item["bytes"]))
        if abs(scale - 1.0) > 1e-3:
            resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
            img = img.resize((max(1, int(round(img.width * scale))), max(1, int(round(img.height * scale)))), resample)
        decoded.append({"img": img, "x": int(round(x)), "y": int(round(y)), "z": int(z), "visible": visible})
    decoded.sort(key=lambda row: (row["z"], row["x"]))
    if width is None or height is None:
        right, bottom = 1, 1
        for row in decoded:
            if not row["visible"]:
                continue
            right = max(right, row["x"] + row["img"].width)
            bottom = max(bottom, row["y"] + row["img"].height)
        width, height = right, bottom
    else:
        if type(width) is not int or type(height) is not int or not 1 <= width <= 8192 or not 1 <= height <= 8192:
            raise ResourceError("合成画布尺寸无效", "invalid_canvas_layer_composition")
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    for row in decoded:
        if not row["visible"]:
            continue
        canvas.paste(row["img"], (row["x"], row["y"]), row["img"])
    return _encode_png(canvas)


def stitch_images(contents, mode: str = "long") -> bytes:
    if mode not in {"long", "grid"}:
        raise ResourceError("拼合模式须为长图或宫格", "invalid_canvas_stitch")
    if not isinstance(contents, list) or not 2 <= len(contents) <= 16:
        raise ResourceError("请选择 2 至 16 张图片拼合", "invalid_canvas_stitch")
    images = [_open_rgba(item) for item in contents]
    resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
    if mode == "long":
        height = min(img.height for img in images)
        resized = []
        for img in images:
            if img.height != height:
                img = img.resize((max(1, int(round(img.width * height / img.height))), height), resample)
            resized.append(img)
        canvas = Image.new("RGBA", (sum(img.width for img in resized), height), (0, 0, 0, 0))
        cursor = 0
        for img in resized:
            canvas.paste(img, (cursor, 0))
            cursor += img.width
        return _encode_png(canvas)
    columns = int(math.ceil(math.sqrt(len(images))))
    rows = int(math.ceil(len(images) / columns))
    cell_w = max(img.width for img in images)
    cell_h = max(img.height for img in images)
    canvas = Image.new("RGBA", (columns * cell_w, rows * cell_h), (0, 0, 0, 0))
    for index, img in enumerate(images):
        canvas.paste(img, ((index % columns) * cell_w, (index // columns) * cell_h))
    return _encode_png(canvas)


def hidden_job_ids(events) -> set:
    """Latest canvas_history_visibility event wins. Order is oldest first."""
    latest = {}
    for event in events or []:
        if not isinstance(event, dict) or not event.get("job_id"):
            continue
        latest[event["job_id"]] = event
    hidden = set()
    for job_id, event in latest.items():
        evidence = event.get("evidence") or {}
        if evidence.get("hidden") is True:
            hidden.add(job_id)
    return hidden
