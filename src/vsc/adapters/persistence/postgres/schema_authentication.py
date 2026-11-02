"""Verified external subjects and bounded, single-use authentication challenges."""
from sqlalchemy import Table, Column, Text, Integer, LargeBinary, DateTime, ForeignKey, ForeignKeyConstraint, CheckConstraint, UniqueConstraint, Index, text
from sqlalchemy.dialects.postgresql import UUID

AUTHENTICATION_TABLES = ('auth_subject_bindings', 'auth_graphic_challenges', 'auth_otp_challenges', 'auth_oidc_attempts')
AUTHENTICATION_IMMUTABLE = ('auth_subject_bindings',)


def declare_authentication(metadata):
    def uid(name='id', **kw): return Column(name, UUID(as_uuid=False), **kw)
    def stamp(name='created_at', **kw): return Column(name, DateTime(timezone=True), **kw)
    def identity(name, nullable=True): return Column(name, UUID(as_uuid=False), ForeignKey('access_identities.id', ondelete='RESTRICT'), nullable=nullable)
    def hashed(name): return Column(name, Text, nullable=False)
    bindings = Table('auth_subject_bindings', metadata, uid(primary_key=True), Column('issuer', Text, nullable=False), Column('subject', Text, nullable=False), identity('identity_id', False), stamp(nullable=False, server_default=text('now()')), UniqueConstraint('issuer', 'subject'), UniqueConstraint('id', 'identity_id'), CheckConstraint("length(issuer) BETWEEN 1 AND 500 AND length(subject) BETWEEN 1 AND 1000", name='subject_shape'))
    graphics = Table('auth_graphic_challenges', metadata, uid(primary_key=True), hashed('browser_sha256'), hashed('answer_sha256'), Column('attempts', Integer, nullable=False, server_default='0'), stamp('expires_at', nullable=False), stamp('consumed_at'), stamp(nullable=False, server_default=text('now()')), UniqueConstraint('id','browser_sha256'), CheckConstraint('attempts BETWEEN 0 AND 5 AND expires_at>created_at', name='bounds'))
    otp = Table('auth_otp_challenges', metadata, uid(primary_key=True), Column('graphic_id', UUID(as_uuid=False), ForeignKey('auth_graphic_challenges.id', ondelete='RESTRICT'), nullable=False, unique=True), hashed('browser_sha256'), Column('channel', Text, nullable=False), Column('purpose', Text, nullable=False), identity('bind_identity_id'), hashed('recipient_sha256'), Column('recipient_ciphertext', LargeBinary, nullable=False), Column('recipient_label', Text, nullable=False), hashed('code_sha256'), Column('request_key', Text, nullable=False), hashed('request_sha256'), Column('send_state', Text, nullable=False), Column('delivery_receipt', Text), Column('error_code', Text), Column('attempts', Integer, nullable=False, server_default='0'), stamp('expires_at', nullable=False), stamp('consumed_at'), identity('identity_id'), Column('subject_binding_id', UUID(as_uuid=False), ForeignKey('auth_subject_bindings.id', ondelete='RESTRICT')), stamp(nullable=False, server_default=text('now()')), UniqueConstraint('browser_sha256', 'request_key'), ForeignKeyConstraint(['graphic_id','browser_sha256'],['auth_graphic_challenges.id','auth_graphic_challenges.browser_sha256']), ForeignKeyConstraint(['subject_binding_id','identity_id'],['auth_subject_bindings.id','auth_subject_bindings.identity_id']), CheckConstraint("channel IN ('email','sms') AND purpose IN ('login','bind') AND (purpose='bind')=(bind_identity_id IS NOT NULL)", name='scope'), CheckConstraint("send_state IN ('sending','sent','failed','unknown') AND attempts BETWEEN 0 AND 5 AND expires_at>created_at", name='bounds'), CheckConstraint('(consumed_at IS NOT NULL)=(identity_id IS NOT NULL) AND (identity_id IS NOT NULL)=(subject_binding_id IS NOT NULL)', name='consumed'))
    oidc = Table('auth_oidc_attempts', metadata, uid(primary_key=True), hashed('browser_sha256'), Column('provider_key', Text, nullable=False), Column('issuer', Text, nullable=False), Column('redirect_uri', Text, nullable=False), hashed('configuration_sha256'), Column('purpose', Text, nullable=False), identity('bind_identity_id'), hashed('state_sha256'), Column('secrets_ciphertext', LargeBinary, nullable=False), Column('status', Text, nullable=False), Column('verified_subject', Text), Column('error_code', Text), stamp('expires_at', nullable=False), stamp('consumed_at'), identity('identity_id'), Column('subject_binding_id', UUID(as_uuid=False), ForeignKey('auth_subject_bindings.id', ondelete='RESTRICT')), stamp(nullable=False, server_default=text('now()')), UniqueConstraint('state_sha256'), ForeignKeyConstraint(['subject_binding_id','identity_id'],['auth_subject_bindings.id','auth_subject_bindings.identity_id']), CheckConstraint("purpose IN ('login','bind') AND (purpose='bind')=(bind_identity_id IS NOT NULL)", name='scope'), CheckConstraint("status IN ('pending','exchanging','verified','failed','unknown','consumed') AND expires_at>created_at", name='status'), CheckConstraint("(status IN ('verified','consumed'))=(verified_subject IS NOT NULL) AND (status='consumed')=(consumed_at IS NOT NULL) AND (consumed_at IS NOT NULL)=(identity_id IS NOT NULL) AND (identity_id IS NOT NULL)=(subject_binding_id IS NOT NULL)", name='completion'))
    for table in (graphics, otp, oidc):
        Index('ix_'+table.name+'_browser_time', table.c.browser_sha256, table.c.created_at)
    Index('ix_auth_otp_recipient_time', otp.c.recipient_sha256, otp.c.created_at)
    for table in (bindings, otp, oidc):
        for column in table.c:
            if column.foreign_keys: Index('ix_'+table.name+'_'+column.name, column)
    return {table.name: table for table in (bindings, graphics, otp, oidc)}


