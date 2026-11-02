"""Commercial credits are distinct from original native-unit reservations."""
from sqlalchemy import Column, Integer, BigInteger, Text, Boolean, DateTime, String, LargeBinary, ForeignKey, CheckConstraint, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import JSONB, UUID

COMMERCE_IMMUTABLE = ("commerce_plan_versions", "commerce_rates", "commerce_payment_events", "commerce_buckets", "commerce_ledger", "commerce_campaigns", "commerce_redemptions")


def declare_commerce(project_table, ref, uid, stamp):
    plans = project_table("commerce_plan_versions", Column("plan_key", Text, nullable=False), Column("version", Integer, nullable=False),
        Column("document", JSONB, nullable=False), Column("sha256", String(64), nullable=False), Column("actor", Text, nullable=False), stamp(),
        UniqueConstraint("project_id", "plan_key", "version"), CheckConstraint("version > 0", name="version"))
    rates = project_table("commerce_rates", *ref("commerce_plan_versions", "plan_id"),
        Column("model_id", UUID(as_uuid=False), ForeignKey("provider_models.id"), nullable=False), Column("unit", Text, nullable=False),
        Column("credits_per_unit", BigInteger, nullable=False), UniqueConstraint("project_id", "plan_id", "model_id", "unit"),
        CheckConstraint("credits_per_unit > 0", name="positive_rate"))
    settings = project_table("commerce_settings", *ref("commerce_plan_versions", "price_version_id"), Column("enabled", Boolean, nullable=False),
        UniqueConstraint("project_id"))
    orders = project_table("commerce_orders", *ref("commerce_plan_versions", "plan_id"), *ref("commerce_orders", "renewal_of_order_id", nullable=True), Column("actor", Text, nullable=False),
        Column("gateway", Text, nullable=False), Column("status", Text, nullable=False), Column("amount_minor", BigInteger, nullable=False),
        Column("currency", String(3), nullable=False), Column("credits", BigInteger, nullable=False), Column("expires_at", DateTime(timezone=True), nullable=False),
        Column("paid_at", DateTime(timezone=True)), Column("external_id", Text), Column("checkout_url", Text), Column("error_code", Text), stamp(),
        UniqueConstraint("project_id", "gateway", "external_id"), CheckConstraint("amount_minor > 0 AND credits > 0", name="amount"),
        CheckConstraint("status IN ('created','checkout_unknown','pending','paid','expired','cancelled','refund_unknown','refunded')", name="status"))
    events = project_table("commerce_payment_events", *ref("commerce_orders", "order_id"), Column("gateway", Text, nullable=False),
        Column("event_id", Text, nullable=False), Column("sha256", String(64), nullable=False), Column("document", JSONB, nullable=False), stamp(),
        UniqueConstraint("project_id", "gateway", "event_id"))
    buckets = project_table("commerce_buckets", *ref("commerce_orders", "order_id", nullable=True),
        *ref("commerce_buckets", "parent_bucket_id", nullable=True), Column("owner_actor", Text), Column("kind", Text, nullable=False),
        Column("purposes", JSONB, nullable=False), Column("expires_at", DateTime(timezone=True)), Column("source_key", Text, nullable=False), stamp(),
        UniqueConstraint("project_id", "source_key"), CheckConstraint("kind IN ('credit','bonus','check_in','special')", name="kind"))
    reservations = project_table("commerce_reservations", *ref("generation_jobs", "job_id"), *ref("commerce_plan_versions", "price_version_id"),
        Column("account_actor", Text), Column("attempt", Integer, nullable=False), Column("bound", BigInteger, nullable=False),
        Column("actual", BigInteger), Column("status", Text, nullable=False), stamp(), UniqueConstraint("project_id", "job_id"),
        CheckConstraint("attempt > 0 AND bound >= 0 AND (actual IS NULL OR actual BETWEEN 0 AND bound)", name="amount"),
        CheckConstraint("status IN ('reserved','settled','released')", name="status"))
    ledger = project_table("commerce_ledger", *ref("commerce_buckets", "bucket_id"), *ref("commerce_reservations", "reservation_id", nullable=True),
        Column("delta", BigInteger, nullable=False), Column("kind", Text, nullable=False), Column("event_key", Text, nullable=False),
        Column("actor", Text, nullable=False), stamp(), UniqueConstraint("project_id", "event_key"),
        CheckConstraint("kind IN ('grant','allocate_out','allocate_in','reclaim_out','reclaim_in','reserve','release','refund')", name="kind"),
        CheckConstraint("delta <> 0", name="nonzero"))
    campaigns = project_table("commerce_campaigns", Column("code_sha256", String(64), nullable=False), Column("title", Text, nullable=False),
        Column("credits", BigInteger, nullable=False), Column("kind", Text, nullable=False), Column("purposes", JSONB, nullable=False),
        Column("starts_at", DateTime(timezone=True)), Column("ends_at", DateTime(timezone=True), nullable=False),
        Column("credit_expires_at", DateTime(timezone=True), nullable=False), Column("daily", Boolean, nullable=False), Column("actor", Text, nullable=False), stamp(),
        UniqueConstraint("project_id", "code_sha256"), CheckConstraint("credits > 0 AND credit_expires_at >= ends_at", name="limits"),
        CheckConstraint("kind IN ('bonus','check_in','special')", name="kind"))
    redemptions = project_table("commerce_redemptions", *ref("commerce_campaigns", "campaign_id"), *ref("commerce_buckets", "bucket_id"),
        Column("actor", Text, nullable=False), Column("period", Text, nullable=False), stamp(), UniqueConstraint("project_id", "campaign_id", "actor", "period"))
    invoices = project_table("commerce_invoices", *ref("commerce_orders", "order_id"), Column("actor", Text, nullable=False),
        Column('workspace_id',UUID(as_uuid=False),ForeignKey('access_workspaces.id')),
        Column("title", Text, nullable=False), Column("tax_id", Text, nullable=False), Column("email", Text, nullable=False),
        Column("gateway", Text, nullable=False), Column("status", Text, nullable=False), Column("external_id", Text), Column("error_code", Text),
        Column("document", LargeBinary), Column("sha256", String(64)), stamp(), UniqueConstraint("project_id", "order_id"),
        CheckConstraint("status IN ('created','unconfigured','submission_unknown','pending','issued','failed')", name="status"),
        CheckConstraint("(status='issued') = (document IS NOT NULL AND sha256 IS NOT NULL)", name="document"))
    result = (plans, rates, settings, orders, events, buckets, reservations, ledger, campaigns, redemptions, invoices)
    for table in result:
        for column in table.c:
            if column.name.endswith("_id") and column.name not in {"id", "project_id"}:
                Index("ix_" + table.name + "_" + column.name, table.c.project_id, column)
    return {table.name: table for table in result}


