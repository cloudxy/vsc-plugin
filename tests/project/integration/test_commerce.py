"""Real isolated PostgreSQL and HTTP; payment/issuer are offline contracts only."""
import copy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import tempfile
import unittest
import uuid

from support.fixtures.resource_store import ResourceStoreFixture, HAS_DB_DEPS, TEST_URL
from vsc.assets.resource_service import ResourceError, Conflict
from vsc.adapters.providers.commerce import Checkout, PaymentEvent, InvoiceResult


class OfflinePayment:
    id = "isolated-test-payment"

    def __init__(self):
        self.created = self.refunds = self.queries = 0
        self.lose_checkout = self.lose_refund = False
        self.query_status = "paid"

    def create_checkout(self, order):
        self.created += 1
        if self.lose_checkout: raise TimeoutError("synthetic lost response")
        return Checkout("ext-" + order["id"], "https://example.invalid/isolated-checkout")

    def event(self, order, status, event_id=None):
        return PaymentEvent(self.id, event_id or uuid.uuid4().hex, order["id"], status,
                            order["amount_minor"], order["currency"], "ext-" + order["id"])

    def query_order(self, order):
        self.queries += 1
        return self.event(order, self.query_status)

    def refund(self, order):
        self.refunds += 1
        if self.lose_refund: raise TimeoutError("synthetic lost refund response")
        return self.event(order, "refunded")

    def cancel(self, order): return self.event(order, "cancelled")

    def verify_notification(self, headers, body):
        if headers.get("isolated-signature") != "valid": raise ResourceError("invalid signature")
        return body  # Test-only event transport; production port requires bytes.


class OfflineIssuer:
    id = "isolated-test-issuer"

    def __init__(self): self.issued = self.queried = 0

    def issue(self, invoice, order):
        self.issued += 1
        raise TimeoutError("synthetic issue accepted; response lost")

    def query(self, invoice):
        self.queried += 1
        return InvoiceResult("invoice-" + invoice["id"], "issued", b"%PDF-1.4\n% isolated contract bytes, not a tax invoice\n%%EOF")


