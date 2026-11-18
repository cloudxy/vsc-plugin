"""Persistent AI character studio generation store: dated disk files + PostgreSQL catalog.

Generated images and prompt sidecars are written atomically under
``assets/ai-generate-image/<YYYY-MM-DD>/``; PostgreSQL stores relative paths,
SHA-256 checksums, exact model/method provenance, prompts and non-Base64 snapshots.
"""
from __future__ import annotations

import base64
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import uuid

from sqlalchemy import delete, desc, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from vsc.adapters.persistence.postgres import schema as S
from vsc.assets.resource_service import Conflict, NotFound, ResourceError
from vsc.bootstrap import repository_root

DEFAULT_SUBDIR = "assets/ai-generate-image"
MEDIA_URL_PREFIX = "/api/v1/character-studio/media/"
MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".avif": "image/avif",
}
MIME_EXT = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
    "image/avif": "avif",
}
_SECRET_KEY_RE = re.compile(r"(^|_)(api_?key|secret|password|token|authorization|credential)(_|$)", re.I)
_DATA_IMAGE_RE = re.compile(r"^data:(image/[a-z0-9.+-]+)(;base64)?,([\s\S]+)$", re.I)


def ai_generate_image_root(repo_root: Path | None = None) -> Path:
    base_repo = Path(repo_root) if repo_root is not None else repository_root()
    configured = ""
    if repo_root is None:
        try:
            from vsc.configuration import get_config
            configured = str(get_config("AI_GENERATE_IMAGE_ROOT") or "").strip()
        except Exception:
            configured = ""
    raw = Path(configured) if configured else Path(DEFAULT_SUBDIR)
    target = raw if raw.is_absolute() else (base_repo / raw)
    return target.resolve()


def detect_image_mime(data: bytes) -> str | None:
    if not data:
        return None
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in (b"avif", b"avis", b"mif1"):
        return "image/avif"
    return None


def decode_data_image_uri(uri: str) -> tuple[bytes, str]:
    match = _DATA_IMAGE_RE.match(str(uri or "").strip())
    if not match:
        raise ResourceError("图片数据格式无效", "invalid_image_data", 422)
    declared_mime, is_b64, payload = match.groups()
    try:
        raw = base64.b64decode(payload, validate=False) if is_b64 else payload.encode("utf-8")
    except ValueError as exc:
        raise ResourceError("图片 Base64 解码失败", "invalid_image_data", 422) from exc
    mime = detect_image_mime(raw)
    if not mime:
        mime = declared_mime.lower() if declared_mime.lower() in MIME_EXT and raw else None
    if not mime:
        raise ResourceError("图片内容不是受支持的有效图像格式", "invalid_image_data", 422)
    return raw, mime


def _count_snapshot_refs(snapshot: dict | None) -> int:
    if not isinstance(snapshot, dict):
        return 1
    recipe = snapshot.get("recipe")
    if not isinstance(recipe, dict):
        return 1
    base = sum(1 for k in ("portrait", "costume", "pose") if recipe.get(k))
    extra = recipe.get("extraImages")
    if isinstance(extra, list):
        base += len(extra)
    settings = snapshot.get("settings") if isinstance(snapshot.get("settings"), dict) else {}
    if base > 0 and settings.get("sendStitchedSheet"):
        base += 1
    return base


