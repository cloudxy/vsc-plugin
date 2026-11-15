"""Configured commercial operations; no default prices or external money calls."""
from contextvars import ContextVar
from dataclasses import asdict
from datetime import datetime, timezone
import re


_verified_notification = ContextVar("vsc_verified_commerce_notification", default=None)


def is_verified_commerce_notification(project_id, document):
    """Exact, request-local proof for settling an existing recycled-project order.

    This is set only after the configured gateway verifies the original bytes;
    a caller-controlled payload flag or the absence of a user is not authority.
    The repository still validates the fixed order inside its locked transaction.
    """
    return _verified_notification.get() == (project_id, document)


def _error(message, code="invalid_commerce_input", status_code=422, details=None):
    from vsc.assets.resource_service import ResourceError
    raise ResourceError(message, code, status_code, details=details)


def instant(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError()
        return parsed.astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError):
        _error("日期需要带时区的 ISO 时间")


def positive(value, name, maximum=10**12):
    if type(value) is not int or not 1 <= value <= maximum:
        _error(name + "需要范围内的正整数")
    return value


def purposes(value):
    if (
        not isinstance(value, list)
        or not value
        or len(value) > 100
        or any(not isinstance(v, str) or not re.fullmatch(r"\*|[a-z][a-z0-9_]{0,63}", v) for v in value)
        or len(set(value)) != len(value)
    ):
        _error("额度用途须为明确、不重复的用途编号")
    return value


