"""Official npm ArkCLI package staging; never run postinstall or candidate code.

Checksums establish downloaded-byte integrity and registered source identity,
not publisher signatures or an audit of the closed executable's behavior.
"""
import base64
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import tarfile
import tempfile
import urllib.request
from urllib.parse import urlsplit

TOOL_ID = "volcengine-ark-cli-release"
PACKAGE = "@volcengine/ark-cli"
REGISTRY = "https://registry.npmjs.org/@volcengine%2fark-cli/"
CDN = "https://lf3-static.bytednsdoc.com/obj/eden-cn/psjryh/ljhwZthlaukjlkulzlp/prod/"
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")


class PackageError(RuntimeError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise PackageError("官方分发地址重定向未采用；保留旧版")


def fetch(url, limit=8 * 1024 * 1024):
    """Credential-free HTTPS GET with byte cap and no redirect/proxy/auth reuse."""
    if not url.startswith((REGISTRY, CDN, "https://registry.npmjs.org/@volcengine/ark-cli/-/ark-cli-")):
        raise PackageError("分发 URL 不属于登记的官方来源")
    parsed = urlsplit(url)
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.scheme != "https":
        raise PackageError("分发 URL 含不允许的身份或查询字段")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(urllib.request.Request(url, headers={"Accept": "application/json, application/octet-stream"}), timeout=20) as response:
            if response.status != 200:
                raise PackageError("官方分发未返回成功响应")
            value = response.read(limit + 1)
        if len(value) > limit:
            raise PackageError("官方分发超过安全大小限制")
        return value
    except PackageError:
        raise
    except Exception:
        raise PackageError("官方包下载失败或超时；旧版保持可用") from None


def metadata(version="latest", download=fetch):
    if version != "latest" and not VERSION.fullmatch(version):
        raise PackageError("官方包版本格式无效")
    try:
        value = json.loads(download(REGISTRY + version))
        release = value["version"]
        dist = value["dist"]
        if value["name"] != PACKAGE or not VERSION.fullmatch(release) or (version != "latest" and version != release):
            raise ValueError()
        if dist["tarball"] != "https://registry.npmjs.org/@volcengine/ark-cli/-/ark-cli-" + release + ".tgz":
            raise ValueError()
        if not re.fullmatch(r"sha512-[A-Za-z0-9+/]{86}==", dist["integrity"]):
            raise ValueError()
        fixed = {"version": release, "tarball": dist["tarball"], "integrity": dist["integrity"]}
        digest = hashlib.sha256(json.dumps(fixed, sort_keys=True).encode()).hexdigest()
        return dict(fixed, revision=release + "." + digest)
    except PackageError:
        raise
    except Exception:
        raise PackageError("官方 npm 元数据、来源或完整性字段无效") from None


def unpack(content, target):
    """Only bounded regular package files; never links, devices, traversal or scripts execution."""
    with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as archive:
        members, size = [], 0
        for member in archive:
            members.append(member)
            size += member.size
            if len(members) > 512 or size > 32 * 1024 * 1024:
                raise PackageError("官方包解压后超过限制")
        seen = set()
        for member in members:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != "package" or member.name in seen:
                raise PackageError("官方包含不安全路径")
            seen.add(member.name)
            if member.isdir():
                continue
            if not member.isfile() or member.size < 0:
                raise PackageError("官方包含链接或非普通文件")
            output = target.joinpath(*path.parts)
            output.parent.mkdir(parents=True, exist_ok=True)
            stream = archive.extractfile(member)
            if stream is None:
                raise PackageError("官方包文件不可读取")
            output.write_bytes(stream.read())


def current(work):
    path = Path(work) / "official-packages" / TOOL_ID / "active.json"
    if path.is_symlink():
        raise PackageError("官方包活跃指针不可为链接")
    if not path.exists():
        return None
    value = json.loads(path.read_text("utf-8"))
    revision = value.get("revision", "")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+\.[0-9a-f]{64}", revision):
        raise PackageError("官方包活跃版本记录无效")
    root = path.parent / revision
    if root.is_symlink() or not root.is_dir():
        raise PackageError("官方包固定环境缺失")
    for relative, digest in value.get("files", {}).items():
        file = root / relative
        if ".." in PurePosixPath(relative).parts or PurePosixPath(relative).is_absolute() or file.is_symlink() or not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest() != digest:
            raise PackageError("官方包固定环境被修改；未覆盖")
    return value


def tool(work):
    active = current(work)
    return {"id": TOOL_ID, "name": "Ark CLI 官方分发包（交互参考）", "source_kind": "official_npm", "official": True,
        "source_url": "https://www.npmjs.com/package/@volcengine/ark-cli", "status": "unchecked",
        "current_revision": active["revision"] if active else None, "latest_revision": None, "can_update": False,
        "execution_status": "method_reference", "verification": "official_url_and_checksums_not_signature_or_source_audit",
        "message": "可校验下载固定版本；内部重试与输入改写未经源码核验，不接自动生产执行，不运行 postinstall"}


def check(work, download=fetch):
    item = tool(work)
    latest = metadata(download=download)
    same = item["current_revision"] == latest["revision"]
    return dict(item, latest_revision=latest["revision"], status="up_to_date" if same else "update_available", can_update=not same)


def adopt(work, expected, actor, active_jobs, download=fetch):
    """Called under ProviderSync process/DB locks; one atomic pointer is the commit."""
    match = re.fullmatch(r"([0-9]+\.[0-9]+\.[0-9]+)\.[0-9a-f]{64}", str(expected))
    if not match or not actor:
        raise PackageError("需要人工更新动作与检查得到的固定包版本")
    release = metadata(match[1], download)
    if release["revision"] != expected:
        raise PackageError("检查后的官方包元数据改变；保留旧版，请重新检查")
    base = Path(work) / "official-packages" / TOOL_ID
    for path in (base.parent, base):
        if path.is_symlink():
            raise PackageError("官方包目录不能为链接")
        path.mkdir(parents=True, exist_ok=True)
    old = current(work)
    if old and old["revision"] == expected:
        return dict(tool(work), status="up_to_date", latest_revision=expected)
    stage = Path(tempfile.mkdtemp(prefix="candidate-", dir=base))
    try:
        package = download(release["tarball"])
        actual = "sha512-" + base64.b64encode(hashlib.sha512(package).digest()).decode()
        if actual != release["integrity"]:
            raise PackageError("npm 包完整性校验失败；旧版保持可用")
        unpack(package, stage)
        manifest = json.loads((stage / "package/manifest.json").read_text("utf-8"))
        info = json.loads((stage / "package/package.json").read_text("utf-8"))
        if info.get("name") != PACKAGE or info.get("version") != release["version"] or manifest.get("version") != release["version"]:
            raise PackageError("官方包内版本或身份不匹配")
        license_text = (stage / "package/LICENSE").read_text("utf-8")
        if info.get("license") != "Apache-2.0" or "Apache License" not in license_text or "Version 2.0, January 2004" not in license_text:
            raise PackageError("官方包许可证缺失或改变，未采用")
        system = {"Darwin": "darwin", "Linux": "linux"}.get(platform.system())
        machine = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "amd64", "AMD64": "amd64"}.get(platform.machine())
        if not system or not machine:
            raise PackageError("当前系统没有受支持的官方固定分发包")
        name = system + "-" + machine
        entry = manifest.get("platforms", {}).get(name, {})
        expected_url = CDN + release["version"] + "/arkcli-" + release["version"] + "-" + name
        if entry.get("url") != expected_url or not re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256"))):
            raise PackageError("官方平台分发来源或摘要无效")
        executable = download(expected_url, 256 * 1024 * 1024)
        if hashlib.sha256(executable).hexdigest() != entry["sha256"]:
            raise PackageError("官方执行文件完整性校验失败")
        (stage / "arkcli").write_bytes(executable)
        (stage / "arkcli").chmod(0o700)
        files = {str(path.relative_to(stage)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(stage.rglob("*")) if path.is_file()}
        record = dict(release, files=files, actor=actor, execution_status="method_reference",
            verification="official_url_and_checksums_not_signature_or_source_audit", scripts_executed=False,
            license_spdx="Apache-2.0", license_evidence="package/LICENSE", redistribution="local_only")
        if active_jobs is None or active_jobs(TOOL_ID):
            raise PackageError("未连接任务权威或存在在途任务；没有切换环境")
        if current(work) != old:
            raise PackageError("活跃版本发生变化，请重新检查")
        destination = base / expected
        if destination.exists():
            # Never overwrite an old immutable environment, including a failed stage.
            raise PackageError("固定版本目录已经存在，需先核对本机记录")
        os.replace(stage, destination)
        from tools.maintenance.vendor_review import write_atomic
        write_atomic(base / "active.json", json.dumps(record, ensure_ascii=False, indent=2) + "\n")
        return dict(tool(work), status="updated", latest_revision=expected,
            message="已校验下载官方分发包，保留旧版本；未执行安装脚本或模型调用，CLI仅作交互参考")
    except PackageError:
        raise
    except Exception:
        raise PackageError("官方包下载或切换失败；旧活跃指针保持不变") from None
    finally:
        if stage.exists():
            shutil.rmtree(stage)
