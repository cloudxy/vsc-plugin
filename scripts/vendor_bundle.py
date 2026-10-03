#!/usr/bin/env python3
"""Bounded, non-executing Skill resource bundles shared by review and candidate storage.

A usable bundle includes the complete Skill directory, recursively referenced local resources,
and repository-level license/dependency declarations. URLs and fenced examples are not downloaded.
Diagnostic mode records unusable Skills and rejected-resource metadata without reading unsafe paths,
symlink destinations or oversized blobs. Such candidates are explicitly incomplete and cannot be
silently adopted. Aggregate file/byte limits still fail the whole scan closed.
"""
import hashlib
import json
import os
import re
import stat
from pathlib import Path, PurePosixPath

MAX_FILES = 5000
MAX_BYTES = 64 * 1024 * 1024
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_INVENTORY = 100000
EXCLUDED = {".git", "node_modules", "__pycache__", ".venv", "venv", ".reviews"}
INTERNAL_FILES = {".vsc-candidate.json", ".analysis.json"}
ROOT_METADATA = {"package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lock",
                 "bun.lockb", "pyproject.toml", "requirements.txt", "uv.lock", "Cargo.toml", "Cargo.lock"}
TEXT_SUFFIXES = {".md", ".markdown", ".yaml", ".yml", ".json", ".toml"}
LINK = re.compile(r"!?\[[^\]]*\]\(([^\s)]+)(?:\s+[^)]*)?\)")
BACKTICK = re.compile(r"`([^`\n]+)`")
CODE_ABSOLUTE = re.compile(r"(?:^|[\s=\"'])(~?/[^\s`'\"]+|[A-Za-z]:[/\\][^\s`'\"]+|file:[^\s`'\"]+)")
CODE_RELATIVE = re.compile(r"(?:^|[\s=\"'])(\.{1,2}/(?:[\w.-]+/)*[\w.-]+\.[\w]+|(?:[\w.-]+/)+[\w.-]+\.[\w]+)")
BUNDLE_ALGORITHM = "vsc.skill-resource-closure/v2"
FILESYSTEM_ROOTS = {"Users", "home", "root", "etc", "tmp", "private", "var", "opt", "usr", "bin", "sbin", "dev", "proc", "sys", "Volumes", "Applications", "Library"}
RUNTIME_CONFIG_ROOTS = ("~/.claude/", "~/.dsh/", "~/.agents/")


class BundleError(ValueError):
    pass


class ResourceError(BundleError):
    """One resource is unusable; diagnostic mode can report it without following/reading it."""


def safe_relative(relative):
    if not isinstance(relative, str) or "\\" in relative or any(ord(char) < 32 or ord(char) == 127 for char in relative):
        raise BundleError(f"不安全资源路径：{relative!r}")
    path = PurePosixPath(relative)
    if path.is_absolute() or not path.parts or any(part in {"..", "."} for part in path.parts):
        raise BundleError(f"不安全资源路径：{relative!r}")
    return path.as_posix()


def local_inventory(root):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise BundleError(f"资源根目录必须是存在的非符号链接目录：{root}")
    records = {}
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(name for name in dirs if name not in EXCLUDED)
        for name in dirs + files:
            if name in INTERNAL_FILES:
                continue
            path = Path(directory) / name
            relative = safe_relative(path.relative_to(root).as_posix())
            info = path.lstat()
            if stat.S_ISDIR(info.st_mode):
                continue
            records[relative] = {"size": info.st_size, "mode": info.st_mode}
            if len(records) > MAX_INVENTORY:
                raise BundleError("仓库文件清单超过安全上限")
    return records


def metadata_path(path):
    name = PurePosixPath(path).name
    upper = name.upper()
    return "/" not in path and (upper.startswith(("LICENSE", "LICENCE", "NOTICE", "COPYING"))
                                or name in ROOT_METADATA or name.startswith("requirements"))


def prose_only(text):
    """Markdown fenced examples are not runtime dependency declarations."""
    lines, fence = [], None
    for line in text.splitlines():
        opening = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if fence:
            if opening and opening.group(1)[0] == fence[0] and len(opening.group(1)) >= len(fence):
                fence = None
            continue
        if opening:
            fence = opening.group(1)
            continue
        lines.append(line)
    return "\n".join(lines)