def validate_plan(value):
    from vsc.adapters.persistence.postgres.budget_store import UNITS
    fields = {
        "plan_key", "title", "amount_minor", "currency", "credits", "bucket_kind",
        "validity_days", "checkout_minutes", "purposes", "rates", "refund_policy",
        "max_concurrent_jobs", "invoice_enabled", "seat_limit", "watermark_required", "renewal_policy",
    }
    if not isinstance(value, dict) or set(value) != fields:
        _error("价格版本需要完整、明确的业务配置")
    if not isinstance(value["plan_key"], str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", value["plan_key"]):
        _error("套餐编号格式不正确")
    if not isinstance(value["title"], str) or not 1 <= len(value["title"]) <= 200 or not re.fullmatch(r"[A-Z]{3}", str(value["currency"])):
        _error("需要套餐名称与三位币种代码")
    for key, maximum in (
        ("amount_minor", 10**12), ("credits", 10**12), ("validity_days", 3650),
        ("checkout_minutes", 1440), ("max_concurrent_jobs", 100), ("seat_limit", 10000),
    ):
        positive(value[key], key, maximum)
    if value["bucket_kind"] not in {"credit", "special"} or value["refund_policy"] not in {"none", "unused_order_only"} or type(value["invoice_enabled"]) is not bool:
        _error("额度类型、退款政策或发票开关不正确")
    if type(value["watermark_required"]) is not bool or value["renewal_policy"] not in {"none", "manual_from_payment"}:
        _error("水印开关和续期政策需要明确配置")
    require_supported_entitlements(value)
    purposes(value["purposes"])
    rates, seen = value["rates"], set()
    if not isinstance(rates, list) or not rates or len(rates) > 200:
        _error("需要 1–200 条模型原生单位到信用额度的价格")
    for row in rates:
        if not isinstance(row, dict) or set(row) != {"model_id", "unit", "credits_per_unit"} or row["unit"] not in UNITS or not isinstance(row["model_id"], str):
            _error("价格须绑定实际模型与原生单位")
        positive(row["credits_per_unit"], "单位信用价格")
        key = (row["model_id"], row["unit"])
        if key in seen:
            _error("模型单位价格重复")
        seen.add(key)
    return value


def validate_campaign(payload):
    if not isinstance(payload, dict) or set(payload) != {"code", "title", "credits", "kind", "purposes", "starts_at", "ends_at", "credit_expires_at", "daily"}:
        _error("活动配置字段不完整")
    if not isinstance(payload["code"], str) or not 6 <= len(payload["code"]) <= 100:
        _error("兑换码须为6–100字符")
    if not isinstance(payload["title"], str) or not 1 <= len(payload["title"].strip()) <= 200:
        _error("需要有效的活动标题")
    positive(payload["credits"], "活动额度")
    purposes(payload["purposes"])
    if payload["kind"] not in {"bonus", "check_in", "special"} or type(payload["daily"]) is not bool:
        _error("活动类型不正确")
    if not instant(payload["starts_at"]) < instant(payload["ends_at"]) <= instant(payload["credit_expires_at"]):
        _error("活动与额度有效期不正确")
    return payload


def validate_invoice_title_payload(payload):
    if not isinstance(payload, dict):
        _error("发票抬头参数格式不正确")
    allowed = {
        "id", "invoice_type", "title_type", "title", "tax_id", "email",
        "bank_name", "bank_account", "bank_account_masked",
        "address_phone", "billing_address_phone", "is_default",
    }
    if set(payload) - allowed:
        _error("发票抬头包含未知字段")
    raw_type = payload.get("invoice_type") or payload.get("title_type") or ""
    if raw_type == "enterprise":
        raw_type = "enterprise_normal"
    if raw_type not in {"enterprise_normal", "enterprise_special", "personal"}:
        _error("发票抬头类型须为企业普票、企业专票或个人", details={"field": "invoice_type"})
    title = (payload.get("title") or "").strip() if isinstance(payload.get("title"), str) else ""
    if not 1 <= len(title) <= 200:
        _error("发票抬头名称须为 1–200 字符", details={"field": "title"})
    email = (payload.get("email") or "").strip() if isinstance(payload.get("email"), str) else ""
    if not 3 <= len(email) <= 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        _error("接收邮箱格式不正确", details={"field": "email"})
    if raw_type == "personal":
        tax_id = "PERSONAL"
    else:
        raw_tax = payload.get("tax_id")
        tax_id = raw_tax.strip().upper() if isinstance(raw_tax, str) else ""
        if tax_id == "PERSONAL" or not re.fullmatch(r"[A-Z0-9]{15,32}", tax_id):
            _error("企业发票抬头税号须为 15–32 位大写字母或数字", "invalid_tax_id", 422, details={"field": "tax_id"})
    bank_name_raw = payload.get("bank_name")
    bank_name = bank_name_raw.strip() if isinstance(bank_name_raw, str) and bank_name_raw.strip() else None
    if bank_name is not None and len(bank_name) > 200:
        _error("开户行名称不能超过 200 字符", details={"field": "bank_name"})
    acct_raw = payload.get("bank_account") if "bank_account" in payload else payload.get("bank_account_masked")
    bank_account = acct_raw.strip() if isinstance(acct_raw, str) and acct_raw.strip() else None
    if bank_account is not None and len(bank_account) > 64:
        _error("银行账号长度不能超过 64 字符", details={"field": "bank_account"})
    addr_raw = payload.get("address_phone") if "address_phone" in payload else payload.get("billing_address_phone")
    address_phone = addr_raw.strip() if isinstance(addr_raw, str) and addr_raw.strip() else None
    if address_phone is not None and len(address_phone) > 300:
        _error("注册地址及电话不能超过 300 字符", details={"field": "address_phone"})
    is_default = payload.get("is_default", False)
    if type(is_default) is not bool:
        _error("默认抬头标记须为布尔值", details={"field": "is_default"})
    normalized = {
        "invoice_type": raw_type,
        "title": title,
        "tax_id": tax_id,
        "email": email,
        "bank_name": bank_name,
        "bank_account": bank_account,
        "address_phone": address_phone,
        "is_default": is_default,
    }
    if payload.get("id"):
        if not isinstance(payload["id"], str):
            _error("抬头编号无效", details={"field": "id"})
        normalized["id"] = payload["id"]
    return normalized


def require_supported_entitlements(document):
    if document.get("watermark_required"):
        from vsc.post.export_entitlements import available
        if not available():
            _error("本机缺少导出水印所需的 FFmpeg、ffprobe 或 Pillow", "commerce_entitlement_unavailable")


class CommerceService:
    def _commerce(self):
        from vsc.adapters.persistence.postgres.commerce import CommerceRepository
        return CommerceRepository(self.store)

    def _commerce_access(self, project_id, capability):
        if hasattr(self, "authorize_access"):
            self.authorize_access(project_id, capability)

    def _commerce_manage(self, project_id):
        try:
            self._commerce_access(project_id, "manage")
            return True
        except Exception as exc:
            if getattr(exc, "status_code", None) in {401, 403}:
                return False
            raise

    def _resolve_commerce_scope(self, scope_kind, scope_id=None, *, capability="read"):
        from vsc.adapters.persistence.postgres.commerce import make_scope_ref
        from vsc.assets.access_control import CAPABILITIES, current_principal, denied
        from vsc.assets.resource_service import ResourceError

        if scope_kind == "project":
            self._commerce_access(scope_id, capability)
            manage = self._commerce_manage(scope_id) if capability != "manage" else True
            return make_scope_ref("project", scope_id), manage

        principal = current_principal()
        if principal is not None and (principal.api_key_id or principal.share_id):
            denied("治理商业接口不接受开放 API 密钥或只读分享访问")

        with self.store.engine.connect() as conn:
            _, person, _ = self.store._access_principal(conn, principal)
            if scope_kind == "identity":
                ident_id = scope_id or (person["id"] if person else None)
                if not ident_id:
                    denied("个人商业账户需要登录成员身份")
                if person and ident_id != person["id"]:
                    denied("个人商业账户仅限本人操作")
                return make_scope_ref("identity", ident_id), True
            if scope_kind == "workspace":
                if not scope_id:
                    _error("需要指定工作室编号")
                if principal is not None:
                    if not person:
                        denied("工作室商业账户需要登录成员身份")
                    roles = self.store._workspace_require(conn, scope_id, capability, person["id"])
                    caps = set().union(*(CAPABILITIES[r] for r in roles))
                    manage = "manage" in caps
                else:
                    manage = True
                return make_scope_ref("workspace", scope_id), manage
            if scope_kind == "platform":
                if not self.store._is_platform_admin(person, principal):
                    raise ResourceError("需要平台治理管理员权限", "platform_admin_required", 403)
                return make_scope_ref("platform"), True
        _error("未知商业作用域")

    def _commerce_capabilities(self, result, *, manage):
        from vsc.assets.access_control import current_principal
        from vsc.post.export_entitlements import available
        principal = current_principal()
        platform_admin = True
        if principal is not None and hasattr(self, "store") and hasattr(self.store, "_access_principal"):
            with self.store.engine.connect() as conn:
                _, person, _ = self.store._access_principal(conn, principal)
                platform_admin = self.store._is_platform_admin(person, principal)
        return {
            "pricing": bool(result.get("plans")),
            "payment": bool(getattr(self, "commerce_payment_gateway", None)),
            "invoice": bool(getattr(self, "commerce_invoice_gateway", None)),
            "manage": bool(manage),
            "platform_admin": bool(platform_admin),
            "renewal": True,
            "automatic_renewal": False,
            "partial_refund": False,
            "watermark_entitlement": available(),
            "watermark_scope": ["edit_video", "edit_cover", "selected_clips", "edit_package_render"],
            "seat_entitlement": hasattr(self, "authorize_access"),
        }

    def commerce_summary(self, project_id, *, actor):
        self._actor(actor)
        self._commerce_access(project_id, "read")
        manage = self._commerce_manage(project_id)
        result = self._commerce().summary(project_id, actor, manage=manage)
        result["native_budget"] = self.budget_status(project_id)
        result["capabilities"] = self._commerce_capabilities(result, manage=manage)
        from vsc.assets.access_control import current_principal
        principal = current_principal()
        result["workspace"] = (
            self._commerce().workspace_summary(project_id)
            if principal and principal.identity_id and result["capabilities"]["manage"]
            else {"workspace_id": None, "projects": [], "members": [], "transfers": []}
        )
        return result

    def commerce_summary_scoped(self, scope_kind, scope_id=None, *, actor):
        self._actor(actor)
        if scope_kind == "project":
            return self.commerce_summary(scope_id, actor=actor)
        if scope_kind == "platform":
            return self.platform_commerce_summary(actor=actor)
        scope_ref, manage = self._resolve_commerce_scope(scope_kind, scope_id, capability="read")
        result = self._commerce().summary_scoped(scope_ref, actor, manage=manage)
        result["native_budget"] = None
        result["capabilities"] = self._commerce_capabilities(result, manage=manage)
        return result

    def platform_commerce_summary(self, *, actor):
        self._actor(actor)
        self._resolve_commerce_scope("platform", capability="manage")
        result = self._commerce().platform_summary(actor)
        result["capabilities"] = self._commerce_capabilities(result, manage=True)
        return result

    def transfer_workspace_credits(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        self._commerce_access(project_id, "manage")
        if set(payload) - {"bucket_id", "target_project_id", "target_revision", "credits", "reclaim_transfer_id"} or not {"bucket_id", "target_project_id", "target_revision", "credits"} <= set(payload):
            _error("分配需要来源额度、目标项目与版本、信用数")
        positive(payload["credits"], "额度")
        if type(payload["target_revision"]) is not int or payload["target_revision"] < 0:
            _error("目标项目版本无效")
        return self._commerce().transfer_workspace(project_id, payload, **kw)

    def commerce_entitlements(self, project_id, conn=None):
        return self._commerce().entitlements(project_id, conn=conn)

    @staticmethod
    def _extract_plan_payload(payload, *, require_confirmed=False):
        if not isinstance(payload, dict):
            _error("配置需要完整价格、所见版本和计费开关")
        clean_payload = dict(payload)
        has_confirmed = "confirmed" in clean_payload
        confirmed = clean_payload.pop("confirmed", None)
        diff_sha256 = clean_payload.pop("diff_sha256", None)
        if diff_sha256 is not None and (not isinstance(diff_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", diff_sha256)):
            _error("差异摘要格式不正确")
        if require_confirmed or has_confirmed:
            if confirmed is not True:
                _error("发布套餐价格需要明确人工二次确认", "commerce_confirmation_required", 422)
        if set(clean_payload) != {"document", "base_version_id", "metering_enabled"} or type(clean_payload["metering_enabled"]) is not bool:
            _error("配置需要完整价格、所见版本和计费开关")
        validate_plan(clean_payload["document"])
        if diff_sha256 is not None:
            clean_payload["diff_sha256"] = diff_sha256
        return clean_payload

    @staticmethod
    def _extract_campaign_payload(payload, *, require_confirmed=False):
        if not isinstance(payload, dict):
            _error("活动配置字段不完整")
        clean_payload = dict(payload)
        has_confirmed = "confirmed" in clean_payload
        confirmed = clean_payload.pop("confirmed", None)
        diff_sha256 = clean_payload.pop("diff_sha256", None)
        if diff_sha256 is not None and (not isinstance(diff_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", diff_sha256)):
            _error("差异摘要格式不正确")
        if require_confirmed or has_confirmed:
            if confirmed is not True:
                _error("发布营销活动需要明确人工二次确认", "commerce_confirmation_required", 422)
        if set(clean_payload) == {"document"} and isinstance(clean_payload["document"], dict):
            clean_payload = dict(clean_payload["document"])
        elif isinstance(clean_payload.get("document"), dict):
            doc_inner = dict(clean_payload.pop("document"))
            clean_payload = {**doc_inner, **clean_payload}
        validate_campaign(clean_payload)
        return clean_payload

    def preview_commerce_plan_diff(self, scope_kind, scope_id, payload, *, actor):
        self._actor(actor)
        scope_ref, _ = self._resolve_commerce_scope(scope_kind, scope_id, capability="manage")
        clean_payload = self._extract_plan_payload(payload, require_confirmed=False)
        return self._commerce().preview_plan_diff(scope_ref, clean_payload)

    def configure_commerce_plan_scoped(self, scope_kind, scope_id, payload, *, confirmed=None, **kw):
        self._validate_write(payload, **kw)
        scope_ref, _ = self._resolve_commerce_scope(scope_kind, scope_id, capability="manage")
        merged = dict(payload, confirmed=confirmed) if confirmed is not None and isinstance(payload, dict) and "confirmed" not in payload else payload
        clean_payload = self._extract_plan_payload(merged, require_confirmed=(scope_kind == "platform"))
        return self._commerce().configure_plan_scoped(scope_ref, clean_payload, **kw)

    def configure_commerce_plan(self, project_id, payload, **kw):
        return self.configure_commerce_plan_scoped("project", project_id, payload, **kw)

    def preview_commerce_campaign_diff(self, scope_kind, scope_id, payload, *, actor):
        self._actor(actor)
        scope_ref, _ = self._resolve_commerce_scope(scope_kind, scope_id, capability="manage")
        clean_payload = self._extract_campaign_payload(payload, require_confirmed=False)
        return self._commerce().preview_campaign_diff(scope_ref, clean_payload)

    def configure_commerce_campaign_scoped(self, scope_kind, scope_id, payload, *, confirmed=None, **kw):
        self._validate_write(payload, **kw)
        scope_ref, _ = self._resolve_commerce_scope(scope_kind, scope_id, capability="manage")
        merged = dict(payload, confirmed=confirmed) if confirmed is not None and isinstance(payload, dict) and "confirmed" not in payload else payload
        clean_payload = self._extract_campaign_payload(merged, require_confirmed=(scope_kind == "platform"))
        return self._commerce().configure_campaign_scoped(scope_ref, clean_payload, **kw)

    def configure_commerce_campaign(self, project_id, payload, **kw):
        return self.configure_commerce_campaign_scoped("project", project_id, payload, **kw)

    def _commerce_checkout_scoped(self, scope_ref, identifier, gateway):
        repo = self._commerce()
        claimed = repo.claim_checkout(scope_ref, identifier)
        if claimed["claimed"]:
            try:
                checkout = gateway.create_checkout(claimed["order"])
                repo.checkout_result(scope_ref, identifier, asdict(checkout))
            except Exception:
                pass
        return repo.order_scoped(scope_ref, identifier)

    def _commerce_checkout(self, project_id, identifier, gateway):
        from vsc.adapters.persistence.postgres.commerce import make_scope_ref
        return self._commerce_checkout_scoped(make_scope_ref("project", project_id), identifier, gateway)

    def _commerce_owned_order_scoped(self, scope_ref, identifier, actor):
        order = self._commerce().order_scoped(scope_ref, identifier)
        if order["actor"] != actor:
            self._resolve_commerce_scope(scope_ref["scope_kind"], scope_ref["scope_id"], capability="manage")
        return order

    def _commerce_owned_order(self, project_id, identifier, actor):
        from vsc.adapters.persistence.postgres.commerce import make_scope_ref
        return self._commerce_owned_order_scoped(make_scope_ref("project", project_id), identifier, actor)

    def create_commerce_order_scoped(self, scope_kind, scope_id, payload, **kw):
        self._validate_write(payload, **kw)
        cap = "edit" if scope_kind == "project" else "manage"
        scope_ref, _ = self._resolve_commerce_scope(scope_kind, scope_id, capability=cap)
        if set(payload) != {"plan_id"}:
            _error("订单只接受明确套餐版本，价格来自服务端")
        gateway = getattr(self, "commerce_payment_gateway", None)
        if gateway is None:
            _error("支付服务未配置；没有创建付款或扣费", "payment_unconfigured")
        result = self._commerce().create_order_scoped(scope_ref, payload, gateway=gateway.id, **kw)
        return self._commerce_checkout_scoped(scope_ref, result["id"], gateway)

    def create_commerce_order(self, project_id, payload, **kw):
        return self.create_commerce_order_scoped("project", project_id, payload, **kw)

    def renew_commerce_order_scoped(self, scope_kind, scope_id, payload, **kw):
        self._validate_write(payload, **kw)
        cap = "edit" if scope_kind == "project" else "manage"
        scope_ref, _ = self._resolve_commerce_scope(scope_kind, scope_id, capability=cap)
        if set(payload) != {"order_id"}:
            _error("手动续期需要明确原订单")
        order = self._commerce_owned_order_scoped(scope_ref, payload["order_id"], kw["actor"])
        gateway = getattr(self, "commerce_payment_gateway", None)
        if gateway is None or gateway.id != order["gateway"]:
            _error("原支付服务未配置", "payment_unconfigured")
        result = self._commerce().create_order_scoped(
            scope_ref,
            {"plan_id": order["plan_id"], "renewal_of_order_id": order["id"]},
            gateway=gateway.id,
            **kw,
        )
        return self._commerce_checkout_scoped(scope_ref, result["id"], gateway)

    def renew_commerce_order(self, project_id, payload, **kw):
        return self.renew_commerce_order_scoped("project", project_id, payload, **kw)

    def refresh_commerce_order_scoped(self, scope_kind, scope_id, payload, **kw):
        self._validate_write(payload, **kw)
        scope_ref, _ = self._resolve_commerce_scope(scope_kind, scope_id, capability="read")
        if set(payload) != {"order_id"}:
            _error("订单恢复需要固定订单编号")
        order = self._commerce_owned_order_scoped(scope_ref, payload["order_id"], kw["actor"])
        gateway = getattr(self, "commerce_payment_gateway", None)
        if gateway is None or gateway.id != order["gateway"]:
            _error("原支付服务未配置", "payment_unconfigured")
        event = gateway.query_order(order)
        return self._commerce().payment_event(scope_ref, event, expected_order=order["id"])

    def refresh_commerce_order(self, project_id, payload, **kw):
        return self.refresh_commerce_order_scoped("project", project_id, payload, **kw)

    def _verify_gateway_payload(self, headers, body, gateway_id):
        from vsc.adapters.providers.commerce import PaymentEvent
        from vsc.assets.resource_service import ResourceError
        gateway = getattr(self, "commerce_payment_gateway", None)
        if gateway is None:
            raise ResourceError("支付服务未配置", "payment_unconfigured", 503)
        if gateway_id is not None and gateway_id != gateway.id:
            raise ResourceError("回调网关未配置", "payment_gateway_unknown", 404)
        if not isinstance(body, bytes) or not 0 < len(body) <= 128 * 1024:
            raise ResourceError("回调需要128KiB以内的原始签名字节", "payment_body_invalid", 400)
        try:
            event = gateway.verify_notification(headers, body)
        except ResourceError:
            raise
        except (ValueError, TypeError):
            raise ResourceError("支付回调签名或正文无效", "payment_signature_invalid", 401)
        except Exception:
            raise ResourceError("支付签名验证服务暂不可用", "payment_verification_unavailable", 503)
        if not isinstance(event, PaymentEvent) or event.gateway != gateway.id:
            raise ResourceError("支付回执网关不匹配", "payment_event_invalid")
        return event

    def handle_commerce_notification(self, project_id, headers, body, *, gateway_id=None):
        from vsc.assets.access_control import reset_principal, set_principal
        event = self._verify_gateway_payload(headers, body, gateway_id)
        token = set_principal(None)
        verified_token = _verified_notification.set((project_id, asdict(event)))
        try:
            return self._commerce().payment_event(project_id, event)
        finally:
            _verified_notification.reset(verified_token)
            reset_principal(token)

    def handle_commerce_order_notification(self, order_id, headers, body, *, gateway_id=None):
        from vsc.assets.access_control import reset_principal, set_principal
        from vsc.assets.resource_service import ResourceError
        event = self._verify_gateway_payload(headers, body, gateway_id)
        if event.order_id != order_id:
            raise ResourceError("支付查询返回其他订单", "payment_event_invalid")
        scope_ref, _ = self._commerce().find_order_scope(order_id)
        target_key = scope_ref["project_id"] if scope_ref["scope_kind"] == "project" else scope_ref["scope_id"]
        token = set_principal(None)
        verified_token = _verified_notification.set((target_key, asdict(event)))
        try:
            return self._commerce().payment_event(scope_ref, event, expected_order=order_id)
        finally:
            _verified_notification.reset(verified_token)
            reset_principal(token)

    def refund_commerce_order_scoped(self, scope_kind, scope_id, payload, **kw):
        self._validate_write(payload, **kw)
        cap = "edit" if scope_kind == "project" else "manage"
        scope_ref, _ = self._resolve_commerce_scope(scope_kind, scope_id, capability=cap)
        if set(payload) != {"order_id"}:
            _error("退款需要明确订单")
        order = self._commerce_owned_order_scoped(scope_ref, payload["order_id"], kw["actor"])
        gateway = getattr(self, "commerce_payment_gateway", None)
        if gateway is None or gateway.id != order["gateway"]:
            _error("原支付服务未配置", "payment_unconfigured")
        claimed = self._commerce().claim_refund(scope_ref, payload, **kw)
        if claimed["claimed"]:
            try:
                return self._commerce().payment_event(scope_ref, gateway.refund(order), expected_order=order["id"])
            except Exception:
                return self._commerce().order_scoped(scope_ref, order["id"])
        return self._commerce().order_scoped(scope_ref, order["id"])

    def refund_commerce_order(self, project_id, payload, **kw):
        return self.refund_commerce_order_scoped("project", project_id, payload, **kw)

    def cancel_commerce_order_scoped(self, scope_kind, scope_id, payload, **kw):
        self._validate_write(payload, **kw)
        cap = "edit" if scope_kind == "project" else "manage"
        scope_ref, _ = self._resolve_commerce_scope(scope_kind, scope_id, capability=cap)
        if set(payload) != {"order_id"}:
            _error("取消需要明确订单")
        order = self._commerce_owned_order_scoped(scope_ref, payload["order_id"], kw["actor"])
        if order["status"] not in {"created", "pending", "checkout_unknown"}:
            _error("此订单状态不能取消", "order_state_conflict")
        gateway = getattr(self, "commerce_payment_gateway", None)
        if gateway is None or gateway.id != order["gateway"]:
            _error("原支付服务未配置", "payment_unconfigured")
        return self._commerce().payment_event(scope_ref, gateway.cancel(order), expected_order=order["id"])

    def cancel_commerce_order(self, project_id, payload, **kw):
        return self.cancel_commerce_order_scoped("project", project_id, payload, **kw)

    def redeem_commerce_campaign_scoped(self, scope_kind, scope_id, payload, **kw):
        self._validate_write(payload, **kw)
        cap = "edit" if scope_kind == "project" else "manage"
        scope_ref, _ = self._resolve_commerce_scope(scope_kind, scope_id, capability=cap)
        if set(payload) != {"code"} or not isinstance(payload["code"], str):
            _error("兑换需要明确活动码")
        return self._commerce().redeem_scoped(scope_ref, payload, **kw)

    def redeem_commerce_campaign(self, project_id, payload, **kw):
        return self.redeem_commerce_campaign_scoped("project", project_id, payload, **kw)

    def allocate_commerce_credits_scoped(self, scope_kind, scope_id, payload, **kw):
        self._validate_write(payload, **kw)
        scope_ref, _ = self._resolve_commerce_scope(scope_kind, scope_id, capability="manage")
        if set(payload) != {"bucket_id", "target_actor", "credits", "reclaim"} or type(payload["reclaim"]) is not bool:
            _error("分配/回收字段不正确")
        positive(payload["credits"], "额度")
        target = payload["target_actor"]
        if target is not None and (not isinstance(target, str) or not 1 <= len(target) <= 200):
            _error("成员身份不正确")
        if scope_kind == "project":
            if target and hasattr(self, "commerce_validate_member"):
                if self.commerce_validate_member(scope_id, target) is False:
                    _error("目标不是有效项目成员", "commerce_member_invalid")
            elif target:
                _error("成员身份接缝尚未配置", "commerce_member_unconfigured")
        return self._commerce().allocate_scoped(scope_ref, payload, **kw)

    def allocate_commerce_credits(self, project_id, payload, **kw):
        return self.allocate_commerce_credits_scoped("project", project_id, payload, **kw)

    def preview_commerce_charge(self, project_id, payload, *, actor):
        if not isinstance(payload, dict):
            _error("商业报价需要完整操作与承担账户")
        if "billing_scope" in payload:
            self._commerce_access(project_id, "execute")
            return self._commerce().preview_charge(project_id, payload, actor=actor)
        self._commerce_access(project_id, "read")
        if set(payload) != {"operations", "account_actor"}:
            _error("商业报价需要完整操作与承担账户")
        if payload["account_actor"] != actor:
            self._commerce_access(project_id, "manage")
        return self._commerce().preview_charge(project_id, payload, actor=actor)

    def request_commerce_invoice_scoped(self, scope_kind, scope_id, payload, **kw):
        self._validate_write(payload, **kw)
        cap = "edit" if scope_kind == "project" else "manage"
        scope_ref, _ = self._resolve_commerce_scope(scope_kind, scope_id, capability=cap)
        if not isinstance(payload, dict):
            _error("发票需要订单、抬头、税号和接收邮箱")
        has_title_id = bool(payload.get("title_id"))
        allowed = {"order_id", "title_id", "title", "tax_id", "email", "workspace_id", "invoice_type"}
        if set(payload) - allowed or "order_id" not in payload:
            _error("发票需要订单、抬头、税号和接收邮箱")
        if not has_title_id:
            if not {"order_id", "title", "tax_id", "email"} <= set(payload):
                _error("发票需要订单、抬头、税号和接收邮箱")
            for key, limit in (("title", 200), ("tax_id", 100), ("email", 254)):
                if not isinstance(payload[key], str) or not payload[key].strip() or len(payload[key]) > limit:
                    _error("发票字段不正确：" + key)
            if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", payload["email"]):
                _error("邮箱格式不正确")
        self._commerce_owned_order_scoped(scope_ref, payload["order_id"], kw["actor"])
        gateway = getattr(self, "commerce_invoice_gateway", None)
        result = self._commerce().request_invoice_scoped(scope_ref, payload, gateway=gateway.id if gateway else None, **kw)
        return self.refresh_commerce_invoice_scoped(scope_kind, scope_ref["scope_id"], {"invoice_id": result["id"]}, **kw) if gateway else result

    def request_commerce_invoice(self, project_id, payload, **kw):
        return self.request_commerce_invoice_scoped("project", project_id, payload, **kw)

    def refresh_commerce_invoice_scoped(self, scope_kind, scope_id, payload, **kw):
        self._validate_write(payload, **kw)
        scope_ref, _ = self._resolve_commerce_scope(scope_kind, scope_id, capability="read")
        if set(payload) != {"invoice_id"}:
            _error("需要明确发票申请")
        repo = self._commerce()
        invoice = repo.invoice_scoped(scope_ref, payload["invoice_id"])
        if invoice["actor"] != kw["actor"]:
            self._resolve_commerce_scope(scope_kind, scope_ref["scope_id"], capability="manage")
        gateway = getattr(self, "commerce_invoice_gateway", None)
        if gateway is None:
            _error("发票服务未配置，申请已保留", "invoice_unconfigured")
        claimed = repo.claim_invoice(scope_ref, invoice["id"], gateway.id)
        if claimed["claimed"]:
            try:
                result = gateway.issue(invoice, repo.order_scoped(scope_ref, invoice["order_id"]))
            except Exception:
                return repo.invoice_scoped(scope_ref, invoice["id"])
        elif invoice["status"] in {"issued", "failed", "void"}:
            return invoice
        else:
            result = gateway.query(repo.invoice_scoped(scope_ref, invoice["id"]))
        return repo.invoice_result(scope_ref, invoice["id"], result)

    def refresh_commerce_invoice(self, project_id, payload, **kw):
        return self.refresh_commerce_invoice_scoped("project", project_id, payload, **kw)

    def commerce_invoice_content_scoped(self, scope_kind, scope_id, identifier, *, actor):
        scope_ref, _ = self._resolve_commerce_scope(scope_kind, scope_id, capability="read")
        invoice = self._commerce().invoice_scoped(scope_ref, identifier, content=True)
        if invoice["actor"] != actor:
            self._resolve_commerce_scope(scope_kind, scope_ref["scope_id"], capability="manage")
        if invoice["status"] != "issued":
            _error("尚无已开具发票文件", "invoice_not_issued")
        return invoice["document"], invoice["sha256"]

    def commerce_invoice_content(self, project_id, identifier, *, actor):
        return self.commerce_invoice_content_scoped("project", project_id, identifier, actor=actor)

    def commerce_invoice_titles_scoped(self, scope_kind, scope_id, *, actor, query=""):
        self._actor(actor)
        scope_ref, _ = self._resolve_commerce_scope(scope_kind, scope_id, capability="read")
        if not isinstance(query, str) or len(query) > 100:
            _error("抬头检索关键词过长")
        return self._commerce().invoice_titles_scoped(scope_ref, actor, query=query)

    def commerce_invoice_titles(self, project_id, *, actor, query=""):
        return self.commerce_invoice_titles_scoped("project", project_id, actor=actor, query=query)

    def save_commerce_invoice_title_scoped(self, scope_kind, scope_id, payload, **kw):
        self._validate_write(payload, **kw)
        cap = "edit" if scope_kind == "project" else "manage"
        scope_ref, _ = self._resolve_commerce_scope(scope_kind, scope_id, capability=cap)
        normalized = validate_invoice_title_payload(payload)
        return self._commerce().save_invoice_title(scope_ref, normalized, **kw)

    def delete_commerce_invoice_title_scoped(self, scope_kind, scope_id, title_id, payload, **kw):
        self._validate_write(payload, **kw)
        cap = "edit" if scope_kind == "project" else "manage"
        scope_ref, _ = self._resolve_commerce_scope(scope_kind, scope_id, capability=cap)
        return self._commerce().delete_invoice_title(scope_ref, title_id, payload, **kw)

    def commerce_ledger_scoped(self, scope_kind, scope_id, *, actor, cursor="", limit=50, kind="", attribution_project_id=""):
        self._actor(actor)
        scope_ref, manage = self._resolve_commerce_scope(scope_kind, scope_id, capability="read")
        return self._commerce().list_ledger_and_reservations(
            scope_ref, actor, manage=manage, cursor=cursor, limit=limit,
            kind=kind, attribution_project_id=attribution_project_id,
        )

    def commerce_ledger_csv_scoped(self, scope_kind, scope_id, *, actor, kind="", attribution_project_id=""):
        self._actor(actor)
        scope_ref, manage = self._resolve_commerce_scope(scope_kind, scope_id, capability="read")
        return self._commerce().export_ledger_csv(
            scope_ref, actor, manage=manage, kind=kind, attribution_project_id=attribution_project_id,
        )
