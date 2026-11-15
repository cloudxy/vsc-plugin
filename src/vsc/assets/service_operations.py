"""Operations consumers retain original account, task, budget and storage authority."""
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit
import re
import uuid

KINDS = {"feedback", "support", "fcp", "studio", "production_service", "distribution", "account_close", "personal_export"}
EXPORT_FIELDS = {"profile", "memberships", "requests", "orders"}
FEEDBACK_CATEGORIES = {"feature", "quality", "billing", "ux", "bug"}
FEEDBACK_STATUSES = {
    "received": ("received",),
    "processing": ("under_review", "awaiting_configuration", "error"),
    "reviewed": ("local_approved",),
    "closed": ("rejected", "withdrawn", "account_closed", "export_ready"),
}
DRAMA_STATUSES = {
    "pending": ("received", "awaiting_configuration"),
    "processing": ("under_review", "error"),
    "reviewed": ("local_approved",),
    "closed": ("rejected", "withdrawn"),
}


def api_capabilities(project_id="{project_id}"):
    base = "/api/v1/service-api/projects/" + project_id
    return {
        "version": "vsc.service-api/v1",
        "authentication": "Bearer",
        "operations": [
            {"operation": "jobs", "method": "GET", "path": base + "/jobs", "capability": "read", "input": {"offset": 0, "limit": 24}},
            {"operation": "job", "method": "GET", "path": base + "/jobs/{job_id}", "capability": "read", "input": {}},
            {"operation": "usage", "method": "GET", "path": base + "/usage", "capability": "read", "input": {}},
            {"operation": "preview", "method": "POST", "path": base + "/runs/preview", "capability": "read", "input": {"run_version_id": "固定运行版本", "run_sha256": "固定摘要"}},
            {"operation": "execute", "method": "POST", "path": base + "/runs/execute", "capability": "execute", "input": {"run_version_id": "固定运行版本", "run_sha256": "固定摘要"}},
            {
                "operation": "cancel",
                "method": "POST",
                "path": base + "/jobs/{job_id}/cancel",
                "capability": "execute",
                "input": {"expected_revision": 0, "idempotency_key": "每次明确操作使用唯一键"},
                "constraint": "仅未领取的本地任务；远端在途任务保留原状态",
            },
        ],
        "execution_contract": "执行已确认的固定运行，复用原队列、原报价与预算。未知提交不能改模型重发。",
    }


def error(message, code="invalid_service_operations"):
    from vsc.assets.resource_service import ResourceError
    raise ResourceError(message, code)


def text(value, name, limit=200, empty=False):
    if not isinstance(value, str) or len(value) > limit or "\x00" in value or (not empty and not value.strip()):
        error(name + "为空或超过长度")
    return value.strip()


def fields(payload, names):
    if not isinstance(payload, dict) or set(payload) != set(names.split()):
        error("操作字段不完整或包含未授权字段")


