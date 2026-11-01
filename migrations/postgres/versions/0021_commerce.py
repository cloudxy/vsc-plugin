"""Versioned commercial credit contracts; native generation usage stays original."""
from alembic import op

revision="0021_commerce"
down_revision="0020_canvas_agent"
branch_labels=None
depends_on=None

DDL=['\n'
 'CREATE TABLE commerce_campaigns (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tcode_sha256 VARCHAR(64) NOT NULL, \n'
 '\ttitle TEXT NOT NULL, \n'
 '\tcredits BIGINT NOT NULL, \n'
 '\tkind TEXT NOT NULL, \n'
 '\tpurposes JSONB NOT NULL, \n'
 '\tstarts_at TIMESTAMP WITH TIME ZONE, \n'
 '\tends_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tcredit_expires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tdaily BOOLEAN NOT NULL, \n'
 '\tactor TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_commerce_campaigns PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT uq_commerce_campaigns_project_id_code_sha256 UNIQUE (project_id, code_sha256), \n'
 '\tCONSTRAINT ck_commerce_campaigns_limits CHECK (credits > 0 AND credit_expires_at >= ends_at), \n'
 "\tCONSTRAINT ck_commerce_campaigns_kind CHECK (kind IN ('bonus','check_in','special')), \n"
 '\tCONSTRAINT fk_commerce_campaigns_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON '
 'DELETE RESTRICT, \n'
 '\tCONSTRAINT ck_commerce_campaigns_code_sha256_format CHECK (code_sha256 IS NULL OR code_sha256 ~ '
 "'^[0-9a-f]{64}$')\n"
 ')\n'
 '\n',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON commerce_campaigns FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 '\n'
 'CREATE TABLE commerce_plan_versions (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tplan_key TEXT NOT NULL, \n'
 '\tversion INTEGER NOT NULL, \n'
 '\tdocument JSONB NOT NULL, \n'
 '\tsha256 VARCHAR(64) NOT NULL, \n'
 '\tactor TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_commerce_plan_versions PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT uq_commerce_plan_versions_project_id_plan_key_version UNIQUE (project_id, plan_key, '
 'version), \n'
 '\tCONSTRAINT ck_commerce_plan_versions_version CHECK (version > 0), \n'
 '\tCONSTRAINT fk_commerce_plan_versions_project_id_projects FOREIGN KEY(project_id) REFERENCES projects '
 '(id) ON DELETE RESTRICT, \n'
 "\tCONSTRAINT ck_commerce_plan_versions_sha256_format CHECK (sha256 IS NULL OR sha256 ~ '^[0-9a-f]{64}$')\n"
 ')\n'
 '\n',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON commerce_plan_versions FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 '\n'
 'CREATE TABLE commerce_orders (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tplan_id UUID NOT NULL, \n'
 '\trenewal_of_order_id UUID, \n'
 '\tactor TEXT NOT NULL, \n'
 '\tgateway TEXT NOT NULL, \n'
 '\tstatus TEXT NOT NULL, \n'
 '\tamount_minor BIGINT NOT NULL, \n'
 '\tcurrency VARCHAR(3) NOT NULL, \n'
 '\tcredits BIGINT NOT NULL, \n'
 '\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tpaid_at TIMESTAMP WITH TIME ZONE, \n'
 '\texternal_id TEXT, \n'
 '\tcheckout_url TEXT, \n'
 '\terror_code TEXT, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_commerce_orders PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_commerce_orders_project_id_plan_id_commerce_plan_versions FOREIGN KEY(project_id, plan_id) '
 'REFERENCES commerce_plan_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_commerce_orders_project_id_renewal_of_order_id_comme_19e0 FOREIGN KEY(project_id, '
 'renewal_of_order_id) REFERENCES commerce_orders (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_commerce_orders_project_id_gateway_external_id UNIQUE (project_id, gateway, '
 'external_id), \n'
 '\tCONSTRAINT ck_commerce_orders_amount CHECK (amount_minor > 0 AND credits > 0), \n'
 '\tCONSTRAINT ck_commerce_orders_status CHECK (status IN '
 "('created','checkout_unknown','pending','paid','expired','cancelled','refund_unknown','refunded')), \n"
 '\tCONSTRAINT fk_commerce_orders_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON '
 'DELETE RESTRICT\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_commerce_orders_external_id ON commerce_orders (project_id, external_id)',
 'CREATE INDEX ix_commerce_orders_plan_id ON commerce_orders (project_id, plan_id)',
 'CREATE INDEX ix_commerce_orders_renewal_of_order_id ON commerce_orders (project_id, renewal_of_order_id)',
 '\n'
 'CREATE TABLE commerce_rates (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tplan_id UUID NOT NULL, \n'
 '\tmodel_id UUID NOT NULL, \n'
 '\tunit TEXT NOT NULL, \n'
 '\tcredits_per_unit BIGINT NOT NULL, \n'
 '\tCONSTRAINT pk_commerce_rates PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_commerce_rates_project_id_plan_id_commerce_plan_versions FOREIGN KEY(project_id, plan_id) '
 'REFERENCES commerce_plan_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_commerce_rates_project_id_plan_id_model_id_unit UNIQUE (project_id, plan_id, model_id, '
 'unit), \n'
 '\tCONSTRAINT ck_commerce_rates_positive_rate CHECK (credits_per_unit > 0), \n'
 '\tCONSTRAINT fk_commerce_rates_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON '
 'DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_commerce_rates_model_id_provider_models FOREIGN KEY(model_id) REFERENCES provider_models '
 '(id)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_commerce_rates_model_id ON commerce_rates (project_id, model_id)',
 'CREATE INDEX ix_commerce_rates_plan_id ON commerce_rates (project_id, plan_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON commerce_rates FOR EACH ROW EXECUTE FUNCTION '
 'vsc_reject_mutation()',
 '\n'
 'CREATE TABLE commerce_settings (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tprice_version_id UUID NOT NULL, \n'
 '\tenabled BOOLEAN NOT NULL, \n'
 '\tCONSTRAINT pk_commerce_settings PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_commerce_settings_project_id_price_version_id_commer_b77e FOREIGN KEY(project_id, '
 'price_version_id) REFERENCES commerce_plan_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_commerce_settings_project_id UNIQUE (project_id), \n'
 '\tCONSTRAINT fk_commerce_settings_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON '
 'DELETE RESTRICT\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_commerce_settings_price_version_id ON commerce_settings (project_id, price_version_id)',
 '\n'
 'CREATE TABLE commerce_buckets (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\torder_id UUID, \n'
 '\tparent_bucket_id UUID, \n'
 '\towner_actor TEXT, \n'
 '\tkind TEXT NOT NULL, \n'
 '\tpurposes JSONB NOT NULL, \n'
 '\texpires_at TIMESTAMP WITH TIME ZONE, \n'
 '\tsource_key TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_commerce_buckets PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_commerce_buckets_project_id_order_id_commerce_orders FOREIGN KEY(project_id, order_id) '
 'REFERENCES commerce_orders (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_commerce_buckets_project_id_parent_bucket_id_commerc_f1df FOREIGN KEY(project_id, '
 'parent_bucket_id) REFERENCES commerce_buckets (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_commerce_buckets_project_id_source_key UNIQUE (project_id, source_key), \n'
 "\tCONSTRAINT ck_commerce_buckets_kind CHECK (kind IN ('credit','bonus','check_in','special')), \n"
 '\tCONSTRAINT fk_commerce_buckets_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON '
 'DELETE RESTRICT\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_commerce_buckets_order_id ON commerce_buckets (project_id, order_id)',
 'CREATE INDEX ix_commerce_buckets_parent_bucket_id ON commerce_buckets (project_id, parent_bucket_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON commerce_buckets FOR EACH ROW EXECUTE FUNCTION '
 'vsc_reject_mutation()',
 '\n'
 'CREATE TABLE commerce_invoices (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\torder_id UUID NOT NULL, \n'
 '\tactor TEXT NOT NULL, \n'
 '\ttitle TEXT NOT NULL, \n'
 '\ttax_id TEXT NOT NULL, \n'
 '\temail TEXT NOT NULL, \n'
 '\tgateway TEXT NOT NULL, \n'
 '\tstatus TEXT NOT NULL, \n'
 '\texternal_id TEXT, \n'
 '\terror_code TEXT, \n'
 '\tdocument BYTEA, \n'
 '\tsha256 VARCHAR(64), \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_commerce_invoices PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_commerce_invoices_project_id_order_id_commerce_orders FOREIGN KEY(project_id, order_id) '
 'REFERENCES commerce_orders (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_commerce_invoices_project_id_order_id UNIQUE (project_id, order_id), \n'
 '\tCONSTRAINT ck_commerce_invoices_status CHECK (status IN '
 "('created','unconfigured','submission_unknown','pending','issued','failed')), \n"
 "\tCONSTRAINT ck_commerce_invoices_document CHECK ((status='issued') = (document IS NOT NULL AND sha256 IS "
 'NOT NULL)), \n'
 '\tCONSTRAINT fk_commerce_invoices_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON '
 'DELETE RESTRICT, \n'
 "\tCONSTRAINT ck_commerce_invoices_sha256_format CHECK (sha256 IS NULL OR sha256 ~ '^[0-9a-f]{64}$')\n"
 ')\n'
 '\n',
 'CREATE INDEX ix_commerce_invoices_external_id ON commerce_invoices (project_id, external_id)',
 'CREATE INDEX ix_commerce_invoices_order_id ON commerce_invoices (project_id, order_id)',
 'CREATE INDEX ix_commerce_invoices_tax_id ON commerce_invoices (project_id, tax_id)',
 '\n'
 'CREATE TABLE commerce_payment_events (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\torder_id UUID NOT NULL, \n'
 '\tgateway TEXT NOT NULL, \n'
 '\tevent_id TEXT NOT NULL, \n'
 '\tsha256 VARCHAR(64) NOT NULL, \n'
 '\tdocument JSONB NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_commerce_payment_events PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_commerce_payment_events_project_id_order_id_commerce_orders FOREIGN KEY(project_id, '
 'order_id) REFERENCES commerce_orders (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_commerce_payment_events_project_id_gateway_event_id UNIQUE (project_id, gateway, '
 'event_id), \n'
 '\tCONSTRAINT fk_commerce_payment_events_project_id_projects FOREIGN KEY(project_id) REFERENCES projects '
 '(id) ON DELETE RESTRICT, \n'
 "\tCONSTRAINT ck_commerce_payment_events_sha256_format CHECK (sha256 IS NULL OR sha256 ~ '^[0-9a-f]{64}$')\n"
 ')\n'
 '\n',
 'CREATE INDEX ix_commerce_payment_events_event_id ON commerce_payment_events (project_id, event_id)',
 'CREATE INDEX ix_commerce_payment_events_order_id ON commerce_payment_events (project_id, order_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON commerce_payment_events FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 '\n'
 'CREATE TABLE commerce_redemptions (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tcampaign_id UUID NOT NULL, \n'
 '\tbucket_id UUID NOT NULL, \n'
 '\tactor TEXT NOT NULL, \n'
 '\tperiod TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_commerce_redemptions PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_commerce_redemptions_project_id_campaign_id_commerce_9be6 FOREIGN KEY(project_id, '
 'campaign_id) REFERENCES commerce_campaigns (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_commerce_redemptions_project_id_bucket_id_commerce_buckets FOREIGN KEY(project_id, '
 'bucket_id) REFERENCES commerce_buckets (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_commerce_redemptions_project_id_campaign_id_actor_period UNIQUE (project_id, campaign_id, '
 'actor, period), \n'
 '\tCONSTRAINT fk_commerce_redemptions_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) '
 'ON DELETE RESTRICT\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_commerce_redemptions_bucket_id ON commerce_redemptions (project_id, bucket_id)',
 'CREATE INDEX ix_commerce_redemptions_campaign_id ON commerce_redemptions (project_id, campaign_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON commerce_redemptions FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 '\n'
 'CREATE TABLE commerce_reservations (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tjob_id UUID NOT NULL, \n'
 '\tprice_version_id UUID NOT NULL, \n'
 '\taccount_actor TEXT, \n'
 '\tattempt INTEGER NOT NULL, \n'
 '\tbound BIGINT NOT NULL, \n'
 '\tactual BIGINT, \n'
 '\tstatus TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_commerce_reservations PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_commerce_reservations_project_id_job_id_generation_jobs FOREIGN KEY(project_id, job_id) '
 'REFERENCES generation_jobs (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_commerce_reservations_project_id_price_version_id_co_f1da FOREIGN KEY(project_id, '
 'price_version_id) REFERENCES commerce_plan_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_commerce_reservations_project_id_job_id UNIQUE (project_id, job_id), \n'
 '\tCONSTRAINT ck_commerce_reservations_amount CHECK (attempt > 0 AND bound >= 0 AND (actual IS NULL OR '
 'actual BETWEEN 0 AND bound)), \n'
 "\tCONSTRAINT ck_commerce_reservations_status CHECK (status IN ('reserved','settled','released')), \n"
 '\tCONSTRAINT fk_commerce_reservations_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) '
 'ON DELETE RESTRICT\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_commerce_reservations_job_id ON commerce_reservations (project_id, job_id)',
 'CREATE INDEX ix_commerce_reservations_price_version_id ON commerce_reservations (project_id, '
 'price_version_id)',
 '\n'
 'CREATE TABLE commerce_ledger (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tbucket_id UUID NOT NULL, \n'
 '\treservation_id UUID, \n'
 '\tdelta BIGINT NOT NULL, \n'
 '\tkind TEXT NOT NULL, \n'
 '\tevent_key TEXT NOT NULL, \n'
 '\tactor TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_commerce_ledger PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_commerce_ledger_project_id_bucket_id_commerce_buckets FOREIGN KEY(project_id, bucket_id) '
 'REFERENCES commerce_buckets (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_commerce_ledger_project_id_reservation_id_commerce_r_6c18 FOREIGN KEY(project_id, '
 'reservation_id) REFERENCES commerce_reservations (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_commerce_ledger_project_id_event_key UNIQUE (project_id, event_key), \n'
 '\tCONSTRAINT ck_commerce_ledger_kind CHECK (kind IN '
 "('grant','allocate_out','allocate_in','reclaim_out','reclaim_in','reserve','release','refund')), \n"
 '\tCONSTRAINT ck_commerce_ledger_nonzero CHECK (delta <> 0), \n'
 '\tCONSTRAINT fk_commerce_ledger_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON '
 'DELETE RESTRICT\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_commerce_ledger_bucket_id ON commerce_ledger (project_id, bucket_id)',
 'CREATE INDEX ix_commerce_ledger_reservation_id ON commerce_ledger (project_id, reservation_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON commerce_ledger FOR EACH ROW EXECUTE FUNCTION '
 'vsc_reject_mutation()']