def referenced_paths(text, origin, inventory, missing=None, runtime=None):
    """Resolve explicit local references; ../ is allowed only while staying inside the source root."""
    text = prose_only(text)
    def reject(raw, message):
        if missing is None:
            raise BundleError(f"{message}：{origin} -> {raw}")
        missing.append({"origin": origin, "reference": raw, "kind": "unsafe_local_reference", "reason": message})

    links = LINK.findall(text)
    references = [(value, "link") for value in links]
    for code in BACKTICK.findall(text):
        if code.strip() in {"/tmp", "/private/tmp"}:
            if runtime is not None:
                runtime.append({"origin": origin, "reference": code, "kind": "runtime_output_directory_not_bundled"})
            continue  # Documented output directory, not a source resource.
        absolute = CODE_ABSOLUTE.findall(code)
        for path in absolute:
            if path.startswith(RUNTIME_CONFIG_ROOTS):
                if runtime is not None:
                    runtime.append({"origin": origin, "reference": path, "kind": "runtime_configuration_not_bundled"})
                continue
            first = path.lstrip("/").split("/", 1)[0]
            if path.startswith("/") and first not in FILESYSTEM_ROOTS and (
                re.match(r"^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+/", code)
                or not re.search(r"[A-Za-z0-9_]", path)
                or re.fullmatch(r"v\d+", first)
                or ("." not in path and not re.match(r"^(?:cat|python\d*|bash|sh|node|cp|mv|rm|open)\s", code))
            ):
                continue  # HTTP endpoint, JSX closure or /skill command, not a filesystem path.
            reject(code, "反引号中的本机绝对路径不允许")
        references.extend((value, "code") for value in CODE_RELATIVE.findall(code))
    result = set()
    for raw, kind in references:
        raw = raw.split("#", 1)[0].split("?", 1)[0]
        if raw.lower().startswith("file:") or re.match(r"^[A-Za-z]:[/\\]", raw):
            reject(raw, "本机绝对引用不允许")
            continue
        if not raw or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", raw) or raw.startswith("#"):
            continue
        if raw.startswith("/"):
            first = raw.lstrip("/").split("/", 1)[0]
            if kind == "link" and (raw.startswith("//") or first not in FILESYSTEM_ROOTS):
                # CommonMark links resolve against a web origin: /docs/... and /v1/... are URL
                # routes, not POSIX filesystem requests. Never download or materialize them.
                continue
            reject(raw, "本机绝对引用不允许")
            continue
        if "\\" in raw:
            reject(raw, "本地引用越界")
            continue
        parts = list(PurePosixPath(origin).parent.parts)
        invalid = False
        for part in PurePosixPath(raw).parts:
            if part == "..":
                if not parts:
                    reject(raw, "本地引用越界")
                    invalid = True
                    break
                parts.pop()
            elif part != ".":
                parts.append(part)
        if invalid:
            continue
        relative = "/".join(parts)
        matches = [name for name in inventory if name == relative or name.startswith(relative + "/")]
        if not matches:
            symlink_parents = [name for name, record in inventory.items()
                               if stat.S_ISLNK(record["mode"]) and relative.startswith(name + "/")]
            if symlink_parents:
                reject(raw, "引用穿越符号链接，不读取目标")
                continue
            # Backtick paths can be example output paths; links are commitments, not examples.
            if kind == "link":
                problem = {"origin": origin, "reference": raw, "kind": "missing_local_reference"}
                if missing is None:
                    raise BundleError(f"本地引用缺失：{origin} -> {raw}")
                missing.append(problem)
            continue
        result.update(matches)
    return result


