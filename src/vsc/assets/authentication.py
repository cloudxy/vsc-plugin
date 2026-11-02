"""Authentication orchestration: no channel enabled without explicit configuration."""
import base64,hashlib,hmac,io,json,os,re,secrets
from datetime import datetime,timedelta,timezone
from vsc.adapters.providers.authentication import AuthenticationProvider


def failed(result):
    if result.get('error'):
        from vsc.assets.resource_service import ResourceError
        raise ResourceError(result['message'],result['error'],result.get('status',400))
    return result


def invalid(message,code='authentication_invalid',status=422):
    from vsc.assets.resource_service import ResourceError
    raise ResourceError(message,code,status)


class AuthenticationServiceMixin:
    def _authentication_settings(self):
        if hasattr(self,'authentication_settings'):return self.authentication_settings
        from vsc.configuration import get_settings
        value=get_settings().get('AUTHENTICATION',{})
        return value.to_dict() if hasattr(value,'to_dict') else dict(value)

    def _authentication_key(self,purpose='hmac'):
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
        settings=self._authentication_settings();raw=os.environ.get(settings.get('challenge_key_ref','AUTH_CHALLENGE_KEY'),'')
        if not settings.get('enabled') or len(raw.encode())<32:invalid('身份登录未启用或挑战密钥尚未加载。','authentication_disabled',503)
        return HKDF(algorithm=hashes.SHA256(),length=32,salt=b'vsc-authentication-v1',info=('challenge-'+purpose).encode()).derive(raw.encode())

    def _auth_hash(self,kind,value):return hmac.new(self._authentication_key(),(kind+'\0'+value).encode(),hashlib.sha256).hexdigest()
    def _auth_cipher(self):
        from cryptography.fernet import Fernet
        return Fernet(base64.urlsafe_b64encode(self._authentication_key('encryption')))
    def _auth_provider(self):return getattr(self,'authentication_provider',None) or AuthenticationProvider(self._authentication_settings())
    def _auth_purpose(self,purpose):
        from vsc.assets.access_control import current_principal
        if purpose not in ('login','bind'):invalid('请选择登录或明确绑定当前账号。')
        principal=current_principal()
        if purpose=='bind' and (not principal or not principal.identity_id):invalid('绑定登录方式需要当前成员会话。','authentication_binding_required',403)
        return principal.identity_id if purpose=='bind' else None

    def authentication_options(self):
        settings=self._authentication_settings();enabled=bool(settings.get('enabled'))
        try:self._authentication_key()
        except Exception:enabled=False
        channels=[]
        for key,label,required in [('email','邮箱',('host','from_address')),('sms','手机',('account_sid','api_key_sid','from_number','api_key_secret_ref'))]:
            row=settings.get(key,{})
            ready=enabled and bool(row.get('enabled')) and all(row.get(field) for field in required)
            if key=='email' and row.get('username'):ready=ready and bool(os.environ.get(row.get('password_ref','')))
            if key=='sms':ready=ready and bool(os.environ.get(row.get('api_key_secret_ref','')))
            channels.append({'id':key,'label':label,'enabled':bool(ready),'reason':None if ready else '此登录方式尚未配置或启用'})
        providers=[]
        for key,row in settings.get('oidc',{}).get('providers',{}).items():
            ready=enabled and row.get('enabled') and all(row.get(v) for v in ('issuer','client_id','client_secret_ref','redirect_uri')) and bool(os.environ.get(row.get('client_secret_ref','')))
            providers.append({'id':key,'label':row.get('label') or ('Google' if key=='google' else key),'enabled':bool(ready),'reason':None if ready else '第三方登录尚未配置或启用'})
        if not providers:providers=[{'id':'google','label':'Google','enabled':False,'reason':'第三方登录尚未配置或启用'}]
        return {'enabled':enabled,'channels':channels,'providers':providers}

    def authentication_bindings(self):
        rows=failed(self.store.authentication_bindings())['items'];providers=self._authentication_settings().get('oidc',{}).get('providers',{})
        result=[]
        for row in rows:
            subject=row['subject'];issuer=row['issuer']
            if issuer=='urn:vsc:email':label='邮箱';display=subject[:2]+'***'+subject[subject.index('@'):]
            elif issuer=='urn:vsc:sms':label='手机';display=subject[:3]+'***'+subject[-4:]
            else:label=next((value.get('label') or ('Google' if key=='google' else key) for key,value in providers.items() if value.get('issuer')==issuer),'第三方身份');display='已验证并绑定'
            result.append({'label':label,'subject_label':display,'created_at':row['created_at'].isoformat()})
        return {'items':result}

    def authentication_graphic(self,browser):
        from PIL import Image,ImageDraw,ImageFont
        identifier=str(__import__('uuid').uuid4());answer=''.join(secrets.choice('23456789ABCDEFGHJKLMNPQRSTUVWXYZ') for _ in range(5));expires=datetime.now(timezone.utc)+timedelta(minutes=5)
        failed(self.store.authentication_graphic(dict(id=identifier,browser_sha256=self._auth_hash('browser',browser),answer_sha256=self._auth_hash('graphic',identifier+':'+answer),expires_at=expires)))
        image=Image.new('RGB',(210,72),'#f2f4f7');draw=ImageDraw.Draw(image)
        for _ in range(16):draw.line((secrets.randbelow(210),secrets.randbelow(72),secrets.randbelow(210),secrets.randbelow(72)),fill='#b1b9c5',width=1)
        font=ImageFont.load_default(size=34)
        for index,char in enumerate(answer):draw.text((12+index*38,12+secrets.randbelow(10)),char,font=font,fill='#23334b')
        output=io.BytesIO();image.save(output,format='PNG')
        return {'id':str(__import__('uuid').UUID(identifier)),'image_base64':base64.b64encode(output.getvalue()).decode(),'expires_at':expires.isoformat()}

    def _auth_recipient(self,channel,value):
        if not isinstance(value,str):invalid('请输入手机号或邮箱。')
        value=value.strip()
        if channel=='email':
            # Accept one dot-atom mailbox, never an RFC header/address list.
            if len(value)>254 or not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+",value):invalid('请输入有效的单个邮箱地址。')
            local,domain=value.rsplit('@',1)
            if local.startswith('.') or local.endswith('.') or '..' in local:invalid('请输入有效的单个邮箱地址。')
            return local+'@'+domain.lower()
        if channel=='sms' and re.fullmatch(r'\+[1-9][0-9]{7,14}',value):return value
        invalid('手机号请包含国家区号，例如 +86。')

    def _auth_public_otp(self,row):
        status=row['send_state'];status='unknown' if status=='sending' else status
        return {'id':row['id'],'channel':row['channel'],'recipient_label':row['recipient_label'],'send_state':status,'expires_at':row['expires_at'].isoformat(),'attempts_remaining':max(0,5-row.get('attempts',0)),'consumed':bool(row.get('consumed_at')),'message':{'sent':'验证码发送请求已受理，请查看收件箱或短信。','failed':'发送被拒绝，请核对后重新开始。','unknown':'发送回执未知。若已收到验证码，请继续验证；不会自动重复发送。'}[status]}

    def authentication_send_otp(self,browser,payload):
        if not isinstance(payload,dict) or set(payload)!={'channel','recipient','graphic_id','graphic_answer','purpose','request_key'}:invalid('验证码请求字段不完整。')
        channel=payload['channel'];options=self.authentication_options()
        if not any(r['id']==channel and r['enabled'] for r in options['channels']):invalid('此验证码通道尚未配置或启用。','authentication_channel_disabled',503)
        subject=self._auth_recipient(channel,payload['recipient']);bind=self._auth_purpose(payload['purpose'])
        if not isinstance(payload['request_key'],str) or not 8<=len(payload['request_key'])<=100:invalid('请固定本次发码请求标识。')
        if not isinstance(payload['graphic_answer'],str) or len(payload['graphic_answer'])>20:invalid('图形答案无效。')
        from uuid import uuid4,UUID
        try:graphic=str(UUID(payload['graphic_id']))
        except (ValueError,TypeError,AttributeError):invalid('图形挑战标识无效。')
        identifier=str(uuid4());code=f'{secrets.randbelow(1000000):06d}';expires=datetime.now(timezone.utc)+timedelta(minutes=5)
        request_hash=self._auth_hash('request',json.dumps({**payload,'recipient':subject,'bind_identity_id':bind},sort_keys=True))
        label=(subject[:2]+'***'+subject[subject.index('@'):] if channel=='email' else subject[:3]+'***'+subject[-4:])
        result=failed(self.store.authentication_prepare_otp(dict(id=identifier,graphic_id=graphic,browser_sha256=self._auth_hash('browser',browser),channel=channel,purpose=payload['purpose'],bind_identity_id=bind,recipient_sha256=self._auth_hash('recipient',channel+':'+subject),recipient_ciphertext=self._auth_cipher().encrypt(subject.encode()),recipient_label=label,code_sha256=self._auth_hash('otp',identifier+':'+code),request_key=payload['request_key'],request_sha256=request_hash,send_state='sending',expires_at=expires),self._auth_hash('graphic',graphic+':'+payload['graphic_answer'].strip().upper())))
        if result['send']:
            try:delivery=self._auth_provider().deliver(channel,subject,code)
            except Exception as exc:
                code=getattr(exc,'code','delivery_receipt_unknown')
                delivery={'state':'failed' if code in {'authentication_credentials_missing','authentication_provider_invalid','authentication_tls_required'} else 'unknown','code':code}
            self.store.authentication_record_delivery(identifier,delivery['state'],delivery.get('receipt'),delivery.get('code'))
        return self.authentication_otp_status(browser,result['row']['id'])

    def authentication_otp_status(self,browser,identifier):return self._auth_public_otp(failed(self.store.authentication_read_otp(identifier,self._auth_hash('browser',browser)))['row'])
    def authentication_verify_otp(self,browser,identifier,code):
        if not isinstance(code,str) or not re.fullmatch(r'[0-9]{6}',code):invalid('请输入六位验证码。')
        row=failed(self.store.authentication_read_otp(identifier,self._auth_hash('browser',browser)))['row']
        subject=self._auth_cipher().decrypt(bytes(row['recipient_ciphertext'])).decode()
        return failed(self.store.authentication_verify_otp(identifier,self._auth_hash('browser',browser),self._auth_hash('otp',str(row['id'])+':'+code),subject))

    def _auth_oidc_settings(self,provider):
        if not any(r['id']==provider and r['enabled'] for r in self.authentication_options()['providers']):invalid('第三方登录尚未配置或启用。','authentication_provider_disabled',503)
        return self._authentication_settings()['oidc']['providers'][provider]
    def authentication_start_oidc(self,browser,provider,purpose):
        from uuid import uuid4
        settings=self._auth_oidc_settings(provider);bind=self._auth_purpose(purpose);state=secrets.token_urlsafe(32);nonce=secrets.token_urlsafe(32);verifier=secrets.token_urlsafe(48);identifier=str(uuid4())
        failed(self.store.authentication_start_oidc(dict(id=identifier,browser_sha256=self._auth_hash('browser',browser),provider_key=provider,issuer=settings['issuer'],redirect_uri=settings['redirect_uri'],configuration_sha256=self._auth_hash('oidc-config',json.dumps(settings,sort_keys=True)),purpose=purpose,bind_identity_id=bind,state_sha256=self._auth_hash('state',state),secrets_ciphertext=self._auth_cipher().encrypt(json.dumps({'nonce':nonce,'verifier':verifier}).encode()),status='pending',expires_at=datetime.now(timezone.utc)+timedelta(minutes=10))))
        try:url=self._auth_provider().authorization_url(settings,state,nonce,verifier)
        except Exception:
            self.store.authentication_finish_oidc(identifier,code='oidc_authorization_unavailable')
            invalid('第三方登录入口暂不可读取，请稍后重试。','authentication_provider_unavailable',503)
        return {'id':identifier,'authorization_url':url}
    def authentication_oidc_callback(self,browser,provider,state,code,denied=False):
        settings=self._auth_oidc_settings(provider)
        if not isinstance(state,str) or not 20<=len(state)<=200:invalid('第三方状态无效。','authentication_state_invalid',403)
        row=failed(self.store.authentication_claim_oidc(provider,self._auth_hash('state',state),self._auth_hash('browser',browser),self._auth_hash('oidc-config',json.dumps(settings,sort_keys=True))))['row']
        if denied or not isinstance(code,str) or not 1<=len(code)<=4096:
            self.store.authentication_finish_oidc(row['id'],code='provider_denied');return {'id':row['id'],'status':'failed'}
        values=json.loads(self._auth_cipher().decrypt(bytes(row['secrets_ciphertext'])))
        try:
            subject=self._auth_provider().exchange(settings,code,values['nonce'],values['verifier'])
            self.store.authentication_finish_oidc(row['id'],subject=subject);return {'id':row['id'],'status':'verified'}
        except Exception:
            # Authorization code POST is never repeated, including after a lost response.
            self.store.authentication_finish_oidc(row['id'],status='unknown',code='oidc_exchange_or_validation_failed');return {'id':row['id'],'status':'unknown'}
    def authentication_complete_oidc(self,browser,identifier):return failed(self.store.authentication_complete_oidc(identifier,self._auth_hash('browser',browser)))