@unittest.skipUnless(HAS_DB_DEPS and TEST_URL, "isolated PostgreSQL is required")
class CommerceTests(ResourceStoreFixture, unittest.TestCase):
    def setUp(self):
        self.project = self.service.create_project({"name":"商业合同隔离测试", "profile_snapshot":{"profile_id":"vsc.synthetic","version":"1","stages":[],"contract_policy":"production-v2"}}, actor="test-human")
        self.p, self.rev = self.project["id"], 0
        self.gateway = OfflinePayment()
        for name in ("commerce_payment_gateway", "commerce_invoice_gateway", "commerce_validate_member"):
            self.service.__dict__.pop(name, None)
        provider = "commerce_offline_" + uuid.uuid4().hex
        self.service.register_provider({"id": provider, "base_url": "https://example.invalid", "auth_ref": "OFFLINE_ONLY"}, actor="test-admin")
        self.model = self.service.register_model({"provider_id": provider, "model_key": "image", "model_version": "1", "modality": "image", "capabilities": {"purposes": ["identity_ref"]}}, actor="test-admin")["id"]
        self.document = dict(plan_key="isolated", title="隔离合同，无商业报价", amount_minor=100,
            currency="TST", credits=100, bucket_kind="credit", validity_days=2, checkout_minutes=10,
            purposes=["identity_ref"], rates=[dict(model_id=self.model, unit="images", credits_per_unit=10)],
            refund_policy="unused_order_only", max_concurrent_jobs=1, invoice_enabled=True,
            seat_limit=3, watermark_required=False, renewal_policy="manual_from_payment")

    def summary(self): return self.service.commerce_summary(self.p, actor="test-human")

    def configure(self, enabled=True, **changes):
        self.document.update(changes)
        plan = self.write("configure_commerce_plan", dict(document=copy.deepcopy(self.document), base_version_id=getattr(self, "plan", None), metering_enabled=enabled))
        self.plan = plan["id"]
        return plan

    def paid_order(self):
        self.service.commerce_payment_gateway = self.gateway
        order = self.write("create_commerce_order", {"plan_id": self.plan})
        self.write("refresh_commerce_order", {"order_id": order["id"]})
        return self.service._commerce().order(self.p, order["id"])

    def seed_jobs(self, count=1, charge=True):
        from vsc.adapters.persistence.postgres.budget_store import native_units, operation_key
        self.write("configure_budget", dict(limits={"remote_jobs": count, "images": count}, reason="隔离原生预算"))
        asset = self.write("create_object", {"kind": "asset", "asset_kind": "character", "display_code": uuid.uuid4().hex})["id"]
        bible = self.artifact("bible-" + asset, "asset-bible", [asset], {"asset_specs": [{"id": str(uuid.uuid4()), "asset_id": asset, "variant_key": "master"}]})
        context = self.service.compile_asset_context(self.p, asset, "identity_ref")
        request = dict(shot_id=None, asset_id=asset, modality="image", purpose="identity_ref", prompt="Synthetic fixed portrait")
        pins = [{"id": a["id"], "sha256": a["sha256"]} for a in context["artifacts"]]
        operations = [{"operation": operation_key(request, n), "model_id": self.model, "native_units": native_units(request)} for n in range(count)]
        doc = dict(approved_inputs=pins, jobs=[dict(candidate_no=n, request=request) for n in range(count)], operations={r["operation"]:r["native_units"] for r in operations})
        if charge: doc["commerce_charge"] = self.service.preview_commerce_charge(self.p, dict(operations=operations, account_actor="test-human"), actor="test-human")["commerce_charge"]
        run = self.write("create_artifact", dict(artifact_key="run-" + asset, artifact_type="production-run", document=doc, dependency_ids=[bible], object_ids=[asset]))["id"]
        self.write("decide_artifact", dict(artifact_id=run, reason="批准隔离固定请求"))
        return [self.write("create_generation_job", dict(run_version_id=run, asset_id=asset, purpose="identity_ref", modality="image", model_id=self.model, candidate_no=n, context_sha256=context["sha256"], request_payload=request)) for n in range(count)]

    def test_unconfigured_and_versioned_prices_fail_closed(self):
        self.assertFalse(self.summary()["capabilities"]["payment"])
        self.assertEqual(self.service.commerce_entitlements(self.p), {"configured": False})
        first = self.configure()
        with self.assertRaises(ResourceError) as caught: self.write("create_commerce_order", {"plan_id": first["id"]})
        self.assertEqual(caught.exception.code, "payment_unconfigured")
        self.assertEqual(self.summary()["orders"], [])
        self.configure(credits=120)
        self.service.commerce_payment_gateway = self.gateway
        with self.assertRaises(Conflict): self.write("create_commerce_order", {"plan_id": first["id"]})
        self.assertEqual(self.gateway.created, 0)
        self.assertEqual(self.service.commerce_entitlements(self.p)["seat_limit"], 3)
        before = self.store.get_project(self.p)["revision"]
        from unittest.mock import patch
        with patch('vsc.post.export_entitlements.available',return_value=False),self.assertRaises(ResourceError) as caught:
            self.configure(watermark_required=True)
        self.assertEqual(caught.exception.code, "commerce_entitlement_unavailable")
        self.assertEqual(self.store.get_project(self.p)["revision"], before)
        self.configure(watermark_required=True)
        self.assertEqual(self.service.commerce_entitlements(self.p)['watermark_consumer'],'edit-export-v1')

    def test_checkout_response_loss_deduplicates_and_recovers(self):
        self.configure(); self.service.commerce_payment_gateway = self.gateway; self.gateway.lose_checkout = True
        rev = self.rev
        order = self.write("create_commerce_order", {"plan_id": self.plan}, idempotency_key="same-order")
        self.assertEqual(order["status"], "checkout_unknown")
        replay = self.service.create_commerce_order(self.p, {"plan_id": self.plan}, expected_revision=rev, idempotency_key="same-order", actor="test-human")
        self.assertEqual(replay["id"], order["id"]); self.assertEqual(self.gateway.created, 1)
        self.rev = replay["revision"]
        self.write("refresh_commerce_order", {"order_id": order["id"]})
        self.assertEqual(self.summary()["credit_balance"], 100)
        self.write("refresh_commerce_order", {"order_id": order["id"]})
        self.assertEqual(len(self.summary()["buckets"]), 1)

    def test_verified_events_fixed_amount_and_out_of_order_state(self):
        self.configure(); order = self.paid_order(); repo = self.service._commerce()
        event = self.gateway.event(order, "paid", "fixed-event")
        first = repo.payment_event(self.p, event); again = repo.payment_event(self.p, event)
        self.assertEqual(first, again)
        with self.assertRaises(Conflict): repo.payment_event(self.p, replace(event, amount_minor=101))
        with self.assertRaises(ResourceError): repo.payment_event(self.p, replace(event, event_id="wrong-currency", currency="BAD"))
        with self.assertRaises(ResourceError): self.service.handle_commerce_notification(self.p, {}, event)
        repo.payment_event(self.p, self.gateway.event(order, "expired"))
        self.assertEqual(repo.order(self.p, order["id"])["status"], "paid")
        self.assertEqual(self.summary()["credit_balance"], 100)

    def test_campaign_duplicate_and_transfer_conserve_expiry(self):
        now = datetime.now(timezone.utc)
        campaign = dict(code="isolated-code", title="隔离赠送", credits=20, kind="check_in", purposes=["identity_ref"], starts_at=(now-timedelta(hours=1)).isoformat(), ends_at=(now+timedelta(hours=1)).isoformat(), credit_expires_at=(now+timedelta(days=1)).isoformat(), daily=True)
        self.write("configure_commerce_campaign", campaign)
        a = self.write("redeem_commerce_campaign", {"code": campaign["code"]})
        b = self.write("redeem_commerce_campaign", {"code": campaign["code"]})
        self.assertEqual(a["bucket_id"], b["bucket_id"]); self.assertTrue(b["already_redeemed"])
        transfer = self.write("allocate_commerce_credits", dict(bucket_id=a["bucket_id"], target_actor=None, credits=12, reclaim=True))
        self.service.commerce_validate_member = lambda p, actor: actor == "test-human"
        with self.assertRaises(ResourceError): self.write("allocate_commerce_credits", dict(bucket_id=transfer["id"], target_actor="invented-person", credits=1, reclaim=False))
        self.write("allocate_commerce_credits", dict(bucket_id=transfer["id"], target_actor="test-human", credits=7, reclaim=False))
        buckets = self.summary()["buckets"]
        self.assertEqual(sum(b["balance"] for b in buckets), 20)
        self.assertEqual(len({b["expires_at"] for b in buckets}), 1)
        self.assertEqual({b["kind"] for b in buckets}, {"check_in"})
        with self.assertRaises(Conflict): self.write("allocate_commerce_credits", dict(bucket_id=transfer["id"], target_actor=None, credits=6, reclaim=False))

    def test_original_job_submission_reserves_once_and_releases_native_zero(self):
        self.configure(); self.paid_order(); jobs = self.seed_jobs(2)
        self.write("configure_budget", dict(limits={"remote_jobs": 2, "images": 2}, reason="隔离原生预算"))
        self.write("update_generation_job", dict(job_id=jobs[0]["id"], status="submission_unknown"))
        self.assertEqual(self.summary()["credit_balance"], 90)
        self.assertEqual(self.service.budget_status(self.p)["used"], {"remote_jobs": 1, "images": 1})
        with self.assertRaises(Conflict) as caught: self.write("update_generation_job", dict(job_id=jobs[1]["id"], status="submission_unknown"))
        self.assertEqual(caught.exception.code, "commerce_concurrency_limit")
        self.assertEqual(self.service.get_generation_job(self.p,jobs[1]["id"])["status"], "created")
        self.write("update_generation_job", dict(job_id=jobs[0]["id"], status="failed", recovery_evidence={"human_confirmed_not_submitted":True}, actual_units={"remote_jobs":0,"images":0}))
        self.assertEqual(self.summary()["credit_balance"], 100)
        self.write("update_generation_job", dict(job_id=jobs[1]["id"], status="submission_unknown"))
        self.write("update_generation_job", dict(job_id=jobs[1]["id"], status="failed", recovery_evidence={"query":"confirmed failure; usage not supplied"}))
        self.assertEqual(self.summary()["credit_balance"], 90)
        self.assertEqual({r["status"] for r in self.summary()["reservations"]}, {"released", "settled"})

    def test_missing_approved_charge_rolls_back_original_budget(self):
        self.configure(); self.paid_order(); job = self.seed_jobs(charge=False)[0]
        with self.assertRaises(ResourceError) as caught: self.write("update_generation_job", dict(job_id=job["id"],status="submission_unknown"))
        self.assertEqual(caught.exception.code,"commerce_charge_required")
        self.assertEqual(self.service.budget_status(self.p)["used"], {})
        self.assertEqual(self.summary()["credit_balance"], 100)

    def test_refund_unknown_freezes_and_paid_poll_does_not_unfreeze(self):
        self.configure(); order = self.paid_order(); self.gateway.lose_refund = True
        self.write("refund_commerce_order", {"order_id":order["id"]})
        self.assertEqual(self.summary()["credit_balance"], 0)
        self.write("refund_commerce_order", {"order_id":order["id"]})
        self.assertEqual(self.gateway.refunds, 1)
        self.write("refresh_commerce_order", {"order_id":order["id"]})
        self.assertEqual(self.summary()["credit_balance"], 0)
        self.gateway.query_status = "refunded"
        self.write("refresh_commerce_order", {"order_id":order["id"]})
        self.assertEqual(self.summary()["orders"][0]["status"],"refunded")
        self.assertEqual(self.summary()["buckets"][0]["balance"],0)

    def test_explicit_refund_rejection_restores_existing_credit_only(self):
        self.configure(); order = self.paid_order(); self.gateway.lose_refund = True
        self.write("refund_commerce_order", {"order_id":order["id"]})
        self.gateway.query_status = "refund_rejected"
        self.write("refresh_commerce_order", {"order_id":order["id"]})
        self.assertEqual(self.summary()["credit_balance"],100)
        self.assertEqual(len(self.summary()["buckets"]),1)
        self.assertEqual(self.summary()["orders"][0]["status"],"paid")

    def test_purpose_restriction_and_latest_concurrency_limit(self):
        self.configure(purposes=["video_clip"], max_concurrent_jobs=2)
        self.paid_order(); jobs=self.seed_jobs(2)
        with self.assertRaises(Conflict) as caught:self.write("update_generation_job",dict(job_id=jobs[0]["id"],status="submission_unknown"))
        self.assertEqual(caught.exception.code,"credit_insufficient")
        self.assertEqual(self.service.budget_status(self.p)["used"],{})
        self.configure(purposes=["identity_ref"],max_concurrent_jobs=1)
        self.paid_order()
        self.write("update_generation_job",dict(job_id=jobs[0]["id"],status="submission_unknown"))
        with self.assertRaises(Conflict) as caught:self.write("update_generation_job",dict(job_id=jobs[1]["id"],status="submission_unknown"))
        self.assertEqual(caught.exception.code,"commerce_concurrency_limit")

    def test_used_order_refund_refused_and_manual_renewal_is_new_order(self):
        self.configure(); order = self.paid_order(); job = self.seed_jobs()[0]
        renewal = self.write("renew_commerce_order", {"order_id":order["id"]})
        self.assertNotEqual(renewal["id"],order["id"])
        self.assertEqual(renewal["renewal_of_order_id"],order["id"])
        self.write("update_generation_job",dict(job_id=job["id"],status="submission_unknown"))
        with self.assertRaises(Conflict): self.write("refund_commerce_order",{"order_id":order["id"]})
        self.assertEqual(self.gateway.refunds,0)

    def test_invoice_unconfigured_keeps_request_then_queries_lost_issue(self):
        self.configure(); order = self.paid_order()
        payload=dict(order_id=order["id"],title="合成抬头",tax_id="ISOLATED",email="isolated@example.invalid")
        invoice = self.write("request_commerce_invoice",payload)
        self.assertEqual(invoice["status"],"unconfigured")
        same = self.write("request_commerce_invoice",payload)
        self.assertEqual(same["id"],invoice["id"])
        with self.assertRaises(Conflict): self.write("request_commerce_invoice",dict(payload,title="其他抬头"))
        issuer = self.service.commerce_invoice_gateway = OfflineIssuer()
        self.write("refresh_commerce_invoice",{"invoice_id":invoice["id"]})
        self.assertEqual(self.summary()["invoices"][0]["status"],"submission_unknown")
        self.write("refresh_commerce_invoice",{"invoice_id":invoice["id"]})
        content, sha = self.service.commerce_invoice_content(self.p,invoice["id"],actor="test-human")
        self.assertTrue(content.startswith(b"%PDF-")); self.assertEqual(len(sha),64)
        self.assertEqual((issuer.issued,issuer.queried),(1,1))
        self.assertNotIn("document",self.summary()["invoices"][0])

    def test_workspace_transfer_reclaim_and_invoice_scope_use_original_ledgers(self):
        from vsc.assets.access_control import Principal,set_principal,reset_principal
        self.configure();order=self.paid_order()
        owner=self.service.ensure_local_access('test-human')
        token=set_principal(Principal(**owner));self.addCleanup(reset_principal,token)
        def command(action,payload):
            return self.service.access_command(action,payload,expected_revision=self.service.access_snapshot()['access_revision'],idempotency_key=uuid.uuid4().hex,actor='test-human')
        studio=command('workspace',{'name':'制作组织','parent_id':None})['workspace_id']
        child=command('workspace',{'name':'子工作室','parent_id':studio})['workspace_id']
        target=self.service.create_project({'name':'目标制作项目'},actor='test-human')['id']
        for project,workspace in ((self.p,studio),(target,child)):
            preview=self.service.access_migration_preview(project,workspace)
            command('assign-project',{'project_id':project,'workspace_id':workspace,'preview_sha256':preview['sha256']})
        self.rev=self.service.get_project(self.p)['revision']
        source=self.summary()['buckets'][0]
        request=dict(bucket_id=source['id'],target_project_id=target,target_revision=self.service.get_project(target)['revision'],credits=40)
        transferred=self.write('transfer_workspace_credits',request,idempotency_key='fixed-workspace-transfer')
        replay=self.service.transfer_workspace_credits(self.p,request,expected_revision=0,idempotency_key='fixed-workspace-transfer',actor='test-human')
        self.assertEqual(transferred,replay)
        self.assertEqual(self.summary()['credit_balance'],60)
        target_wallet=self.service.commerce_summary(target,actor='test-human')
        self.assertEqual(target_wallet['credit_balance'],40)
        self.assertEqual(target_wallet['buckets'][0]['expires_at'],source['expires_at'])
        with self.assertRaises(Conflict):self.write('refund_commerce_order',{'order_id':order['id']})
        reclaim=dict(bucket_id=transferred['target_bucket_id'],target_project_id=self.p,target_revision=self.rev,credits=40,reclaim_transfer_id=transferred['id'])
        result=self.service.transfer_workspace_credits(target,reclaim,expected_revision=target_wallet['revision'],idempotency_key='return-unused',actor='test-human')
        self.rev=result['target_revision']
        self.assertEqual(self.summary()['credit_balance'],100)
        self.assertEqual(self.service.commerce_summary(target,actor='test-human')['credit_balance'],0)
        self.assertEqual(len(self.summary()['workspace']['transfers']),2)
        payload=dict(order_id=order['id'],title='组织抬头',tax_id='TEST',email='test@example.invalid',workspace_id=child)
        with self.assertRaises(ResourceError):self.write('request_commerce_invoice',payload)
        invoice=self.write('request_commerce_invoice',dict(payload,workspace_id=studio))
        self.assertEqual(self.service._commerce().invoice(self.p,invoice['id'])['workspace_id'],studio)
        self.write('refund_commerce_order',{'order_id':order['id']})
        self.assertEqual(self.summary()['credit_balance'],0)

    def test_database_blocks_negative_balance_and_contract_mutation(self):
        from sqlalchemy import insert, update
        from sqlalchemy.exc import DBAPIError
        from vsc.adapters.persistence.postgres import schema as S
        self.configure(); self.paid_order(); bucket=self.summary()["buckets"][0]
        with self.assertRaises(DBAPIError):
            with self.engine.begin() as conn:
                conn.execute(update(S.commerce_plan_versions).where(S.commerce_plan_versions.c.id==self.plan).values(version=99))
        with self.assertRaises(DBAPIError):
            with self.engine.begin() as conn:
                conn.execute(insert(S.commerce_ledger).values(project_id=self.p,id=str(uuid.uuid4()),bucket_id=bucket["id"],delta=-101,kind="allocate_out",event_key="illegal-overdraft",actor="test"))
        self.assertEqual(self.summary()["credit_balance"],100)

    def test_http_private_finance_trusted_session_and_idempotent_campaign(self):
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        self.configure(); self.service.commerce_payment_gateway=self.gateway
        with tempfile.TemporaryDirectory() as directory:
            app=create_app(dict(projects_root=directory,allowed_hosts=["testserver"],allowed_origins=["http://testserver"],access_token="isolated-token",human_identity="test-human"),service=self.service)
            with TestClient(app) as client:
                url=f"/api/v1/projects/{self.p}/commerce"
                self.assertEqual(client.get(url).status_code,403)
                login=client.post("/api/v1/session",json={"token":"isolated-token"},headers={"Origin":"http://testserver"})
                self.assertEqual(login.status_code,200,login.text)
                headers={"X-CSRF-Token":login.json()["csrf_token"],"Origin":"http://testserver"}
                response=client.get(url,headers=headers);self.assertEqual(response.status_code,200,response.text)
                now=datetime.now(timezone.utc)
                payload=dict(code="http-isolated",title="HTTP隔离",credits=4,kind="bonus",purposes=["identity_ref"],starts_at=(now-timedelta(hours=1)).isoformat(),ends_at=(now+timedelta(hours=1)).isoformat(),credit_expires_at=(now+timedelta(days=1)).isoformat(),daily=False)
                body=dict(payload=payload,expected_revision=response.json()["revision"],idempotency_key="http-campaign")
                bad=client.post(url+"/campaigns",json=dict(body,actor="fake-owner"),headers=headers)
                self.assertEqual(bad.status_code,422)
                a=client.post(url+"/campaigns",json=body,headers=headers);b=client.post(url+"/campaigns",json=body,headers=headers)
                self.assertEqual(a.status_code,200,a.text);self.assertEqual(a.json(),b.json())
                self.assertEqual(client.get(url,headers={"X-CSRF-Token":headers["X-CSRF-Token"]}).status_code,200)
                order=client.post(url+"/orders",json=dict(payload={"plan_id":self.plan},expected_revision=a.json()["revision"],idempotency_key="http-order"),headers=headers)
                self.assertEqual(order.status_code,200,order.text);self.assertEqual(order.json()["status"],"pending")
                paid=client.post(url+"/orders/refresh",json=dict(payload={"order_id":order.json()["id"]},expected_revision=order.json()["revision"],idempotency_key="http-query"),headers=headers)
                self.assertEqual(paid.status_code,200,paid.text);self.assertEqual(paid.json()["status"],"paid")



    def test_verified_late_notification_settles_recycled_order_without_reopening_writes(self):
        import hashlib,hmac,json
        from dataclasses import asdict
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        from vsc.project.resource_catalog import ResourceCatalog
        from vsc.assets.commerce import is_verified_commerce_notification
        class SignedOfflinePayment(OfflinePayment):
            secret=b'isolated-late-order-signing-contract'
            def verify_notification(inner,headers,body):
                expected=hmac.new(inner.secret,body,hashlib.sha256).hexdigest()
                if not hmac.compare_digest(headers.get('x-isolated-signature',''),expected):raise ValueError('signature mismatch')
                return PaymentEvent(**json.loads(body))
        self.gateway=SignedOfflinePayment();self.service.commerce_payment_gateway=self.gateway
        self.configure();created=self.write('create_commerce_order',{'plan_id':self.plan})
        repo=self.service._commerce();order=repo.order(self.p,created['id'])
        recycled=self.write('management_command',dict(operation='trash',target_type='project',target_id=self.p,reason='isolated lifecycle test'))
        self.assertEqual(recycled['state'],'trashed')
        event=self.gateway.event(order,'paid','late-paid')
        def direct_blocked():
            with self.assertRaises(ResourceError) as caught:repo.payment_event(self.p,replace(event,event_id=uuid.uuid4().hex))
            self.assertEqual(caught.exception.code,'project_recycled')
            self.assertFalse(is_verified_commerce_notification(self.p,asdict(event)))
        direct_blocked()
        with tempfile.TemporaryDirectory() as root,TestClient(create_app({'allowed_hosts':['testserver'],'allowed_origins':['http://testserver'],'access_token':'private-only','human_identity':'test-human'},catalog=ResourceCatalog(root,self.service))) as client:
            route=f'/api/v1/commerce-notifications/{self.gateway.id}/{self.p}'
            def notify(value):
                raw=json.dumps(asdict(value),separators=(',',':')).encode()
                return client.post(route,content=raw,headers={'x-isolated-signature':hmac.new(self.gateway.secret,raw,hashlib.sha256).hexdigest()})
            response=notify(event);self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(notify(event).json(),response.json());self.assertEqual(self.summary()['credit_balance'],100)
            self.assertEqual(notify(replace(event,event_id='late-expired',status='expired')).json()['status'],'paid')
            self.assertEqual(notify(replace(event,event_id='wrong-amount',amount_minor=101)).status_code,422)
            self.assertEqual(notify(replace(event,event_id='unknown-order',order_id=str(uuid.uuid4()))).status_code,404)
            direct_blocked()
            self.rev=self.store.get_project(self.p)['revision']
            with self.assertRaises(ResourceError) as caught:self.write('create_commerce_order',{'plan_id':self.plan})
            self.assertEqual(caught.exception.code,'project_recycled')
            with self.assertRaises(ResourceError) as caught:self.write('create_object',{'kind':'work','display_code':'BLOCKED'})
            self.assertEqual(caught.exception.code,'project_recycled')
            self.assertEqual(client.post(f'/api/v1/projects/{self.p}/commerce/orders',json={'payload':{'plan_id':self.plan}}).status_code,403)
            purged=self.write('management_command',dict(operation='purge',target_type='project',target_id=self.p,confirm_name=self.project['name'],reason='retain only synthetic audit'))
            self.assertEqual(purged['state'],'purged')
            refund=notify(replace(event,event_id='late-refund',status='refunded'))
            self.assertEqual(refund.status_code,200,refund.text);self.assertEqual(refund.json()['status'],'refunded')
            self.assertEqual(notify(replace(event,event_id='paid-after-refund')).json()['status'],'refunded')
            direct_blocked()
        self.assertEqual(self.summary()['credit_balance'],0)
        self.assertEqual(self.service.management_snapshot(self.p)['state'],'purged')
        self.assertEqual(len(self.summary()['buckets']),1)

    def test_signed_notification_http_raw_body_scope_replay_and_limits(self):
        import hashlib,hmac,json
        from dataclasses import asdict
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        from vsc.project.resource_catalog import ResourceCatalog
        class SignedOfflinePayment(OfflinePayment):
            secret=b'isolated-synthetic-webhook-secret'
            def verify_notification(inner,headers,body):
                expected=hmac.new(inner.secret,body,hashlib.sha256).hexdigest()
                if not hmac.compare_digest(headers.get('x-isolated-signature',''),expected):raise ValueError('signature mismatch')
                return PaymentEvent(**json.loads(body))
        self.gateway=SignedOfflinePayment();self.service.commerce_payment_gateway=self.gateway
        self.configure();created=self.write('create_commerce_order',{'plan_id':self.plan});order=self.service._commerce().order(self.p,created['id'])
        event=self.gateway.event(order,'paid','http-fixed-paid');raw=json.dumps(asdict(event),ensure_ascii=False,separators=(',',':')).encode()
        def signed(body):return {'content-type':'application/json','x-isolated-signature':hmac.new(self.gateway.secret,body,hashlib.sha256).hexdigest()}
        with tempfile.TemporaryDirectory() as root,TestClient(create_app({'allowed_hosts':['testserver'],'allowed_origins':['http://testserver'],'access_token':'private-only','human_identity':'test-human'},catalog=ResourceCatalog(root,self.service))) as client:
            route=f'/api/v1/commerce-notifications/{self.gateway.id}/{self.p}'
            self.assertEqual(client.post(route,content=raw).status_code,401)
            response=client.post(route,content=raw,headers=signed(raw));self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.json()['status'],'paid')
            self.assertEqual(client.post(route,content=raw,headers=signed(raw)).json(),response.json())
            self.assertEqual(client.post(route,content=raw+b' ',headers=signed(raw)).status_code,401)
            late=json.dumps(asdict(replace(event,event_id='late-expired',status='expired'))).encode();self.assertEqual(client.post(route,content=late,headers=signed(late)).json()['status'],'paid')
            wrong=json.dumps(asdict(replace(event,event_id='wrong-amount',amount_minor=101))).encode();self.assertEqual(client.post(route,content=wrong,headers=signed(wrong)).status_code,422)
            other=self.service.create_project({'name':'callback wrong project'},actor='test-human')['id']
            self.assertEqual(client.post(route.replace(self.p,other),content=raw,headers=signed(raw)).status_code,404)
            self.assertEqual(client.post(route.replace(self.gateway.id,'other-gateway'),content=raw,headers=signed(raw)).status_code,404)
            large=b'x'*(128*1024+1);self.assertEqual(client.post(route,content=large,headers=signed(large)).status_code,413)
            self.assertEqual(client.post(f'/api/v1/projects/{self.p}/commerce/orders',json={'payload':{'plan_id':self.plan}},headers=signed(raw)).status_code,403)
            self.service.commerce_payment_gateway=None;self.assertEqual(client.post(route,content=raw,headers=signed(raw)).status_code,503)
        self.assertEqual(self.summary()['credit_balance'],100)

    def test_fixed_rate_members_match_complete_document_and_reject_late_changes(self):
        import json
        from sqlalchemy import insert,select,text,update,delete
        from sqlalchemy.exc import IntegrityError
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.adapters.persistence.postgres.values import digest
        plan=self.configure()
        with self.engine.connect() as conn:source=dict(conn.execute(select(S.commerce_plan_versions).where(S.commerce_plan_versions.c.project_id==self.p,S.commerce_plan_versions.c.id==plan['id'])).mappings().one())
        for members in ([],[dict(model_id=self.model,unit='images',credits_per_unit=11)],[dict(model_id=self.model,unit='video_seconds',credits_per_unit=10)]):
            with self.subTest(members=members),self.assertRaises(IntegrityError) as failure:
                with self.engine.begin() as conn:
                    identifier=str(uuid.uuid4());key=uuid.uuid4().hex;doc=dict(source['document'],plan_key=key)
                    conn.execute(insert(S.commerce_plan_versions).values(dict(source,id=identifier,plan_key=key,version=1,document=doc,sha256=digest(doc))))
                    for row in members:conn.execute(insert(S.commerce_rates).values(project_id=self.p,id=str(uuid.uuid4()),plan_id=identifier,**row))
            self.assertEqual(failure.exception.orig.sqlstate,'23514')
        with self.assertRaises(IntegrityError) as failure:
            with self.engine.begin() as conn:conn.execute(insert(S.commerce_rates).values(project_id=self.p,id=str(uuid.uuid4()),plan_id=plan['id'],model_id=self.model,unit='video_seconds',credits_per_unit=17))
        self.assertEqual(failure.exception.orig.sqlstate,'23514')
        # A complete parent+member transaction is legal; order of rates is immaterial.
        with self.engine.begin() as conn:
            identifier=str(uuid.uuid4());key=uuid.uuid4().hex
            doc=dict(source['document'],plan_key=key,rates=[dict(model_id=self.model,unit='images',credits_per_unit=10),dict(model_id=self.model,unit='video_seconds',credits_per_unit=17)])
            conn.execute(insert(S.commerce_plan_versions).values(dict(source,id=identifier,plan_key=key,version=1,document=doc,sha256=digest(doc))))
            for row in reversed(doc['rates']):conn.execute(insert(S.commerce_rates).values(project_id=self.p,id=str(uuid.uuid4()),plan_id=identifier,**row))
            conn.execute(text('SET CONSTRAINTS commerce_rates_sealed IMMEDIATE'))
        with self.engine.connect() as conn:
            self.assertEqual(self.service._commerce()._price(conn,self.p,plan['id'],self.model,{'images':2}),20)
            with self.assertRaises(ResourceError):self.service._commerce()._price(conn,self.p,plan['id'],self.model,{'video_seconds':1})
            self.assertEqual(dict(conn.execute(select(S.commerce_plan_versions).where(S.commerce_plan_versions.c.project_id==self.p,S.commerce_plan_versions.c.id==plan['id'])).mappings().one()),source)
        for statement in (update(S.commerce_rates).where(S.commerce_rates.c.plan_id==plan['id']).values(credits_per_unit=1),delete(S.commerce_rates).where(S.commerce_rates.c.plan_id==plan['id'])):
            with self.assertRaises(IntegrityError) as failure:
                with self.engine.begin() as conn:conn.execute(statement)
            self.assertEqual(failure.exception.orig.sqlstate,'23514')
        # Duplicate document rows cannot be collapsed to a set and accepted.
        with self.assertRaises(IntegrityError) as failure:
            with self.engine.begin() as conn:
                identifier=str(uuid.uuid4());key=uuid.uuid4().hex;doc=dict(source['document'],plan_key=key,rates=source['document']['rates']*2)
                conn.execute(insert(S.commerce_plan_versions).values(dict(source,id=identifier,plan_key=key,version=1,document=doc,sha256=digest(doc))))
                conn.execute(insert(S.commerce_rates).values(project_id=self.p,id=str(uuid.uuid4()),plan_id=identifier,**doc['rates'][0]))
        self.assertEqual(failure.exception.orig.sqlstate,'23514')

if __name__ == "__main__": unittest.main()
