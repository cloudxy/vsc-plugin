"""Zero-provider-POST quote, fixed approval, price drift and recorded-use recovery."""
import importlib.util
import json
import os
import unittest
import uuid
from unittest.mock import patch
from support.fixtures.trial_quality import TrialQualityFixture


@unittest.skipUnless(os.environ.get('VSC_TEST_DATABASE_URL') and importlib.util.find_spec('psycopg'),'requires configured isolated PostgreSQL')
class PostgresQuoteTest(TrialQualityFixture,unittest.TestCase):
    def model_price(self, price, *, expires_at=None):
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        with self.engine.connect() as conn:
            row=dict(conn.execute(select(S.provider_models).where(S.provider_models.c.id==self.model)).mappings().one())
        payload={key:row[key] for key in ('provider_id','model_key','model_version','modality','capabilities','default_params')}
        payload['model_version']='synthetic-quote-'+uuid.uuid4().hex
        payload['cost_rule']={} if price is None else {'unit':'video_seconds','unit_price':price,'currency':'CNY','basis':'cash',
            'source_url':'https://example.invalid/synthetic-price','source_date':'2026-01-01'}
        if expires_at:payload['cost_rule']['expires_at']=expires_at
        self.model=self.service.register_model(payload,actor='test-human')['id']

    def document(self):
        source,_,logical=self.fixture_run()
        document=json.loads(source['document']);document['jobs'][0]['model_id']=self.model
        return document,logical

    def quote(self,document):
        return self.service.preview_generation_quote(self.p,{'document':document})['generation_quote']

    def quoted_run(self,document):
        return self.approved('quoted-run','production-run',document,
            dependency_ids=[row['id'] for row in document['approved_inputs']])

    def test_quote_before_approval_is_read_only_fixed_and_reconciles_actual_units(self):
        self.model_price('0.25');document,logical=self.document();revision=self.store.get_project(self.p)['revision']
        with patch('httpx.Client.post') as remote_post:
            quote=self.quote(document);self.assertEqual(quote,self.quote(document));remote_post.assert_not_called()
        self.assertEqual(self.store.get_project(self.p)['revision'],revision)
        self.assertEqual(quote['known_subtotals'],{'CNY':'1.25'})
        document['generation_quote']=quote;document['quote_policy']={'max_native_delta':{'video_seconds':1}};run=self.quoted_run(document)
        self.write('configure_budget',{'limits':{'remote_jobs':2,'video_seconds':10},'reason':'Synthetic bounded quote test'})
        job=self.job(run,logical)
        self.write('update_generation_job',{'job_id':job['id'],'status':'submitted','external_task_id':'offline-quote'})
        failure={'job_id':job['id'],'status':'failed','actual_units':{'remote_jobs':1,'video_seconds':2}}
        first=self.write('update_generation_job',failure,idempotency_key='quote-settle-once')
        repeated=self.write('update_generation_job',failure,idempotency_key='quote-settle-once');self.assertEqual(first,repeated)
        status=self.service.budget_status(self.p);self.assertEqual(status['used']['video_seconds'],2)
        row=next(row for row in status['quote_reconciliation'] if row['job_id']==job['id'])
        self.assertEqual(row['native_delta']['video_seconds'],-3);self.assertIsNone(row['actual_amount']);self.assertTrue(row['actual_units_reported'])
        self.assertTrue(row['threshold_exceeded'])
        fixed=self.service.get_generation_quote_status(self.p,job['id'])
        self.assertEqual(fixed['quote']['amount'],'1.25');self.assertEqual(fixed['reconciliation']['native_delta']['video_seconds'],-3)

    def test_new_price_version_cannot_reuse_old_quote_and_old_model_stays_fixed(self):
        from vsc.assets.resource_service import ResourceError
        self.model_price('0.25');document,logical=self.document();document['generation_quote']=self.quote(document);run=self.quoted_run(document)
        original_model=self.model;self.model_price('0.5')
        with self.assertRaises(ResourceError) as error:self.job(run,logical)
        self.assertEqual(error.exception.code,'generation_quote_stale')
        self.model=original_model;job=self.job(run,logical)
        self.write('configure_budget',{'limits':{'remote_jobs':2,'video_seconds':10},'reason':'Synthetic quote guard'})
        self.write('update_generation_job',{'job_id':job['id'],'status':'submitted','external_task_id':'same-fixed-price'})
        self.assertEqual(self.service.get_generation_job(self.p,job['id'])['model_id'],original_model)

    def test_explicit_bill_is_project_scoped_immutable_idempotent_and_read_by_consumers(self):
        from vsc.assets.resource_service import ResourceError
        self.model_price('0.25');document,logical=self.document();document['generation_quote']=self.quote(document)
        job=self.job(self.quoted_run(document),logical)
        bill={'job_id':job['id'],'actual_cost':{'amount':'0.80','currency':'CNY','evidence':'Synthetic invoice fixture INV-1; not a real bill'}}
        with self.assertRaises(ResourceError):self.write('record_generation_bill',bill)
        self.write('configure_budget',{'limits':{'remote_jobs':2,'video_seconds':10},'reason':'Synthetic bill test'})
        self.write('update_generation_job',{'job_id':job['id'],'status':'submitted','external_task_id':'offline-bill'})
        with self.assertRaises(ResourceError) as rejected:
            self.write('update_generation_job',dict(bill,status='failed'))
        self.assertEqual(rejected.exception.code,'separate_bill_required')
        self.write('update_generation_job',{'job_id':job['id'],'status':'failed','actual_units':{'remote_jobs':1,'video_seconds':2}})
        for invalid in ({'amount':True,'currency':'CNY','evidence':'x'}, {'amount':'1','currency':'CNY','evidence':''}):
            with self.assertRaises(ResourceError):self.write('record_generation_bill',dict(bill,actual_cost=invalid))
        first=self.write('record_generation_bill',bill,idempotency_key='bill-once')
        self.assertEqual(first,self.write('record_generation_bill',bill,idempotency_key='bill-once'))
        with self.assertRaises(ResourceError):self.write('record_generation_bill',dict(bill,actual_cost=dict(bill['actual_cost'],amount='9')))
        actual=self.service.get_generation_quote_status(self.p,job['id'])['reconciliation']
        self.assertEqual((actual['actual_amount'],actual['amount_delta']),('0.80','-0.45'))
        self.assertEqual(self.service.budget_status(self.p)['quote_reconciliation'][0]['actual_amount'],'0.80')
        other=self.service.create_project({'name':'Synthetic other invoice','profile_snapshot':{'profile_id':'vsc.synthetic','version':'1','stages':[]}},actor='test-human')
        with self.assertRaises(ResourceError):self.service.record_generation_bill(other['id'],bill,actor='test-human',expected_revision=0,idempotency_key='cross-project')

    def test_expired_quote_before_submit_preserves_unsubmitted_intent_and_budget(self):
        from datetime import datetime,timezone
        from vsc.assets.resource_service import ResourceError
        self.model_price('0.25',expires_at='2100-01-01T00:00:00Z')
        document,logical=self.document();document['generation_quote']=self.quote(document);run=self.quoted_run(document)
        job=self.job(run,logical)
        self.write('configure_budget',{'limits':{'remote_jobs':2,'video_seconds':10},'reason':'Synthetic quote expiry'})
        class FutureDatetime(datetime):
            @classmethod
            def now(cls,tz=None):return datetime(2101,1,1,tzinfo=timezone.utc)
        with patch('vsc.production.quotes.datetime',FutureDatetime), self.assertRaises(ResourceError) as error:
            self.write('update_generation_job',{'job_id':job['id'],'status':'submitted','external_task_id':'never-submitted'})
        self.assertEqual(error.exception.code,'generation_quote_stale')
        self.assertEqual(self.service.get_generation_job(self.p,job['id'])['status'],'created')
        self.assertEqual(self.service.budget_status(self.p)['used'],{})

    def test_unknown_http_quote_and_invalid_scope_do_not_create_jobs(self):
        from vsc.interfaces.web.app import create_app
        from fastapi.testclient import TestClient
        self.model_price(None);document,_=self.document()
        client=TestClient(create_app({'projects_root':'/nonexistent','access_token':'synthetic-quote'},service=self.service),base_url='http://127.0.0.1',headers={'Origin':'http://127.0.0.1'})
        response=client.post(f'/api/v1/projects/{self.p}/generation-quote',json={'payload':{'document':document}})
        self.assertEqual(response.status_code,200,response.text)
        quote=response.json()['generation_quote'];self.assertFalse(quote['all_prices_known']);self.assertEqual(quote['unknown_jobs'],1)
        self.assertEqual(quote['known_subtotals'],{})
        other=self.service.create_project({'name':'Other synthetic quote','profile_snapshot':{'profile_id':'vsc.synthetic','version':'1','stages':[]}},actor='test-human')
        denied=client.post(f'/api/v1/projects/{other["id"]}/generation-quote',json={'payload':{'document':document}})
        self.assertEqual(denied.status_code,404,denied.text)
