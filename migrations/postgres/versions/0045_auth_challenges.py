"""Single-use authentication challenges and immutable original-identity bindings."""
from alembic import op
revision='0045_auth_challenges'
down_revision='0044_spatial_direct'
branch_labels=None
depends_on=None
DDL=['\n'
 'CREATE TABLE auth_subject_bindings (\n'
 '\tid UUID NOT NULL, \n'
 '\tissuer TEXT NOT NULL, \n'
 '\tsubject TEXT NOT NULL, \n'
 '\tidentity_id UUID NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_auth_subject_bindings PRIMARY KEY (id), \n'
 '\tCONSTRAINT uq_auth_subject_bindings_issuer_subject UNIQUE (issuer, subject), \n'
 '\tCONSTRAINT uq_auth_subject_bindings_id_identity_id UNIQUE (id, identity_id), \n'
 '\tCONSTRAINT ck_auth_subject_bindings_subject_shape CHECK (length(issuer) BETWEEN 1 AND 500 AND '
 'length(subject) BETWEEN 1 AND 1000), \n'
 '\tCONSTRAINT fk_auth_subject_bindings_identity_id_access_identities FOREIGN KEY(identity_id) '
 'REFERENCES access_identities (id) ON DELETE RESTRICT\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_auth_subject_bindings_identity_id ON auth_subject_bindings (identity_id)',
 '\n'
 'CREATE TABLE auth_graphic_challenges (\n'
 '\tid UUID NOT NULL, \n'
 '\tbrowser_sha256 TEXT NOT NULL, \n'
 '\tanswer_sha256 TEXT NOT NULL, \n'
 "\tattempts INTEGER DEFAULT '0' NOT NULL, \n"
 '\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tconsumed_at TIMESTAMP WITH TIME ZONE, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_auth_graphic_challenges PRIMARY KEY (id), \n'
 '\tCONSTRAINT uq_auth_graphic_challenges_id_browser_sha256 UNIQUE (id, browser_sha256), \n'
 '\tCONSTRAINT ck_auth_graphic_challenges_bounds CHECK (attempts BETWEEN 0 AND 5 AND '
 'expires_at>created_at), \n'
 '\tCONSTRAINT ck_auth_graphic_challenges_browser_sha256_format CHECK (browser_sha256 IS NULL OR '
 "browser_sha256 ~ '^[0-9a-f]{64}$'), \n"
 '\tCONSTRAINT ck_auth_graphic_challenges_answer_sha256_format CHECK (answer_sha256 IS NULL OR '
 "answer_sha256 ~ '^[0-9a-f]{64}$')\n"
 ')\n'
 '\n',
 'CREATE INDEX ix_auth_graphic_challenges_browser_time ON auth_graphic_challenges (browser_sha256, '
 'created_at)',
 '\n'
 'CREATE TABLE auth_otp_challenges (\n'
 '\tid UUID NOT NULL, \n'
 '\tgraphic_id UUID NOT NULL, \n'
 '\tbrowser_sha256 TEXT NOT NULL, \n'
 '\tchannel TEXT NOT NULL, \n'
 '\tpurpose TEXT NOT NULL, \n'
 '\tbind_identity_id UUID, \n'
 '\trecipient_sha256 TEXT NOT NULL, \n'
 '\trecipient_ciphertext BYTEA NOT NULL, \n'
 '\trecipient_label TEXT NOT NULL, \n'
 '\tcode_sha256 TEXT NOT NULL, \n'
 '\trequest_key TEXT NOT NULL, \n'
 '\trequest_sha256 TEXT NOT NULL, \n'
 '\tsend_state TEXT NOT NULL, \n'
 '\tdelivery_receipt TEXT, \n'
 '\terror_code TEXT, \n'
 "\tattempts INTEGER DEFAULT '0' NOT NULL, \n"
 '\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tconsumed_at TIMESTAMP WITH TIME ZONE, \n'
 '\tidentity_id UUID, \n'
 '\tsubject_binding_id UUID, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_auth_otp_challenges PRIMARY KEY (id), \n'
 '\tCONSTRAINT uq_auth_otp_challenges_browser_sha256_request_key UNIQUE (browser_sha256, '
 'request_key), \n'
 '\tCONSTRAINT fk_auth_otp_challenges_graphic_id_browser_sha256_auth_g_0b87 FOREIGN '
 'KEY(graphic_id, browser_sha256) REFERENCES auth_graphic_challenges (id, browser_sha256), \n'
 '\tCONSTRAINT fk_auth_otp_challenges_subject_binding_id_identity_id_a_9f56 FOREIGN '
 'KEY(subject_binding_id, identity_id) REFERENCES auth_subject_bindings (id, identity_id), \n'
 "\tCONSTRAINT ck_auth_otp_challenges_scope CHECK (channel IN ('email','sms') AND purpose IN "
 "('login','bind') AND (purpose='bind')=(bind_identity_id IS NOT NULL)), \n"
 '\tCONSTRAINT ck_auth_otp_challenges_bounds CHECK (send_state IN '
 "('sending','sent','failed','unknown') AND attempts BETWEEN 0 AND 5 AND expires_at>created_at), \n"
 '\tCONSTRAINT ck_auth_otp_challenges_consumed CHECK ((consumed_at IS NOT NULL)=(identity_id IS '
 'NOT NULL) AND (identity_id IS NOT NULL)=(subject_binding_id IS NOT NULL)), \n'
 '\tCONSTRAINT uq_auth_otp_challenges_graphic_id UNIQUE (graphic_id), \n'
 '\tCONSTRAINT fk_auth_otp_challenges_graphic_id_auth_graphic_challenges FOREIGN KEY(graphic_id) '
 'REFERENCES auth_graphic_challenges (id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_auth_otp_challenges_bind_identity_id_access_identities FOREIGN '
 'KEY(bind_identity_id) REFERENCES access_identities (id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_auth_otp_challenges_identity_id_access_identities FOREIGN KEY(identity_id) '
 'REFERENCES access_identities (id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_auth_otp_challenges_subject_binding_id_auth_subject_bindings FOREIGN '
 'KEY(subject_binding_id) REFERENCES auth_subject_bindings (id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT ck_auth_otp_challenges_browser_sha256_format CHECK (browser_sha256 IS NULL OR '
 "browser_sha256 ~ '^[0-9a-f]{64}$'), \n"
 '\tCONSTRAINT ck_auth_otp_challenges_recipient_sha256_format CHECK (recipient_sha256 IS NULL OR '
 "recipient_sha256 ~ '^[0-9a-f]{64}$'), \n"
 '\tCONSTRAINT ck_auth_otp_challenges_code_sha256_format CHECK (code_sha256 IS NULL OR code_sha256 '
 "~ '^[0-9a-f]{64}$'), \n"
 '\tCONSTRAINT ck_auth_otp_challenges_request_sha256_format CHECK (request_sha256 IS NULL OR '
 "request_sha256 ~ '^[0-9a-f]{64}$')\n"
 ')\n'
 '\n',
 'CREATE INDEX ix_auth_otp_challenges_bind_identity_id ON auth_otp_challenges (bind_identity_id)',
 'CREATE INDEX ix_auth_otp_challenges_browser_sha256 ON auth_otp_challenges (browser_sha256)',
 'CREATE INDEX ix_auth_otp_challenges_browser_time ON auth_otp_challenges (browser_sha256, '
 'created_at)',
 'CREATE INDEX ix_auth_otp_challenges_graphic_id ON auth_otp_challenges (graphic_id)',
 'CREATE INDEX ix_auth_otp_challenges_identity_id ON auth_otp_challenges (identity_id)',
 'CREATE INDEX ix_auth_otp_challenges_subject_binding_id ON auth_otp_challenges '
 '(subject_binding_id)',
 'CREATE INDEX ix_auth_otp_recipient_time ON auth_otp_challenges (recipient_sha256, created_at)',
 '\n'
 'CREATE TABLE auth_oidc_attempts (\n'
 '\tid UUID NOT NULL, \n'
 '\tbrowser_sha256 TEXT NOT NULL, \n'
 '\tprovider_key TEXT NOT NULL, \n'
 '\tissuer TEXT NOT NULL, \n'
 '\tredirect_uri TEXT NOT NULL, \n'
 '\tconfiguration_sha256 TEXT NOT NULL, \n'
 '\tpurpose TEXT NOT NULL, \n'
 '\tbind_identity_id UUID, \n'
 '\tstate_sha256 TEXT NOT NULL, \n'
 '\tsecrets_ciphertext BYTEA NOT NULL, \n'
 '\tstatus TEXT NOT NULL, \n'
 '\tverified_subject TEXT, \n'
 '\terror_code TEXT, \n'
 '\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tconsumed_at TIMESTAMP WITH TIME ZONE, \n'
 '\tidentity_id UUID, \n'
 '\tsubject_binding_id UUID, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_auth_oidc_attempts PRIMARY KEY (id), \n'
 '\tCONSTRAINT uq_auth_oidc_attempts_state_sha256 UNIQUE (state_sha256), \n'
 '\tCONSTRAINT fk_auth_oidc_attempts_subject_binding_id_identity_id_au_5149 FOREIGN '
 'KEY(subject_binding_id, identity_id) REFERENCES auth_subject_bindings (id, identity_id), \n'
 "\tCONSTRAINT ck_auth_oidc_attempts_scope CHECK (purpose IN ('login','bind') AND "
 "(purpose='bind')=(bind_identity_id IS NOT NULL)), \n"
 '\tCONSTRAINT ck_auth_oidc_attempts_status CHECK (status IN '
 "('pending','exchanging','verified','failed','unknown','consumed') AND expires_at>created_at), \n"
 '\tCONSTRAINT ck_auth_oidc_attempts_completion CHECK ((status IN '
 "('verified','consumed'))=(verified_subject IS NOT NULL) AND (status='consumed')=(consumed_at IS "
 'NOT NULL) AND (consumed_at IS NOT NULL)=(identity_id IS NOT NULL) AND (identity_id IS NOT '
 'NULL)=(subject_binding_id IS NOT NULL)), \n'
 '\tCONSTRAINT fk_auth_oidc_attempts_bind_identity_id_access_identities FOREIGN '
 'KEY(bind_identity_id) REFERENCES access_identities (id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_auth_oidc_attempts_identity_id_access_identities FOREIGN KEY(identity_id) '
 'REFERENCES access_identities (id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_auth_oidc_attempts_subject_binding_id_auth_subject_bindings FOREIGN '
 'KEY(subject_binding_id) REFERENCES auth_subject_bindings (id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT ck_auth_oidc_attempts_browser_sha256_format CHECK (browser_sha256 IS NULL OR '
 "browser_sha256 ~ '^[0-9a-f]{64}$'), \n"
 '\tCONSTRAINT ck_auth_oidc_attempts_configuration_sha256_format CHECK (configuration_sha256 IS '
 "NULL OR configuration_sha256 ~ '^[0-9a-f]{64}$'), \n"
 '\tCONSTRAINT ck_auth_oidc_attempts_state_sha256_format CHECK (state_sha256 IS NULL OR '
 "state_sha256 ~ '^[0-9a-f]{64}$')\n"
 ')\n'
 '\n',
 'CREATE INDEX ix_auth_oidc_attempts_bind_identity_id ON auth_oidc_attempts (bind_identity_id)',
 'CREATE INDEX ix_auth_oidc_attempts_browser_time ON auth_oidc_attempts (browser_sha256, '
 'created_at)',
 'CREATE INDEX ix_auth_oidc_attempts_identity_id ON auth_oidc_attempts (identity_id)',
 'CREATE INDEX ix_auth_oidc_attempts_subject_binding_id ON auth_oidc_attempts (subject_binding_id)']

