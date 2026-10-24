"""Prices are explicit dated estimates; recorded use and invoices stay separate."""
from datetime import datetime, timezone
import unittest
from vsc.production.quotes import quote_request, reconcile_quote, quote_errors, fingerprint


class QuoteTest(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,10,24,tzinfo=timezone.utc)
        self.model={'id':'fixture','provider_id':'offline','model_key':'fixture-video','model_version':'1',
            'capabilities':{},'default_params':{},'cost_rule':{'unit':'video_seconds','unit_price':'0.25','currency':'CNY',
                'basis':'cash','source_url':'https://example.invalid/synthetic-price','source_date':'2026-10-01'}}
        self.request={'modality':'video','duration_ms':5000,'params':{},'context_sha256':'a'*64}

    def quote(self):
        return quote_request(self.model,self.request,{'remote_jobs':1,'video_seconds':5},now=self.now)

    def test_fixed_request_source_price_and_unknown_are_distinct(self):
        first=self.quote();self.assertEqual(first['amount'],'1.25');self.assertEqual(first,self.quote())
        self.request['params']['resolution']='720p';self.assertNotEqual(first['quote_sha256'],self.quote()['quote_sha256'])
        self.model['cost_rule']={};unknown=self.quote();self.assertIsNone(unknown['amount']);self.assertEqual(unknown['status'],'unknown')
        self.assertEqual(unknown['native_units']['video_seconds'],5)

    def test_source_expiry_subscription_and_request_conditions_do_not_become_cash_zero(self):
        for update in ({'source_date':False},{'unit_price':True},{'unit_price':'NaN'},
                       {'expires_at':'2026-10-01T00:00:00Z'},{'basis':'subscription'},
                       {'conditions':{'params':{'resolution':'1080p'}}}):
            with self.subTest(update=update):
                old=dict(self.model['cost_rule']);self.model['cost_rule'].update(update)
                self.assertEqual(self.quote()['status'],'unknown');self.assertIsNone(self.quote()['amount'])
                self.model['cost_rule']=old

    def test_materialized_input_details_do_not_change_the_fixed_logical_quote(self):
        first=self.quote();self.request.update(input_media=[{'id':'fixture'}],input_versions=[],voice_binding={})
        self.assertEqual(first,self.quote())

    def test_actual_native_usage_is_not_a_fabricated_bill(self):
        value=reconcile_quote(self.quote(),{'video_seconds':3})
        self.assertEqual(value['native_delta'],{'video_seconds':-2});self.assertIsNone(value['actual_amount'])
        self.assertIsNone(value['threshold_exceeded'])
        self.assertIsNone(reconcile_quote(self.quote(),{},policy={'max_native_delta':{'video_seconds':1}})['threshold_exceeded'])
        checked=reconcile_quote(self.quote(),{'video_seconds':3},policy={'max_native_delta':{'video_seconds':1}},
            actual_cost={'amount':'0.80','currency':'CNY','evidence':'synthetic offline invoice'})
        self.assertEqual(checked['amount_delta'],'-0.45');self.assertTrue(checked['threshold_exceeded'])

    def test_forged_unknown_amount_and_totals_cannot_be_approved(self):
        row=dict(self.quote(),operation='synthetic-one')
        document={'format':'vsc.generation-quote/v1','jobs':[row],'native_units':row['native_units'],
                  'all_prices_known':True,'known_subtotals':{'CNY':'1.25'},'unknown_jobs':0}
        document['quote_sha256']=fingerprint(document)
        self.assertEqual(quote_errors(document),[])
        document['known_subtotals']['CNY']='0'
        document['quote_sha256']=fingerprint({key:value for key,value in document.items() if key!='quote_sha256'})
        self.assertTrue(quote_errors(document))