def inspect_tos_signed_url(raw_url, *, now=None):
    value = (raw_url or "").strip()
    if not value:
        return None
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        error("TOS 签名链接须为完整 HTTP/HTTPS 地址", "invalid_tos_url")
    params = {k.lower(): v[-1] for k, v in parse_qs(parsed.query, keep_blank_values=True).items() if v}
    tos_date = params.get("x-tos-date") or params.get("x-amz-date") or ""
    tos_expires = params.get("x-tos-expires") or params.get("x-amz-expires") or ""
    result = {
        "host": parsed.hostname,
        "path": parsed.path,
        "signed": bool(tos_date and tos_expires),
        "algorithm": params.get("x-tos-algorithm") or params.get("x-amz-algorithm") or "",
    }
    if not (tos_date and tos_expires):
        result["status"] = "unsigned_or_custom"
        result["message"] = "链接未包含标准 X-Tos-Date / X-Tos-Expires 签名参数。"
        return result
    try:
        issued = datetime.strptime(tos_date, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        ttl = int(tos_expires)
        if ttl < 0 or ttl > 365 * 86400:
            raise ValueError()
    except ValueError:
        error("TOS 签名链接中的 X-Tos-Date 或 X-Tos-Expires 格式无效", "invalid_tos_url")
    current = now or datetime.now(timezone.utc)
    expires_at = issued + timedelta(seconds=ttl)
    remaining = int((expires_at - current).total_seconds())
    result.update({
        "status": "expired" if remaining <= 0 else "valid",
        "issued_at": issued.isoformat(),
        "expires_seconds": ttl,
        "expires_at": expires_at.isoformat(),
        "expired": remaining <= 0,
        "remaining_seconds": max(0, remaining),
        "message": "签名链接已过期，请回原任务重新获取受控访问地址。" if remaining <= 0 else f"签名链接仍在有效期内（剩余 {remaining} 秒）。",
    })
    return result


class ServiceOperationsService:
    def _operations(self):
        from vsc.adapters.persistence.postgres.service_operations import ServiceOperationsRepository
        return ServiceOperationsRepository(self.store)

    def preview_account_close(self, p, payload):
        self.authorize_access(p, "read")
        fields(payload, "request_id")
        from vsc.adapters.persistence.postgres.account_lifecycle import AccountLifecycleRepository
        return AccountLifecycleRepository(self.store).preview(p, payload["request_id"])

    def preview_account_close_identity(self, payload):
        raw = payload.get("payload") if isinstance(payload, dict) and isinstance(payload.get("payload"), dict) else payload
        fields(raw, "request_id")
        from vsc.adapters.persistence.postgres.account_lifecycle import AccountLifecycleRepository
        return AccountLifecycleRepository(self.store).preview_identity(raw["request_id"])

    def close_service_account(self, p, payload, **kw):
        self._validate_write(payload, **kw)
        self.authorize_access(p, "read")
        if not isinstance(payload, dict) or set(payload) - {"request_id", "preview_sha256", "confirm_actor", "confirmed"} or not {"request_id", "preview_sha256", "confirm_actor"} <= set(payload):
            error("操作字段不完整或包含未授权字段")
        if "confirmed" in payload and payload["confirmed"] is not True:
            error("执行账户停用须经明确人工确认", "commerce_confirmation_required")
        from vsc.adapters.persistence.postgres.account_lifecycle import AccountLifecycleRepository
        return AccountLifecycleRepository(self.store).close(p, payload, **kw)

    def close_service_account_identity(self, payload, *, confirmed=None, **kw):
        self._validate_write(payload, **kw)
        if not isinstance(payload, dict) or set(payload) - {"request_id", "preview_sha256", "confirm_actor", "confirmed"} or not {"request_id", "preview_sha256", "confirm_actor"} <= set(payload):
            error("操作字段不完整或包含未授权字段")
        effective_confirmed = payload.get("confirmed") if "confirmed" in payload else confirmed
        if effective_confirmed is not True:
            error("执行账户停用须经明确人工确认", "commerce_confirmation_required")
        clean_payload = {k: payload[k] for k in ("request_id", "preview_sha256", "confirm_actor")}
        from vsc.adapters.persistence.postgres.account_lifecycle import AccountLifecycleRepository
        return AccountLifecycleRepository(self.store).close_identity(clean_payload, **kw)

    def service_operations_snapshot(self, p):
        self.authorize_access(p, "read")
        result = self._operations().snapshot(p)
        result["api_catalog"] = api_capabilities(p)
        return result

    def scoped_service_operations_snapshot(self, scope_kind, scope_id=None):
        if scope_kind == "project":
            return self.service_operations_snapshot(scope_id)
        result = self._operations().snapshot_scoped(scope_kind, scope_id)
        result["api_catalog"] = api_capabilities("{project_id}") if scope_kind != "platform" else None
        return result

    def _validate_feedback_query(self, scope, status, query, category, offset, limit):
        if scope not in {"mine", "manage"} or status not in {"all", *FEEDBACK_STATUSES}:
            error("反馈范围或状态无效")
        if category not in {"", "uncategorized", *FEEDBACK_CATEGORIES}:
            error("反馈分类无效")
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            error("反馈分页需要非负 offset 与 1–100 的 limit")
        return text(query, "反馈搜索", 200, True)

    def service_feedback(self, p, *, scope="mine", status="all", query="", category="", offset=0, limit=24):
        self.authorize_access(p, "manage" if scope == "manage" else "read")
        q = self._validate_feedback_query(scope, status, query, category, offset, limit)
        return self._operations().feedback(p, scope=scope, status=status, query=q, category=category, offset=offset, limit=limit)

    def scoped_service_feedback(self, scope_kind, scope_id=None, *, scope="mine", status="all", query="", category="", offset=0, limit=24):
        if scope_kind == "project":
            return self.service_feedback(scope_id, scope=scope, status=status, query=query, category=category, offset=offset, limit=limit)
        q = self._validate_feedback_query(scope, status, query, category, offset, limit)
        return self._operations().feedback_scoped(scope_kind, scope_id, scope=scope, status=status, query=q, category=category, offset=offset, limit=limit)

    def _validate_drama_query(self, scope, status, query, offset, limit):
        if scope not in {"mine", "manage"} or status not in {"all", *DRAMA_STATUSES}:
            error("申请范围或状态无效")
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            error("申请分页需要非负 offset 与 1–100 的 limit")
        return text(query, "申请搜索", 200, True)

    def service_drama_requests(self, p, *, scope="mine", status="all", query="", offset=0, limit=12):
        self.authorize_access(p, "manage" if scope == "manage" else "read")
        q = self._validate_drama_query(scope, status, query, offset, limit)
        return self._operations().drama_requests(p, scope=scope, status=status, query=q, offset=offset, limit=limit)

    def scoped_service_drama_requests(self, scope_kind, scope_id=None, *, scope="mine", status="all", query="", offset=0, limit=12):
        if scope_kind == "project":
            return self.service_drama_requests(scope_id, scope=scope, status=status, query=query, offset=offset, limit=limit)
        q = self._validate_drama_query(scope, status, query, offset, limit)
        return self._operations().drama_requests_scoped(scope_kind, scope_id, scope=scope, status=status, query=q, offset=offset, limit=limit)

    def _verify_seedance_common(self, scope_kind, scope_id, payload):
        if not isinstance(payload, dict) or set(payload) - {"task_id", "tos_url"} or "task_id" not in payload:
            error("验真仅接受 task_id 与可选 tos_url")
        raw_id = text(payload["task_id"], "Seedance 任务编号", 100)
        is_hex16 = bool(re.fullmatch(r"[0-9a-fA-F]{16}", raw_id))
        is_uuid = False
        if not is_hex16:
            try:
                uuid.UUID(raw_id)
                is_uuid = True
            except ValueError:
                error("任务编号须为 16 位十六进制 Seedance Task ID 或有效本地任务 UUID", "invalid_seedance_task_id")
        tos_info = inspect_tos_signed_url(payload.get("tos_url", "")) if payload.get("tos_url") else None
        matched = self._operations().find_seedance_job_scoped(scope_kind, scope_id, raw_id, is_uuid=is_uuid)
        return {
            "project_id": scope_id if scope_kind == "project" else (matched.get("project_id") if matched else None),
            "scope_kind": scope_kind,
            "task_id": raw_id.lower() if is_hex16 else raw_id,
            "is_seedance_hex16": is_hex16,
            "read_only": True,
            "credits_consumed": 0,
            "co_brand": "VSC 创作工作台 · 任务回执核对",
            "verified": bool(matched),
            "job": matched,
            "tos_signature": tos_info,
            "message": (
                "已核对本地原始生成任务回执；本次操作仅查询，未重新生成且未消耗积分。"
                if matched
                else "当前已授权范围内未检索到该任务回执；本次核验仅做只读查询，未触发生成且未消耗任何积分。"
            ),
        }

    def verify_seedance_task(self, p, payload):
        self.authorize_access(p, "read")
        return self._verify_seedance_common("project", p, payload)

    def verify_account_seedance_task(self, payload):
        return self._verify_seedance_common("identity", None, payload)

    def network_diagnostic_probe(self, p, probe_key=""):
        self.authorize_access(p, "read")
        if not isinstance(probe_key, str) or len(probe_key) > 64:
            error("诊断探针标识无效")
        info = self._operations().diagnostic_ping(p)
        info.update({
            "probe_key": probe_key or "default",
            "storage": "configured" if self.storage is not None else "unconfigured",
            "api_version": "vsc.service-api/v1",
        })
        return info

    def account_network_diagnostic_probe(self, probe_key=""):
        if not isinstance(probe_key, str) or len(probe_key) > 64:
            error("诊断探针标识无效")
        info = self._operations().diagnostic_ping_scoped("identity", None)
        info.update({
            "probe_key": probe_key or "default",
            "storage": "configured" if self.storage is not None else "unconfigured",
            "api_version": "vsc.service-api/v1",
        })
        return info

    def _validate_configuration_payload(self, payload):
        fields(payload, "document base_version_id")
        doc = payload["document"]
        required = {"support_text", "terms_url", "privacy_url", "api_documentation"}
        optional = {"support_email", "service_hours"}
        if not isinstance(doc, dict) or not required <= set(doc) or set(doc) - (required | optional):
            error("操作字段不完整或包含未授权字段")
        for name in ("support_text", "api_documentation"):
            text(doc[name], name, 5000, True)
        for name in ("terms_url", "privacy_url"):
            value = text(doc[name], name, 2000, True)
            if value and (urlsplit(value).scheme != "https" or not urlsplit(value).hostname or urlsplit(value).username):
                error("条款/隐私链接须为明确HTTPS地址")
        if "support_email" in doc and doc["support_email"] is not None:
            mail = text(doc["support_email"], "support_email", 254, True)
            if mail and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", mail):
                error("支持邮箱格式不正确")
        if "service_hours" in doc and doc["service_hours"] is not None:
            text(doc["service_hours"], "service_hours", 200, True)

    def configure_service_operations(self, p, payload, **kw):
        self._validate_write(payload, **kw)
        self.authorize_access(p, "manage")
        self._validate_configuration_payload(payload)
        return self._operations().configure(p, payload, **kw)

    def configure_scoped_service_operations(self, scope_kind, scope_id, payload, **kw):
        if scope_kind == "project":
            return self.configure_service_operations(scope_id, payload, **kw)
        self._validate_write(payload, **kw)
        self._validate_configuration_payload(payload)
        return self._operations().configure_scoped(scope_kind, scope_id, payload, **kw)

    def _validate_announcement_payload(self, payload):
        fields(payload, "announcement_key base_version_id title body status")
        for name, limit in (("announcement_key", 80), ("title", 200), ("body", 10000)):
            text(payload[name], name, limit)
        if payload["status"] not in {"published", "withdrawn"}:
            error("选择发布或撤回公告")

    def publish_service_announcement(self, p, payload, **kw):
        self._validate_write(payload, **kw)
        self.authorize_access(p, "manage")
        self._validate_announcement_payload(payload)
        return self._operations().publish(p, payload, **kw)

    def publish_scoped_service_announcement(self, scope_kind, scope_id, payload, **kw):
        if scope_kind == "project":
            return self.publish_service_announcement(scope_id, payload, **kw)
        self._validate_write(payload, **kw)
        self._validate_announcement_payload(payload)
        return self._operations().publish_scoped(scope_kind, scope_id, payload, **kw)

    def _validate_request_payload(self, payload, *, require_legacy_fields=True):
        if not isinstance(payload, dict):
            error("操作字段不完整或包含未授权字段")
        allowed = {"kind", "title", "body", "contact", "channel", "artifact_id", "media_id", "requested_fields", "feedback_category"}
        if set(payload) - allowed:
            error("操作字段不完整或包含未授权字段")
        if require_legacy_fields:
            required = {"kind", "title", "body", "contact", "channel", "artifact_id", "media_id", "requested_fields"}
            if not required <= set(payload):
                error("操作字段不完整或包含未授权字段")
        else:
            if not {"kind", "title", "body"} <= set(payload):
                error("申请需要类型、标题与正文")
        normalized = dict(payload)
        normalized.setdefault("contact", "")
        normalized.setdefault("channel", "")
        normalized.setdefault("artifact_id", None)
        normalized.setdefault("media_id", None)
        normalized.setdefault("requested_fields", [])
        if normalized["contact"] is None:
            normalized["contact"] = ""
        if normalized["channel"] is None:
            normalized["channel"] = ""
        if normalized["kind"] not in KINDS:
            error("申请类型未支持")
        category = normalized.get("feedback_category")
        if category is not None and (normalized["kind"] != "feedback" or not isinstance(category, str) or category not in FEEDBACK_CATEGORIES):
            error("反馈分类无效或用于非反馈申请")
        for name, limit, empty in (("title", 200, False), ("body", 10000, False), ("contact", 254, True), ("channel", 200, True)):
            normalized[name] = text(normalized[name], name, limit, empty)
        selected = normalized["requested_fields"]
        if not isinstance(selected, list) or any(not isinstance(x, str) or x not in EXPORT_FIELDS for x in selected) or len(set(selected)) != len(selected):
            error("导出字段范围不正确")
        if (normalized["kind"] == "personal_export") != bool(selected):
            error("个人导出需要明确字段，其他申请不能附带导出字段")
        return normalized

    def create_service_request(self, p, payload, **kw):
        self._validate_write(payload, **kw)
        self.authorize_access(p, "read")
        normalized = self._validate_request_payload(payload, require_legacy_fields=True)
        return self._operations().create_request(p, normalized, **kw)

    def create_scoped_service_request(self, scope_kind, scope_id, payload, **kw):
        if scope_kind == "project":
            return self.create_service_request(scope_id, payload, **kw)
        self._validate_write(payload, **kw)
        normalized = self._validate_request_payload(payload, require_legacy_fields=False)
        return self._operations().create_request_scoped(scope_kind, scope_id, normalized, **kw)

    def process_service_request(self, p, payload, **kw):
        self._validate_write(payload, **kw)
        self.authorize_access(p, "manage")
        fields(payload, "request_id base_event_id status reason")
        text(payload["reason"], "处理说明", 3000)
        if payload["status"] not in {"under_review", "awaiting_configuration", "local_approved", "rejected"}:
            error("处理记录不能冒充实际执行完成")
        return self._operations().transition(p, payload, **kw)

    def process_scoped_service_request(self, scope_kind, scope_id, payload, **kw):
        if scope_kind == "project":
            return self.process_service_request(scope_id, payload, **kw)
        self._validate_write(payload, **kw)
        fields(payload, "request_id base_event_id status reason")
        text(payload["reason"], "处理说明", 3000)
        if payload["status"] not in {"under_review", "awaiting_configuration", "local_approved", "rejected"}:
            error("处理记录不能冒充实际执行完成")
        return self._operations().transition_scoped(scope_kind, scope_id, payload, **kw)

    def withdraw_service_request(self, p, payload, **kw):
        self._validate_write(payload, **kw)
        self.authorize_access(p, "read")
        fields(payload, "request_id base_event_id reason")
        text(payload["reason"], "撤回说明", 3000)
        return self._operations().transition(p, payload, withdraw=True, **kw)

    def withdraw_scoped_service_request(self, scope_kind, scope_id, payload, **kw):
        if scope_kind == "project":
            return self.withdraw_service_request(scope_id, payload, **kw)
        self._validate_write(payload, **kw)
        fields(payload, "request_id base_event_id reason")
        text(payload["reason"], "撤回说明", 3000)
        return self._operations().transition_scoped(scope_kind, scope_id, payload, withdraw=True, **kw)

    def _validate_api_key_payload(self, payload):
        if not isinstance(payload, dict):
            error("操作字段不完整或包含未授权字段")
        data = dict(payload)
        data.setdefault("ip_allowlist", [])
        data.setdefault("requests_per_minute", 0)
        fields(data, "name secret capabilities expires_at ip_allowlist requests_per_minute")
        text(data["name"], "凭据名称", 100)
        import ipaddress
        networks = data["ip_allowlist"]
        if not isinstance(networks, list) or len(networks) > 100 or any(not isinstance(n, str) for n in networks):
            error("IP白名单需要至多100项IP或CIDR网段")
        try:
            data["ip_allowlist"] = sorted(set(str(ipaddress.ip_network(n, strict=False)) for n in networks))
        except ValueError:
            error("IP白名单包含无效IP或网段")
        limit = data["requests_per_minute"]
        if type(limit) is not int or not 0 <= limit <= 10000:
            error("每分钟调用上限须为0–10000；0表示不设置此项限制")
        from vsc.assets.access_control import secret_hash
        secret_hash(data["secret"])
        caps = data["capabilities"]
        if not isinstance(caps, list) or any(c not in {"read", "execute"} for c in caps) or "read" not in caps or len(set(caps)) != len(caps):
            error("API范围只可为read或read+execute")
        from vsc.assets.commerce import instant
        expiry = instant(data["expires_at"])
        if not 0 < (expiry - datetime.now(timezone.utc)).total_seconds() <= 366 * 86400:
            error("API凭据有效期须在未来一年内")
        data["expires_at"] = expiry
        return data

    def issue_service_api_key(self, p, payload, **kw):
        self._validate_write(payload, **kw)
        self.authorize_access(p, "read")
        normalized = self._validate_api_key_payload(payload)
        return self._operations().issue_key(p, normalized, **kw)

    def issue_scoped_service_api_key(self, scope_kind, scope_id, payload, **kw):
        if scope_kind == "project":
            return self.issue_service_api_key(scope_id, payload, **kw)
        self._validate_write(payload, **kw)
        normalized = self._validate_api_key_payload(payload)
        return self._operations().issue_key_scoped(scope_kind, scope_id, normalized, **kw)

    def revoke_service_api_key(self, p, payload, **kw):
        self._validate_write(payload, **kw)
        self.authorize_access(p, "read")
        fields(payload, "key_id")
        return self._operations().revoke_key(p, payload, **kw)

    def revoke_scoped_service_api_key(self, scope_kind, scope_id, payload, **kw):
        if scope_kind == "project":
            return self.revoke_service_api_key(scope_id, payload, **kw)
        self._validate_write(payload, **kw)
        fields(payload, "key_id")
        return self._operations().revoke_key_scoped(scope_kind, scope_id, payload, **kw)

    def authenticate_service_api_key(self, secret):
        return self._operations().authenticate_api_key(secret)

    def build_service_export(self, p, payload, **kw):
        self._validate_write(payload, **kw)
        self.authorize_access(p, "read")
        fields(payload, "request_id")
        if self.storage is None:
            error("本地受控存储未配置，导出申请已保留", "export_storage_unconfigured")
        return self._operations().build_export(p, payload, self.storage, **kw)

    def build_scoped_service_export(self, scope_kind, scope_id, payload, **kw):
        if scope_kind == "project":
            return self.build_service_export(scope_id, payload, **kw)
        self._validate_write(payload, **kw)
        fields(payload, "request_id")
        if self.storage is None:
            error("本地受控存储未配置，导出申请已保留", "export_storage_unconfigured")
        return self._operations().build_export_scoped(scope_kind, scope_id, payload, self.storage, **kw)

    def service_export_content(self, p, identifier):
        row = self._operations().export_file(p, identifier)
        if self.storage is None:
            error("本地受控存储未配置", "export_storage_unconfigured")
        return self.storage.read(row["object_key"], row["sha256"]), row["sha256"]

    def scoped_service_export_content(self, scope_kind, scope_id, identifier):
        if scope_kind == "project":
            return self.service_export_content(scope_id, identifier)
        row = self._operations().export_file_scoped(scope_kind, scope_id, identifier)
        if self.storage is None:
            error("本地受控存储未配置", "export_storage_unconfigured")
        return self.storage.read(row["object_key"], row["sha256"]), row["sha256"]

    def service_api_operation(self, p, operation, payload=None, *, client_ip=None):
        from vsc.assets.access_control import current_principal, denied
        principal = current_principal()
        if not principal or not principal.api_key_id:
            denied("开放接口只接受专用API凭据")
        capability = "execute" if operation in {"execute", "cancel"} else "read"
        self.authorize_access(p, capability)
        if operation not in {"capabilities", "jobs", "job", "usage", "preview", "execute", "cancel"}:
            error("开放操作不存在")
        payload = payload or {}
        call_id = str(uuid.uuid4())
        repo = self._operations()
        repo.call_event(p, call_id, operation, "started", 0, client_ip=client_ip)
        try:
            if operation == "capabilities":
                fields(payload, "")
                result = api_capabilities(p)
            elif operation == "jobs":
                if payload:
                    fields(payload, "offset limit")
                offset, limit = payload.get("offset", 0), payload.get("limit", 50)
                if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 200:
                    error("任务分页需要非负offset与1–200的limit")
                rows = self.list_generation_jobs(p, offset=offset, limit=limit)
                result = dict(total=rows["total"], offset=offset, limit=limit, items=[self._api_job(r) for r in rows["items"]])
            elif operation == "job":
                fields(payload, "job_id")
                result = self._api_job(self.get_generation_job(p, payload["job_id"]))
            elif operation == "usage":
                fields(payload, "")
                result = self.budget_status(p)
            elif operation in {"preview", "execute"}:
                if set(payload) - {"run_version_id", "run_sha256", "task_keys"} or not payload.get("run_sha256"):
                    error("API执行需要已批准运行编号、所见摘要及可选固定任务编号")
                from vsc.production.bounded import preview_batch, execute_batch
                result = execute_batch(self, p, payload, principal.actor) if operation == "execute" else preview_batch(self, p, payload)
                for item in result["tasks"]:
                    item.pop("payload", None)
            else:
                fields(payload, "job_id expected_revision idempotency_key")
                command = {"job_id": payload["job_id"]}
                kw = dict(actor=principal.actor, expected_revision=payload["expected_revision"], idempotency_key=payload["idempotency_key"])
                self._validate_write(command, **kw)
                result = repo.cancel_job(p, command, **kw)
        except Exception as exc:
            repo.call_event(p, call_id, operation, "finished", getattr(exc, "status_code", 500), getattr(exc, "code", "internal_error"))
            raise
        job_ids = [r["job_id"] for r in result.get("tasks", []) if r.get("job_id")]
        if operation in {"job", "cancel"}:
            job_ids.append(payload["job_id"])
        repo.call_event(
            p, call_id, operation, "finished", 200,
            run_id=result.get("run_version_id") if operation in {"execute", "preview"} else None,
            job_ids=job_ids,
        )
        return dict(result, api_call_id=call_id)

    @staticmethod
    def _api_job(value):
        return {
            k: value.get(k)
            for k in (
                "id", "project_id", "run_version_id", "shot_id", "asset_id",
                "purpose", "modality", "candidate_no", "status", "attempt",
                "created_at", "updated_at", "outputs",
            )
        }
