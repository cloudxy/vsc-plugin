"""Configured commercial operations; no default prices or external money calls."""
from dataclasses import asdict
from contextvars import ContextVar
from datetime import datetime, timezone
import re


_verified_notification = ContextVar('vsc_verified_commerce_notification', default=None)


def is_verified_commerce_notification(project_id, document):
    """Exact, request-local proof for settling an existing recycled-project order.

    This is set only after the configured gateway verifies the original bytes;
    a caller-controlled payload flag or the absence of a user is not authority.
    The repository still validates the fixed order inside its locked transaction.
    """
    return _verified_notification.get() == (project_id, document)


def _error(message, code="invalid_commerce_input"):
    from vsc.assets.resource_service import ResourceError
    raise ResourceError(message, code)


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
    if not isinstance(value, list) or not value or len(value)>100 or any(not isinstance(v,str) or not re.fullmatch(r"\*|[a-z][a-z0-9_]{0,63}",v) for v in value) or len(set(value)) != len(value):
        _error("额度用途须为明确、不重复的用途编号")
    return value


def validate_plan(value):
    from vsc.adapters.persistence.postgres.budget_store import UNITS
    fields = {"plan_key", "title", "amount_minor", "currency", "credits", "bucket_kind", "validity_days", "checkout_minutes", "purposes", "rates", "refund_policy", "max_concurrent_jobs", "invoice_enabled", "seat_limit", "watermark_required", "renewal_policy"}
    if not isinstance(value,dict) or set(value)!=fields:
        _error("价格版本需要完整、明确的业务配置")
    if not isinstance(value["plan_key"],str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}",value["plan_key"]):
        _error("套餐编号格式不正确")
    if not isinstance(value["title"],str) or not 1<=len(value["title"])<=200 or not re.fullmatch(r"[A-Z]{3}",str(value["currency"])):
        _error("需要套餐名称与三位币种代码")
    for key,maximum in (("amount_minor",10**12),("credits",10**12),("validity_days",3650),("checkout_minutes",1440),("max_concurrent_jobs",100),("seat_limit",10000)):
        positive(value[key],key,maximum)
    if value["bucket_kind"] not in {"credit","special"} or value["refund_policy"] not in {"none","unused_order_only"} or type(value["invoice_enabled"]) is not bool:
        _error("额度类型、退款政策或发票开关不正确")
    if type(value["watermark_required"]) is not bool or value["renewal_policy"] not in {"none","manual_from_payment"}:
        _error("水印开关和续期政策需要明确配置")
    require_supported_entitlements(value)
    purposes(value["purposes"])
    rates,seen=value["rates"],set()
    if not isinstance(rates,list) or not rates or len(rates)>200:
        _error("需要 1–200 条模型原生单位到信用额度的价格")
    for row in rates:
        if not isinstance(row,dict) or set(row)!={"model_id","unit","credits_per_unit"} or row["unit"] not in UNITS or not isinstance(row["model_id"],str):
            _error("价格须绑定实际模型与原生单位")
        positive(row["credits_per_unit"],"单位信用价格")
        key=(row["model_id"],row["unit"])
        if key in seen:_error("模型单位价格重复")
        seen.add(key)
    return value


def require_supported_entitlements(document):
    if document.get("watermark_required"):
        _error("导出水印尚无完整执行能力，不能启用或出售要求水印的套餐", "commerce_entitlement_unavailable")


