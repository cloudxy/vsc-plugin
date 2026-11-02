"""Explicitly configured TLS delivery and Authlib authorization-code OIDC."""
import os
import smtplib
import ssl
from email.message import EmailMessage
from urllib.parse import urlparse


def secret(reference):
    from vsc.assets.resource_service import ResourceError
    value=os.environ.get(reference or '')
    if not value:raise ResourceError('身份适配器凭据未加载，请核对所配置的环境变量引用。','authentication_credentials_missing',503)
    return value


def https_url(value):
    from vsc.assets.resource_service import ResourceError
    parsed=urlparse(value)
    if parsed.scheme!='https' or not parsed.netloc or parsed.username or parsed.password or parsed.fragment:
        raise ResourceError('身份提供方地址必须是无凭据的 HTTPS URL。','authentication_provider_invalid',503)
    return value


class AuthenticationProvider:
    def __init__(self, settings):self.settings=settings

    def deliver(self, channel, recipient, code):
        import httpx
        from vsc.assets.resource_service import ResourceError
        settings=self.settings[channel]
        try:
            if channel=='email':
                message=EmailMessage();message['Subject']='VSC 登录验证码';message['From']=settings['from_address'];message['To']=recipient
                message.set_content('你的 VSC 验证码：'+code+'\n5 分钟内有效。若非本人操作，请忽略此邮件。')
                context=ssl.create_default_context()
                if settings.get('tls','implicit')=='implicit':
                    client=smtplib.SMTP_SSL(settings['host'],int(settings.get('port',465)),timeout=15,context=context)
                elif settings['tls']=='starttls':
                    client=smtplib.SMTP(settings['host'],int(settings.get('port',587)),timeout=15);client.ehlo();client.starttls(context=context);client.ehlo()
                else:raise ResourceError('邮件验证码必须使用 TLS。','authentication_tls_required',503)
                with client:
                    if settings.get('username'):client.login(settings['username'],secret(settings.get('password_ref')))
                    refused=client.send_message(message)
                    if refused:return {'state':'failed','code':'smtp_recipient_refused'}
                return {'state':'sent','receipt':'smtp_accepted'}
            account=settings['account_sid']
            if not account.startswith('AC') or not account.isalnum():raise ResourceError('短信账户配置无效。','authentication_provider_invalid',503)
            response=httpx.post('https://api.twilio.com/2010-04-01/Accounts/'+account+'/Messages.json',auth=(settings['api_key_sid'],secret(settings.get('api_key_secret_ref'))),data={'To':recipient,'From':settings['from_number'],'Body':'VSC 验证码：'+code+'。5 分钟内有效，非本人操作请忽略。'},timeout=15,follow_redirects=False)
            if 400<=response.status_code<500:return {'state':'failed','code':'sms_request_rejected'}
            response.raise_for_status();data=response.json()
            if not isinstance(data.get('sid'),str):return {'state':'unknown','code':'sms_receipt_missing'}
            if data.get('status') in {'failed','undelivered'}:return {'state':'failed','receipt':data['sid'],'code':'sms_delivery_rejected'}
            return {'state':'sent','receipt':data['sid']}
        except ResourceError:raise
        except (smtplib.SMTPAuthenticationError,smtplib.SMTPRecipientsRefused,smtplib.SMTPSenderRefused,smtplib.SMTPDataError):
            return {'state':'failed','code':'smtp_request_rejected'}
        except Exception:return {'state':'unknown','code':'delivery_receipt_unknown'}

    def metadata(self, settings):
        import httpx
        from vsc.assets.resource_service import ResourceError
        issuer=https_url(settings['issuer']).rstrip('/')
        response=httpx.get(issuer+'/.well-known/openid-configuration',timeout=15,follow_redirects=False);response.raise_for_status();data=response.json()
        if data.get('issuer')!=settings['issuer']:raise ResourceError('OIDC issuer 与固定配置不符。','authentication_oidc_issuer',403)
        for key in ('authorization_endpoint','token_endpoint','jwks_uri'):https_url(data[key])
        if data.get('code_challenge_methods_supported') and 'S256' not in data['code_challenge_methods_supported']:raise ResourceError('OIDC 提供方没有声明 S256 PKCE。','authentication_oidc_pkce',503)
        return data

    def authorization_url(self, settings, state, nonce, verifier):
        from authlib.integrations.httpx_client import OAuth2Client
        metadata=self.metadata(settings)
        with OAuth2Client(settings['client_id'],redirect_uri=settings['redirect_uri'],scope='openid',code_challenge_method='S256') as client:
            url,_=client.create_authorization_url(metadata['authorization_endpoint'],state=state,nonce=nonce,code_verifier=verifier)
        return url

    def exchange(self, settings, code, nonce, verifier):
        import httpx
        from vsc.assets.resource_service import ResourceError
        from authlib.integrations.httpx_client import OAuth2Client
        from authlib.jose import JsonWebToken, JsonWebKey
        from authlib.oidc.core import CodeIDToken
        metadata=self.metadata(settings)
        with OAuth2Client(settings['client_id'],client_secret=secret(settings.get('client_secret_ref')),redirect_uri=settings['redirect_uri'],code_challenge_method='S256',token_endpoint_auth_method='client_secret_post',timeout=15) as client:
            token=client.fetch_token(metadata['token_endpoint'],grant_type='authorization_code',code=code,code_verifier=verifier)
        response=httpx.get(metadata['jwks_uri'],timeout=15,follow_redirects=False);response.raise_for_status()
        key=JsonWebKey.import_key_set(response.json())
        claims=JsonWebToken(['RS256']).decode(token['id_token'],key,claims_cls=CodeIDToken,
            claims_options={'iss':{'essential':True,'value':settings['issuer']},'aud':{'essential':True,'value':settings['client_id']},'exp':{'essential':True},'iat':{'essential':True},'sub':{'essential':True}},
            claims_params={'nonce':nonce,'client_id':settings['client_id'],'access_token':token.get('access_token')})
        claims.validate(leeway=0)
        subject=claims.get('sub')
        if not isinstance(subject,str) or not 1<=len(subject)<=1000:raise ResourceError('OIDC 主体无效。','authentication_oidc_subject',403)
        return subject
