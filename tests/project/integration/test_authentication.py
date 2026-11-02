"""Isolated PG and original HTTP sessions with local transport mocks only."""
import io,json,os,re,tempfile,time,unittest,uuid
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
from urllib.parse import urlparse,parse_qs
import support.paths
from support.fixtures.resource_store import ResourceStoreFixture,HAS_DB_DEPS,TEST_URL
from vsc.adapters.persistence.postgres import schema as S
from sqlalchemy import select,update,insert
from sqlalchemy.exc import IntegrityError
from fastapi.testclient import TestClient


@unittest.skipUnless(HAS_DB_DEPS and TEST_URL,'requires isolated PostgreSQL')
class AuthenticationTests(ResourceStoreFixture,unittest.TestCase):
    def setUp(self):
        super().setUp();self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        env=patch.dict(os.environ,{'VSC_TEST_AUTH_KEY':'a'*48,'VSC_TEST_SMTP_SECRET':'smtp-isolated','VSC_TEST_SMS_SECRET':'sms-isolated','VSC_TEST_OIDC_SECRET':'oidc-isolated'});env.start();self.addCleanup(env.stop)
        self.service.authentication_settings={'enabled':True,'challenge_key_ref':'VSC_TEST_AUTH_KEY','email':{'enabled':True,'host':'smtp.example.invalid','port':465,'tls':'implicit','username':'synthetic','password_ref':'VSC_TEST_SMTP_SECRET','from_address':'vsc@example.invalid'},'sms':{'enabled':True,'account_sid':'ACsynthetic','api_key_sid':'SKsynthetic','api_key_secret_ref':'VSC_TEST_SMS_SECRET','from_number':'+15550001000'},'oidc':{'providers':{'google':{'enabled':True,'issuer':'https://issuer.example.invalid','client_id':'synthetic-client','client_secret_ref':'VSC_TEST_OIDC_SECRET','redirect_uri':'https://testserver/api/v1/authentication/oidc/google/callback'}}}}
        from vsc.interfaces.web.app import create_app
        self.app=create_app({'projects_root':self.temp.name,'allowed_hosts':['testserver'],'allowed_origins':['https://testserver'],'access_token':'local-secret','human_identity':'test-human','background_enabled':False},service=self.service)
        self.sent=[];self.send_unknown=False
        smtp=patch('vsc.adapters.providers.authentication.smtplib.SMTP_SSL');self.smtp=smtp.start();self.addCleanup(smtp.stop)
        def send(message):
            self.sent.append(message)
            if self.send_unknown:raise TimeoutError('synthetic lost DATA response')
            return {}
        self.smtp.return_value.send_message.side_effect=send
        choices=patch('vsc.assets.authentication.secrets.choice',return_value='A');choices.start();self.addCleanup(choices.stop)
    def client(self):
        client=TestClient(self.app,base_url='https://testserver');self.addCleanup(client.close);response=client.get('/api/v1/authentication/options');self.assertEqual(response.status_code,200,response.text);return client
    def headers(self,client):
        result={'Origin':'https://testserver'};session=client.get('/api/v1/session').json()
        if session.get('csrf_token'):result['X-CSRF-Token']=session['csrf_token']
        return result
    def post(self,client,path,payload):return client.post('/api/v1/authentication/'+path,json=payload,headers=self.headers(client))
    def graphic(self,client):
        row=self.post(client,'graphic',{});self.assertEqual(row.status_code,200,row.text)
        from PIL import Image
        import base64
        self.assertEqual(Image.open(io.BytesIO(base64.b64decode(row.json()['image_base64']))).size,(210,72));return row.json()
    def otp(self,client,recipient=None,purpose='login',channel='email'):
        payload=dict(channel=channel,recipient=recipient or uuid.uuid4().hex+'@example.invalid',graphic_id=self.graphic(client)['id'],graphic_answer='AAAAA',purpose=purpose,request_key=uuid.uuid4().hex)
        response=self.post(client,'otp',payload);self.assertEqual(response.status_code,200,response.text);return response.json(),payload
    def code(self):return re.search(r'\b[0-9]{6}\b',self.sent[-1].get_content()).group()
    def verify(self,client,row,code=None):return self.post(client,'otp/'+row['id']+'/verify',{'code':code or self.code()})
    def row(self,table,identifier):
        with self.engine.connect() as conn:return dict(conn.execute(select(table).where(table.c.id==identifier)).mappings().one())

    def test_email_http_login_logout_uses_original_identity_personal_workspace_and_no_project_grants(self):
        client=self.client();row,_=self.otp(client);response=self.verify(client,row);self.assertEqual(response.status_code,200,response.text);identity=response.json()['identity_id']
        current=client.get('/api/v1/session').json();self.assertEqual(current['identity_id'],identity)
        snapshot=client.get('/api/v1/access').json();self.assertEqual(snapshot['identity']['id'],identity);self.assertEqual(snapshot['workspaces'][0]['kind'],'personal');self.assertEqual(client.get('/api/v1/projects').json()['items'],[])
        self.assertEqual(self.verify(client,row).status_code,409)
        with self.engine.connect() as conn:
            binding=conn.execute(select(S.auth_subject_bindings).where(S.auth_subject_bindings.c.identity_id==identity)).mappings().one();self.assertEqual(binding['issuer'],'urn:vsc:email')
            self.assertFalse(conn.execute(select(S.access_project_members).where(S.access_project_members.c.identity_id==identity)).first())
        self.assertEqual(client.post('/api/v1/session/logout',json={},headers=self.headers(client)).status_code,200)
        self.assertIsNone(client.get('/api/v1/session').json()['actor']);self.assertEqual(self.smtp.return_value.send_message.call_count,1)

    def test_challenge_failures_commit_attempts_expire_bind_browser_limit_and_seal_inputs(self):
        client=self.client();graphic=self.graphic(client);payload=dict(channel='email',recipient='wrong@example.invalid',graphic_id=graphic['id'],graphic_answer='WRONG',purpose='login',request_key=uuid.uuid4().hex)
        for _ in range(5):self.assertEqual(self.post(client,'otp',payload).status_code,400)
        self.assertEqual(self.row(S.auth_graphic_challenges,graphic['id'])['attempts'],5);payload['graphic_answer']='AAAAA';self.assertEqual(self.post(client,'otp',payload).status_code,429)
        fresh=self.client();row,payload=self.otp(fresh);code=self.code();other=self.client();self.assertEqual(self.verify(other,row,code).status_code,403);self.assertEqual(self.row(S.auth_otp_challenges,row['id'])['attempts'],0)
        wrong='000000' if code!='000000' else '111111'
        for _ in range(5):self.assertEqual(self.verify(fresh,row,wrong).status_code,400)
        self.assertEqual(self.verify(fresh,row,code).status_code,429);self.assertEqual(self.row(S.auth_otp_challenges,row['id'])['attempts'],5)
        with self.assertRaises(IntegrityError) as caught:
            with self.engine.begin() as conn:conn.execute(update(S.auth_otp_challenges).where(S.auth_otp_challenges.c.id==row['id']).values(code_sha256='0'*64))
        self.assertEqual(caught.exception.orig.sqlstate,'23514')
        # Original row quotas prevent a new request from bypassing per-recipient limits.
        another=self.client();new=dict(payload,graphic_id=self.graphic(another)['id'],request_key=uuid.uuid4().hex);self.assertEqual(self.post(another,'otp',new).status_code,429)
        expired=self.client();row,_=self.otp(expired)
        with patch('vsc.adapters.persistence.postgres.authentication.now',return_value=datetime.now(timezone.utc)+timedelta(minutes=6)):self.assertEqual(self.verify(expired,row).status_code,400)

    def test_unknown_smtp_delivery_recovers_original_request_without_second_send(self):
        self.send_unknown=True;client=self.client();row,payload=self.otp(client);code=self.code();self.assertEqual(row['send_state'],'unknown')
        again=self.post(client,'otp',payload);self.assertEqual(again.status_code,200,again.text);self.assertEqual(again.json()['id'],row['id']);self.assertEqual(self.smtp.return_value.send_message.call_count,1)
        self.assertEqual(client.get('/api/v1/authentication/otp/'+row['id']).json()['send_state'],'unknown');self.assertEqual(self.verify(client,row,code).status_code,200)

    def test_sms_adapter_consumes_twilio_receipt_and_disabled_channels_do_not_send(self):
        import httpx
        sent=[]
        def send(url,**kw):sent.append((url,kw));return httpx.Response(201,json={'sid':'SMsynthetic','status':'queued'},request=httpx.Request('POST',url))
        client=self.client()
        with patch('httpx.post',side_effect=send):row,payload=self.otp(client,'+15550002000',channel='sms')
        self.assertEqual(sent[0][0],'https://api.twilio.com/2010-04-01/Accounts/ACsynthetic/Messages.json');self.assertEqual(sent[0][1]['auth'],('SKsynthetic','sms-isolated'))
        code=re.search(r'[0-9]{6}',sent[0][1]['data']['Body']).group();self.assertEqual(self.verify(client,row,code).status_code,200)
        self.service.authentication_settings['enabled']=False
        self.assertFalse(client.get('/api/v1/authentication/options').json()['enabled']);self.assertEqual(self.post(client,'graphic',{}).status_code,503)

    def test_explicit_binding_uses_csrf_and_refuses_other_identity_merge(self):
        a=self.client();first,_=self.otp(a,'account-a@example.invalid');self.assertEqual(self.verify(a,first).status_code,200);a_id=a.get('/api/v1/session').json()['identity_id']
        b=self.client();second,_=self.otp(b,'account-b@example.invalid');self.assertEqual(self.verify(b,second).status_code,200);b_id=b.get('/api/v1/session').json()['identity_id']
        with patch('vsc.adapters.persistence.postgres.authentication.now',return_value=datetime.now(timezone.utc)+timedelta(seconds=61)):
            graphic=self.graphic(b);payload=dict(channel='email',recipient='account-a@example.invalid',graphic_id=graphic['id'],graphic_answer='AAAAA',purpose='bind',request_key=uuid.uuid4().hex)
            denied=b.post('/api/v1/authentication/otp',json=payload,headers={'Origin':'https://testserver'});self.assertEqual(denied.status_code,403)
            row=self.post(b,'otp',payload);self.assertEqual(row.status_code,200,row.text);response=self.verify(b,row.json());self.assertEqual(response.status_code,409,response.text)
            bound,_=self.otp(b,'new-binding@example.invalid',purpose='bind');response=self.verify(b,bound);self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.json()['identity_id'],b_id)
        with self.engine.connect() as conn:
            rows=conn.execute(select(S.auth_subject_bindings).where(S.auth_subject_bindings.c.subject.in_(['account-a@example.invalid','new-binding@example.invalid']))).mappings().all();self.assertEqual({r['subject']:r['identity_id'] for r in rows},{'account-a@example.invalid':a_id,'new-binding@example.invalid':b_id})
        with self.assertRaises(IntegrityError) as caught:
            with self.engine.begin() as conn:conn.execute(update(S.auth_subject_bindings).where(S.auth_subject_bindings.c.subject=='account-a@example.invalid').values(identity_id=b_id))
        self.assertEqual(caught.exception.orig.sqlstate,'23514')
        proof=self.row(S.auth_otp_challenges,bound['id'])
        with self.engine.connect() as conn:a_binding=conn.execute(select(S.auth_subject_bindings.c.id).where(S.auth_subject_bindings.c.identity_id==a_id)).scalar_one()
        mismatched=dict(proof,id=str(uuid.uuid4()),request_key=uuid.uuid4().hex,graphic_id=self.graphic(b)['id'],subject_binding_id=a_binding)
        with self.assertRaises(IntegrityError) as caught:
            with self.engine.begin() as conn:conn.execute(insert(S.auth_otp_challenges).values(**mismatched))
        self.assertEqual(caught.exception.orig.sqlstate,'23503')
        cross_browser=dict(proof,id=str(uuid.uuid4()),request_key=uuid.uuid4().hex,graphic_id=self.graphic(a)['id'])
        with self.assertRaises(IntegrityError) as caught:
            with self.engine.begin() as conn:conn.execute(insert(S.auth_otp_challenges).values(**cross_browser))
        self.assertEqual(caught.exception.orig.sqlstate,'23503')


    def test_signed_oidc_http_pkce_nonce_claims_state_single_exchange_and_completion(self):
        import httpx
        from authlib.jose import JsonWebKey,JsonWebToken
        from authlib.integrations.httpx_client import OAuth2Client
        key=JsonWebKey.generate_key('RSA',2048,is_private=True);key2=JsonWebKey.generate_key('RSA',2048,is_private=True);public=key.as_dict(is_private=False);public['kid']='one'
        state={'nonce':None,'challenge':None,'posts':0,'case':'ok'}
        metadata={'issuer':'https://issuer.example.invalid','authorization_endpoint':'https://issuer.example.invalid/authorize','token_endpoint':'https://issuer.example.invalid/token','jwks_uri':'https://issuer.example.invalid/jwks','code_challenge_methods_supported':['S256']}
        def get(url,**kw):return httpx.Response(200,json={'keys':[public]} if url.endswith('/jwks') else metadata,request=httpx.Request('GET',url))
        def token(request):
            state['posts']+=1;params=parse_qs(request.content.decode());self.assertEqual(params['grant_type'],['authorization_code']);verifier=params['code_verifier'][0]
            import hashlib,base64
            self.assertEqual(base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('='),state['challenge'])
            if state['case']=='unknown':raise httpx.ReadTimeout('synthetic unknown token exchange',request=request)
            claims={'iss':metadata['issuer'],'aud':'synthetic-client','sub':'subject-123','iat':int(time.time()),'exp':int(time.time())+300,'nonce':state['nonce']}
            if state['case']=='issuer':claims['iss']='https://other.example.invalid'
            if state['case']=='audience':claims['aud']='wrong-client'
            if state['case']=='expired':claims['exp']=int(time.time())-1
            if state['case']=='nonce':claims['nonce']='wrong'
            signed=JsonWebToken(['RS256']).encode({'alg':'RS256','kid':'one'},claims,key2 if state['case']=='signature' else key).decode()
            return httpx.Response(200,json={'access_token':'synthetic-token','token_type':'Bearer','id_token':signed})
        transport=httpx.MockTransport(token)
        def oauth(*args,**kw):return OAuth2Client(*args,**kw,transport=transport)
        with patch('httpx.get',side_effect=get),patch('authlib.integrations.httpx_client.OAuth2Client',side_effect=oauth):
            client=self.client()
            for scenario in ('issuer','audience','expired','nonce','signature','unknown','ok'):
                state['case']=scenario;start=self.post(client,'oidc/google/start',{'purpose':'login'});self.assertEqual(start.status_code,200,start.text);q=parse_qs(urlparse(start.json()['authorization_url']).query);state['nonce']=q['nonce'][0];state['challenge']=q['code_challenge'][0];self.assertEqual(q['code_challenge_method'],['S256'])
                callback='/api/v1/authentication/oidc/google/callback?'+__import__('urllib.parse',fromlist=['urlencode']).urlencode({'state':q['state'][0],'code':'synthetic-code'})
                if scenario=='ok':
                    other=self.client();self.assertEqual(other.get(callback,follow_redirects=False).status_code,403)
                response=client.get(callback,follow_redirects=False);self.assertEqual(response.status_code,303,response.text);before=state['posts'];self.assertEqual(client.get(callback,follow_redirects=False).status_code,409);self.assertEqual(state['posts'],before)
                result=self.post(client,'oidc/'+start.json()['id']+'/complete',{})
                self.assertEqual(result.status_code,200 if scenario=='ok' else 409,result.text)
                if scenario=='ok':self.assertEqual(self.post(client,'oidc/'+start.json()['id']+'/complete',{}).status_code,409)
            self.assertEqual(state['posts'],7)