GUARD="\nCREATE FUNCTION vsc_authentication_challenge_guard() RETURNS trigger LANGUAGE plpgsql AS $$\nDECLARE mutable text[];\nBEGIN\n IF TG_OP='DELETE' THEN RAISE EXCEPTION 'authentication history is retained' USING ERRCODE='23514'; END IF;\n IF TG_TABLE_NAME='auth_graphic_challenges' THEN mutable=ARRAY['attempts','consumed_at'];\n ELSIF TG_TABLE_NAME='auth_otp_challenges' THEN mutable=ARRAY['attempts','send_state','delivery_receipt','error_code','consumed_at','identity_id','subject_binding_id'];\n ELSE mutable=ARRAY['status','verified_subject','error_code','consumed_at','identity_id','subject_binding_id']; END IF;\n IF (to_jsonb(NEW)-mutable) IS DISTINCT FROM (to_jsonb(OLD)-mutable) THEN\n  RAISE EXCEPTION 'authentication challenge inputs are immutable' USING ERRCODE='23514'; END IF;\n IF TG_TABLE_NAME<>'auth_oidc_attempts' AND ((to_jsonb(NEW)->>'attempts')::int < (to_jsonb(OLD)->>'attempts')::int OR (to_jsonb(NEW)->>'attempts')::int > (to_jsonb(OLD)->>'attempts')::int+1) THEN\n  RAISE EXCEPTION 'authentication attempts must advance one at a time' USING ERRCODE='23514'; END IF;\n IF OLD.consumed_at IS NOT NULL AND (NEW.consumed_at IS DISTINCT FROM OLD.consumed_at OR (to_jsonb(NEW)->'identity_id') IS DISTINCT FROM (to_jsonb(OLD)->'identity_id') OR (to_jsonb(NEW)->'subject_binding_id') IS DISTINCT FROM (to_jsonb(OLD)->'subject_binding_id') OR (to_jsonb(NEW)->'attempts') IS DISTINCT FROM (to_jsonb(OLD)->'attempts')) THEN\n  RAISE EXCEPTION 'consumed authentication proof cannot be replayed or replaced' USING ERRCODE='23514'; END IF;\n IF TG_TABLE_NAME='auth_otp_challenges' THEN\n  IF OLD.delivery_receipt IS NOT NULL AND NEW.delivery_receipt IS DISTINCT FROM OLD.delivery_receipt THEN RAISE EXCEPTION 'original delivery receipt is immutable' USING ERRCODE='23514'; END IF;\n  IF NEW.send_state IS DISTINCT FROM OLD.send_state AND OLD.send_state<>'sending' THEN RAISE EXCEPTION 'original sending state is terminal' USING ERRCODE='23514'; END IF;\n ELSIF TG_TABLE_NAME='auth_oidc_attempts' THEN\n  IF OLD.verified_subject IS NOT NULL AND NEW.verified_subject IS DISTINCT FROM OLD.verified_subject THEN RAISE EXCEPTION 'verified subject is immutable' USING ERRCODE='23514'; END IF;\n  IF NEW.status IS DISTINCT FROM OLD.status AND NOT ((OLD.status='pending' AND NEW.status IN ('exchanging','failed')) OR (OLD.status='exchanging' AND NEW.status IN ('verified','failed','unknown')) OR (OLD.status='verified' AND NEW.status='consumed')) THEN RAISE EXCEPTION 'invalid OIDC authentication transition' USING ERRCODE='23514'; END IF;\n END IF;\n RETURN NEW;\nEND $$;\nCREATE TRIGGER auth_graphic_fixed BEFORE UPDATE OR DELETE ON auth_graphic_challenges FOR EACH ROW EXECUTE FUNCTION vsc_authentication_challenge_guard();\nCREATE TRIGGER auth_otp_fixed BEFORE UPDATE OR DELETE ON auth_otp_challenges FOR EACH ROW EXECUTE FUNCTION vsc_authentication_challenge_guard();\nCREATE TRIGGER auth_oidc_fixed BEFORE UPDATE OR DELETE ON auth_oidc_attempts FOR EACH ROW EXECUTE FUNCTION vsc_authentication_challenge_guard();\n"

def upgrade():
    for statement in DDL:op.execute(statement)
    op.execute(GUARD)
    op.execute("CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON auth_subject_bindings FOR EACH ROW EXECUTE FUNCTION vsc_reject_mutation()")

def downgrade():
    op.execute('LOCK TABLE auth_oidc_attempts,auth_otp_challenges,auth_graphic_challenges,auth_subject_bindings IN ACCESS EXCLUSIVE MODE')
    op.execute("DO $$ BEGIN IF EXISTS(SELECT 1 FROM auth_subject_bindings) OR EXISTS(SELECT 1 FROM auth_graphic_challenges) OR EXISTS(SELECT 1 FROM auth_otp_challenges) OR EXISTS(SELECT 1 FROM auth_oidc_attempts) THEN RAISE EXCEPTION 'authentication facts exist; use forward recovery' USING ERRCODE='23514'; END IF; END $$")
    for table in ('auth_oidc_attempts','auth_otp_challenges','auth_graphic_challenges','auth_subject_bindings'):op.execute('DROP TABLE '+table)

    op.execute('DROP FUNCTION vsc_authentication_challenge_guard()')
