"""Commercial credits are distinct from original native-unit reservations."""
from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey,
    ForeignKeyConstraint, Index, Integer, LargeBinary, PrimaryKeyConstraint,
    String, Table, Text, UniqueConstraint, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

COMMERCE_IMMUTABLE = (
    "scoped_command_receipts",
    "commerce_plan_versions",
    "commerce_rates",
    "commerce_payment_events",
    "commerce_buckets",
    "commerce_ledger",
    "commerce_campaigns",
    "commerce_redemptions",
)

PLATFORM_SCOPE_CHECK = (
    "(scope_kind = 'platform' AND owner_identity_id IS NULL AND workspace_id IS NULL AND project_id IS NULL) OR "
    "(scope_kind = 'workspace' AND workspace_id IS NOT NULL AND owner_identity_id IS NULL AND project_id IS NULL) OR "
    "(scope_kind = 'project' AND project_id IS NOT NULL AND owner_identity_id IS NULL AND workspace_id IS NULL)"
)

ENTITY_SCOPE_CHECK = (
    "(scope_kind = 'identity' AND owner_identity_id IS NOT NULL AND workspace_id IS NULL AND project_id IS NULL) OR "
    "(scope_kind = 'workspace' AND workspace_id IS NOT NULL AND owner_identity_id IS NULL AND project_id IS NULL) OR "
    "(scope_kind = 'project' AND project_id IS NOT NULL AND owner_identity_id IS NULL AND workspace_id IS NULL)"
)


def _infer_scope_kind(ctx):
    params = ctx.get_current_parameters()
    if params.get("project_id") is not None:
        return "project"
    if params.get("workspace_id") is not None:
        return "workspace"
    if params.get("owner_identity_id") is not None:
        return "identity"
    return None


def make_scoped_table(metadata, uid, name, scope_check, *columns):
    return Table(
        name,
        metadata,
        uid(),
        Column("scope_kind", Text, nullable=False, default=_infer_scope_kind),
        Column("owner_identity_id", UUID(as_uuid=False), ForeignKey("access_identities.id", ondelete="RESTRICT")),
        Column("workspace_id", UUID(as_uuid=False), ForeignKey("access_workspaces.id", ondelete="RESTRICT")),
        Column("project_id", UUID(as_uuid=False), ForeignKey("projects.id", ondelete="RESTRICT")),
        *columns,
        PrimaryKeyConstraint("id"),
        CheckConstraint(scope_check, name="scope_target"),
    )