AUTHENTICATION_GUARD_DDL = """
CREATE FUNCTION vsc_authentication_challenge_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE mutable text[];
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'authentication history is retained' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='auth_graphic_challenges' THEN mutable=ARRAY['attempts','consumed_at'];
 ELSIF TG_TABLE_NAME='auth_otp_challenges' THEN mutable=ARRAY['attempts','send_state','delivery_receipt','error_code','consumed_at','identity_id','subject_binding_id'];
 ELSE mutable=ARRAY['status','verified_subject','error_code','consumed_at','identity_id','subject_binding_id']; END IF;
 IF (to_jsonb(NEW)-mutable) IS DISTINCT FROM (to_jsonb(OLD)-mutable) THEN
  RAISE EXCEPTION 'authentication challenge inputs are immutable' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME<>'auth_oidc_attempts' AND ((to_jsonb(NEW)->>'attempts')::int < (to_jsonb(OLD)->>'attempts')::int OR (to_jsonb(NEW)->>'attempts')::int > (to_jsonb(OLD)->>'attempts')::int+1) THEN
  RAISE EXCEPTION 'authentication attempts must advance one at a time' USING ERRCODE='23514'; END IF;
 IF OLD.consumed_at IS NOT NULL AND (NEW.consumed_at IS DISTINCT FROM OLD.consumed_at OR (to_jsonb(NEW)->'identity_id') IS DISTINCT FROM (to_jsonb(OLD)->'identity_id') OR (to_jsonb(NEW)->'subject_binding_id') IS DISTINCT FROM (to_jsonb(OLD)->'subject_binding_id') OR (to_jsonb(NEW)->'attempts') IS DISTINCT FROM (to_jsonb(OLD)->'attempts')) THEN
  RAISE EXCEPTION 'consumed authentication proof cannot be replayed or replaced' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='auth_otp_challenges' THEN
  IF OLD.delivery_receipt IS NOT NULL AND NEW.delivery_receipt IS DISTINCT FROM OLD.delivery_receipt THEN RAISE EXCEPTION 'original delivery receipt is immutable' USING ERRCODE='23514'; END IF;
  IF NEW.send_state IS DISTINCT FROM OLD.send_state AND OLD.send_state<>'sending' THEN RAISE EXCEPTION 'original sending state is terminal' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='auth_oidc_attempts' THEN
  IF OLD.verified_subject IS NOT NULL AND NEW.verified_subject IS DISTINCT FROM OLD.verified_subject THEN RAISE EXCEPTION 'verified subject is immutable' USING ERRCODE='23514'; END IF;
  IF NEW.status IS DISTINCT FROM OLD.status AND NOT ((OLD.status='pending' AND NEW.status IN ('exchanging','failed')) OR (OLD.status='exchanging' AND NEW.status IN ('verified','failed','unknown')) OR (OLD.status='verified' AND NEW.status='consumed')) THEN RAISE EXCEPTION 'invalid OIDC authentication transition' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER auth_graphic_fixed BEFORE UPDATE OR DELETE ON auth_graphic_challenges FOR EACH ROW EXECUTE FUNCTION vsc_authentication_challenge_guard();
CREATE TRIGGER auth_otp_fixed BEFORE UPDATE OR DELETE ON auth_otp_challenges FOR EACH ROW EXECUTE FUNCTION vsc_authentication_challenge_guard();
CREATE TRIGGER auth_oidc_fixed BEFORE UPDATE OR DELETE ON auth_oidc_attempts FOR EACH ROW EXECUTE FUNCTION vsc_authentication_challenge_guard();
"""