class CommerceService:
    def _commerce(self):
        from vsc.adapters.persistence.postgres.commerce import CommerceRepository
        return CommerceRepository(self.store)

    def _commerce_access(self, project_id, capability):
        if hasattr(self,"authorize_access"):
            self.authorize_access(project_id,capability)

    def _commerce_manage(self, project_id):
        try:
            self._commerce_access(project_id,"manage")
            return True
        except Exception as exc:
            if getattr(exc,"status_code",None) in {401,403}:return False
            raise

    def commerce_summary(self, project_id, *, actor):
        self._actor(actor)
        self._commerce_access(project_id,"read")
        result=self._commerce().summary(project_id,actor,manage=self._commerce_manage(project_id))
        result["native_budget"]=self.budget_status(project_id)
        result["capabilities"]={"pricing":bool(result["plans"]),"payment":bool(getattr(self,"commerce_payment_gateway",None)),
            "invoice":bool(getattr(self,"commerce_invoice_gateway",None)),"manage":self._commerce_manage(project_id),
            "renewal":True,"automatic_renewal":False,"partial_refund":False,"watermark_entitlement":False,"seat_entitlement":hasattr(self,"authorize_access")}
        return result

    def commerce_entitlements(self,project_id,conn=None):
        return self._commerce().entitlements(project_id,conn=conn)

    def configure_commerce_plan(self, project_id, payload, **kw):
        self._validate_write(payload,**kw);self._commerce_access(project_id,"manage")
        if set(payload)!={"document","base_version_id","metering_enabled"} or type(payload["metering_enabled"]) is not bool:
            _error("配置需要完整价格、所见版本和计费开关")
        validate_plan(payload["document"])
        return self._commerce().configure_plan(project_id,payload,**kw)

    def create_commerce_order(self, project_id, payload, **kw):
        self._validate_write(payload,**kw);self._commerce_access(project_id,"edit")
        if set(payload)!={"plan_id"}:_error("订单只接受明确套餐版本，价格来自服务端")
        gateway=getattr(self,"commerce_payment_gateway",None)
        if gateway is None:_error("支付服务未配置；没有创建付款或扣费", "payment_unconfigured")
        result=self._commerce().create_order(project_id,payload,gateway=gateway.id,**kw)
        return self._commerce_checkout(project_id,result["id"],gateway)

    def renew_commerce_order(self,project_id,payload,**kw):
        self._validate_write(payload,**kw);self._commerce_access(project_id,"edit")
        if set(payload)!={"order_id"}:_error("手动续期需要明确原订单")
        order=self._commerce_owned_order(project_id,payload["order_id"],kw["actor"])
        gateway=getattr(self,"commerce_payment_gateway",None)
        if gateway is None or gateway.id!=order["gateway"]:_error("原支付服务未配置","payment_unconfigured")
        result=self._commerce().create_order(project_id,dict(plan_id=order["plan_id"],renewal_of_order_id=order["id"]),gateway=gateway.id,**kw)
        return self._commerce_checkout(project_id,result["id"],gateway)

    def _commerce_checkout(self, project_id, identifier, gateway):
        repo=self._commerce()
        claimed=repo.claim_checkout(project_id,identifier)
        if claimed["claimed"]:
            try:
                checkout=gateway.create_checkout(claimed["order"])
                repo.checkout_result(project_id,identifier,asdict(checkout))
            except Exception:
                # Intention remains unknown; a query by merchant order ID can
                # recover it. Retrying the page cannot issue a second checkout.
                pass
        return repo.order(project_id,identifier)

    def _commerce_owned_order(self,project_id,identifier,actor):
        order=self._commerce().order(project_id,identifier)
        if order["actor"]!=actor:self._commerce_access(project_id,"manage")
        return order

    def refresh_commerce_order(self,project_id,payload,**kw):
        self._validate_write(payload,**kw);self._commerce_access(project_id,"read")
        if set(payload)!={"order_id"}:_error("订单恢复需要固定订单编号")
        order=self._commerce_owned_order(project_id,payload["order_id"],kw["actor"])
        gateway=getattr(self,"commerce_payment_gateway",None)
        if gateway is None or gateway.id!=order["gateway"]:_error("原支付服务未配置","payment_unconfigured")
        event=gateway.query_order(order)
        return self._commerce().payment_event(project_id,event,expected_order=order["id"])

    def handle_commerce_notification(self,project_id,headers,body,*,gateway_id=None):
        from vsc.assets.resource_service import ResourceError
        from vsc.assets.access_control import set_principal,reset_principal
        from vsc.adapters.providers.commerce import PaymentEvent
        gateway=getattr(self,'commerce_payment_gateway',None)
        if gateway is None:raise ResourceError('支付服务未配置','payment_unconfigured',503)
        if gateway_id is not None and gateway_id!=gateway.id:raise ResourceError('回调网关未配置','payment_gateway_unknown',404)
        if not isinstance(body,bytes) or not 0<len(body)<=128*1024:raise ResourceError('回调需要128KiB以内的原始签名字节','payment_body_invalid',400)
        try:event=gateway.verify_notification(headers,body)
        except ResourceError:raise
        except (ValueError,TypeError):raise ResourceError('支付回调签名或正文无效','payment_signature_invalid',401)
        except Exception:raise ResourceError('支付签名验证服务暂不可用','payment_verification_unavailable',503)
        if not isinstance(event,PaymentEvent) or event.gateway!=gateway.id:raise ResourceError('支付回执网关不匹配','payment_event_invalid')
        # Only the configured verifier can produce this port value. Ambient UI
        # cookies never become authority for the internal gateway consumer.
        token=set_principal(None)
        verified_token=_verified_notification.set((project_id,asdict(event)))
        try:return self._commerce().payment_event(project_id,event)
        finally:
            _verified_notification.reset(verified_token)
            reset_principal(token)

    def refund_commerce_order(self,project_id,payload,**kw):
        self._validate_write(payload,**kw);self._commerce_access(project_id,"edit")
        if set(payload)!={"order_id"}:_error("退款需要明确订单")
        order=self._commerce_owned_order(project_id,payload["order_id"],kw["actor"])
        gateway=getattr(self,"commerce_payment_gateway",None)
        if gateway is None or gateway.id!=order["gateway"]:_error("原支付服务未配置","payment_unconfigured")
        claimed=self._commerce().claim_refund(project_id,payload,**kw)
        if claimed["claimed"]:
            try:return self._commerce().payment_event(project_id,gateway.refund(order),expected_order=order["id"])
            except Exception:return self._commerce().order(project_id,order["id"])
        return self._commerce().order(project_id,order["id"])

    def cancel_commerce_order(self,project_id,payload,**kw):
        self._validate_write(payload,**kw);self._commerce_access(project_id,"edit")
        if set(payload)!={"order_id"}:_error("取消需要明确订单")
        order=self._commerce_owned_order(project_id,payload["order_id"],kw["actor"])
        if order["status"] not in {"created","pending","checkout_unknown"}:_error("此订单状态不能取消","order_state_conflict")
        gateway=getattr(self,"commerce_payment_gateway",None)
        if gateway is None or gateway.id!=order["gateway"]:_error("原支付服务未配置","payment_unconfigured")
        return self._commerce().payment_event(project_id,gateway.cancel(order),expected_order=order["id"])

    def configure_commerce_campaign(self,project_id,payload,**kw):
        self._validate_write(payload,**kw);self._commerce_access(project_id,"manage")
        if set(payload)!={"code","title","credits","kind","purposes","starts_at","ends_at","credit_expires_at","daily"}:_error("活动配置字段不完整")
        if not isinstance(payload["code"],str) or not 6<=len(payload["code"])<=100:_error("兑换码须为6–100字符")
        positive(payload["credits"],"活动额度");purposes(payload["purposes"])
        if payload["kind"] not in {"bonus","check_in","special"} or type(payload["daily"]) is not bool:_error("活动类型不正确")
        if not instant(payload["starts_at"])<instant(payload["ends_at"])<=instant(payload["credit_expires_at"]):_error("活动与额度有效期不正确")
        return self._commerce().configure_campaign(project_id,payload,**kw)

    def redeem_commerce_campaign(self,project_id,payload,**kw):
        self._validate_write(payload,**kw);self._commerce_access(project_id,"edit")
        if set(payload)!={"code"} or not isinstance(payload["code"],str):_error("兑换需要明确活动码")
        return self._commerce().redeem(project_id,payload,**kw)

    def allocate_commerce_credits(self,project_id,payload,**kw):
        self._validate_write(payload,**kw);self._commerce_access(project_id,"manage")
        if set(payload)!={"bucket_id","target_actor","credits","reclaim"} or type(payload["reclaim"]) is not bool:_error("分配/回收字段不正确")
        positive(payload["credits"],"额度")
        target=payload["target_actor"]
        if target is not None and (not isinstance(target,str) or not 1<=len(target)<=200):_error("成员身份不正确")
        # Identity membership is provided by DS20; never make up a member from a label.
        if target and hasattr(self,"commerce_validate_member"):
            if self.commerce_validate_member(project_id,target) is False:_error("目标不是有效项目成员","commerce_member_invalid")
        elif target:_error("成员身份接缝尚未配置","commerce_member_unconfigured")
        return self._commerce().allocate(project_id,payload,**kw)

    def preview_commerce_charge(self,project_id,payload,*,actor):
        self._commerce_access(project_id,"read")
        if not isinstance(payload,dict) or set(payload)!={"operations","account_actor"}:_error("商业报价需要完整操作与承担账户")
        if payload["account_actor"]!=actor:self._commerce_access(project_id,"manage")
        return self._commerce().preview_charge(project_id,payload)

    def request_commerce_invoice(self,project_id,payload,**kw):
        self._validate_write(payload,**kw);self._commerce_access(project_id,"edit")
        if set(payload)!={"order_id","title","tax_id","email"}:_error("发票需要订单、抬头、税号和接收邮箱")
        for key,limit in (("title",200),("tax_id",100),("email",254)):
            if not isinstance(payload[key],str) or not payload[key].strip() or len(payload[key])>limit:_error("发票字段不正确："+key)
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+",payload["email"]):_error("邮箱格式不正确")
        self._commerce_owned_order(project_id,payload["order_id"],kw["actor"])
        gateway=getattr(self,"commerce_invoice_gateway",None)
        result=self._commerce().request_invoice(project_id,payload,gateway=gateway.id if gateway else None,**kw)
        return self.refresh_commerce_invoice(project_id,{"invoice_id":result["id"]},**kw) if gateway else result

    def refresh_commerce_invoice(self,project_id,payload,**kw):
        self._validate_write(payload,**kw);self._commerce_access(project_id,"read")
        if set(payload)!={"invoice_id"}:_error("需要明确发票申请")
        repo=self._commerce();invoice=repo.invoice(project_id,payload["invoice_id"])
        if invoice["actor"]!=kw["actor"]:self._commerce_access(project_id,"manage")
        gateway=getattr(self,"commerce_invoice_gateway",None)
        if gateway is None:_error("发票服务未配置，申请已保留","invoice_unconfigured")
        claimed=repo.claim_invoice(project_id,invoice["id"],gateway.id)
        if claimed["claimed"]:
            try:result=gateway.issue(invoice,repo.order(project_id,invoice["order_id"]))
            except Exception:return repo.invoice(project_id,invoice["id"])
        elif invoice["status"] in {"issued","failed"}:return invoice
        else:result=gateway.query(repo.invoice(project_id,invoice["id"]))
        return repo.invoice_result(project_id,invoice["id"],result)

    def commerce_invoice_content(self,project_id,identifier,*,actor):
        self._commerce_access(project_id,"read")
        invoice=self._commerce().invoice(project_id,identifier,content=True)
        if invoice["actor"]!=actor:self._commerce_access(project_id,"manage")
        if invoice["status"]!="issued":_error("尚无已开具发票文件","invoice_not_issued")
        return invoice["document"],invoice["sha256"]