# Canonical trigger specification; migration 0032 carries a frozen SQL snapshot.
COMMERCE_RATE_SEAL_DDL = (
    """CREATE FUNCTION vsc_commerce_rates_match(p uuid, plan uuid) RETURNS boolean
LANGUAGE plpgsql STABLE AS $$
DECLARE wanted jsonb; item jsonb;
BEGIN
 SELECT document->'rates' INTO wanted FROM commerce_plan_versions WHERE project_id=p AND id=plan;
 IF jsonb_typeof(wanted) IS DISTINCT FROM 'array' THEN RETURN false; END IF;
 IF jsonb_array_length(wanted) NOT BETWEEN 1 AND 200 THEN RETURN false; END IF;
 FOR item IN SELECT value FROM jsonb_array_elements(wanted) LOOP
  IF jsonb_typeof(item) IS DISTINCT FROM 'object' THEN RETURN false; END IF;
  IF (item-ARRAY['model_id','unit','credits_per_unit'])<>'{}'::jsonb
   OR jsonb_typeof(item->'model_id') IS DISTINCT FROM 'string'
   OR jsonb_typeof(item->'unit') IS DISTINCT FROM 'string'
   OR jsonb_typeof(item->'credits_per_unit') IS DISTINCT FROM 'number'
   OR (item->>'credits_per_unit') !~ '^[1-9][0-9]*$' THEN RETURN false; END IF;
 END LOOP;
 RETURN NOT EXISTS(
  (SELECT (value->>'model_id')::uuid, value->>'unit', (value->>'credits_per_unit')::bigint
   FROM jsonb_array_elements(wanted)
   EXCEPT ALL SELECT model_id, unit, credits_per_unit FROM commerce_rates WHERE project_id=p AND plan_id=plan)
  UNION ALL
  (SELECT model_id, unit, credits_per_unit FROM commerce_rates WHERE project_id=p AND plan_id=plan
   EXCEPT ALL SELECT (value->>'model_id')::uuid, value->>'unit', (value->>'credits_per_unit')::bigint
   FROM jsonb_array_elements(wanted))
 );
EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN RETURN false;
END $$""",
    """CREATE FUNCTION vsc_commerce_rates_sealed() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE member_plan uuid;
BEGIN
 IF TG_TABLE_NAME='commerce_plan_versions' THEN member_plan:=NEW.id; ELSE member_plan:=NEW.plan_id; END IF;
 IF NOT vsc_commerce_rates_match(NEW.project_id,member_plan) THEN
  RAISE EXCEPTION 'commerce rates must equal the complete fixed pricing document' USING ERRCODE='23514';
 END IF;
 RETURN NULL;
END $$""",
    "CREATE CONSTRAINT TRIGGER commerce_rates_sealed AFTER INSERT ON commerce_plan_versions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_commerce_rates_sealed()",
    "CREATE CONSTRAINT TRIGGER commerce_rates_sealed AFTER INSERT ON commerce_rates DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_commerce_rates_sealed()",
)
COMMERCE_RATE_SEAL_PREFLIGHT = """DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM commerce_plan_versions WHERE NOT vsc_commerce_rates_match(project_id,id)) THEN
  RAISE EXCEPTION 'existing rates differ from their fixed pricing document; migration requires explicit repair' USING ERRCODE='23514';
 END IF;
END $$"""


def install_commerce_rate_seals(connection):
    """Install the canonical invariant; inconsistent legacy facts abort atomically."""
    connection.exec_driver_sql('LOCK TABLE commerce_plan_versions, commerce_rates IN SHARE ROW EXCLUSIVE MODE')
    for statement in COMMERCE_RATE_SEAL_DDL:
        connection.exec_driver_sql(statement)
    connection.exec_driver_sql(COMMERCE_RATE_SEAL_PREFLIGHT)