def infer_provenance(
    provider: str,
    model: str,
    *,
    method: str = "",
    method_label: str = "",
    endpoint: str = "",
    snapshot: dict | None = None,
) -> tuple[str, str, str, str]:
    prov = str(provider or "").strip()
    mdl = str(model or "").strip()
    if not mdl and isinstance(snapshot, dict) and prov:
        models_map = snapshot.get("models")
        if isinstance(models_map, dict) and isinstance(models_map.get(prov), dict):
            sm = models_map[prov]
            raw = str(sm.get("customModel") or "").strip() if sm.get("model") == "custom" else str(sm.get("model") or "").strip()
            mdl = "gpt-image-2" if prov == "codex_auth" and raw == "image-generation" else raw
    if not mdl:
        mdl = "unrecorded"
    if not prov:
        prov = "unknown"

    m_code = str(method or "").strip()
    m_label = str(method_label or "").strip()
    ep = str(endpoint or "").strip()
    if m_code and m_label:
        return prov, mdl, m_code, m_label, ep  # type: ignore[return-value]

    ref_count = _count_snapshot_refs(snapshot)
    settings = snapshot.get("settings") if isinstance(snapshot, dict) and isinstance(snapshot.get("settings"), dict) else {}
    norm_mdl = mdl.lower()
    is_grok_direct = norm_mdl.startswith("grok-imagine-") or norm_mdl.startswith("grok-2-image")

    if prov == "grok_auth":
        if is_grok_direct:
            if ref_count == 0:
                m_code = m_code or "grok_sub_images_generations"
                m_label = m_label or "Grok 订阅直连 · /v1/images/generations（文生图）"
                ep = ep or "/v1/images/generations"
            else:
                scope = "多图编辑" if ref_count > 1 else "单图编辑"
                m_code = m_code or "grok_sub_images_edits"
                m_label = m_label or f"Grok 订阅直连 · /v1/images/edits（{scope}）"
                ep = ep or "/v1/images/edits"
        else:
            custom = norm_mdl not in ("image_edit", "image_gen", "grok-cli", "grok-cli-imagine", "unrecorded")
            m_code = m_code or "grok_cli_image_edit"
            m_label = m_label or (f"Grok CLI · image_edit 工具（协调: {mdl}）" if custom else "Grok CLI · image_edit 工具")
            ep = ep or "grok CLI (image_edit)"
    elif prov == "agy_auth":
        custom = mdl not in ("image-generator", "unrecorded")
        m_code = m_code or "agy_cli_image_generator"
        m_label = m_label or (f"AGY CLI · image-generator 智能体（协调: {mdl}）" if custom else "AGY CLI · image-generator 智能体")
        ep = ep or "agy CLI (image-generator)"
    elif prov == "codex_auth":
        m_code = m_code or "codex_cli_image_gen"
        m_label = m_label or "Codex CLI · image_gen 工具（ChatGPT 订阅）"
        ep = ep or "codex exec (image_gen)"
    elif prov == "grok":
        gr = settings.get("grokParams") if isinstance(settings.get("grokParams"), dict) else {}
        pure = gr.get("endpointMode") == "generations" or mdl == "grok-2-image-1212" or ref_count == 0
        if pure:
            m_code = m_code or "grok_api_images_generations"
            m_label = m_label or "Grok API · /v1/images/generations（文生图）"
            ep = ep or "/v1/images/generations"
        else:
            scope = "多图编辑" if ref_count > 1 else "单图编辑"
            m_code = m_code or "grok_api_images_edits"
            m_label = m_label or f"Grok API · /v1/images/edits（{scope}）"
            ep = ep or "/v1/images/edits"
    elif prov == "gemini":
        gm = settings.get("geminiParams") if isinstance(settings.get("geminiParams"), dict) else {}
        if gm.get("endpointMode", "native") == "native":
            m_code = m_code or "gemini_native_generate_content"
            m_label = m_label or "Gemini API · 原生 generateContent"
            ep = ep or "/v1beta/models/:generateContent"
        else:
            m_code = m_code or "gemini_openai_chat"
            m_label = m_label or "Gemini API · Chat Completions 兼容"
            ep = ep or "/v1/chat/completions"
    elif prov == "gpt":
        mode = (settings.get("gptParams") or {}).get("endpointMode", "images_edits_json") if isinstance(settings.get("gptParams"), dict) else "images_edits_json"
        mapping = {
            "images_edits_json": ("gpt_images_edits_json", "GPT API · /v1/images/edits (JSON)", "/v1/images/edits"),
            "images_edits": ("gpt_images_edits_multipart", "GPT API · /v1/images/edits (Multipart)", "/v1/images/edits"),
            "responses": ("gpt_responses_image_gen", "GPT API · /v1/responses (image_generation)", "/v1/responses"),
        }
        d_code, d_label, d_ep = mapping.get(mode, ("gpt_chat_completions", "GPT API · /v1/chat/completions", "/v1/chat/completions"))
        m_code, m_label, ep = m_code or d_code, m_label or d_label, ep or d_ep
    elif prov == "qwen":
        m_code = m_code or "qwen_multimodal_generation"
        m_label = m_label or "百炼 API · multimodal-generation"
        ep = ep or "/api/v1/services/aigc/multimodal-generation/generation"
    elif prov == "doubao":
        m_code = m_code or "doubao_images_generations"
        m_label = m_label or "方舟 API · /api/v3/images/generations"
        ep = ep or "/api/v3/images/generations"
    else:
        m_code = m_code or "unrecorded"
        m_label = m_label or m_code
    return prov, mdl, m_code, m_label or m_code, ep