def build_bundles(inventory, read_file, allow_missing=False):
    """Return Skill manifests plus selected bytes. Reader may be filesystem or non-checkout Git."""
    skills = sorted(path for path in inventory if PurePosixPath(path).name == "SKILL.md")
    shared = {path for path in inventory if metadata_path(path)}
    content = {}

    def read(path):
        if path not in content:
            record = inventory[path]
            mode = record["mode"]
            if not stat.S_ISREG(mode) or stat.S_ISLNK(mode):
                raise ResourceError(f"拒绝符号链接或特殊资源：{path}")
            if record["size"] is not None and record["size"] > MAX_FILE_BYTES:
                raise ResourceError(f"资源文件超过 {MAX_FILE_BYTES} 字节：{path}")
            data = read_file(path)
            if len(data) > MAX_FILE_BYTES:
                raise ResourceError(f"资源文件超过 {MAX_FILE_BYTES} 字节：{path}")
            if record["size"] is not None and len(data) != record["size"]:
                raise BundleError(f"读取期间资源大小变化：{path}")
            content[path] = data
            if len(content) > MAX_FILES or sum(len(value) for value in content.values()) > MAX_BYTES:
                raise BundleError("Skill 资源包超过文件数或总大小上限")
        return content[path]

    # Preserve provenance even for sources that currently contain no SKILL.md.
    for path in sorted(shared):
        read(path)
    bundles = {}
    for skill in skills:
        problems = []
        runtime = []
        rejected = {}
        directory = PurePosixPath(skill).parent.as_posix()
        paths = set(shared)
        paths.update(path for path in inventory if directory == "." or path.startswith(directory + "/"))
        pending = sorted(paths)
        done = set()
        while pending:
            path = pending.pop()
            if path in done:
                continue
            try:
                data = read(path)
            except ResourceError as exc:
                if not allow_missing:
                    raise
                problems.append({"origin": skill, "reference": path, "kind": "rejected_resource", "reason": str(exc)})
                rejected[path] = inventory[path]
                done.add(path)
                continue
            done.add(path)
            if PurePosixPath(path).suffix.lower() in TEXT_SUFFIXES:
                try:
                    linked = referenced_paths(data.decode("utf-8"), path, inventory, problems if allow_missing else None, runtime)
                except UnicodeDecodeError as exc:
                    raise BundleError(f"文本资源不是 UTF-8：{path}") from exc
                pending.extend(sorted(linked - done))
                paths.update(linked)
        files = {path: {"sha256": hashlib.sha256(content[path]).hexdigest(), "size": len(content[path]),
                        "executable": bool(inventory[path]["mode"] & 0o111)} for path in sorted(paths) if path in content}
        problems = [dict(values) for values in sorted({tuple(sorted(problem.items())) for problem in problems})]
        runtime = [dict(values) for values in sorted({tuple(sorted(reference.items())) for reference in runtime})]
        digest_input = {"files": files, "problems": problems} if problems else files
        digest = hashlib.sha256(json.dumps(digest_input, sort_keys=True).encode()).hexdigest()
        bundles[skill] = {"sha256": digest, "files": files}
        if problems:
            bundles[skill].update(usable=False, problems=problems)
        if runtime:
            bundles[skill]["external_runtime_references"] = runtime
        if rejected:
            bundles[skill]["rejected_resources"] = rejected
    return bundles, content


def scan(root, allow_missing=False):
    root = Path(root)
    metadata = root / ".vsc-candidate.json"
    candidate = None
    if metadata.exists():
        try:
            candidate = json.loads(metadata.read_text("utf-8"))
            version = candidate.get("format")
        except (OSError, ValueError) as exc:
            raise BundleError("候选清单损坏") from exc
        if version != "vsc.vendor-skill-candidate/v2":
            raise BundleError("旧候选只有 SKILL.md，必须重新生成完整资源包")
    inventory = local_inventory(root)
    if candidate:
        # Rejected links/oversize files are never materialized. Their original lstat record remains
        # in the manifest so integrity/review reproduces the diagnostic rather than calling a
        # deliberately incomplete candidate usable. No link destination or huge blob is read.
        for bundle in candidate.get("skills", {}).values():
            for path, record in bundle.get("rejected_resources", {}).items():
                safe_relative(path)
                if path in inventory:
                    raise BundleError(f"被拒绝资源不应已物化：{path}")
                if not isinstance(record.get("mode"), int) or not isinstance(record.get("size"), (int, type(None))):
                    raise BundleError("拒绝资源的清单不合法")
                if stat.S_ISREG(record["mode"]) and (record["size"] is None or record["size"] <= MAX_FILE_BYTES):
                    raise BundleError("拒绝资源清单不能指示可读取的普通文件")
                inventory[path] = record
    return build_bundles(inventory, lambda path: (root / path).read_bytes(), allow_missing=allow_missing)