DDL += ["""
CREATE FUNCTION vsc_commerce_identity() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'commerce history cannot be deleted' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='commerce_orders' THEN
  IF (to_jsonb(NEW)-ARRAY['status','paid_at','external_id','checkout_url','error_code']) IS DISTINCT FROM
     (to_jsonb(OLD)-ARRAY['status','paid_at','external_id','checkout_url','error_code']) OR
     (OLD.external_id IS NOT NULL AND NEW.external_id IS DISTINCT FROM OLD.external_id) OR
     (OLD.paid_at IS NOT NULL AND NEW.paid_at IS DISTINCT FROM OLD.paid_at) OR
     (OLD.status='refunded' AND NEW.status<>'refunded') OR
     (OLD.status='paid' AND NEW.status NOT IN ('paid','refund_unknown','refunded')) THEN
    RAISE EXCEPTION 'order contract or terminal history cannot change' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='commerce_reservations' THEN
  IF (to_jsonb(NEW)-ARRAY['status','actual']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['status','actual']) OR OLD.status<>'reserved' THEN
    RAISE EXCEPTION 'credit reservation contract and terminal settlement are immutable' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='commerce_invoices' THEN
  IF (to_jsonb(NEW)-ARRAY['status','gateway','external_id','error_code','document','sha256']) IS DISTINCT FROM
     (to_jsonb(OLD)-ARRAY['status','gateway','external_id','error_code','document','sha256']) OR OLD.status='issued' OR
     (OLD.external_id IS NOT NULL AND OLD.external_id IS DISTINCT FROM NEW.external_id) OR
     (OLD.gateway<>'unconfigured' AND OLD.gateway IS DISTINCT FROM NEW.gateway) THEN
    RAISE EXCEPTION 'invoice request or issued document cannot change' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$
""", """
CREATE FUNCTION vsc_commerce_ledger_lock() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 PERFORM id FROM projects WHERE id=NEW.project_id FOR UPDATE;
 RETURN NEW;
END $$
""", """
CREATE FUNCTION vsc_commerce_balance() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (SELECT COALESCE(SUM(delta),0) FROM commerce_ledger WHERE project_id=NEW.project_id AND bucket_id=NEW.bucket_id)<0 THEN
   RAISE EXCEPTION 'commercial credit bucket cannot be overdrawn' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END $$
"""]
for _table in ('commerce_orders','commerce_reservations','commerce_invoices','commerce_settings'):
    DDL.append('CREATE TRIGGER commerce_identity BEFORE UPDATE OR DELETE ON '+_table+' FOR EACH ROW EXECUTE FUNCTION vsc_commerce_identity()')