def _atomic_write_bytes(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, target)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def _strip_secrets_and_inline_images(value):
    if isinstance(value, dict):
        cleaned = {}
        for k, v in value.items():
            key_str = str(k)
            if _SECRET_KEY_RE.search(key_str) or key_str in ("providers", "videoProviders"):
                continue
            cleaned[key_str] = _strip_secrets_and_inline_images(v)
        return cleaned
    if isinstance(value, list):
        return [_strip_secrets_and_inline_images(x) for x in value]
    if isinstance(value, str) and value.lower().startswith("data:image/"):
        return ""
    return value


def _parse_created_at(value) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)) and value > 0:
        seconds = value / 1000.0 if value > 1e11 else float(value)
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    if isinstance(value, str) and value.strip():
        text = value.strip()
        if text.isdigit():
            num = int(text)
            return datetime.fromtimestamp(num / 1000.0 if num > 1e11 else float(num), tz=timezone.utc)
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _format_prompt_sidecar(
    *,
    record_id: str,
    local_dt: datetime,
    provider: str,
    model: str,
    upstream_model: str,
    method_label: str,
    endpoint: str,
    recipe_summary: str,
    prompt: str,
) -> str:
    lines = [
        f"ID: {record_id}",
        f"生成时间: {local_dt.strftime('%Y-%m-%d %H:%M:%S%z')}",
        f"接入通道: {provider}",
        f"实际模型: {model}",
    ]
    if upstream_model and upstream_model != model:
        lines.append(f"平台返回模型: {upstream_model}")
    lines.append(f"调用方式: {method_label}")
    if endpoint:
        lines.append(f"调用入口: {endpoint}")
    if recipe_summary:
        lines.append(f"参考配方: {recipe_summary}")
    lines.extend(["", "--- 提示词 (Prompt) ---", str(prompt or "").strip(), ""])
    return "\n".join(lines)


