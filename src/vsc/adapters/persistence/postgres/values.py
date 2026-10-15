"""Canonical immutable values shared by PostgreSQL repository modules."""
import hashlib
import json
import uuid
from datetime import datetime
from decimal import Decimal
from vsc.assets.resource_service import ResourceError


def new_id():
    return str(uuid.uuid4())


def checked_id(value):
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise ResourceError("无效的资源 ID", "invalid_id")


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [clean(v) for v in value]
    if isinstance(value, (datetime, uuid.UUID)):
        return value.isoformat() if isinstance(value, datetime) else str(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def canonical(value):
    return json.dumps(clean(value), sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def verify_sha(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ResourceError("sha256 必须是 64 位小写十六进制摘要", "invalid_sha256")
    return value