def declare_commerce(metadata, project_table, ref, uid, stamp):
    def platform_table(name, *columns):
        return make_scoped_table(metadata, uid, name, PLATFORM_SCOPE_CHECK, *columns)

    def entity_table(name, *columns):
        return make_scoped_table(metadata, uid, name, ENTITY_SCOPE_CHECK, *columns)

    states = Table(
        "scoped_domain_states",
        metadata,
        Column("domain", Text, nullable=False),
        Column("scope_kind", Text, nullable=False),
        Column("scope_key", Text, nullable=False),
        Column("owner_identity_id", UUID(as_uuid=False), ForeignKey("access_identities.id", ondelete="RESTRICT")),
        Column("workspace_id", UUID(as_uuid=False), ForeignKey("access_workspaces.id", ondelete="RESTRICT")),
        Column("revision", BigInteger, nullable=False, server_default="0"),
        Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
        PrimaryKeyConstraint("domain", "scope_kind", "scope_key"),
        CheckConstraint("domain IN ('commerce','service_operations')", name="domain"),
        CheckConstraint("scope_kind IN ('identity','workspace','platform')", name="scope_kind"),
        CheckConstraint("revision >= 0", name="revision"),
        CheckConstraint(
            "(scope_kind = 'platform' AND scope_key = 'platform' AND owner_identity_id IS NULL AND workspace_id IS NULL) OR "
            "(scope_kind = 'identity' AND owner_identity_id IS NOT NULL AND workspace_id IS NULL AND scope_key = owner_identity_id::text) OR "
            "(scope_kind = 'workspace' AND workspace_id IS NOT NULL AND owner_identity_id IS NULL AND scope_key = workspace_id::text)",
            name="scope_target",
        ),
    )
    Index("ix_scoped_domain_states_owner_identity_id", states.c.owner_identity_id,
          postgresql_where=text("owner_identity_id IS NOT NULL"))
    Index("ix_scoped_domain_states_workspace_id", states.c.workspace_id,
          postgresql_where=text("workspace_id IS NOT NULL"))

    receipts = Table(
        "scoped_command_receipts",
        metadata,
        Column("domain", Text, nullable=False),
        Column("scope_kind", Text, nullable=False),
        Column("scope_key", Text, nullable=False),
        Column("idempotency_key", Text, nullable=False),
        Column("actor", Text, nullable=False),
        Column("action", Text, nullable=False),
        Column("request_sha256", String(64), nullable=False),
        Column("revision", BigInteger, nullable=False),
        Column("response", JSONB, nullable=False),
        stamp(),
        PrimaryKeyConstraint("domain", "scope_kind", "scope_key", "idempotency_key"),
        ForeignKeyConstraint(
            ["domain", "scope_kind", "scope_key"],
            ["scoped_domain_states.domain", "scoped_domain_states.scope_kind", "scoped_domain_states.scope_key"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("length(btrim(idempotency_key)) BETWEEN 1 AND 200", name="idempotency_key"),
        CheckConstraint("revision > 0", name="revision"),
    )

    titles = entity_table(
        "commerce_invoice_titles",
        Column("title_type", Text, nullable=False),
        Column("title", Text, nullable=False),
        Column("tax_id", Text, nullable=False),
        Column("email", Text, nullable=False),
        Column("bank_name", Text),
        Column("bank_account_masked", Text),
        Column("billing_address_phone", Text),
        Column("is_default", Boolean, nullable=False, server_default="false"),
        Column("created_by", UUID(as_uuid=False), ForeignKey("access_identities.id", ondelete="RESTRICT"), nullable=False),
        stamp(),
        Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
        CheckConstraint("title_type IN ('enterprise_normal','enterprise_special','personal')", name="title_type"),
        CheckConstraint("length(btrim(title)) BETWEEN 1 AND 200 AND length(email) BETWEEN 3 AND 254", name="title_email"),
        CheckConstraint(
            "(title_type = 'personal' AND tax_id = 'PERSONAL') OR "
            "(title_type IN ('enterprise_normal','enterprise_special') AND tax_id <> 'PERSONAL' AND tax_id ~ '^[A-Z0-9]{15,32}$')",
            name="tax_id",
        ),
        CheckConstraint(
            "(bank_name IS NULL OR char_length(bank_name) <= 200) AND "
            "(bank_account_masked IS NULL OR char_length(bank_account_masked) <= 64) AND "
            "(billing_address_phone IS NULL OR char_length(billing_address_phone) <= 300)",
            name="optional_fields",
        ),
    )
    Index("uq_commerce_invoice_titles_default_identity", titles.c.owner_identity_id, unique=True,
          postgresql_where=text("scope_kind = 'identity' AND is_default = true"))
    Index("uq_commerce_invoice_titles_default_workspace", titles.c.workspace_id, unique=True,
          postgresql_where=text("scope_kind = 'workspace' AND is_default = true"))
    Index("uq_commerce_invoice_titles_default_project", titles.c.project_id, unique=True,
          postgresql_where=text("scope_kind = 'project' AND is_default = true"))
    Index("uq_commerce_invoice_titles_identity_title_tax", titles.c.owner_identity_id,
          func.lower(func.btrim(titles.c.title)), titles.c.tax_id, unique=True,
          postgresql_where=text("scope_kind = 'identity'"))
    Index("uq_commerce_invoice_titles_workspace_title_tax", titles.c.workspace_id,
          func.lower(func.btrim(titles.c.title)), titles.c.tax_id, unique=True,
          postgresql_where=text("scope_kind = 'workspace'"))
    Index("uq_commerce_invoice_titles_project_title_tax", titles.c.project_id,
          func.lower(func.btrim(titles.c.title)), titles.c.tax_id, unique=True,
          postgresql_where=text("scope_kind = 'project'"))
    Index("ix_commerce_invoice_titles_identity_list", titles.c.owner_identity_id,
          titles.c.is_default.desc(), titles.c.updated_at.desc(), titles.c.id,
          postgresql_where=text("scope_kind = 'identity'"))
    Index("ix_commerce_invoice_titles_workspace_list", titles.c.workspace_id,
          titles.c.is_default.desc(), titles.c.updated_at.desc(), titles.c.id,
          postgresql_where=text("scope_kind = 'workspace'"))
    Index("ix_commerce_invoice_titles_project_list", titles.c.project_id,
          titles.c.is_default.desc(), titles.c.updated_at.desc(), titles.c.id,
          postgresql_where=text("scope_kind = 'project'"))
    Index("ix_commerce_invoice_titles_created_by", titles.c.created_by)

    plans = platform_table(
        "commerce_plan_versions",
        Column("base_version_id", UUID(as_uuid=False), ForeignKey("commerce_plan_versions.id", ondelete="RESTRICT")),
        Column("plan_key", Text, nullable=False),
        Column("version", Integer, nullable=False),
        Column("document", JSONB, nullable=False),
        Column("sha256", String(64), nullable=False),
        Column("actor", Text, nullable=False),
        stamp(),
        CheckConstraint("version > 0", name="version"),
    )
    Index("uq_commerce_plan_versions_platform_key_ver", plans.c.plan_key, plans.c.version, unique=True,
          postgresql_where=text("scope_kind = 'platform'"))
    Index("uq_commerce_plan_versions_workspace_key_ver", plans.c.workspace_id, plans.c.plan_key, plans.c.version, unique=True,
          postgresql_where=text("scope_kind = 'workspace'"))
    Index("uq_commerce_plan_versions_project_key_ver", plans.c.project_id, plans.c.plan_key, plans.c.version, unique=True,
          postgresql_where=text("scope_kind = 'project'"))
    Index("ix_commerce_plan_versions_base_version_id", plans.c.base_version_id,
          postgresql_where=text("base_version_id IS NOT NULL"))

    rates = platform_table(
        "commerce_rates",
        Column("plan_id", UUID(as_uuid=False), ForeignKey("commerce_plan_versions.id", ondelete="RESTRICT"), nullable=False),
        Column("model_id", UUID(as_uuid=False), ForeignKey("provider_models.id", ondelete="RESTRICT"), nullable=False),
        Column("unit", Text, nullable=False),
        Column("credits_per_unit", BigInteger, nullable=False),
        UniqueConstraint("plan_id", "model_id", "unit", name="uq_commerce_rates_plan_model_unit"),
        CheckConstraint("credits_per_unit > 0", name="positive_rate"),
    )
    Index("ix_commerce_rates_model_id", rates.c.model_id)

    settings = platform_table(
        "commerce_settings",
        Column("price_version_id", UUID(as_uuid=False), ForeignKey("commerce_plan_versions.id", ondelete="RESTRICT"), nullable=False),
        Column("enabled", Boolean, nullable=False),
    )
    Index("uq_commerce_settings_platform", settings.c.scope_kind, unique=True,
          postgresql_where=text("scope_kind = 'platform'"))
    Index("uq_commerce_settings_workspace", settings.c.workspace_id, unique=True,
          postgresql_where=text("scope_kind = 'workspace'"))
    Index("uq_commerce_settings_project", settings.c.project_id, unique=True,
          postgresql_where=text("scope_kind = 'project'"))
    Index("ix_commerce_settings_price_version_id", settings.c.price_version_id)

    orders = entity_table(
        "commerce_orders",
        Column("plan_id", UUID(as_uuid=False), ForeignKey("commerce_plan_versions.id", ondelete="RESTRICT"), nullable=False),
        Column("renewal_of_order_id", UUID(as_uuid=False), ForeignKey("commerce_orders.id", ondelete="RESTRICT")),
        Column("actor", Text, nullable=False),
        Column("gateway", Text, nullable=False),
        Column("status", Text, nullable=False),
        Column("amount_minor", BigInteger, nullable=False),
        Column("currency", String(3), nullable=False),
        Column("credits", BigInteger, nullable=False),
        Column("expires_at", DateTime(timezone=True), nullable=False),
        Column("paid_at", DateTime(timezone=True)),
        Column("external_id", Text),
        Column("checkout_url", Text),
        Column("error_code", Text),
        stamp(),
        CheckConstraint("amount_minor > 0 AND credits > 0", name="amount"),
        CheckConstraint("status IN ('created','checkout_unknown','pending','paid','expired','cancelled','refund_unknown','refunded')", name="status"),
    )
    Index("uq_commerce_orders_gateway_external_id", orders.c.gateway, orders.c.external_id, unique=True,
          postgresql_where=text("external_id IS NOT NULL"))
    Index("ix_commerce_orders_scope_created", orders.c.scope_kind,
          func.coalesce(orders.c.owner_identity_id, orders.c.workspace_id, orders.c.project_id),
          orders.c.created_at.desc(), orders.c.id.desc())
    Index("ix_commerce_orders_actor_unsettled", orders.c.actor, orders.c.status,
          postgresql_where=text("status IN ('created','checkout_unknown','pending','refund_unknown')"))
    Index("ix_commerce_orders_plan_id", orders.c.plan_id)
    Index("ix_commerce_orders_renewal_of_order_id", orders.c.renewal_of_order_id,
          postgresql_where=text("renewal_of_order_id IS NOT NULL"))

    events = entity_table(
        "commerce_payment_events",
        Column("order_id", UUID(as_uuid=False), ForeignKey("commerce_orders.id", ondelete="RESTRICT"), nullable=False),
        Column("gateway", Text, nullable=False),
        Column("event_id", Text, nullable=False),
        Column("sha256", String(64), nullable=False),
        Column("document", JSONB, nullable=False),
        stamp(),
        UniqueConstraint("gateway", "event_id", name="uq_commerce_payment_events_gateway_event_id"),
    )
    Index("ix_commerce_payment_events_order_id", events.c.order_id)

    buckets = entity_table(
        "commerce_buckets",
        Column("order_id", UUID(as_uuid=False), ForeignKey("commerce_orders.id", ondelete="RESTRICT")),
        Column("parent_bucket_id", UUID(as_uuid=False), ForeignKey("commerce_buckets.id", ondelete="RESTRICT")),
        Column("owner_actor", Text),
        Column("kind", Text, nullable=False),
        Column("purposes", JSONB, nullable=False),
        Column("expires_at", DateTime(timezone=True)),
        Column("source_key", Text, nullable=False),
        stamp(),
        UniqueConstraint("project_id", "id", name="uq_commerce_buckets_project_id_id"),
        CheckConstraint("kind IN ('credit','bonus','check_in','special')", name="kind"),
    )
    Index("uq_commerce_buckets_identity_source_key", buckets.c.owner_identity_id, buckets.c.source_key, unique=True,
          postgresql_where=text("scope_kind = 'identity'"))
    Index("uq_commerce_buckets_workspace_source_key", buckets.c.workspace_id, buckets.c.source_key, unique=True,
          postgresql_where=text("scope_kind = 'workspace'"))
    Index("uq_commerce_buckets_project_source_key", buckets.c.project_id, buckets.c.source_key, unique=True,
          postgresql_where=text("scope_kind = 'project'"))
    Index("ix_commerce_buckets_scope_expiry", buckets.c.scope_kind,
          func.coalesce(buckets.c.owner_identity_id, buckets.c.workspace_id, buckets.c.project_id),
          buckets.c.expires_at.asc().nulls_last(), buckets.c.created_at.asc())
    Index("ix_commerce_buckets_owner_actor_active", buckets.c.owner_actor, buckets.c.expires_at,
          postgresql_where=text("owner_actor IS NOT NULL"))
    Index("ix_commerce_buckets_order_id", buckets.c.order_id,
          postgresql_where=text("order_id IS NOT NULL"))
    Index("ix_commerce_buckets_parent_bucket_id", buckets.c.parent_bucket_id,
          postgresql_where=text("parent_bucket_id IS NOT NULL"))

    reservations = entity_table(
        "commerce_reservations",
        Column("attribution_project_id", UUID(as_uuid=False), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False),
        uid("job_id", nullable=False),
        Column("price_version_id", UUID(as_uuid=False), ForeignKey("commerce_plan_versions.id", ondelete="RESTRICT"), nullable=False),
        Column("account_actor", Text),
        Column("attempt", Integer, nullable=False),
        Column("bound", BigInteger, nullable=False),
        Column("actual", BigInteger),
        Column("status", Text, nullable=False),
        stamp(),
        ForeignKeyConstraint(
            ["attribution_project_id", "job_id"],
            ["generation_jobs.project_id", "generation_jobs.id"],
            ondelete="RESTRICT",
            match="FULL",
        ),
        UniqueConstraint("attribution_project_id", "job_id", name="uq_commerce_reservations_attribution_job"),
        UniqueConstraint("attribution_project_id", "job_id", "id", name="uq_commerce_reservations_attribution_job_id"),
        CheckConstraint("attempt > 0 AND bound >= 0 AND (actual IS NULL OR actual BETWEEN 0 AND bound)", name="amount"),
        CheckConstraint("status IN ('reserved','settled','released')", name="status"),
    )
    Index("ix_commerce_reservations_scope_status_actor", reservations.c.scope_kind,
          func.coalesce(reservations.c.owner_identity_id, reservations.c.workspace_id, reservations.c.project_id),
          reservations.c.status, reservations.c.account_actor)
    Index("ix_commerce_reservations_attribution_status_actor", reservations.c.attribution_project_id,
          reservations.c.status, reservations.c.account_actor)
    Index("ix_commerce_reservations_actor_reserved", reservations.c.account_actor,
          postgresql_where=text("status = 'reserved'"))
    Index("ix_commerce_reservations_price_version_id", reservations.c.price_version_id)

    ledger = entity_table(
        "commerce_ledger",
        Column("bucket_id", UUID(as_uuid=False), ForeignKey("commerce_buckets.id", ondelete="RESTRICT"), nullable=False),
        Column("reservation_id", UUID(as_uuid=False), ForeignKey("commerce_reservations.id", ondelete="RESTRICT")),
        uid("attribution_project_id", nullable=True),
        uid("job_id", nullable=True),
        Column("delta", BigInteger, nullable=False),
        Column("kind", Text, nullable=False),
        Column("event_key", Text, nullable=False),
        Column("actor", Text, nullable=False),
        stamp(),
        ForeignKeyConstraint(
            ["attribution_project_id", "job_id"],
            ["generation_jobs.project_id", "generation_jobs.id"],
            ondelete="RESTRICT",
            match="FULL",
        ),
        ForeignKeyConstraint(
            ["attribution_project_id", "job_id", "reservation_id"],
            ["commerce_reservations.attribution_project_id", "commerce_reservations.job_id", "commerce_reservations.id"],
            ondelete="RESTRICT",
            match="FULL",
        ),
        UniqueConstraint("project_id", "id", name="uq_commerce_ledger_project_id_id"),
        CheckConstraint("kind IN ('grant','allocate_out','allocate_in','reclaim_out','reclaim_in','reserve','release','refund')", name="kind"),
        CheckConstraint("delta <> 0", name="nonzero"),
        CheckConstraint(
            "(kind IN ('reserve','release') AND reservation_id IS NOT NULL AND attribution_project_id IS NOT NULL AND job_id IS NOT NULL) OR "
            "(kind NOT IN ('reserve','release') AND reservation_id IS NULL AND attribution_project_id IS NULL AND job_id IS NULL)",
            name="attribution_pair",
        ),
    )
    Index("uq_commerce_ledger_identity_event_key", ledger.c.owner_identity_id, ledger.c.event_key, unique=True,
          postgresql_where=text("scope_kind = 'identity'"))
    Index("uq_commerce_ledger_workspace_event_key", ledger.c.workspace_id, ledger.c.event_key, unique=True,
          postgresql_where=text("scope_kind = 'workspace'"))
    Index("uq_commerce_ledger_project_event_key", ledger.c.project_id, ledger.c.event_key, unique=True,
          postgresql_where=text("scope_kind = 'project'"))
    Index("ix_commerce_ledger_bucket_id", ledger.c.bucket_id)
    Index("ix_commerce_ledger_scope_created", ledger.c.scope_kind,
          func.coalesce(ledger.c.owner_identity_id, ledger.c.workspace_id, ledger.c.project_id),
          ledger.c.created_at.desc(), ledger.c.id.desc())
    Index("ix_commerce_ledger_attribution_created", ledger.c.attribution_project_id,
          ledger.c.created_at.desc(), ledger.c.id.desc(),
          postgresql_where=text("attribution_project_id IS NOT NULL"))
    Index("ix_commerce_ledger_reservation_id", ledger.c.reservation_id,
          postgresql_where=text("reservation_id IS NOT NULL"))

    campaigns = platform_table(
        "commerce_campaigns",
        Column("code_sha256", String(64), nullable=False),
        Column("title", Text, nullable=False),
        Column("credits", BigInteger, nullable=False),
        Column("kind", Text, nullable=False),
        Column("purposes", JSONB, nullable=False),
        Column("starts_at", DateTime(timezone=True), nullable=False),
        Column("ends_at", DateTime(timezone=True), nullable=False),
        Column("credit_expires_at", DateTime(timezone=True), nullable=False),
        Column("daily", Boolean, nullable=False),
        Column("actor", Text, nullable=False),
        stamp(),
        CheckConstraint("credits > 0 AND starts_at < ends_at AND ends_at <= credit_expires_at", name="window"),
        CheckConstraint("kind IN ('bonus','check_in','special')", name="kind"),
    )
    Index("uq_commerce_campaigns_platform_code", campaigns.c.code_sha256, unique=True,
          postgresql_where=text("scope_kind = 'platform'"))
    Index("uq_commerce_campaigns_workspace_code", campaigns.c.workspace_id, campaigns.c.code_sha256, unique=True,
          postgresql_where=text("scope_kind = 'workspace'"))
    Index("uq_commerce_campaigns_project_code", campaigns.c.project_id, campaigns.c.code_sha256, unique=True,
          postgresql_where=text("scope_kind = 'project'"))

    redemptions = entity_table(
        "commerce_redemptions",
        Column("campaign_id", UUID(as_uuid=False), ForeignKey("commerce_campaigns.id", ondelete="RESTRICT"), nullable=False),
        Column("bucket_id", UUID(as_uuid=False), ForeignKey("commerce_buckets.id", ondelete="RESTRICT"), nullable=False),
        Column("actor", Text, nullable=False),
        Column("period", Text, nullable=False),
        Column("redeemed_day", Date, nullable=False),
        stamp(),
    )
    Index("uq_commerce_redemptions_identity_day", redemptions.c.owner_identity_id, redemptions.c.campaign_id,
          redemptions.c.actor, redemptions.c.redeemed_day, unique=True,
          postgresql_where=text("scope_kind = 'identity'"))
    Index("uq_commerce_redemptions_workspace_day", redemptions.c.workspace_id, redemptions.c.campaign_id,
          redemptions.c.actor, redemptions.c.redeemed_day, unique=True,
          postgresql_where=text("scope_kind = 'workspace'"))
    Index("uq_commerce_redemptions_project_day", redemptions.c.project_id, redemptions.c.campaign_id,
          redemptions.c.actor, redemptions.c.redeemed_day, unique=True,
          postgresql_where=text("scope_kind = 'project'"))
    Index("uq_commerce_redemptions_identity_period", redemptions.c.owner_identity_id, redemptions.c.campaign_id,
          redemptions.c.actor, redemptions.c.period, unique=True,
          postgresql_where=text("scope_kind = 'identity'"))
    Index("uq_commerce_redemptions_workspace_period", redemptions.c.workspace_id, redemptions.c.campaign_id,
          redemptions.c.actor, redemptions.c.period, unique=True,
          postgresql_where=text("scope_kind = 'workspace'"))
    Index("uq_commerce_redemptions_project_period", redemptions.c.project_id, redemptions.c.campaign_id,
          redemptions.c.actor, redemptions.c.period, unique=True,
          postgresql_where=text("scope_kind = 'project'"))
    Index("ix_commerce_redemptions_bucket_id", redemptions.c.bucket_id)

    invoices = entity_table(
        "commerce_invoices",
        Column("billing_workspace_id", UUID(as_uuid=False), ForeignKey("access_workspaces.id", ondelete="RESTRICT")),
        Column("order_id", UUID(as_uuid=False), ForeignKey("commerce_orders.id", ondelete="RESTRICT"), nullable=False),
        Column("actor", Text, nullable=False),
        Column("title", Text, nullable=False),
        Column("tax_id", Text, nullable=False),
        Column("email", Text, nullable=False),
        Column("gateway", Text, nullable=False),
        Column("status", Text, nullable=False),
        Column("external_id", Text),
        Column("error_code", Text),
        Column("document", LargeBinary),
        Column("sha256", String(64)),
        Column("voided_at", DateTime(timezone=True)),
        Column("void_reason", Text),
        stamp(),
        CheckConstraint("status IN ('created','unconfigured','submission_unknown','pending','issued','failed','void')", name="status"),
        CheckConstraint(
            "(status = 'issued' AND document IS NOT NULL AND sha256 IS NOT NULL AND voided_at IS NULL AND void_reason IS NULL) OR "
            "(status = 'void' AND voided_at IS NOT NULL AND void_reason IS NOT NULL AND ((document IS NULL) = (sha256 IS NULL))) OR "
            "(status NOT IN ('issued','void') AND document IS NULL AND sha256 IS NULL AND voided_at IS NULL AND void_reason IS NULL)",
            name="document",
        ),
    )
    Index("uq_commerce_invoices_active_order", invoices.c.order_id, unique=True,
          postgresql_where=text("status <> 'void'"))
    Index("ix_commerce_invoices_scope_created", invoices.c.scope_kind,
          func.coalesce(invoices.c.owner_identity_id, invoices.c.workspace_id, invoices.c.project_id),
          invoices.c.created_at.desc(), invoices.c.id.desc())
    Index("ix_commerce_invoices_actor_inflight", invoices.c.actor, invoices.c.status,
          postgresql_where=text("status IN ('created','unconfigured','submission_unknown','pending')"))
    Index("ix_commerce_invoices_billing_workspace_id", invoices.c.billing_workspace_id,
          postgresql_where=text("billing_workspace_id IS NOT NULL"))

    result = (
        states, receipts, titles,
        plans, rates, settings, orders, events, buckets, reservations, ledger, campaigns, redemptions, invoices,
    )
    return {table.name: table for table in result}


# Canonical trigger specification; migration 0059 upgrades single-key plan rate seals.
COMMERCE_RATE_SEAL_DDL = (
    """CREATE OR REPLACE FUNCTION vsc_commerce_rates_match(plan uuid) RETURNS boolean
LANGUAGE plpgsql STABLE AS $$
DECLARE
 p_scope text; p_ident uuid; p_ws uuid; p_proj uuid;
 wanted jsonb; item jsonb;
BEGIN
 SELECT scope_kind, owner_identity_id, workspace_id, project_id, document->'rates'
   INTO p_scope, p_ident, p_ws, p_proj, wanted
   FROM commerce_plan_versions WHERE id = plan;
 IF NOT FOUND OR jsonb_typeof(wanted) IS DISTINCT FROM 'array' THEN RETURN false; END IF;
 IF jsonb_array_length(wanted) NOT BETWEEN 1 AND 200 THEN RETURN false; END IF;
 FOR item IN SELECT value FROM jsonb_array_elements(wanted) LOOP
  IF jsonb_typeof(item) IS DISTINCT FROM 'object' THEN RETURN false; END IF;
  IF (item - ARRAY['model_id','unit','credits_per_unit']) <> '{}'::jsonb
   OR jsonb_typeof(item->'model_id') IS DISTINCT FROM 'string'
   OR jsonb_typeof(item->'unit') IS DISTINCT FROM 'string'
   OR jsonb_typeof(item->'credits_per_unit') IS DISTINCT FROM 'number'
   OR (item->>'credits_per_unit') !~ '^[1-9][0-9]*$' THEN RETURN false; END IF;
 END LOOP;
 IF EXISTS (
  SELECT 1 FROM commerce_rates r
   WHERE r.plan_id = plan
     AND (r.scope_kind, r.owner_identity_id, r.workspace_id, r.project_id)
         IS DISTINCT FROM (p_scope, p_ident, p_ws, p_proj)
 ) THEN RETURN false; END IF;
 RETURN NOT EXISTS (
  (SELECT (value->>'model_id')::uuid, value->>'unit', (value->>'credits_per_unit')::bigint
   FROM jsonb_array_elements(wanted)
   EXCEPT ALL SELECT model_id, unit, credits_per_unit FROM commerce_rates WHERE plan_id = plan)
  UNION ALL
  (SELECT model_id, unit, credits_per_unit FROM commerce_rates WHERE plan_id = plan
   EXCEPT ALL SELECT (value->>'model_id')::uuid, value->>'unit', (value->>'credits_per_unit')::bigint
   FROM jsonb_array_elements(wanted))
 );
EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN RETURN false;
END $$""",
    """CREATE OR REPLACE FUNCTION vsc_commerce_rates_sealed() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE member_plan uuid;
BEGIN
 IF TG_TABLE_NAME = 'commerce_plan_versions' THEN member_plan := NEW.id; ELSE member_plan := NEW.plan_id; END IF;
 IF NOT vsc_commerce_rates_match(member_plan) THEN
  RAISE EXCEPTION 'commerce rates must equal the complete fixed pricing document' USING ERRCODE = '23514';
 END IF;
 RETURN NULL;
END $$""",
    "CREATE CONSTRAINT TRIGGER commerce_rates_sealed AFTER INSERT ON commerce_plan_versions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_commerce_rates_sealed()",
    "CREATE CONSTRAINT TRIGGER commerce_rates_sealed AFTER INSERT ON commerce_rates DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_commerce_rates_sealed()",
)
COMMERCE_RATE_SEAL_PREFLIGHT = """DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM commerce_plan_versions WHERE NOT vsc_commerce_rates_match(id)) THEN
  RAISE EXCEPTION 'existing rates differ from their fixed pricing document; migration requires explicit repair' USING ERRCODE='23514';
 END IF;
END $$"""


def install_commerce_rate_seals(connection):
    """Install the canonical invariant; inconsistent legacy facts abort atomically."""
    connection.exec_driver_sql('LOCK TABLE commerce_plan_versions, commerce_rates IN SHARE ROW EXCLUSIVE MODE')
    for statement in COMMERCE_RATE_SEAL_DDL:
        connection.exec_driver_sql(statement)
    connection.exec_driver_sql(COMMERCE_RATE_SEAL_PREFLIGHT)