class CharacterStudioStore:
    def __init__(self, engine, root: Path | None = None):
        self.engine = engine
        self.root = (Path(root) if root is not None else ai_generate_image_root()).resolve()

    def _safe_relative(self, subpath: str) -> Path | None:
        clean = str(subpath or "").strip().lstrip("/")
        if not clean or "\\" in clean:
            return None
        rel = Path(clean)
        if rel.is_absolute() or any(part in ("", ".", "..") or part.startswith(".") for part in rel.parts):
            return None
        candidate = self.root / rel
        cursor = candidate
        while cursor != self.root and cursor != cursor.parent:
            if cursor.is_symlink():
                return None
            cursor = cursor.parent
        try:
            resolved = candidate.resolve()
            if not resolved.is_relative_to(self.root):
                return None
        except OSError:
            return None
        return resolved

    def media_file(self, subpath: str) -> tuple[Path, str] | None:
        resolved = self._safe_relative(subpath)
        if resolved is None or not resolved.is_file():
            return None
        mime = MEDIA_TYPES.get(resolved.suffix.lower())
        if not mime:
            return None
        return resolved, mime

    def _serialize(self, row: dict) -> dict:
        created_at: datetime = row["created_at"]
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        pub = row.get("publication")
        has_pub = isinstance(pub, dict) and bool(pub)
        model_val = "" if row["model"] == "unrecorded" else row["model"]
        method_val = "" if row["method"] == "unrecorded" else row["method"]
        method_label_val = "" if row["method"] == "unrecorded" and row["method_label"] == "unrecorded" else row["method_label"]
        return {
            "id": str(row["id"]),
            "createdAt": int(round(created_at.timestamp() * 1000)),
            "created_at": created_at.astimezone().isoformat(),
            "imagePath": row["image_path"],
            "promptPath": row["prompt_path"],
            "storageDisplayPath": f"assets/ai-generate-image/{row['image_path']}",
            "promptDisplayPath": f"assets/ai-generate-image/{row['prompt_path']}" if row["prompt_path"] else "",
            "imageUrl": f"{MEDIA_URL_PREFIX}{row['image_path']}",
            "sha256": row["sha256"],
            "mimeType": row["mime_type"],
            "sizeBytes": int(row["size_bytes"]),
            "provider": row["provider"],
            "model": model_val,
            "upstreamModel": row["upstream_model"] or "",
            "method": method_val,
            "methodLabel": method_label_val,
            "endpoint": row["endpoint"] or "",
            "prompt": row["prompt"] or "",
            "recipeSummary": row["recipe_summary"] or "",
            "snapshot": row["snapshot"] if isinstance(row["snapshot"], dict) else {},
            "publication": pub if has_pub else None,
        }

    def _externalize_snapshot(self, raw_snapshot: dict | None, day_folder: str, stem: str, written_files: list[Path]) -> dict:
        if not isinstance(raw_snapshot, dict):
            return {}
        snap = deepcopy(raw_snapshot)
        recipe = snap.get("recipe")
        if isinstance(recipe, dict):
            for slot in ("portrait", "costume", "pose"):
                item = recipe.get(slot)
                if not isinstance(item, dict):
                    continue
                inline_src = next(
                    (str(item.get(field) or "") for field in ("原图", "预览图", "缩略图") if str(item.get(field) or "").lower().startswith("data:image/")),
                    "",
                )
                if inline_src:
                    ref_bytes, ref_mime = decode_data_image_uri(inline_src)
                    ref_ext = MIME_EXT.get(ref_mime, "png")
                    rel_ref = f"{day_folder}/refs/{stem}_{slot}.{ref_ext}"
                    abs_ref = self.root / rel_ref
                    _atomic_write_bytes(abs_ref, ref_bytes)
                    written_files.append(abs_ref)
                    ref_url = f"{MEDIA_URL_PREFIX}{rel_ref}"
                    for field in ("原图", "预览图", "缩略图"):
                        if field in item and str(item.get(field) or "").lower().startswith("data:image/"):
                            item[field] = ref_url
            extras = recipe.get("extraImages")
            if isinstance(extras, list):
                for idx, extra in enumerate(extras, 1):
                    if isinstance(extra, dict) and str(extra.get("url") or "").lower().startswith("data:image/"):
                        ref_bytes, ref_mime = decode_data_image_uri(str(extra["url"]))
                        ref_ext = MIME_EXT.get(ref_mime, "png")
                        rel_ref = f"{day_folder}/refs/{stem}_extra_{idx}.{ref_ext}"
                        abs_ref = self.root / rel_ref
                        _atomic_write_bytes(abs_ref, ref_bytes)
                        written_files.append(abs_ref)
                        extra["url"] = f"{MEDIA_URL_PREFIX}{rel_ref}"
        return _strip_secrets_and_inline_images(snap)

    def get_generation(self, record_id: str) -> dict | None:
        try:
            uid = str(uuid.UUID(str(record_id)))
        except (ValueError, TypeError):
            return None
        table = S.character_studio_generations
        with self.engine.connect() as conn:
            row = conn.execute(select(table).where(table.c.id == uid)).mappings().first()
        return self._serialize(dict(row)) if row else None

    def save_generation(
        self,
        *,
        image_bytes: bytes,
        provider: str,
        model: str,
        prompt: str,
        method: str = "",
        method_label: str = "",
        endpoint: str = "",
        upstream_model: str = "",
        recipe_summary: str = "",
        snapshot: dict | None = None,
        publication: dict | None = None,
        created_by: str = "",
        created_at=None,
        record_id: str | None = None,
    ) -> dict:
        if not image_bytes:
            raise ResourceError("生成图片字节为空", "empty_image", 422)
        mime = detect_image_mime(image_bytes)
        if not mime:
            raise ResourceError("生成结果不是受支持的有效图片格式", "invalid_image", 422)

        if record_id:
            try:
                uid = str(uuid.UUID(str(record_id)))
            except (ValueError, TypeError):
                uid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"character-studio:{record_id}"))
            existing = self.get_generation(uid)
            if existing is not None:
                return existing
        else:
            uid = str(uuid.uuid4())

        dt_utc = _parse_created_at(created_at)
        local_dt = dt_utc.astimezone()
        day_folder = local_dt.strftime("%Y-%m-%d")
        ext = MIME_EXT[mime]
        short_id = uid.split("-")[0]
        stem = f"{local_dt.strftime('%Y%m%d_%H%M%S')}_{short_id}"
        if (self.root / day_folder / f"{stem}.{ext}").exists():
            stem = f"{local_dt.strftime('%Y%m%d_%H%M%S')}_{uid.replace('-', '')[:16]}"

        prov, mdl, m_code, m_label, ep = infer_provenance(
            provider,
            model,
            method=method,
            method_label=method_label,
            endpoint=endpoint,
            snapshot=snapshot,
        )
        up_mdl = str(upstream_model or "").strip()
        if up_mdl == mdl:
            up_mdl = ""
        prompt_text = str(prompt or "")
        summary_text = str(recipe_summary or "").strip()

        rel_image = f"{day_folder}/{stem}.{ext}"
        rel_prompt = f"{day_folder}/{stem}.txt"
        abs_image = self.root / rel_image
        abs_prompt = self.root / rel_prompt
        sha = hashlib.sha256(image_bytes).hexdigest()

        written: list[Path] = []
        try:
            clean_snapshot = self._externalize_snapshot(snapshot, day_folder, stem, written)
            clean_pub = _strip_secrets_and_inline_images(publication) if isinstance(publication, dict) else {}
            _atomic_write_bytes(abs_image, image_bytes)
            written.append(abs_image)
            sidecar_text = _format_prompt_sidecar(
                record_id=uid,
                local_dt=local_dt,
                provider=prov,
                model=mdl,
                upstream_model=up_mdl,
                method_label=m_label,
                endpoint=ep,
                recipe_summary=summary_text,
                prompt=prompt_text,
            )
            _atomic_write_bytes(abs_prompt, sidecar_text.encode("utf-8"))
            written.append(abs_prompt)

            table = S.character_studio_generations
            values = {
                "id": uid,
                "image_path": rel_image,
                "prompt_path": rel_prompt,
                "sha256": sha,
                "mime_type": mime,
                "size_bytes": len(image_bytes),
                "provider": prov[:64],
                "model": mdl[:160],
                "upstream_model": up_mdl[:160],
                "method": m_code[:120],
                "method_label": m_label[:240],
                "endpoint": ep[:240],
                "prompt": prompt_text,
                "recipe_summary": summary_text,
                "snapshot": clean_snapshot,
                "publication": clean_pub,
                "created_by": str(created_by or ""),
                "created_at": dt_utc,
            }
            with self.engine.begin() as conn:
                stmt = pg_insert(table).values(**values).on_conflict_do_nothing(index_elements=[table.c.id])
                res = conn.execute(stmt)
                row = conn.execute(select(table).where(table.c.id == uid)).mappings().one()
                inserted = bool(res.rowcount)
            if not inserted and row["image_path"] != rel_image:
                for path in reversed(written):
                    path.unlink(missing_ok=True)
            return self._serialize(dict(row))
        except BaseException:
            for path in reversed(written):
                path.unlink(missing_ok=True)
            raise

    def list_generations(
        self,
        *,
        q: str = "",
        filter_key: str = "",
        provider: str = "",
        model: str = "",
        method: str = "",
        offset: int = 0,
        limit: int = 20,
    ) -> dict:
        if isinstance(offset, bool) or isinstance(limit, bool) or offset < 0 or not 1 <= limit <= 100:
            raise ResourceError("分页参数无效", "invalid_pagination", 422)
        table = S.character_studio_generations

        if filter_key:
            parts = filter_key.split("|", 2)
            if len(parts) == 3:
                provider, model, method = parts[0], parts[1], parts[2]

        conditions = []
        if provider:
            conditions.append(table.c.provider == provider)
        if model:
            conditions.append(table.c.model == model)
        if method:
            conditions.append(table.c.method == method)

        query_text = str(q or "").strip()
        if query_text:
            escaped = query_text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            like_pat = f"%{escaped}%"
            norm_query = re.sub(r"[_-]+", "-", query_text.lower())
            norm_escaped = norm_query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            norm_pat = f"%{norm_escaped}%"
            text_cols = (
                table.c.prompt,
                table.c.recipe_summary,
                table.c.model,
                table.c.upstream_model,
                table.c.method,
                table.c.method_label,
                table.c.endpoint,
                table.c.provider,
            )
            clauses = [col.ilike(like_pat, escape="\\") for col in text_cols]
            for id_col in (table.c.model, table.c.method, table.c.method_label):
                clauses.append(func.replace(func.lower(id_col), "_", "-").like(norm_pat, escape="\\"))
            conditions.append(or_(*clauses))

        with self.engine.connect() as conn:
            overall_total = int(conn.execute(select(func.count()).select_from(table)).scalar_one())
            facet_rows = conn.execute(
                select(
                    table.c.provider,
                    table.c.model,
                    table.c.method,
                    func.max(table.c.method_label).label("method_label"),
                    func.count().label("count"),
                    func.max(table.c.created_at).label("latest"),
                )
                .group_by(table.c.provider, table.c.model, table.c.method)
                .order_by(desc("latest"))
            ).mappings().all()

            count_stmt = select(func.count()).select_from(table)
            rows_stmt = select(table).order_by(desc(table.c.created_at), desc(table.c.id)).offset(offset).limit(limit)
            if conditions:
                count_stmt = count_stmt.where(*conditions)
                rows_stmt = rows_stmt.where(*conditions)
            total = int(conn.execute(count_stmt).scalar_one())
            rows = conn.execute(rows_stmt).mappings().all()

        facets = []
        for f in facet_rows:
            f_model = "" if f["model"] == "unrecorded" else f["model"]
            f_method = "" if f["method"] == "unrecorded" else f["method"]
            f_label = "" if f["method"] == "unrecorded" and f["method_label"] == "unrecorded" else f["method_label"]
            facets.append({
                "key": f"{f['provider']}|{f['model']}|{f['method']}",
                "provider": f["provider"],
                "model": f_model,
                "method": f_method,
                "methodLabel": f_label,
                "count": int(f["count"]),
            })

        next_offset = offset + limit if offset + limit < total else None
        return {
            "items": [self._serialize(dict(r)) for r in rows],
            "total": total,
            "overall_total": overall_total,
            "offset": offset,
            "limit": limit,
            "next_offset": next_offset,
            "facets": facets,
        }

    def update_publication(self, record_id: str, publication: dict, *, actor: str = "") -> dict:
        try:
            uid = str(uuid.UUID(str(record_id)))
        except (ValueError, TypeError) as exc:
            raise NotFound("合成记录不存在") from exc
        if not isinstance(publication, dict):
            raise ResourceError("入库回执格式无效", "invalid_publication", 422)
        clean_pub = _strip_secrets_and_inline_images(publication)
        table = S.character_studio_generations
        with self.engine.begin() as conn:
            existing = conn.execute(select(table).where(table.c.id == uid).with_for_update()).mappings().first()
            if not existing:
                raise NotFound("合成记录不存在")
            prev_pub = existing["publication"] if isinstance(existing["publication"], dict) else {}
            prev_actor = str(prev_pub.get("actor") or "").strip()
            next_actor = str(clean_pub.get("actor") or actor or "").strip()
            if prev_actor and next_actor and prev_actor != next_actor:
                raise Conflict("这次入库由另一账号发起，请切回原账号继续，不能复用另一身份的回执")
            conn.execute(update(table).where(table.c.id == uid).values(publication=clean_pub))
            updated = conn.execute(select(table).where(table.c.id == uid)).mappings().one()
        return self._serialize(dict(updated))

    def _collect_record_files(self, row: dict) -> list[Path]:
        paths: list[Path] = []
        for rel in (row.get("image_path"), row.get("prompt_path")):
            if rel:
                resolved = self._safe_relative(str(rel))
                if resolved is not None:
                    paths.append(resolved)
        img_rel = str(row.get("image_path") or "")
        if "/" in img_rel:
            day_folder, filename = img_rel.split("/", 1)
            stem = Path(filename).stem
            refs_dir = self._safe_relative(f"{day_folder}/refs")
            if refs_dir is not None and refs_dir.is_dir():
                for ref_file in refs_dir.glob(f"{stem}_*"):
                    if ref_file.is_file() and not ref_file.is_symlink():
                        paths.append(ref_file)
        return paths

    def _cleanup_files(self, paths: list[Path]) -> None:
        dirs: set[Path] = set()
        for path in paths:
            try:
                if path.parent.is_relative_to(self.root):
                    dirs.add(path.parent)
                path.unlink(missing_ok=True)
            except OSError:
                continue
        for folder in sorted(dirs, key=lambda d: len(d.parts), reverse=True):
            cursor = folder
            while cursor != self.root and cursor.is_relative_to(self.root):
                try:
                    cursor.rmdir()
                except OSError:
                    break
                cursor = cursor.parent

    def delete_generation(self, record_id: str) -> bool:
        try:
            uid = str(uuid.UUID(str(record_id)))
        except (ValueError, TypeError) as exc:
            raise NotFound("合成记录不存在") from exc
        table = S.character_studio_generations
        with self.engine.begin() as conn:
            row = conn.execute(select(table).where(table.c.id == uid).with_for_update()).mappings().first()
            if not row:
                raise NotFound("合成记录不存在")
            files = self._collect_record_files(dict(row))
            conn.execute(delete(table).where(table.c.id == uid))
        self._cleanup_files(files)
        return True

    def clear_generations(self) -> int:
        table = S.character_studio_generations
        with self.engine.begin() as conn:
            rows = conn.execute(select(table).with_for_update()).mappings().all()
            files: list[Path] = []
            for r in rows:
                files.extend(self._collect_record_files(dict(r)))
            deleted = int(conn.execute(delete(table)).rowcount or 0)
        self._cleanup_files(files)
        return deleted
