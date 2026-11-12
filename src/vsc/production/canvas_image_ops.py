"""Deterministic local pixel operations for Canvas in-place image tooling."""
from __future__ import annotations

import io
import math
import re
from PIL import Image, ImageDraw, ImageEnhance, ImageOps

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
    if filter_id not in FILTER_PRESETS:
        raise ResourceError("未知的调色滤镜标识", "invalid_canvas_color_adjust")
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


def doodle_overlay_image_bytes(content: bytes, strokes: list) -> bytes:
    if not isinstance(strokes, list) or not 1 <= len(strokes) <= 500:
        raise ResourceError("涂鸦至少需要一笔有效笔触（上限 500 笔）", "invalid_canvas_doodle")
    img = _open_rgba(content)
    width, height = img.size
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    scale = max(1.0, min(width, height) / 400.0)
    drawn_strokes = 0
    for stroke in strokes:
        if not isinstance(stroke, dict):
            raise ResourceError("涂鸦笔触格式无效", "invalid_canvas_doodle")
        color = str(stroke.get("color", "#ff3b30"))
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise ResourceError("涂鸦颜色须为十六进制 RGB", "invalid_canvas_doodle")
        stroke_w = stroke.get("width", 6)
        if isinstance(stroke_w, bool) or not isinstance(stroke_w, (int, float)) or not 1 <= stroke_w <= 64:
            raise ResourceError("涂鸦笔刷宽度超出范围", "invalid_canvas_doodle")
        pts = stroke.get("points", [])
        if not isinstance(pts, list) or not 1 <= len(pts) <= 2000:
            raise ResourceError("涂鸦笔触坐标点数须在 1..2000 之间", "invalid_canvas_doodle")
        coords = []
        for pt in pts:
            if not isinstance(pt, (list, tuple)) or len(pt) != 2:
                raise ResourceError("涂鸦坐标点无效", "invalid_canvas_doodle")
            px, py = pt
            if isinstance(px, bool) or isinstance(py, bool) or not isinstance(px, (int, float)) or not isinstance(py, (int, float)):
                raise ResourceError("涂鸦坐标点须为数值", "invalid_canvas_doodle")
            coords.append((max(0.0, min(1.0, float(px))) * width, max(0.0, min(1.0, float(py))) * height))
        px_width = max(1, int(round(float(stroke_w) * scale)))
        if len(coords) == 1:
            cx, cy = coords[0]
            r = px_width / 2.0
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color)
        else:
            draw.line(coords, fill=color, width=px_width, joint="curve")
        drawn_strokes += 1
    if drawn_strokes < 1:
        raise ResourceError("涂鸦至少需要一笔有效笔触（上限 500 笔）", "invalid_canvas_doodle")
    merged = Image.alpha_composite(img, overlay)
    return _encode_png(merged)


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


def capture_panorama_views(
    content: bytes,
    mode: str = "current",
    yaw_deg: float = 0.0,
    pitch_deg: float = 0.0,
    fov_deg: float = 75.0,
    out_width: int = 320,
    out_height: int = 180,
) -> list[dict]:
    if mode not in {"current", "four", "twelve"}:
        raise ResourceError("全景截图模式须为当前视角、4大视角或12大视角", "invalid_canvas_panorama_capture")
    for val, low, high in ((yaw_deg, -720.0, 720.0), (pitch_deg, -89.0, 89.0), (fov_deg, 30.0, 120.0)):
        if isinstance(val, bool) or not isinstance(val, (int, float)) or not low <= val <= high:
            raise ResourceError("全景视角参数超出有效范围", "invalid_canvas_panorama_capture")
    src = _open_rgba(content).convert("RGB")
    if mode == "current":
        specs = [(float(yaw_deg), float(pitch_deg), "全景当前截图")]
    elif mode == "four":
        specs = [
            (0.0, 0.0, "全景 4视角 · 正前 0°"),
            (90.0, 0.0, "全景 4视角 · 右侧 90°"),
            (180.0, 0.0, "全景 4视角 · 正后 180°"),
            (270.0, 0.0, "全景 4视角 · 左侧 270°"),
        ]
    else:
        specs = [(float(idx * 30), 0.0, f"全景 12视角 · {idx * 30}°") for idx in range(12)]
    results = []
    for y_deg, p_deg, label in specs:
        png = _render_equirect_perspective(src, y_deg, p_deg, float(fov_deg), out_width, out_height)
        results.append({"yaw": y_deg, "pitch": p_deg, "fov": float(fov_deg), "label": label, "bytes": png})
    return results
