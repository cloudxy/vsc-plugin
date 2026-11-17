"""Bounded public provider failure details; never credentials, bytes or paths."""
import os
import re

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")


def safe_generation_detail(detail: str, redact_secret: str = "") -> str:
    """Expose failure facts, never credentials, image bytes or local file paths."""
    text = _ANSI_RE.sub("", str(detail or ""))
    secrets = [redact_secret, *(value for name, value in os.environ.items()
        if re.search(r"(?:TOKEN|SECRET|API_KEY|ACCESS_KEY)", name, re.I) and len(value) >= 8)]
    for secret in sorted(filter(None, secrets), key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"(?i)\bBearer\s+[^\s\"',;]+", "Bearer [REDACTED]", text)
    text = re.sub(r"(?i)\b(?:sk-|xai-|AIza)[a-z0-9_-]+", "[REDACTED]", text)
    text = re.sub(r"(?i)((?:api[_-]?key|access[_-]?token|refresh[_-]?token|password)[\"']?\s*[:=]\s*[\"']?)[^\s\"',;}]+", r"\1[REDACTED]", text)
    text = re.sub(r"\beyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+", "[REDACTED]", text)
    text = re.sub(r"data:image/[^\s\"']+", "[图片数据]", text)
    text = re.sub(r"(?<![a-zA-Z0-9:/])/(?:Users|home|private|tmp|var)/[^\s\"'<>]+", "[本机路径]", text)
    return re.sub(r"\s+", " ", text).strip()[:2400]

