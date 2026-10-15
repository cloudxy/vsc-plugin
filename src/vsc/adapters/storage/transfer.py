"""Provider-independent HTTPS transfer into controlled staging."""
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen

from vsc.assets.resource_service import ResourceError


def download_https(uri, target, maximum_bytes=1024 * 1024 * 1024):
    if urlsplit(uri).scheme != "https":
        raise ResourceError("下载只接受 HTTPS", "unsafe_output_url")
    target = Path(target)
    partial = target.with_name(target.name + ".part")
    size = 0
    try:
        with urlopen(uri, timeout=180) as response, partial.open("xb") as output:
            if urlsplit(response.geturl()).scheme != "https":
                raise ResourceError("下载重定向离开 HTTPS", "unsafe_output_url")
            for block in iter(lambda: response.read(1024 * 1024), b""):
                size += len(block)
                if size > maximum_bytes:
                    raise ResourceError("下载超过存储大小限制", "output_too_large")
                output.write(block)
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)
