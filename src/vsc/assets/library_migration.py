"""Explicit legacy-library migration; old JSON is never a runtime mirror.

The local manifest is a recoverable migration journal, not resource authority.
Global import keys/versions are authoritative receipts. Source files stay intact.
"""
from pathlib import Path
import hashlib
import json
import shutil

from vsc.assets.resource_service import Conflict, ResourceError
from vsc.assets import library as legacy


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class LegacyLibraryMigration:
    def __init__(self, service=None, root=None):
        self.service = service
        self.root = legacy.library_root(root)
        if self.root.is_symlink():
            raise ResourceError("旧库根目录不能是符号链接", "unsafe_library_root")
        self.root = self.root.resolve()
        self.namespace = hashlib.sha256(str(self.root).encode()).hexdigest()[:20]
        self.marker = self.root / ".vsc-pg-library-migration.json"

    def _state(self):
        if self.marker.is_symlink():
            raise ResourceError("迁移状态不能是符号链接", "unsafe_library_root")
        return json.loads(self.marker.read_text("utf-8")) if self.marker.is_file() else None

    def preview(self, permissions=None):
        """Read files only: no DB connection, staging, locks or source writes."""
        permissions = permissions or {}
        if not isinstance(permissions, dict):
            raise ResourceError("逐项共享许可必须为对象", "invalid_migration_permissions")
        kinds, rights = legacy.taxonomy()
        entries, seen = [], set()
        for path in sorted(self.root.glob("*/*/item.json")):
            issues, members, inventory = [], [], []
            try:
                if path.is_symlink() or not path.resolve().is_relative_to(self.root):
                    raise ValueError("unsafe item path")
                raw = path.read_bytes()
                item = json.loads(raw)
                if not isinstance(item, dict):
                    raise ValueError("legacy item must be an object")
                issues.extend(legacy.item_errors(item, kinds, rights))
            except (ValueError, OSError, TypeError):
                entries.append({"legacy_id": str(path.relative_to(self.root)), "status": "pending",
                    "issues": ["invalid_legacy_index"], "path": str(path.relative_to(self.root)),
                    "index_sha256": legacy.sha256(path) if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(self.root) else None})
                continue
            item_id = item.get("id") if isinstance(item.get("id"), str) else str(path.parent.name)
            if item_id in seen:
                issues.append("duplicate_legacy_id")
            seen.add(item_id)
            if path.parent.name != item_id or path.parent.parent.name != item.get("kind"):
                issues.append("legacy_directory_mismatch")
            declared = permissions.get(item_id)
            if declared is None:
                old_rights = item.get("rights", {})
                old_rights = old_rights if isinstance(old_rights, dict) else {}
                declared = {"license": {"outcome": "owned" if old_rights.get("status") == "owned" else "licensed",
                    "allow_workspace_reuse": old_rights.get("allow_workspace_reuse"),
                    "evidence": old_rights.get("source") or old_rights.get("license")},
                    "allowed_purposes": old_rights.get("allowed_purposes"), "expires_at": old_rights.get("expires_at")}
                if old_rights.get("status") in {"unknown", "temp_only"}:
                    issues.append("legacy_rights_unverified")
            if not isinstance(declared, dict):
                declared = {}
                issues.append("invalid_permission_evidence")
            license = declared.get("license", {})
            if (not isinstance(license, dict) or license.get("allow_workspace_reuse") is not True
                    or license.get("outcome") not in {"owned", "licensed"}
                    or not isinstance(license.get("evidence"), str) or not license["evidence"].strip()):
                issues.append("workspace_reuse_permission_missing")
            purposes = declared.get("allowed_purposes")
            if not isinstance(purposes, list) or not purposes or any(not isinstance(purpose, str) or not purpose for purpose in purposes):
                issues.append("purpose_scope_missing")
            for index, file in enumerate(item.get("files", []) if isinstance(item.get("files", []), list) else []):
                if not isinstance(file, dict) or not isinstance(file.get("path"), str):
                    issues.append("invalid_legacy_file")
                    continue
                relative = Path(file["path"])
                source = path.parent / relative
                safe = not relative.is_absolute() and ".." not in relative.parts and not source.is_symlink() and source.resolve().is_relative_to(path.parent.resolve())
                actual = None
                if not safe:
                    issues.append("unsafe_legacy_file")
                elif not source.is_file():
                    issues.append("legacy_missing_bytes")
                else:
                    actual = legacy.sha256(source)
                    if actual != file.get("sha256"):
                        issues.append("legacy_sha_mismatch")
                inventory.append({"path": file["path"], "expected_sha256": file.get("sha256"), "actual_sha256": actual})
                members.append({"member_key": "file-%03d" % (index + 1), "path": str(source.relative_to(self.root)),
                    "sha256": file.get("sha256"), "role": file.get("role", "reference")})
            specification = {key: item[key] for key in ("attributes", "tags", "style") if item.get(key)}
            if not members and not item.get("attributes"):
                issues.append("provider_reference_without_bytes")
            identity = "legacy:" + self.namespace + ":" + str(item.get("kind")) + ":" + item_id
            content_sha = _digest({"index_sha256": hashlib.sha256(raw).hexdigest(), "files": inventory, "permission": declared})
            payload = {"library_key": identity, "title": item.get("name"), "category": item.get("kind"),
                "description": item.get("summary"), "specification": specification, "allowed_purposes": purposes,
                "license": license, "expires_at": declared.get("expires_at"), "import_key": identity + ":" + content_sha}
            entries.append({"legacy_id": item_id, "path": str(path.relative_to(self.root)),
                "index_sha256": hashlib.sha256(raw).hexdigest(), "content_sha256": content_sha,
                "library_key": identity, "import_key": payload["import_key"], "payload": payload,
                "members": members, "files": inventory, "specification_only": not members,
                "status": "pending" if issues else "ready", "issues": sorted(set(issues))})
        inventory_sha = _digest(entries)
        state = self._state()
        return {"format": "vsc.library-migration-preview/v1", "library_root": str(self.root),
            "inventory_sha256": inventory_sha, "entries": entries, "total": len(entries),
            "ready": sum(entry["status"] == "ready" for entry in entries),
            "pending": sum(entry["status"] == "pending" for entry in entries),
            "state": state["status"] if state else "legacy", "writes": 0}

    def _freeze(self, inventory_sha, permissions, actor):
        plan = self.preview(permissions)
        if plan["inventory_sha256"] != inventory_sha:
            raise Conflict("旧库或许可已改变，请重做迁移预览", "library_migration_source_changed")
        state = self._state()
        if state:
            if state["inventory_sha256"] != inventory_sha:
                raise Conflict("已有另一固定迁移，不能覆盖", "library_migration_conflict")
            return state, plan
        backup = self.root / ".vsc-migration-backups" / inventory_sha
        if backup.is_symlink() or not backup.resolve().is_relative_to(self.root):
            raise ResourceError("备份路径不安全", "unsafe_library_root")
        backup.mkdir(parents=True, exist_ok=True)
        # Snapshot index and every safe, present declared file. Missing files
        # remain pending evidence, never replaced with invented media.
        for entry in plan["entries"]:
            paths = [entry["path"]] + [member["path"] for member in entry.get("members", [])]
            for relative in paths:
                source = self.root / relative
                if (".." not in Path(relative).parts and source.is_file() and not source.is_symlink()
                        and source.resolve().is_relative_to(self.root)):
                    target = backup / relative
                    if target.is_symlink() or not target.resolve().is_relative_to(backup):
                        raise ResourceError("备份目标不安全", "unsafe_library_root")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
                    if legacy.sha256(target) != legacy.sha256(source):
                        raise ResourceError("备份字节核对失败", "library_backup_mismatch")
        legacy.write_json(backup / "inventory.json", plan)
        if self.preview(permissions)["inventory_sha256"] != inventory_sha:
            raise Conflict("备份期间旧库发生变化，尚未冻结或导入", "library_migration_source_changed")
        state = {"format": "vsc.library-migration/v1", "status": "frozen", "inventory_sha256": inventory_sha,
            "backup": str(backup), "actor": actor, "permissions": permissions or {}, "receipts": {},
            "pending": [{"legacy_id": entry["legacy_id"], "issues": entry["issues"]} for entry in plan["entries"] if entry["status"] == "pending"]}
        legacy.write_json(self.marker, state)
        return state, plan

    def import_items(self, inventory_sha, *, actor, permissions=None):
        if self.service is None or self.service.storage is None:
            raise ResourceError("迁移导入需要真实共享库和受控存储", "storage_unavailable")
        self.service._actor(actor)
        with legacy.mutation_lock(self.root, allow_migration=True):
            old = self._state()
            permissions = permissions if permissions is not None else (old or {}).get("permissions", {})
            state, plan = self._freeze(inventory_sha, permissions, actor)
            if state["actor"] != actor:
                raise Conflict("迁移执行主体与原固定导入不同", "library_migration_actor_mismatch")
            if state["status"] == "cutover":
                return self._compare(state, plan)
            for entry in plan["entries"]:
                if entry["status"] != "ready":
                    continue
                members = []
                for member in entry["members"]:
                    source = self.root / member["path"]
                    with source.open("rb") as stream:
                        staged = self.service.storage.stage_upload(stream, source.name)
                    if staged["sha256"] != member["sha256"]:
                        raise Conflict("旧库字节在暂存期间改变，尚未导入此项", "library_migration_source_changed")
                    members.append({"member_key": member["member_key"], "role": member["role"], "staged_upload": staged["staged_upload"]})
                # Same fixed import key recovers a committed DB receipt even if
                # the process stopped before writing its local journal.
                receipt = self.service.import_library(dict(entry["payload"], members=members), actor=actor)
                state["receipts"][entry["legacy_id"]] = receipt
                legacy.write_json(self.marker, state)
            return self._compare(state, plan)

    def _compare(self, state, plan):
        differences = []
        backup = Path(state["backup"])
        try:
            frozen = json.loads((backup / "inventory.json").read_text("utf-8"))
            if _digest(frozen["entries"]) != state["inventory_sha256"]:
                raise ValueError("backup inventory changed")
            for entry in frozen["entries"]:
                checks = [(entry["path"], entry.get("index_sha256"))]
                checks += [(str((Path(entry["path"]).parent / item["path"])), item.get("actual_sha256"))
                           for item in entry.get("files", [])]
                for relative, sha in checks:
                    if not sha or ".." in Path(relative).parts:
                        continue
                    target = backup / relative
                    if target.is_symlink() or not target.resolve().is_relative_to(backup) or legacy.sha256(target) != sha:
                        raise ValueError("backup bytes changed")
        except (OSError, ValueError, KeyError, TypeError):
            differences.append({"code": "library_backup_mismatch"})
        if plan["inventory_sha256"] != state["inventory_sha256"]:
            differences.append({"code": "library_migration_source_changed"})
        for entry in plan["entries"]:
            if entry["status"] != "ready":
                continue
            receipt = state["receipts"].get(entry["legacy_id"])
            if not receipt:
                differences.append({"legacy_id": entry["legacy_id"], "code": "not_imported"})
                continue
            detail = self.service.get_library_version(receipt["library_version_id"])
            expected = {member["member_key"]: member["sha256"] for member in entry["members"]}
            actual = {member["member_key"]: member["sha256"] for member in detail["members"]}
            fields = ("library_key", "description", "specification", "allowed_purposes", "license")
            if expected != actual or any(detail[key] != entry["payload"][key] for key in fields):
                differences.append({"legacy_id": entry["legacy_id"], "code": "fixed_content_mismatch"})
            for member in detail["members"]:
                try:
                    self.service.library_member_content(receipt["library_version_id"], member["member_key"])
                except (ResourceError, OSError):
                    differences.append({"legacy_id": entry["legacy_id"], "code": "library_missing_bytes"})
        return {"inventory_sha256": state["inventory_sha256"], "status": state["status"],
            "backup": state["backup"], "receipts": state["receipts"], "pending": state["pending"],
            "differences": differences, "passed": not differences,
            "can_cutover": not differences and not state["pending"], "legacy_writable": False}

    def compare(self):
        state = self._state()
        if not state:
            raise ResourceError("请先预览、备份并导入", "library_migration_not_started")
        return self._compare(state, self.preview(state["permissions"]))

    def cutover(self, *, actor, allow_pending=False):
        if self.service is None:
            raise ResourceError("切换需要真实共享库", "database_unavailable")
        self.service._actor(actor)
        with legacy.mutation_lock(self.root, allow_migration=True):
            state = self._state()
            if not state:
                raise ResourceError("请先导入并核对", "library_migration_not_started")
            result = self._compare(state, self.preview(state["permissions"]))
            if not result["passed"] or result["pending"] and not allow_pending:
                raise Conflict("迁移仍有差异或待处理条目，不能切换", "library_migration_incomplete")
            state.update(status="cutover", cutover_actor=actor, pending_retained=bool(state["pending"]))
            legacy.write_json(self.marker, state)
            return self._compare(state, self.preview(state["permissions"]))
