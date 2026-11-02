"""Authentication proofs join the existing identity and personal workspace authority."""
from datetime import datetime, timedelta, timezone
import secrets
from sqlalchemy import select, insert, update, func
from vsc.assets.access_control import current_principal
from . import schema as S
from .access_control import authority_lock
from .values import new_id, checked_id


def now(): return datetime.now(timezone.utc)
def error(code, message, status=400): return {'error': code, 'message': message, 'status': status}


class AuthenticationRepository:
    def _auth_bind_guard(self, conn, identity_id):
        principal, person, _ = self._access_principal(conn)
        if not principal or not person or principal.identity_id != identity_id:
            return error('authentication_binding_changed', '当前绑定身份已改变，请从原账号重新发起。', 403)

    def _auth_scope(self, conn, row, browser):
        if not secrets.compare_digest(row['browser_sha256'], browser):
            return error('authentication_browser_mismatch', '挑战属于另一浏览器，请在原浏览器继续。', 403)
        if row['expires_at'] <= now(): return error('authentication_expired', '挑战已过期，请重新开始。')
        if row.get('consumed_at'): return error('authentication_consumed', '验证已使用，请重新开始登录。', 409)
        if row.get('purpose') == 'bind': return self._auth_bind_guard(conn, row['bind_identity_id'])

    def authentication_bindings(self):
        with self.engine.connect() as conn:
            principal,person,_=self._access_principal(conn)
            if not principal or not person:return error('authentication_identity_required','请先登录成员账号。',403)
            return {'items':[dict(row) for row in conn.execute(select(S.auth_subject_bindings.c.issuer,S.auth_subject_bindings.c.subject,S.auth_subject_bindings.c.created_at).where(S.auth_subject_bindings.c.identity_id==person['id']).order_by(S.auth_subject_bindings.c.created_at)).mappings()]}

    def authentication_graphic(self, values):
        with self.engine.begin() as conn:
            authority_lock(conn, True)
            total = conn.execute(select(func.count()).select_from(S.auth_graphic_challenges).where(S.auth_graphic_challenges.c.browser_sha256==values['browser_sha256'], S.auth_graphic_challenges.c.created_at>now()-timedelta(minutes=1))).scalar_one()
            if total >= 10: return error('authentication_rate_limit', '图形挑战请求过于频繁，请稍后再试。', 429)
            conn.execute(insert(S.auth_graphic_challenges).values(**values)); return {'id':values['id']}

    def authentication_prepare_otp(self, values, graphic_answer):
        with self.engine.begin() as conn:
            authority_lock(conn, True)
            old = conn.execute(select(S.auth_otp_challenges).where(S.auth_otp_challenges.c.browser_sha256==values['browser_sha256'], S.auth_otp_challenges.c.request_key==values['request_key']).with_for_update()).mappings().first()
            if old:
                if old['request_sha256'] != values['request_sha256']: return error('authentication_request_conflict', '原发码请求已经固定，请恢复原请求。', 409)
                return {'row':dict(old), 'send':False}
            if values['purpose']=='bind':
                invalid=self._auth_bind_guard(conn,values['bind_identity_id'])
                if invalid:return invalid
            graphic=conn.execute(select(S.auth_graphic_challenges).where(S.auth_graphic_challenges.c.id==checked_id(values['graphic_id'])).with_for_update()).mappings().first()
            if not graphic:return error('authentication_graphic_missing','请先取得图形挑战。')
            invalid=self._auth_scope(conn,graphic,values['browser_sha256'])
            if invalid:return invalid
            if graphic['attempts']>=5:return error('authentication_attempt_limit','图形验证错误次数已达上限。',429)
            conn.execute(update(S.auth_graphic_challenges).where(S.auth_graphic_challenges.c.id==graphic['id']).values(attempts=graphic['attempts']+1))
            if not secrets.compare_digest(graphic['answer_sha256'],graphic_answer):return error('authentication_graphic_wrong','图形验证码不正确。')
            # One ordered authority lock protects both recipient and browser quotas.
            for column,value,limit in ((S.auth_otp_challenges.c.recipient_sha256,values['recipient_sha256'],5),(S.auth_otp_challenges.c.browser_sha256,values['browser_sha256'],10)):
                count=conn.execute(select(func.count()).select_from(S.auth_otp_challenges).where(column==value,S.auth_otp_challenges.c.created_at>now()-timedelta(hours=1))).scalar_one()
                recent=conn.execute(select(S.auth_otp_challenges.c.id).where(column==value,S.auth_otp_challenges.c.created_at>now()-timedelta(seconds=60)).limit(1)).first()
                if count>=limit or recent:return error('authentication_rate_limit','验证码请求过于频繁，请稍后再试或继续验证原验证码。',429)
            conn.execute(update(S.auth_graphic_challenges).where(S.auth_graphic_challenges.c.id==graphic['id']).values(consumed_at=now()))
            conn.execute(insert(S.auth_otp_challenges).values(**values));return {'row':values,'send':True}

    def authentication_record_delivery(self, identifier, state, receipt=None, code=None):
        with self.engine.begin() as conn:
            authority_lock(conn,True)
            conn.execute(update(S.auth_otp_challenges).where(S.auth_otp_challenges.c.id==identifier,S.auth_otp_challenges.c.send_state=='sending').values(send_state=state,delivery_receipt=receipt,error_code=code))

    def authentication_read_otp(self, identifier, browser):
        with self.engine.connect() as conn:
            row=conn.execute(select(S.auth_otp_challenges).where(S.auth_otp_challenges.c.id==checked_id(identifier))).mappings().first()
            if not row:return error('authentication_not_found','验证码请求不存在。',404)
            if not secrets.compare_digest(row['browser_sha256'],browser):return error('authentication_browser_mismatch','验证码请求属于另一浏览器。',403)
            return {'row':dict(row)}

    def _authentication_subject(self, conn, issuer, subject, bind_identity_id=None):
        binding=conn.execute(select(S.auth_subject_bindings).where(S.auth_subject_bindings.c.issuer==issuer,S.auth_subject_bindings.c.subject==subject)).mappings().first()
        if binding:
            if bind_identity_id and binding['identity_id']!=bind_identity_id:return error('authentication_subject_bound','此登录方式已属于另一账号；不会合并账号。',409)
            person=self._access_identity(conn,binding['identity_id'])
        else:
            revision=self._access_state(conn)
            if bind_identity_id:person=self._access_identity(conn,bind_identity_id)
            else:
                identifier=new_id();person={'id':identifier,'subject_key':'authentication:'+identifier,'actor':'member:'+identifier,'display_name':'新成员','preferences':{},'active':True}
                conn.execute(insert(S.access_identities).values(**person))
            binding={'id':new_id(),'issuer':issuer,'subject':subject,'identity_id':person['id']}
            conn.execute(insert(S.auth_subject_bindings).values(**binding))
            self._access_event(conn,'authentication-binding:'+binding['id'],person['id'],'authentication_binding',__import__('hashlib').sha256((issuer+'\0'+subject).encode()).hexdigest(),revision,{'identity_id':person['id'],'subject_binding_id':binding['id']})
        workspace=self._personal_workspace(conn,person)
        principal=current_principal()
        if bind_identity_id and principal and principal.workspace_id and self._workspace_roles(conn,principal.workspace_id,person['id']):workspace=principal.workspace_id
        return {'binding_id':binding['id'],'session':{'identity_id':person['id'],'actor':person['actor'],'local':False,'workspace_id':workspace}}

    def authentication_verify_otp(self, identifier, browser, code_hash, subject):
        with self.engine.begin() as conn:
            authority_lock(conn,True)
            row=conn.execute(select(S.auth_otp_challenges).where(S.auth_otp_challenges.c.id==checked_id(identifier)).with_for_update()).mappings().first()
            if not row:return error('authentication_not_found','验证码请求不存在。',404)
            invalid=self._auth_scope(conn,row,browser)
            if invalid:return invalid
            if row['attempts']>=5:return error('authentication_attempt_limit','验证码错误次数已达上限，请重新开始。',429)
            if row['send_state']=='failed':return error('authentication_send_failed','原验证码发送被拒绝，请重新开始。')
            conn.execute(update(S.auth_otp_challenges).where(S.auth_otp_challenges.c.id==row['id']).values(attempts=row['attempts']+1))
            if not secrets.compare_digest(row['code_sha256'],code_hash):return error('authentication_code_wrong','验证码不正确。')
            result=self._authentication_subject(conn,'urn:vsc:'+row['channel'],subject,row['bind_identity_id'])
            if 'error' in result:return result
            conn.execute(update(S.auth_otp_challenges).where(S.auth_otp_challenges.c.id==row['id']).values(consumed_at=now(),identity_id=result['session']['identity_id'],subject_binding_id=result['binding_id']))
            return dict(result,purpose=row['purpose'])

    def authentication_start_oidc(self, values):
        with self.engine.begin() as conn:
            authority_lock(conn,True)
            if values['purpose']=='bind':
                invalid=self._auth_bind_guard(conn,values['bind_identity_id'])
                if invalid:return invalid
            count=conn.execute(select(func.count()).select_from(S.auth_oidc_attempts).where(S.auth_oidc_attempts.c.browser_sha256==values['browser_sha256'],S.auth_oidc_attempts.c.created_at>now()-timedelta(minutes=10))).scalar_one()
            if count>=10:return error('authentication_rate_limit','第三方登录请求过于频繁，请稍后再试。',429)
            conn.execute(insert(S.auth_oidc_attempts).values(**values));return {'id':values['id']}

    def authentication_claim_oidc(self, provider, state_hash, browser, configuration_hash):
        with self.engine.begin() as conn:
            authority_lock(conn,True)
            row=conn.execute(select(S.auth_oidc_attempts).where(S.auth_oidc_attempts.c.state_sha256==state_hash).with_for_update()).mappings().first()
            if not row or row['provider_key']!=provider:return error('authentication_state_invalid','第三方登录状态无效。',403)
            if row['browser_sha256']!=browser:return error('authentication_browser_mismatch','第三方登录属于另一浏览器。',403)
            if row['expires_at']<=now():return error('authentication_expired','第三方登录已过期。')
            if row['configuration_sha256']!=configuration_hash:return error('authentication_configuration_changed','登录配置已改变，请重新开始。',409)
            if row['status']!='pending':return error('authentication_exchange_started','原授权码已经处理或回执未知；不会重复交换，请重新开始登录。',409)
            conn.execute(update(S.auth_oidc_attempts).where(S.auth_oidc_attempts.c.id==row['id']).values(status='exchanging'));return {'row':dict(row)}

    def authentication_finish_oidc(self, identifier, *, subject=None, status='failed', code=None):
        with self.engine.begin() as conn:
            authority_lock(conn,True)
            conn.execute(update(S.auth_oidc_attempts).where(S.auth_oidc_attempts.c.id==identifier,S.auth_oidc_attempts.c.status.in_(['pending','exchanging'])).values(status='verified' if subject else status,verified_subject=subject,error_code=code))

    def authentication_complete_oidc(self, identifier, browser):
        with self.engine.begin() as conn:
            authority_lock(conn,True)
            row=conn.execute(select(S.auth_oidc_attempts).where(S.auth_oidc_attempts.c.id==checked_id(identifier)).with_for_update()).mappings().first()
            if not row:return error('authentication_not_found','第三方登录请求不存在。',404)
            invalid=self._auth_scope(conn,row,browser)
            if invalid:return invalid
            if row['status']!='verified':return error('authentication_not_verified','第三方登录尚未完成有效身份验证。',409)
            result=self._authentication_subject(conn,row['issuer'],row['verified_subject'],row['bind_identity_id'])
            if 'error' in result:return result
            conn.execute(update(S.auth_oidc_attempts).where(S.auth_oidc_attempts.c.id==row['id']).values(status='consumed',consumed_at=now(),identity_id=result['session']['identity_id'],subject_binding_id=result['binding_id']))
            return dict(result,purpose=row['purpose'])
