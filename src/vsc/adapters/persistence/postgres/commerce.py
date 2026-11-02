"""One credit ledger, immutable prices/events and original job usage references."""
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
from urllib.parse import urlsplit
from sqlalchemy import select, insert, update, func, and_, or_
from sqlalchemy.dialects.postgresql import insert as pg_insert

from vsc.assets.resource_service import Conflict, ResourceError
from vsc.assets.commerce import instant, require_supported_entitlements
from . import schema as S
from .values import CURRENT_REVISION, checked_id, clean, digest, new_id
from .workspace_commerce import WorkspaceCommerceRepository


class CommerceRepository(WorkspaceCommerceRepository):
    def __init__(self,store):self.store=store

    def _internal(self,p,action,payload,fn,key=None):
        from vsc.assets.access_control import current_principal
        principal=current_principal()
        return self.store._mutate(p,action,payload,callback=fn,expected_revision=CURRENT_REVISION,
            idempotency_key=key or new_id(),actor=principal.actor if principal and principal.actor else "commerce-consumer")

    def _plan(self,conn,p,identifier):return dict(self.store._one(conn,S.commerce_plan_versions,p,identifier))

    def _policy(self,conn,p):
        row=conn.execute(select(S.commerce_settings).where(S.commerce_settings.c.project_id==p)).mappings().first()
        return self._plan(conn,p,row["price_version_id"]) if row and row["enabled"] else None

    @staticmethod
    def _balance(conn,p,bucket_id):
        return conn.execute(select(func.coalesce(func.sum(S.commerce_ledger.c.delta),0)).where(
            S.commerce_ledger.c.project_id==p,S.commerce_ledger.c.bucket_id==bucket_id)).scalar_one()

    def _entry(self,conn,p,bucket,delta,kind,key,actor,reservation=None):
        if delta:
            identifier=new_id()
            conn.execute(insert(S.commerce_ledger).values(project_id=p,id=identifier,bucket_id=bucket,delta=delta,
                kind=kind,event_key=key,actor=actor,reservation_id=reservation))
            return identifier

    def _bucket(self,conn,p,*,source_key,credits,owner,kind,purposes,expires,order=None,parent=None,entry_kind="grant",actor="commerce-consumer"):
        identifier=new_id()
        conn.execute(insert(S.commerce_buckets).values(project_id=p,id=identifier,source_key=source_key,
            owner_actor=owner,kind=kind,purposes=purposes,expires_at=expires,order_id=order,parent_bucket_id=parent))
        self._entry(conn,p,identifier,credits,entry_kind,source_key+":in",actor)
        return identifier

    def summary(self,p,actor,manage=False):
        with self.store.engine.connect() as conn:
            project=self.store._project(conn,p);p=project["id"]
            rows=conn.execute(select(S.commerce_plan_versions).where(S.commerce_plan_versions.c.project_id==p)
                .order_by(S.commerce_plan_versions.c.version.desc())).mappings()
            plans={}
            for row in rows:plans.setdefault(row["plan_key"],dict(row))
            policy=self._policy(conn,p)
            orders=[dict(row) for row in conn.execute(select(S.commerce_orders).where(S.commerce_orders.c.project_id==p,
                True if manage else S.commerce_orders.c.actor==actor).order_by(S.commerce_orders.c.created_at.desc()).limit(100)).mappings()]
            now=datetime.now(timezone.utc)
            buckets=[]
            for row in conn.execute(select(S.commerce_buckets).where(S.commerce_buckets.c.project_id==p,
                    True if manage else or_(S.commerce_buckets.c.owner_actor==actor,S.commerce_buckets.c.owner_actor.is_(None)))
                    .order_by(S.commerce_buckets.c.created_at.desc())).mappings():
                value=dict(row,balance=self._balance(conn,p,row["id"]))
                value["expired"]=bool(row["expires_at"] and row["expires_at"]<=now)
                value["frozen"]=False
                if row["order_id"]:
                    order=self.store._one(conn,S.commerce_orders,p,row["order_id"])
                    value["frozen"]=order["status"] in {"refund_unknown","refunded"}
                value["available"]=0 if value["expired"] or value["frozen"] else value["balance"]
                buckets.append(value)
            ids=[b["id"] for b in buckets]
            ledger=[dict(row) for row in conn.execute(select(S.commerce_ledger).where(S.commerce_ledger.c.project_id==p,
                S.commerce_ledger.c.bucket_id.in_(ids)).order_by(S.commerce_ledger.c.created_at.desc()).limit(200)).mappings()]
            invoice_rows=conn.execute(select(S.commerce_invoices).where(S.commerce_invoices.c.project_id==p,
                True if manage else S.commerce_invoices.c.actor==actor).order_by(S.commerce_invoices.c.created_at.desc()).limit(100)).mappings()
            invoices=[{k:v for k,v in row.items() if k not in {"document","tax_id","email"}} for row in invoice_rows]
            reservations=[dict(row) for row in conn.execute(select(S.commerce_reservations).where(S.commerce_reservations.c.project_id==p,
                True if manage else S.commerce_reservations.c.account_actor==actor).order_by(S.commerce_reservations.c.created_at.desc()).limit(100)).mappings()]
            return clean(dict(project_id=p,revision=project["revision"],plans=list(plans.values()),policy=policy,
                orders=orders,buckets=buckets,ledger=ledger,invoices=invoices,reservations=reservations,
                credit_balance=sum(row["available"] for row in buckets),credit_unit="commercial_credit",native_units_are_separate=True))

    def configure_plan(self,p,payload,**kw):
        def work(conn,project):
            p=project["id"];doc=payload["document"]
            prior=conn.execute(select(S.commerce_plan_versions).where(S.commerce_plan_versions.c.project_id==p,
                S.commerce_plan_versions.c.plan_key==doc["plan_key"]).order_by(S.commerce_plan_versions.c.version.desc()).limit(1)).mappings().first()
            if (prior["id"] if prior else None)!=payload["base_version_id"]:raise Conflict("价格已有新版本，请读取比较","commerce_plan_conflict")
            identifier=new_id();version=prior["version"]+1 if prior else 1
            conn.execute(insert(S.commerce_plan_versions).values(project_id=p,id=identifier,plan_key=doc["plan_key"],version=version,document=doc,sha256=digest(doc),actor=kw["actor"]))
            for rate in doc["rates"]:
                model=conn.execute(select(S.provider_models).where(S.provider_models.c.id==checked_id(rate["model_id"]))).mappings().first()
                if model is None:raise ResourceError("价格引用的模型未登记","commerce_model_missing")
                conn.execute(insert(S.commerce_rates).values(project_id=p,id=new_id(),plan_id=identifier,**rate))
            conn.execute(pg_insert(S.commerce_settings).values(project_id=p,id=new_id(),price_version_id=identifier,enabled=payload["metering_enabled"])
                .on_conflict_do_update(index_elements=[S.commerce_settings.c.project_id],set_={"price_version_id":identifier,"enabled":payload["metering_enabled"]}))
            return dict(id=identifier,version=version,sha256=digest(doc))
        return self.store._mutate(p,"commerce_configure_plan",payload,callback=work,**kw)

    def create_order(self,p,payload,*,gateway,**kw):
        def work(conn,project):
            plan=self._plan(conn,project["id"],checked_id(payload["plan_id"]));doc=plan["document"]
            require_supported_entitlements(doc)
            latest=conn.execute(select(func.max(S.commerce_plan_versions.c.version)).where(S.commerce_plan_versions.c.project_id==project["id"],S.commerce_plan_versions.c.plan_key==plan["plan_key"])).scalar_one()
            if plan["version"]!=latest:raise Conflict("套餐价格已更新，请重新读取","commerce_plan_conflict")
            renewal=payload.get("renewal_of_order_id")
            if renewal:
                prior=self.store._one(conn,S.commerce_orders,project["id"],renewal)
                if prior["status"]!="paid" or prior["plan_id"]!=plan["id"] or doc["renewal_policy"]!="manual_from_payment":
                    raise Conflict("原订单或套餐不支持此手动续期","renewal_unavailable")
            identifier=new_id()
            conn.execute(insert(S.commerce_orders).values(project_id=project["id"],id=identifier,plan_id=plan["id"],renewal_of_order_id=renewal,actor=kw["actor"],gateway=gateway,status="created",
                amount_minor=doc["amount_minor"],currency=doc["currency"],credits=doc["credits"],expires_at=datetime.now(timezone.utc)+timedelta(minutes=doc["checkout_minutes"])))
            return dict(id=identifier,status="created")
        return self.store._mutate(p,"commerce_create_order",payload,callback=work,**kw)

    def entitlements(self,p,conn=None):
        from contextlib import nullcontext
        with (nullcontext(conn) if conn is not None else self.store.engine.connect()) as connection:
            project=self.store._project(connection,p);plan=self._policy(connection,project["id"])
            if not plan:return {"configured":False}
            return {"configured":True,"price_version_id":plan["id"],**{k:plan["document"][k] for k in ("seat_limit","max_concurrent_jobs","watermark_required")},
                "watermark_consumer":"edit-export-v1" if plan["document"]["watermark_required"] else "not_required"}

    def order(self,p,identifier):
        with self.store.engine.connect() as conn:
            project=self.store._project(conn,p)
            return clean(dict(self.store._one(conn,S.commerce_orders,project["id"],checked_id(identifier)),revision=project["revision"]))

    def claim_checkout(self,p,identifier):
        def work(conn,project):
            order=dict(self.store._one(conn,S.commerce_orders,project["id"],identifier));claimed=order["status"]=="created"
            if claimed:conn.execute(update(S.commerce_orders).where(S.commerce_orders.c.project_id==project["id"],S.commerce_orders.c.id==identifier).values(status="checkout_unknown"))
            return dict(claimed=claimed,order=order)
        return self._internal(p,"commerce_claim_checkout",{"order_id":identifier},work)

    def checkout_result(self,p,identifier,checkout):
        url=checkout.get("checkout_url")
        parsed=urlsplit(url or "")
        if url and (parsed.scheme!="https" or not parsed.hostname or parsed.username or parsed.password):raise ResourceError("收银台地址无效","checkout_url_invalid")
        if not isinstance(checkout.get("external_id"),str) or not checkout["external_id"]:raise ResourceError("缺少支付订单回执","checkout_receipt_missing")
        def work(conn,project):
            row=self.store._one(conn,S.commerce_orders,project["id"],identifier)
            if row["status"]=="checkout_unknown":conn.execute(update(S.commerce_orders).where(S.commerce_orders.c.project_id==project["id"],S.commerce_orders.c.id==identifier)
                .values(status="pending",external_id=checkout["external_id"],checkout_url=url))
            return {"id":identifier}
        return self._internal(p,"commerce_checkout_result",dict(order_id=identifier,checkout=checkout),work,"checkout:"+identifier)

    def payment_event(self,p,event,expected_order=None):
        from vsc.adapters.providers.commerce import PaymentEvent
        if not isinstance(event,PaymentEvent) or event.status not in {"pending","paid","expired","cancelled","refunded","refund_rejected"} or type(event.amount_minor) is not int or event.amount_minor<=0 or any(not isinstance(value,str) or not 1<=len(value)<=200 for value in (event.event_id,event.external_id,event.gateway)):
            raise ResourceError("支付回执字段不正确","payment_event_invalid")
        if expected_order and event.order_id!=expected_order:raise ResourceError("支付查询返回其他订单","payment_event_invalid")
        document=asdict(event)
        def work(conn,project):
            p=project["id"];order=self.store._one(conn,S.commerce_orders,p,checked_id(event.order_id))
            if (order["gateway"],order["amount_minor"],order["currency"])!=(event.gateway,event.amount_minor,event.currency):raise ResourceError("支付回执金额、币种或网关与固定订单不符","payment_event_mismatch")
            if order["external_id"] and order["external_id"]!=event.external_id:raise Conflict("外部订单编号不能替换","payment_event_mismatch")
            prior=conn.execute(select(S.commerce_payment_events).where(S.commerce_payment_events.c.project_id==p,
                S.commerce_payment_events.c.gateway==event.gateway,S.commerce_payment_events.c.event_id==event.event_id)).mappings().first()
            if prior:
                if prior["sha256"]!=digest(document):raise Conflict("相同支付事件不能改变内容","payment_event_mismatch")
                return dict(id=order["id"],status=order["status"])
            conn.execute(insert(S.commerce_payment_events).values(project_id=p,id=new_id(),order_id=order["id"],gateway=event.gateway,event_id=event.event_id,sha256=digest(document),document=document))
            plan=self._plan(conn,p,order["plan_id"])["document"];status=order["status"];now=datetime.now(timezone.utc)
            if event.status=="paid" and status not in {"paid","refunded","refund_unknown"}:
                if not order["paid_at"]:
                    self._bucket(conn,p,source_key="order:"+order["id"],credits=order["credits"],owner=order["actor"],kind=plan["bucket_kind"],
                        purposes=plan["purposes"],expires=now+timedelta(days=plan["validity_days"]),order=order["id"])
                status="paid"
                conn.execute(update(S.commerce_orders).where(S.commerce_orders.c.project_id==p,S.commerce_orders.c.id==order["id"]).values(paid_at=order["paid_at"] or now))
            elif event.status=="refund_rejected":
                # Only an explicit verified refund rejection permits spending
                # again. A generic 'paid' poll says nothing about pending refund.
                if status=="refund_unknown":status="paid"
            elif event.status=="refunded" and status!="refunded":
                buckets=conn.execute(select(S.commerce_buckets).where(S.commerce_buckets.c.project_id==p,S.commerce_buckets.c.order_id==order["id"])).mappings().all()
                if not order["paid_at"] or sum(self._balance(conn,p,b["id"]) for b in buckets)!=order["credits"]:
                    raise Conflict("订单存在已发生用量，不能以全额退款抹除","refund_usage_conflict")
                for bucket in buckets:self._entry(conn,p,bucket["id"],-self._balance(conn,p,bucket["id"]),"refund","refund:"+order["id"]+":"+bucket["id"],"commerce-gateway")
                status="refunded"
            elif status not in {"paid","refund_unknown","refunded"}:status=event.status
            conn.execute(update(S.commerce_orders).where(S.commerce_orders.c.project_id==p,S.commerce_orders.c.id==order["id"]).values(status=status,external_id=event.external_id,error_code=None))
            return dict(id=order["id"],status=status)
        from vsc.assets.access_control import current_principal
        principal=current_principal();observer=principal.actor if principal and principal.actor else "commerce-consumer"
        return self._internal(p,"commerce_gateway_event",document,work,"commerce-event:"+hashlib.sha256((event.gateway+":"+event.event_id+":"+observer).encode()).hexdigest())

    def claim_refund(self,p,payload,**kw):
        def work(conn,project):
            p=project["id"];order=self.store._one(conn,S.commerce_orders,p,payload["order_id"])
            if order["status"] in {"refund_unknown","refunded"}:return dict(claimed=False,id=order["id"])
            plan=self._plan(conn,p,order["plan_id"])["document"]
            buckets=conn.execute(select(S.commerce_buckets.c.id).where(S.commerce_buckets.c.project_id==p,S.commerce_buckets.c.order_id==order["id"])).scalars().all()
            if order["status"]!="paid" or plan["refund_policy"]!="unused_order_only" or sum(self._balance(conn,p,b) for b in buckets)!=order["credits"]:
                raise Conflict("只可按已配置政策退回完全未消费订单；已有用量保留","refund_unavailable")
            conn.execute(update(S.commerce_orders).where(S.commerce_orders.c.project_id==p,S.commerce_orders.c.id==order["id"]).values(status="refund_unknown"))
            return dict(claimed=True,id=order["id"])
        # A fresh internal claim is required: reusing a receipt that says claimed
        # would re-send a refund after a lost response.
        return self._internal(p,"commerce_claim_refund",payload,work)

    def configure_campaign(self,p,payload,**kw):
        def work(conn,project):
            identifier=new_id();values={k:v for k,v in payload.items() if k!="code"}
            values.update({k:instant(payload[k]) for k in ("starts_at","ends_at","credit_expires_at")})
            conn.execute(insert(S.commerce_campaigns).values(project_id=project["id"],id=identifier,actor=kw["actor"],code_sha256=hashlib.sha256(payload["code"].encode()).hexdigest(),**values))
            return {"id":identifier}
        return self.store._mutate(p,"commerce_configure_campaign",payload,callback=work,**kw)

    def redeem(self,p,payload,**kw):
        def work(conn,project):
            p=project["id"];now=datetime.now(timezone.utc)
            campaign=conn.execute(select(S.commerce_campaigns).where(S.commerce_campaigns.c.project_id==p,S.commerce_campaigns.c.code_sha256==hashlib.sha256(payload["code"].encode()).hexdigest())).mappings().first()
            if not campaign or not campaign["starts_at"]<=now<campaign["ends_at"]:raise ResourceError("活动码不存在或不在有效期内","campaign_unavailable")
            period=now.date().isoformat() if campaign["daily"] else "once"
            prior=conn.execute(select(S.commerce_redemptions).where(S.commerce_redemptions.c.project_id==p,S.commerce_redemptions.c.campaign_id==campaign["id"],S.commerce_redemptions.c.actor==kw["actor"],S.commerce_redemptions.c.period==period)).mappings().first()
            if prior:return {"id":prior["id"],"bucket_id":prior["bucket_id"],"already_redeemed":True}
            identifier=new_id();bucket=self._bucket(conn,p,source_key="campaign:"+identifier,credits=campaign["credits"],owner=kw["actor"],kind=campaign["kind"],purposes=campaign["purposes"],expires=campaign["credit_expires_at"],actor=kw["actor"])
            conn.execute(insert(S.commerce_redemptions).values(project_id=p,id=identifier,campaign_id=campaign["id"],bucket_id=bucket,actor=kw["actor"],period=period))
            return dict(id=identifier,bucket_id=bucket,already_redeemed=False)
        return self.store._mutate(p,"commerce_redeem",payload,callback=work,**kw)

    def allocate(self,p,payload,**kw):
        def work(conn,project):
            p=project["id"];source=self.store._one(conn,S.commerce_buckets,p,payload["bucket_id"])
            if payload["target_actor"] and not self.store.access_member_valid(p,payload["target_actor"],conn=conn):
                raise ResourceError("目标不是有效项目成员","commerce_member_invalid")
            if source["expires_at"] and source["expires_at"]<=datetime.now(timezone.utc):raise Conflict("已过期额度不能重新分配","credit_expired")
            if source["order_id"] and self.store._one(conn,S.commerce_orders,p,source["order_id"])["status"]!="paid":raise Conflict("订单额度已冻结","credit_frozen")
            if payload["reclaim"] and (source["owner_actor"] is None or payload["target_actor"] is not None):raise ResourceError("回收将成员未用额度回到项目池","credit_reclaim_invalid")
            if self._balance(conn,p,source["id"])<payload["credits"]:raise Conflict("可分配额度不足","credit_insufficient")
            key="transfer:"+new_id();kind="reclaim" if payload["reclaim"] else "allocate"
            self._entry(conn,p,source["id"],-payload["credits"],kind+"_out",key+":out",kw["actor"])
            identifier=self._bucket(conn,p,source_key=key,credits=payload["credits"],owner=payload["target_actor"],kind=source["kind"],purposes=source["purposes"],expires=source["expires_at"],order=source["order_id"],parent=source["id"],entry_kind=kind+"_in",actor=kw["actor"])
            return dict(id=identifier,credits=payload["credits"])
        return self.store._mutate(p,"commerce_reclaim" if payload["reclaim"] else "commerce_allocate",payload,callback=work,**kw)

    def _price(self,conn,p,plan,model_id,native):
        if not isinstance(native,dict) or not native or any(type(v) is not int or v<0 for v in native.values()):raise ResourceError("商业报价需要原生单位整数","commerce_units_invalid")
        rates=conn.execute(select(S.commerce_rates).where(S.commerce_rates.c.project_id==p,S.commerce_rates.c.plan_id==plan,S.commerce_rates.c.model_id==model_id)).mappings().all()
        if not rates or any(r["unit"] not in native for r in rates):raise ResourceError("该模型缺少适用价格版本","commerce_price_missing")
        return sum(native[r["unit"]]*r["credits_per_unit"] for r in rates)

    def preview_charge(self,p,payload):
        with self.store.engine.connect() as conn:
            project=self.store._project(conn,p);plan=self._policy(conn,project["id"])
            if not plan:return dict(enabled=False,commerce_charge=None,revision=project["revision"])
            operations=payload["operations"]
            if not isinstance(operations,list) or not 1<=len(operations)<=200:raise ResourceError("商业报价需1–200个固定操作")
            bounds={}
            for row in operations:
                if not isinstance(row,dict) or set(row)!={"operation","model_id","native_units"} or row["operation"] in bounds:raise ResourceError("商业操作编号或价格输入无效")
                bounds[row["operation"]]=self._price(conn,project["id"],plan["id"],checked_id(row["model_id"]),row["native_units"])
            return dict(enabled=True,commerce_charge=dict(price_version_id=plan["id"],account_actor=payload["account_actor"],max_credits_by_operation=bounds),revision=project["revision"])

    def reserve_for_job(self,conn,project,job):
        p=project["id"];policy=self._policy(conn,p)
        if not policy:return
        require_supported_entitlements(policy["document"])
        if conn.execute(select(S.commerce_reservations.c.id).where(S.commerce_reservations.c.project_id==p,S.commerce_reservations.c.job_id==job["id"])).first():return
        run=self.store._one(conn,S.artifact_versions,p,job["run_version_id"]);charge=json.loads(run["document"]).get("commerce_charge")
        if not isinstance(charge,dict) or set(charge)!={"price_version_id","account_actor","max_credits_by_operation"}:raise ResourceError("已批准运行缺少固定商业承担账户与信用预算","commerce_charge_required")
        from .budget_store import native_units,operation_key
        logical=job["request_payload"].get("logical_request",job["request_payload"])
        plan=self._plan(conn,p,charge["price_version_id"])
        require_supported_entitlements(plan["document"])
        cost=self._price(conn,p,plan["id"],job["model_id"],native_units(logical))
        bound=charge["max_credits_by_operation"].get(operation_key(logical,job["candidate_no"]))
        if type(bound) is not int or bound!=cost:raise ResourceError("商业信用预算与固定价格不一致","commerce_quote_changed")
        active=conn.execute(select(func.count()).select_from(S.commerce_reservations).where(S.commerce_reservations.c.project_id==p,S.commerce_reservations.c.status=="reserved")).scalar_one()
        if active>=min(plan["document"]["max_concurrent_jobs"],policy["document"]["max_concurrent_jobs"]):raise Conflict("已到当前商业方案并发上限","commerce_concurrency_limit")
        owner=charge["account_actor"]
        if owner is not None and (not isinstance(owner,str) or len(owner)>200):raise ResourceError("商业承担账户无效")
        now=datetime.now(timezone.utc);buckets=[]
        for row in conn.execute(select(S.commerce_buckets).where(S.commerce_buckets.c.project_id==p,
            S.commerce_buckets.c.owner_actor==owner,or_(S.commerce_buckets.c.expires_at.is_(None),S.commerce_buckets.c.expires_at>now))
            .order_by(S.commerce_buckets.c.expires_at.asc().nullslast(),S.commerce_buckets.c.created_at,S.commerce_buckets.c.id)).mappings():
            if job["purpose"] not in row["purposes"] and "*" not in row["purposes"]:continue
            if row["order_id"] and self.store._one(conn,S.commerce_orders,p,row["order_id"])["status"]!="paid":continue
            buckets.append((row,self._balance(conn,p,row["id"])))
        if sum(balance for _,balance in buckets)<cost:raise Conflict("指定账户可用商业信用不足（类型/用途/有效期已过滤）","credit_insufficient")
        identifier=new_id()
        conn.execute(insert(S.commerce_reservations).values(project_id=p,id=identifier,job_id=job["id"],price_version_id=plan["id"],account_actor=owner,attempt=job["attempt"]+1,bound=cost,status="reserved"))
        remaining=cost
        for bucket,balance in buckets:
            used=min(balance,remaining);remaining-=used
            self._entry(conn,p,bucket["id"],-used,"reserve","job:"+job["id"]+":"+bucket["id"],owner or "project",identifier)
            if remaining==0:break

    def settle_for_job(self,conn,p,job):
        reservation=conn.execute(select(S.commerce_reservations).where(S.commerce_reservations.c.project_id==p,S.commerce_reservations.c.job_id==job["id"])).mappings().first()
        if not reservation or reservation["status"]!="reserved":return
        units=conn.execute(select(S.job_budget_reservations).where(S.job_budget_reservations.c.project_id==p,S.job_budget_reservations.c.job_id==job["id"])).mappings().all()
        actual={r["unit"]:r["actual"] for r in units if r["actual"] is not None}
        cost=self._price(conn,p,reservation["price_version_id"],job["model_id"],actual) if units and len(actual)==len(units) else reservation["bound"]
        if cost>reservation["bound"]:raise Conflict("商业实际用量超过原批准边界","commerce_actual_exceeded")
        refund=reservation["bound"]-cost
        holds=conn.execute(select(S.commerce_ledger).where(S.commerce_ledger.c.project_id==p,S.commerce_ledger.c.reservation_id==reservation["id"],S.commerce_ledger.c.kind=="reserve").order_by(S.commerce_ledger.c.created_at,S.commerce_ledger.c.id)).mappings()
        for hold in holds:
            returned=min(-hold["delta"],refund);refund-=returned
            self._entry(conn,p,hold["bucket_id"],returned,"release","settle:"+reservation["id"]+":"+hold["bucket_id"],"commerce-consumer",reservation["id"])
        conn.execute(update(S.commerce_reservations).where(S.commerce_reservations.c.project_id==p,S.commerce_reservations.c.id==reservation["id"]).values(actual=cost,status="released" if cost==0 else "settled"))

    def request_invoice(self,p,payload,*,gateway,**kw):
        def work(conn,project):
            p=project["id"];order=self.store._one(conn,S.commerce_orders,p,payload["order_id"])
            workspace=payload.get('workspace_id')
            if workspace:
                self.store.access_workspace_guard(conn,workspace,'manage')
                actual=conn.execute(select(S.access_projects.c.workspace_id).where(S.access_projects.c.project_id==p)).scalar_one_or_none()
                if actual!=workspace:raise ResourceError('组织发票须属于订单所在工作空间','commerce_invoice_scope')
            if order["status"]!="paid" or not self._plan(conn,p,order["plan_id"])["document"]["invoice_enabled"]:raise ResourceError("订单未支付或未配置发票政策","invoice_order_ineligible")
            old=conn.execute(select(S.commerce_invoices).where(S.commerce_invoices.c.project_id==p,S.commerce_invoices.c.order_id==order["id"])).mappings().first()
            if old:
                if any(old[k]!=payload.get(k) for k in ("title","tax_id","email","workspace_id")):raise Conflict("此订单已有发票申请，不能静默改抬头","invoice_conflict")
                return dict(id=old["id"],status=old["status"])
            identifier=new_id();status="created" if gateway else "unconfigured"
            conn.execute(insert(S.commerce_invoices).values(project_id=p,id=identifier,actor=kw["actor"],gateway=gateway or "unconfigured",status=status,**payload))
            return dict(id=identifier,status=status)
        return self.store._mutate(p,"commerce_request_invoice",payload,callback=work,**kw)

    def invoice(self,p,identifier,content=False):
        with self.store.engine.connect() as conn:
            project=self.store._project(conn,p);row=dict(self.store._one(conn,S.commerce_invoices,project["id"],checked_id(identifier)))
            if not content:row.pop("document",None)
            document=row.pop("document",None) if content else None
            result=clean(dict(row,revision=project["revision"]))
            if content:result["document"]=bytes(document) if document else None
            return result

    def claim_invoice(self,p,identifier,gateway):
        def work(conn,project):
            row=self.store._one(conn,S.commerce_invoices,project["id"],identifier)
            claimed=row["status"] in {"created","unconfigured"}
            if row["gateway"] not in {"unconfigured",gateway}:raise Conflict("只能用原发票服务恢复","invoice_gateway_changed")
            if claimed:conn.execute(update(S.commerce_invoices).where(S.commerce_invoices.c.project_id==project["id"],S.commerce_invoices.c.id==identifier).values(status="submission_unknown",gateway=gateway))
            return dict(id=identifier,claimed=claimed)
        return self._internal(p,"commerce_claim_invoice",dict(invoice_id=identifier,gateway=gateway),work)

    def invoice_result(self,p,identifier,result):
        if result.status not in {"pending","issued","failed"} or not result.external_id:raise ResourceError("发票回执无效","invoice_result_invalid")
        raw=result.document
        if result.status=="issued" and (not isinstance(raw,bytes) or not raw.startswith(b"%PDF-") or not 5<len(raw)<=10*1024*1024):raise ResourceError("发票服务尚未返回有效PDF文件","invoice_document_invalid")
        def work(conn,project):
            row=self.store._one(conn,S.commerce_invoices,project["id"],identifier)
            if row["external_id"] and row["external_id"]!=result.external_id:raise Conflict("发票编号不能替换","invoice_result_changed")
            if row["status"]=="issued":
                if result.status!="issued" or row["sha256"]!=hashlib.sha256(raw).hexdigest():raise Conflict("已开具发票不能覆盖","invoice_result_changed")
            else:conn.execute(update(S.commerce_invoices).where(S.commerce_invoices.c.project_id==project["id"],S.commerce_invoices.c.id==identifier).values(status=result.status,external_id=result.external_id,document=raw if result.status=="issued" else None,sha256=hashlib.sha256(raw).hexdigest() if result.status=="issued" else None))
            return dict(id=identifier,status=result.status)
        return self._internal(p,"commerce_invoice_result",dict(invoice_id=identifier,status=result.status,external_id=result.external_id,sha256=hashlib.sha256(raw).hexdigest() if raw else None),work)