DDL += ['CREATE TRIGGER commerce_ledger_lock BEFORE INSERT ON commerce_ledger FOR EACH ROW EXECUTE FUNCTION vsc_commerce_ledger_lock()',
        'CREATE CONSTRAINT TRIGGER commerce_balance AFTER INSERT ON commerce_ledger DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_commerce_balance()']

def upgrade():
    for sql in DDL:op.execute(sql)

def downgrade():
    op.execute('DROP TRIGGER IF EXISTS commerce_ledger_lock ON commerce_ledger')
    op.execute('DROP TRIGGER IF EXISTS commerce_balance ON commerce_ledger')
    op.drop_table('commerce_ledger')
    op.drop_table('commerce_reservations')
    op.drop_table('commerce_redemptions')
    op.drop_table('commerce_payment_events')
    op.drop_table('commerce_invoices')
    op.drop_table('commerce_buckets')
    op.drop_table('commerce_settings')
    op.drop_table('commerce_rates')
    op.drop_table('commerce_orders')
    op.drop_table('commerce_plan_versions')
    op.execute('DROP FUNCTION vsc_commerce_identity()')
    op.execute('DROP FUNCTION vsc_commerce_ledger_lock()')
    op.execute('DROP FUNCTION vsc_commerce_balance()')
    op.drop_table('commerce_campaigns')
