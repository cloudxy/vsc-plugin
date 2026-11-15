"""Decouple commercial and service scopes while preserving project execution attribution.

Explicit downgrade refuses to discard non-project financial or operational records.
Back up before rollback; ordinary releases must use forward recovery.
"""
from alembic import op
from sqlalchemy import text

revision = "0059_platform_scope_decoupling"
down_revision = "0058_project_creator"
branch_labels = None
depends_on = None

DECOUPLED_TABLES = (
    "commerce_plan_versions",
    "commerce_rates",
    "commerce_settings",
    "commerce_orders",
    "commerce_payment_events",
    "commerce_buckets",
    "commerce_reservations",
    "commerce_ledger",
    "commerce_campaigns",
    "commerce_redemptions",
    "commerce_invoices",
    "service_configuration_versions",
    "service_announcements",
    "service_requests",
    "service_request_events",
    "service_export_files",
    "service_api_keys",
    "service_api_calls",
)

PLATFORM_SCOPED_TABLES = {
    "commerce_plan_versions",
    "commerce_rates",
    "commerce_settings",
    "commerce_campaigns",
    "service_configuration_versions",
    "service_announcements",
}

TRIGGER_BACKFILL_TABLES = (
    "commerce_reservations",
    "commerce_ledger",
    "commerce_redemptions",
    "commerce_campaigns",
    "commerce_invoices",
)

SCOPED_PARENT_GUARD_TABLES = (
    "commerce_plan_versions",
    "commerce_rates",
    "commerce_settings",
    "commerce_reservations",
    "commerce_orders",
    "commerce_payment_events",
    "commerce_invoices",
    "commerce_buckets",
    "commerce_ledger",
    "commerce_redemptions",
    "service_request_events",
    "service_export_files",
    "service_api_calls",
)

PLATFORM_SCOPE_CHECK_SQL = (
    "(scope_kind = 'platform' AND owner_identity_id IS NULL AND workspace_id IS NULL AND project_id IS NULL) OR "
    "(scope_kind = 'workspace' AND workspace_id IS NOT NULL AND owner_identity_id IS NULL AND project_id IS NULL) OR "
    "(scope_kind = 'project' AND project_id IS NOT NULL AND owner_identity_id IS NULL AND workspace_id IS NULL)"
)

ENTITY_SCOPE_CHECK_SQL = (
    "(scope_kind = 'identity' AND owner_identity_id IS NOT NULL AND workspace_id IS NULL AND project_id IS NULL) OR "
    "(scope_kind = 'workspace' AND workspace_id IS NOT NULL AND owner_identity_id IS NULL AND project_id IS NULL) OR "
    "(scope_kind = 'project' AND project_id IS NOT NULL AND owner_identity_id IS NULL AND workspace_id IS NULL)"
)


def _snapshot_metrics(conn):
    counts = {
        tbl: int(conn.scalar(text(f"SELECT count(*) FROM {tbl}")) or 0)
        for tbl in DECOUPLED_TABLES + ("commerce_workspace_transfers", "service_api_call_jobs")
    }
    ledger_sum = int(conn.scalar(text("SELECT COALESCE(SUM(delta), 0) FROM commerce_ledger")) or 0)
    return counts, ledger_sum


def upgrade():
    conn = op.get_bind()
    lock_targets = ", ".join(
        DECOUPLED_TABLES
        + (
            "commerce_workspace_transfers",
            "service_api_call_jobs",
            "asset_identities",
            "creative_objects",
            "generation_jobs",
            "asset_card_form_versions",
            "asset_card_favorites",
            "creative_canvases",
            "task_notification_events",
            "task_notification_reads",
        )
    )
    conn.execute(text(f"LOCK TABLE {lock_targets} IN ACCESS EXCLUSIVE MODE"))

    # Step 1: Preflight check on legacy rate seals and baseline conservation metrics.
    conn.execute(text("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM commerce_plan_versions WHERE NOT vsc_commerce_rates_match(project_id, id)) THEN
            RAISE EXCEPTION 'existing rates differ from their fixed pricing document; migration requires explicit repair'
                USING ERRCODE = '23514';
        END IF;
    END $$"""))
    before_counts, before_ledger_sum = _snapshot_metrics(conn)

    # Step 2: Add scope and attribution columns, then strip temporary defaults immediately.
    for tbl in DECOUPLED_TABLES:
        op.execute(f"ALTER TABLE {tbl} ADD COLUMN scope_kind TEXT NOT NULL DEFAULT 'project'")
        op.execute(f"ALTER TABLE {tbl} ADD COLUMN owner_identity_id UUID")
        if tbl != "commerce_invoices":
            op.execute(f"ALTER TABLE {tbl} ADD COLUMN workspace_id UUID")
        op.execute(f"ALTER TABLE {tbl} ALTER COLUMN scope_kind DROP DEFAULT")

    op.execute("ALTER TABLE commerce_plan_versions ADD COLUMN base_version_id UUID")
    op.execute("ALTER TABLE commerce_reservations ADD COLUMN attribution_project_id UUID")
    op.execute("ALTER TABLE commerce_ledger ADD COLUMN attribution_project_id UUID")
    op.execute("ALTER TABLE commerce_ledger ADD COLUMN job_id UUID")
    op.execute("ALTER TABLE commerce_redemptions ADD COLUMN redeemed_day DATE")
    op.execute("ALTER TABLE commerce_invoices ADD COLUMN billing_workspace_id UUID")
    op.execute("ALTER TABLE commerce_invoices ADD COLUMN voided_at TIMESTAMP WITH TIME ZONE")
    op.execute("ALTER TABLE commerce_invoices ADD COLUMN void_reason TEXT")
    op.execute("ALTER TABLE service_requests ALTER COLUMN contact SET DEFAULT ''")
    op.execute("ALTER TABLE asset_identities ADD COLUMN updated_at TIMESTAMP WITH TIME ZONE")

    # Trigger-safe deterministic backfill on existing immutable/guarded tables.
    for tbl in TRIGGER_BACKFILL_TABLES:
        op.execute(f"ALTER TABLE {tbl} DISABLE TRIGGER USER")
    op.execute("UPDATE commerce_reservations SET attribution_project_id = project_id")
    op.execute("""
        UPDATE commerce_ledger l
           SET attribution_project_id = r.project_id,
               job_id = r.job_id
          FROM commerce_reservations r
         WHERE l.reservation_id = r.id
           AND l.project_id = r.project_id
    """)
    op.execute("UPDATE commerce_redemptions SET redeemed_day = (created_at AT TIME ZONE 'UTC')::date")
    op.execute("UPDATE commerce_campaigns SET starts_at = COALESCE(starts_at, created_at) WHERE starts_at IS NULL")
    op.execute("""
        UPDATE commerce_invoices
           SET billing_workspace_id = workspace_id,
               workspace_id = NULL
         WHERE project_id IS NOT NULL
           AND workspace_id IS NOT NULL
    """)
    for tbl in TRIGGER_BACKFILL_TABLES:
        op.execute(f"ALTER TABLE {tbl} ENABLE TRIGGER USER")

    op.execute("""
        UPDATE asset_identities ai
           SET updated_at = COALESCE(
               (SELECT MAX(fv.created_at)
                  FROM asset_card_form_versions fv
                  JOIN asset_card_forms f
                    ON f.project_id = fv.project_id AND f.id = fv.form_id
                 WHERE f.project_id = ai.project_id AND f.asset_id = ai.id),
               (SELECT co.created_at
                  FROM creative_objects co
                 WHERE co.project_id = ai.project_id AND co.id = ai.id),
               now()
           )
    """)

    op.execute("ALTER TABLE commerce_reservations ALTER COLUMN attribution_project_id SET NOT NULL")
    op.execute("ALTER TABLE commerce_redemptions ALTER COLUMN redeemed_day SET NOT NULL")
    op.execute("ALTER TABLE commerce_campaigns ALTER COLUMN starts_at SET NOT NULL")
    op.execute("ALTER TABLE asset_identities ALTER COLUMN updated_at SET NOT NULL")
    op.execute("ALTER TABLE asset_identities ALTER COLUMN updated_at SET DEFAULT now()")

    # Step 3: Drop dependent cross-table FKs and legacy composite FKs/UQs/IXs before PK swap.
    for cname in (
        "fk_commerce_workspace_transfers_project_id_source_bucke_e21e",
        "fk_commerce_workspace_transfers_project_id_source_entry_0f33",
        "fk_commerce_workspace_transfers_target_project_id_targe_2c32",
        "fk_commerce_workspace_transfers_target_project_id_targe_6227",
    ):
        op.execute(f"ALTER TABLE commerce_workspace_transfers DROP CONSTRAINT {cname}")
    op.execute(
        "ALTER TABLE service_api_call_jobs "
        "DROP CONSTRAINT fk_service_api_call_jobs_project_id_call_event_id_servi_db1a"
    )

    legacy_constraints = (
        ("commerce_plan_versions", "uq_commerce_plan_versions_project_id_plan_key_version"),
        ("commerce_rates", "fk_commerce_rates_project_id_plan_id_commerce_plan_versions"),
        ("commerce_rates", "fk_commerce_rates_model_id_provider_models"),
        ("commerce_rates", "uq_commerce_rates_project_id_plan_id_model_id_unit"),
        ("commerce_settings", "fk_commerce_settings_project_id_price_version_id_commer_b77e"),
        ("commerce_settings", "uq_commerce_settings_project_id"),
        ("commerce_orders", "fk_commerce_orders_project_id_plan_id_commerce_plan_versions"),
        ("commerce_orders", "fk_commerce_orders_project_id_renewal_of_order_id_comme_19e0"),
        ("commerce_orders", "uq_commerce_orders_project_id_gateway_external_id"),
        ("commerce_payment_events", "fk_commerce_payment_events_project_id_order_id_commerce_orders"),
        ("commerce_payment_events", "uq_commerce_payment_events_project_id_gateway_event_id"),
        ("commerce_buckets", "fk_commerce_buckets_project_id_order_id_commerce_orders"),
        ("commerce_buckets", "fk_commerce_buckets_project_id_parent_bucket_id_commerc_f1df"),
        ("commerce_buckets", "uq_commerce_buckets_project_id_source_key"),
        ("commerce_reservations", "fk_commerce_reservations_project_id_job_id_generation_jobs"),
        ("commerce_reservations", "fk_commerce_reservations_project_id_price_version_id_co_f1da"),
        ("commerce_reservations", "uq_commerce_reservations_project_id_job_id"),
        ("commerce_ledger", "fk_commerce_ledger_project_id_bucket_id_commerce_buckets"),
        ("commerce_ledger", "fk_commerce_ledger_project_id_reservation_id_commerce_r_6c18"),
        ("commerce_ledger", "uq_commerce_ledger_project_id_event_key"),
        ("commerce_campaigns", "uq_commerce_campaigns_project_id_code_sha256"),
        ("commerce_campaigns", "ck_commerce_campaigns_limits"),
        ("commerce_redemptions", "fk_commerce_redemptions_project_id_campaign_id_commerce_9be6"),
        ("commerce_redemptions", "fk_commerce_redemptions_project_id_bucket_id_commerce_buckets"),
        ("commerce_redemptions", "uq_commerce_redemptions_project_id_campaign_id_actor_period"),
        ("commerce_invoices", "fk_commerce_invoices_project_id_order_id_commerce_orders"),
        ("commerce_invoices", "fk_commerce_invoices_workspace_id_access_workspaces"),
        ("commerce_invoices", "uq_commerce_invoices_project_id_order_id"),
        ("commerce_invoices", "ck_commerce_invoices_status"),
        ("commerce_invoices", "ck_commerce_invoices_document"),
        ("service_configuration_versions", "uq_service_configuration_versions_project_id_version"),
        ("service_announcements", "uq_service_announcements_project_id_announcement_key_version"),
        ("service_requests", "uq_service_requests_project_id_id_requester_id"),
        ("service_request_events", "fk_service_request_events_project_id_request_id_service_6978"),
        ("service_request_events", "uq_service_request_events_project_id_request_id_sequence"),
        ("service_export_files", "fk_service_export_files_project_id_request_id_service_requests"),
        ("service_export_files", "fk_service_export_files_project_id_request_id_requester_c429"),
        ("service_export_files", "uq_service_export_files_project_id_request_id"),
        ("service_api_keys", "uq_service_api_keys_id"),
        ("service_api_calls", "fk_service_api_calls_project_id_api_key_id_service_api_keys"),
        ("service_api_calls", "uq_service_api_calls_project_id_call_id_phase"),
    )
    for tbl, cname in legacy_constraints:
        if cname.startswith("fk_"):
            op.execute(f"ALTER TABLE {tbl} DROP CONSTRAINT {cname}")
    for tbl, cname in legacy_constraints:
        if not cname.startswith("fk_"):
            op.execute(f"ALTER TABLE {tbl} DROP CONSTRAINT {cname}")

    legacy_indexes = (
        "ix_commerce_rates_model_id",
        "ix_commerce_rates_plan_id",
        "ix_commerce_settings_price_version_id",
        "ix_commerce_orders_external_id",
        "ix_commerce_orders_plan_id",
        "ix_commerce_orders_renewal_of_order_id",
        "ix_commerce_payment_events_event_id",
        "ix_commerce_payment_events_order_id",
        "ix_commerce_buckets_order_id",
        "ix_commerce_buckets_parent_bucket_id",
        "ix_commerce_reservations_job_id",
        "ix_commerce_reservations_price_version_id",
        "ix_commerce_ledger_bucket_id",
        "ix_commerce_ledger_reservation_id",
        "ix_commerce_redemptions_bucket_id",
        "ix_commerce_redemptions_campaign_id",
        "ix_commerce_invoices_external_id",
        "ix_commerce_invoices_order_id",
        "ix_commerce_invoices_tax_id",
        "ix_commerce_invoices_workspace_id",
        "ix_service_requests_artifact_id",
        "ix_service_requests_feedback_manage",
        "ix_service_requests_feedback_owner",
        "ix_service_requests_media_id",
        "ix_service_requests_requester_id",
        "ix_service_request_events_request_id",
        "ix_service_export_files_request_id",
        "ix_service_export_files_requester_id",
        "ix_service_api_keys_identity_id",
        "ix_service_api_calls_api_key_id",
        "ix_service_api_calls_call_id",
        "ix_service_api_calls_run_version_id",
        "ix_task_notification_reads_identity",
    )
    for ix_name in legacy_indexes:
        op.execute(f"DROP INDEX {ix_name}")

    # Switch PKs to single-column (id), relax project_id NOT NULL, add scope target & scope FKs.
    for tbl in DECOUPLED_TABLES:
        op.execute(f"ALTER TABLE {tbl} DROP CONSTRAINT pk_{tbl}")
        op.execute(f"ALTER TABLE {tbl} ADD CONSTRAINT pk_{tbl} PRIMARY KEY (id)")
        op.execute(f"ALTER TABLE {tbl} ALTER COLUMN project_id DROP NOT NULL")
        check_sql = PLATFORM_SCOPE_CHECK_SQL if tbl in PLATFORM_SCOPED_TABLES else ENTITY_SCOPE_CHECK_SQL
        op.execute(f"ALTER TABLE {tbl} ADD CONSTRAINT ck_{tbl}_scope_target CHECK ({check_sql})")
        if tbl == "service_configuration_versions":
            id_fk = "fk_service_configuration_versions_owner_identity_id_acc_352c"
            ws_fk = "fk_service_configuration_versions_workspace_id_access_w_47bb"
        else:
            id_fk = f"fk_{tbl}_owner_identity_id_access_identities"
            ws_fk = f"fk_{tbl}_workspace_id_access_workspaces"
        op.execute(
            f"ALTER TABLE {tbl} ADD CONSTRAINT {id_fk} "
            "FOREIGN KEY (owner_identity_id) REFERENCES access_identities (id) ON DELETE RESTRICT"
        )
        op.execute(
            f"ALTER TABLE {tbl} ADD CONSTRAINT {ws_fk} "
            "FOREIGN KEY (workspace_id) REFERENCES access_workspaces (id) ON DELETE RESTRICT"
        )

    # Replacement unique keys and rebound cross-table FKs.
    op.execute("ALTER TABLE commerce_buckets ADD CONSTRAINT uq_commerce_buckets_project_id_id UNIQUE (project_id, id)")
    op.execute("ALTER TABLE commerce_ledger ADD CONSTRAINT uq_commerce_ledger_project_id_id UNIQUE (project_id, id)")
    op.execute("ALTER TABLE service_api_calls ADD CONSTRAINT uq_service_api_calls_project_id_id UNIQUE (project_id, id)")
    op.execute("ALTER TABLE service_requests ADD CONSTRAINT uq_service_requests_id_requester_id UNIQUE (id, requester_id)")

    op.execute(
        "ALTER TABLE commerce_workspace_transfers "
        "ADD CONSTRAINT fk_commerce_workspace_transfers_project_id_source_bucke_e21e "
        "FOREIGN KEY (project_id, source_bucket_id) REFERENCES commerce_buckets (project_id, id) ON DELETE RESTRICT"
    )
    op.execute(
        "ALTER TABLE commerce_workspace_transfers "
        "ADD CONSTRAINT fk_commerce_workspace_transfers_project_id_source_entry_0f33 "
        "FOREIGN KEY (project_id, source_entry_id) REFERENCES commerce_ledger (project_id, id) ON DELETE RESTRICT"
    )
    op.execute(
        "ALTER TABLE commerce_workspace_transfers "
        "ADD CONSTRAINT fk_commerce_workspace_transfers_target_project_id_targe_2c32 "
        "FOREIGN KEY (target_project_id, target_bucket_id) REFERENCES commerce_buckets (project_id, id)"
    )
    op.execute(
        "ALTER TABLE commerce_workspace_transfers "
        "ADD CONSTRAINT fk_commerce_workspace_transfers_target_project_id_targe_6227 "
        "FOREIGN KEY (target_project_id, target_entry_id) REFERENCES commerce_ledger (project_id, id)"
    )
    op.execute(
        "ALTER TABLE service_api_call_jobs "
        "ADD CONSTRAINT fk_service_api_call_jobs_project_id_call_event_id_servi_db1a "
        "FOREIGN KEY (project_id, call_event_id) REFERENCES service_api_calls (project_id, id) ON DELETE RESTRICT"
    )

    # Single-column parent FKs, MATCH FULL attribution FKs, UQs, and updated CKs.
    ddl_constraints = (
        "ALTER TABLE commerce_plan_versions ADD CONSTRAINT fk_commerce_plan_versions_base_version_id_commerce_plan_9d58 FOREIGN KEY (base_version_id) REFERENCES commerce_plan_versions (id) ON DELETE RESTRICT",
        "ALTER TABLE commerce_rates ADD CONSTRAINT uq_commerce_rates_plan_model_unit UNIQUE (plan_id, model_id, unit)",
        "ALTER TABLE commerce_rates ADD CONSTRAINT fk_commerce_rates_plan_id_commerce_plan_versions FOREIGN KEY (plan_id) REFERENCES commerce_plan_versions (id) ON DELETE RESTRICT",
        "ALTER TABLE commerce_rates ADD CONSTRAINT fk_commerce_rates_model_id_provider_models FOREIGN KEY (model_id) REFERENCES provider_models (id) ON DELETE RESTRICT",
        "ALTER TABLE commerce_settings ADD CONSTRAINT fk_commerce_settings_price_version_id_commerce_plan_versions FOREIGN KEY (price_version_id) REFERENCES commerce_plan_versions (id) ON DELETE RESTRICT",
        "ALTER TABLE commerce_orders ADD CONSTRAINT fk_commerce_orders_plan_id_commerce_plan_versions FOREIGN KEY (plan_id) REFERENCES commerce_plan_versions (id) ON DELETE RESTRICT",
        "ALTER TABLE commerce_orders ADD CONSTRAINT fk_commerce_orders_renewal_of_order_id_commerce_orders FOREIGN KEY (renewal_of_order_id) REFERENCES commerce_orders (id) ON DELETE RESTRICT",
        "ALTER TABLE commerce_payment_events ADD CONSTRAINT uq_commerce_payment_events_gateway_event_id UNIQUE (gateway, event_id)",
        "ALTER TABLE commerce_payment_events ADD CONSTRAINT fk_commerce_payment_events_order_id_commerce_orders FOREIGN KEY (order_id) REFERENCES commerce_orders (id) ON DELETE RESTRICT",
        "ALTER TABLE commerce_buckets ADD CONSTRAINT fk_commerce_buckets_order_id_commerce_orders FOREIGN KEY (order_id) REFERENCES commerce_orders (id) ON DELETE RESTRICT",
        "ALTER TABLE commerce_buckets ADD CONSTRAINT fk_commerce_buckets_parent_bucket_id_commerce_buckets FOREIGN KEY (parent_bucket_id) REFERENCES commerce_buckets (id) ON DELETE RESTRICT",
        "ALTER TABLE commerce_reservations ADD CONSTRAINT uq_commerce_reservations_attribution_job UNIQUE (attribution_project_id, job_id)",
        "ALTER TABLE commerce_reservations ADD CONSTRAINT uq_commerce_reservations_attribution_job_id UNIQUE (attribution_project_id, job_id, id)",
        "ALTER TABLE commerce_reservations ADD CONSTRAINT fk_commerce_reservations_attribution_project_id_projects FOREIGN KEY (attribution_project_id) REFERENCES projects (id) ON DELETE RESTRICT",
        "ALTER TABLE commerce_reservations ADD CONSTRAINT fk_commerce_reservations_attribution_project_id_job_id__875a FOREIGN KEY (attribution_project_id, job_id) REFERENCES generation_jobs (project_id, id) MATCH FULL ON DELETE RESTRICT",
        "ALTER TABLE commerce_reservations ADD CONSTRAINT fk_commerce_reservations_price_version_id_commerce_plan_2953 FOREIGN KEY (price_version_id) REFERENCES commerce_plan_versions (id) ON DELETE RESTRICT",
        "ALTER TABLE commerce_ledger ADD CONSTRAINT ck_commerce_ledger_attribution_pair CHECK ((kind IN ('reserve','release') AND reservation_id IS NOT NULL AND attribution_project_id IS NOT NULL AND job_id IS NOT NULL) OR (kind NOT IN ('reserve','release') AND reservation_id IS NULL AND attribution_project_id IS NULL AND job_id IS NULL))",
        "ALTER TABLE commerce_ledger ADD CONSTRAINT fk_commerce_ledger_bucket_id_commerce_buckets FOREIGN KEY (bucket_id) REFERENCES commerce_buckets (id) ON DELETE RESTRICT",
        "ALTER TABLE commerce_ledger ADD CONSTRAINT fk_commerce_ledger_reservation_id_commerce_reservations FOREIGN KEY (reservation_id) REFERENCES commerce_reservations (id) ON DELETE RESTRICT",
        "ALTER TABLE commerce_ledger ADD CONSTRAINT fk_commerce_ledger_attribution_project_id_job_id_genera_3fa5 FOREIGN KEY (attribution_project_id, job_id) REFERENCES generation_jobs (project_id, id) MATCH FULL ON DELETE RESTRICT",
        "ALTER TABLE commerce_ledger ADD CONSTRAINT fk_commerce_ledger_attribution_project_id_job_id_reserv_6e9d FOREIGN KEY (attribution_project_id, job_id, reservation_id) REFERENCES commerce_reservations (attribution_project_id, job_id, id) MATCH FULL ON DELETE RESTRICT",
        "ALTER TABLE commerce_campaigns ADD CONSTRAINT ck_commerce_campaigns_window CHECK (credits > 0 AND starts_at < ends_at AND ends_at <= credit_expires_at)",
        "ALTER TABLE commerce_redemptions ADD CONSTRAINT fk_commerce_redemptions_campaign_id_commerce_campaigns FOREIGN KEY (campaign_id) REFERENCES commerce_campaigns (id) ON DELETE RESTRICT",
        "ALTER TABLE commerce_redemptions ADD CONSTRAINT fk_commerce_redemptions_bucket_id_commerce_buckets FOREIGN KEY (bucket_id) REFERENCES commerce_buckets (id) ON DELETE RESTRICT",
        "ALTER TABLE commerce_invoices ADD CONSTRAINT ck_commerce_invoices_status CHECK (status IN ('created','unconfigured','submission_unknown','pending','issued','failed','void'))",
        "ALTER TABLE commerce_invoices ADD CONSTRAINT ck_commerce_invoices_document CHECK ((status = 'issued' AND document IS NOT NULL AND sha256 IS NOT NULL AND voided_at IS NULL AND void_reason IS NULL) OR (status = 'void' AND voided_at IS NOT NULL AND void_reason IS NOT NULL AND ((document IS NULL) = (sha256 IS NULL))) OR (status NOT IN ('issued','void') AND document IS NULL AND sha256 IS NULL AND voided_at IS NULL AND void_reason IS NULL))",
        "ALTER TABLE commerce_invoices ADD CONSTRAINT fk_commerce_invoices_billing_workspace_id_access_workspaces FOREIGN KEY (billing_workspace_id) REFERENCES access_workspaces (id) ON DELETE RESTRICT",
        "ALTER TABLE commerce_invoices ADD CONSTRAINT fk_commerce_invoices_order_id_commerce_orders FOREIGN KEY (order_id) REFERENCES commerce_orders (id) ON DELETE RESTRICT",
        "ALTER TABLE service_requests ADD CONSTRAINT ck_service_requests_project_attachments CHECK (project_id IS NOT NULL OR (artifact_id IS NULL AND media_id IS NULL))",
        "ALTER TABLE service_requests ADD CONSTRAINT ck_service_requests_contact CHECK (char_length(contact) <= 254)",
        "ALTER TABLE service_request_events ADD CONSTRAINT uq_service_request_events_request_sequence UNIQUE (request_id, sequence)",
        "ALTER TABLE service_request_events ADD CONSTRAINT fk_service_request_events_request_id_service_requests FOREIGN KEY (request_id) REFERENCES service_requests (id) ON DELETE RESTRICT",
        "ALTER TABLE service_export_files ADD CONSTRAINT uq_service_export_files_request_id UNIQUE (request_id)",
        "ALTER TABLE service_export_files ADD CONSTRAINT fk_service_export_files_request_id_service_requests FOREIGN KEY (request_id) REFERENCES service_requests (id) ON DELETE RESTRICT",
        "ALTER TABLE service_export_files ADD CONSTRAINT fk_service_export_files_request_id_requester_id_service_d82f FOREIGN KEY (request_id, requester_id) REFERENCES service_requests (id, requester_id) MATCH FULL ON DELETE RESTRICT",
        "ALTER TABLE service_api_calls ADD CONSTRAINT uq_service_api_calls_call_id_phase UNIQUE (call_id, phase)",
        "ALTER TABLE service_api_calls ADD CONSTRAINT ck_service_api_calls_project_run CHECK (project_id IS NOT NULL OR run_version_id IS NULL)",
        "ALTER TABLE service_api_calls ADD CONSTRAINT fk_service_api_calls_api_key_id_service_api_keys FOREIGN KEY (api_key_id) REFERENCES service_api_keys (id) ON DELETE RESTRICT",
    )
    for stmt in ddl_constraints:
        op.execute(stmt)

    # Step 4: Create the 3 new tables and append-only receipt trigger.
    op.execute("""
        CREATE TABLE scoped_domain_states (
            domain TEXT NOT NULL,
            scope_kind TEXT NOT NULL,
            scope_key TEXT NOT NULL,
            owner_identity_id UUID,
            workspace_id UUID,
            revision BIGINT DEFAULT '0' NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            CONSTRAINT pk_scoped_domain_states PRIMARY KEY (domain, scope_kind, scope_key),
            CONSTRAINT ck_scoped_domain_states_domain CHECK (domain IN ('commerce','service_operations')),
            CONSTRAINT ck_scoped_domain_states_scope_kind CHECK (scope_kind IN ('identity','workspace','platform')),
            CONSTRAINT ck_scoped_domain_states_revision CHECK (revision >= 0),
            CONSTRAINT ck_scoped_domain_states_scope_target CHECK (
                (scope_kind = 'platform' AND scope_key = 'platform' AND owner_identity_id IS NULL AND workspace_id IS NULL) OR
                (scope_kind = 'identity' AND owner_identity_id IS NOT NULL AND workspace_id IS NULL AND scope_key = owner_identity_id::text) OR
                (scope_kind = 'workspace' AND workspace_id IS NOT NULL AND owner_identity_id IS NULL AND scope_key = workspace_id::text)
            ),
            CONSTRAINT fk_scoped_domain_states_owner_identity_id_access_identities
                FOREIGN KEY (owner_identity_id) REFERENCES access_identities (id) ON DELETE RESTRICT,
            CONSTRAINT fk_scoped_domain_states_workspace_id_access_workspaces
                FOREIGN KEY (workspace_id) REFERENCES access_workspaces (id) ON DELETE RESTRICT
        )
    """)
    op.execute("""
        CREATE TABLE scoped_command_receipts (
            domain TEXT NOT NULL,
            scope_kind TEXT NOT NULL,
            scope_key TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            actor TEXT NOT NULL,
            action TEXT NOT NULL,
            request_sha256 VARCHAR(64) NOT NULL,
            revision BIGINT NOT NULL,
            response JSONB NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            CONSTRAINT pk_scoped_command_receipts PRIMARY KEY (domain, scope_kind, scope_key, idempotency_key),
            CONSTRAINT fk_scoped_command_receipts_domain_scope_kind_scope_key__5af6
                FOREIGN KEY (domain, scope_kind, scope_key)
                REFERENCES scoped_domain_states (domain, scope_kind, scope_key) ON DELETE RESTRICT,
            CONSTRAINT ck_scoped_command_receipts_idempotency_key CHECK (length(btrim(idempotency_key)) BETWEEN 1 AND 200),
            CONSTRAINT ck_scoped_command_receipts_revision CHECK (revision > 0),
            CONSTRAINT ck_scoped_command_receipts_request_sha256_format CHECK (request_sha256 IS NULL OR request_sha256 ~ '^[0-9a-f]{64}$')
        )
    """)
    op.execute(
        "CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON scoped_command_receipts "
        "FOR EACH ROW EXECUTE FUNCTION vsc_reject_mutation()"
    )
    op.execute(f"""
        CREATE TABLE commerce_invoice_titles (
            id UUID NOT NULL,
            scope_kind TEXT NOT NULL,
            owner_identity_id UUID,
            workspace_id UUID,
            project_id UUID,
            title_type TEXT NOT NULL,
            title TEXT NOT NULL,
            tax_id TEXT NOT NULL,
            email TEXT NOT NULL,
            bank_name TEXT,
            bank_account_masked TEXT,
            billing_address_phone TEXT,
            is_default BOOLEAN DEFAULT 'false' NOT NULL,
            created_by UUID NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            CONSTRAINT pk_commerce_invoice_titles PRIMARY KEY (id),
            CONSTRAINT ck_commerce_invoice_titles_title_type CHECK (title_type IN ('enterprise_normal','enterprise_special','personal')),
            CONSTRAINT ck_commerce_invoice_titles_title_email CHECK (length(btrim(title)) BETWEEN 1 AND 200 AND length(email) BETWEEN 3 AND 254),
            CONSTRAINT ck_commerce_invoice_titles_tax_id CHECK (
                (title_type = 'personal' AND tax_id = 'PERSONAL') OR
                (title_type IN ('enterprise_normal','enterprise_special') AND tax_id <> 'PERSONAL' AND tax_id ~ '^[A-Z0-9]{{15,32}}$')
            ),
            CONSTRAINT ck_commerce_invoice_titles_optional_fields CHECK (
                (bank_name IS NULL OR char_length(bank_name) <= 200) AND
                (bank_account_masked IS NULL OR char_length(bank_account_masked) <= 64) AND
                (billing_address_phone IS NULL OR char_length(billing_address_phone) <= 300)
            ),
            CONSTRAINT ck_commerce_invoice_titles_scope_target CHECK ({ENTITY_SCOPE_CHECK_SQL}),
            CONSTRAINT fk_commerce_invoice_titles_owner_identity_id_access_identities
                FOREIGN KEY (owner_identity_id) REFERENCES access_identities (id) ON DELETE RESTRICT,
            CONSTRAINT fk_commerce_invoice_titles_workspace_id_access_workspaces
                FOREIGN KEY (workspace_id) REFERENCES access_workspaces (id) ON DELETE RESTRICT,
            CONSTRAINT fk_commerce_invoice_titles_project_id_projects
                FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE RESTRICT,
            CONSTRAINT fk_commerce_invoice_titles_created_by_access_identities
                FOREIGN KEY (created_by) REFERENCES access_identities (id) ON DELETE RESTRICT
        )
    """)

    # Partial unique indexes, ESR indexes, and cross-project aggregation indexes.
    ddl_indexes = (
        "CREATE INDEX ix_scoped_domain_states_owner_identity_id ON scoped_domain_states (owner_identity_id) WHERE owner_identity_id IS NOT NULL",
        "CREATE INDEX ix_scoped_domain_states_workspace_id ON scoped_domain_states (workspace_id) WHERE workspace_id IS NOT NULL",
        "CREATE INDEX ix_commerce_invoice_titles_created_by ON commerce_invoice_titles (created_by)",
        "CREATE INDEX ix_commerce_invoice_titles_identity_list ON commerce_invoice_titles (owner_identity_id, is_default DESC, updated_at DESC, id) WHERE scope_kind = 'identity'",
        "CREATE INDEX ix_commerce_invoice_titles_project_list ON commerce_invoice_titles (project_id, is_default DESC, updated_at DESC, id) WHERE scope_kind = 'project'",
        "CREATE INDEX ix_commerce_invoice_titles_workspace_list ON commerce_invoice_titles (workspace_id, is_default DESC, updated_at DESC, id) WHERE scope_kind = 'workspace'",
        "CREATE UNIQUE INDEX uq_commerce_invoice_titles_default_identity ON commerce_invoice_titles (owner_identity_id) WHERE scope_kind = 'identity' AND is_default = true",
        "CREATE UNIQUE INDEX uq_commerce_invoice_titles_default_project ON commerce_invoice_titles (project_id) WHERE scope_kind = 'project' AND is_default = true",
        "CREATE UNIQUE INDEX uq_commerce_invoice_titles_default_workspace ON commerce_invoice_titles (workspace_id) WHERE scope_kind = 'workspace' AND is_default = true",
        "CREATE UNIQUE INDEX uq_commerce_invoice_titles_identity_title_tax ON commerce_invoice_titles (owner_identity_id, lower(btrim(title)), tax_id) WHERE scope_kind = 'identity'",
        "CREATE UNIQUE INDEX uq_commerce_invoice_titles_project_title_tax ON commerce_invoice_titles (project_id, lower(btrim(title)), tax_id) WHERE scope_kind = 'project'",
        "CREATE UNIQUE INDEX uq_commerce_invoice_titles_workspace_title_tax ON commerce_invoice_titles (workspace_id, lower(btrim(title)), tax_id) WHERE scope_kind = 'workspace'",
        "CREATE INDEX ix_commerce_plan_versions_base_version_id ON commerce_plan_versions (base_version_id) WHERE base_version_id IS NOT NULL",
        "CREATE UNIQUE INDEX uq_commerce_plan_versions_platform_key_ver ON commerce_plan_versions (plan_key, version) WHERE scope_kind = 'platform'",
        "CREATE UNIQUE INDEX uq_commerce_plan_versions_project_key_ver ON commerce_plan_versions (project_id, plan_key, version) WHERE scope_kind = 'project'",
        "CREATE UNIQUE INDEX uq_commerce_plan_versions_workspace_key_ver ON commerce_plan_versions (workspace_id, plan_key, version) WHERE scope_kind = 'workspace'",
        "CREATE INDEX ix_commerce_rates_model_id ON commerce_rates (model_id)",
        "CREATE INDEX ix_commerce_settings_price_version_id ON commerce_settings (price_version_id)",
        "CREATE UNIQUE INDEX uq_commerce_settings_platform ON commerce_settings (scope_kind) WHERE scope_kind = 'platform'",
        "CREATE UNIQUE INDEX uq_commerce_settings_project ON commerce_settings (project_id) WHERE scope_kind = 'project'",
        "CREATE UNIQUE INDEX uq_commerce_settings_workspace ON commerce_settings (workspace_id) WHERE scope_kind = 'workspace'",
        "CREATE INDEX ix_commerce_orders_actor_unsettled ON commerce_orders (actor, status) WHERE status IN ('created','checkout_unknown','pending','refund_unknown')",
        "CREATE INDEX ix_commerce_orders_plan_id ON commerce_orders (plan_id)",
        "CREATE INDEX ix_commerce_orders_renewal_of_order_id ON commerce_orders (renewal_of_order_id) WHERE renewal_of_order_id IS NOT NULL",
        "CREATE INDEX ix_commerce_orders_scope_created ON commerce_orders (scope_kind, coalesce(owner_identity_id, workspace_id, project_id), created_at DESC, id DESC)",
        "CREATE UNIQUE INDEX uq_commerce_orders_gateway_external_id ON commerce_orders (gateway, external_id) WHERE external_id IS NOT NULL",
        "CREATE INDEX ix_commerce_payment_events_order_id ON commerce_payment_events (order_id)",
        "CREATE INDEX ix_commerce_buckets_order_id ON commerce_buckets (order_id) WHERE order_id IS NOT NULL",
        "CREATE INDEX ix_commerce_buckets_owner_actor_active ON commerce_buckets (owner_actor, expires_at) WHERE owner_actor IS NOT NULL",
        "CREATE INDEX ix_commerce_buckets_parent_bucket_id ON commerce_buckets (parent_bucket_id) WHERE parent_bucket_id IS NOT NULL",
        "CREATE INDEX ix_commerce_buckets_scope_expiry ON commerce_buckets (scope_kind, coalesce(owner_identity_id, workspace_id, project_id), expires_at ASC NULLS LAST, created_at ASC)",
        "CREATE UNIQUE INDEX uq_commerce_buckets_identity_source_key ON commerce_buckets (owner_identity_id, source_key) WHERE scope_kind = 'identity'",
        "CREATE UNIQUE INDEX uq_commerce_buckets_project_source_key ON commerce_buckets (project_id, source_key) WHERE scope_kind = 'project'",
        "CREATE UNIQUE INDEX uq_commerce_buckets_workspace_source_key ON commerce_buckets (workspace_id, source_key) WHERE scope_kind = 'workspace'",
        "CREATE INDEX ix_commerce_reservations_actor_reserved ON commerce_reservations (account_actor) WHERE status = 'reserved'",
        "CREATE INDEX ix_commerce_reservations_attribution_status_actor ON commerce_reservations (attribution_project_id, status, account_actor)",
        "CREATE INDEX ix_commerce_reservations_price_version_id ON commerce_reservations (price_version_id)",
        "CREATE INDEX ix_commerce_reservations_scope_status_actor ON commerce_reservations (scope_kind, coalesce(owner_identity_id, workspace_id, project_id), status, account_actor)",
        "CREATE INDEX ix_commerce_ledger_attribution_created ON commerce_ledger (attribution_project_id, created_at DESC, id DESC) WHERE attribution_project_id IS NOT NULL",
        "CREATE INDEX ix_commerce_ledger_bucket_id ON commerce_ledger (bucket_id)",
        "CREATE INDEX ix_commerce_ledger_reservation_id ON commerce_ledger (reservation_id) WHERE reservation_id IS NOT NULL",
        "CREATE INDEX ix_commerce_ledger_scope_created ON commerce_ledger (scope_kind, coalesce(owner_identity_id, workspace_id, project_id), created_at DESC, id DESC)",
        "CREATE UNIQUE INDEX uq_commerce_ledger_identity_event_key ON commerce_ledger (owner_identity_id, event_key) WHERE scope_kind = 'identity'",
        "CREATE UNIQUE INDEX uq_commerce_ledger_project_event_key ON commerce_ledger (project_id, event_key) WHERE scope_kind = 'project'",
        "CREATE UNIQUE INDEX uq_commerce_ledger_workspace_event_key ON commerce_ledger (workspace_id, event_key) WHERE scope_kind = 'workspace'",
        "CREATE UNIQUE INDEX uq_commerce_campaigns_platform_code ON commerce_campaigns (code_sha256) WHERE scope_kind = 'platform'",
        "CREATE UNIQUE INDEX uq_commerce_campaigns_project_code ON commerce_campaigns (project_id, code_sha256) WHERE scope_kind = 'project'",
        "CREATE UNIQUE INDEX uq_commerce_campaigns_workspace_code ON commerce_campaigns (workspace_id, code_sha256) WHERE scope_kind = 'workspace'",
        "CREATE INDEX ix_commerce_redemptions_bucket_id ON commerce_redemptions (bucket_id)",
        "CREATE UNIQUE INDEX uq_commerce_redemptions_identity_day ON commerce_redemptions (owner_identity_id, campaign_id, actor, redeemed_day) WHERE scope_kind = 'identity'",
        "CREATE UNIQUE INDEX uq_commerce_redemptions_identity_period ON commerce_redemptions (owner_identity_id, campaign_id, actor, period) WHERE scope_kind = 'identity'",
        "CREATE UNIQUE INDEX uq_commerce_redemptions_project_day ON commerce_redemptions (project_id, campaign_id, actor, redeemed_day) WHERE scope_kind = 'project'",
        "CREATE UNIQUE INDEX uq_commerce_redemptions_project_period ON commerce_redemptions (project_id, campaign_id, actor, period) WHERE scope_kind = 'project'",
        "CREATE UNIQUE INDEX uq_commerce_redemptions_workspace_day ON commerce_redemptions (workspace_id, campaign_id, actor, redeemed_day) WHERE scope_kind = 'workspace'",
        "CREATE UNIQUE INDEX uq_commerce_redemptions_workspace_period ON commerce_redemptions (workspace_id, campaign_id, actor, period) WHERE scope_kind = 'workspace'",
        "CREATE INDEX ix_commerce_invoices_actor_inflight ON commerce_invoices (actor, status) WHERE status IN ('created','unconfigured','submission_unknown','pending')",
        "CREATE INDEX ix_commerce_invoices_billing_workspace_id ON commerce_invoices (billing_workspace_id) WHERE billing_workspace_id IS NOT NULL",
        "CREATE INDEX ix_commerce_invoices_scope_created ON commerce_invoices (scope_kind, coalesce(owner_identity_id, workspace_id, project_id), created_at DESC, id DESC)",
        "CREATE UNIQUE INDEX uq_commerce_invoices_active_order ON commerce_invoices (order_id) WHERE status <> 'void'",
        "CREATE INDEX ix_service_configuration_versions_created_by ON service_configuration_versions (created_by)",
        "CREATE UNIQUE INDEX uq_service_configuration_versions_platform_ver ON service_configuration_versions (version) WHERE scope_kind = 'platform'",
        "CREATE UNIQUE INDEX uq_service_configuration_versions_project_ver ON service_configuration_versions (project_id, version) WHERE scope_kind = 'project'",
        "CREATE UNIQUE INDEX uq_service_configuration_versions_workspace_ver ON service_configuration_versions (workspace_id, version) WHERE scope_kind = 'workspace'",
        "CREATE INDEX ix_service_announcements_created_by ON service_announcements (created_by)",
        "CREATE UNIQUE INDEX uq_service_announcements_platform_key_ver ON service_announcements (announcement_key, version) WHERE scope_kind = 'platform'",
        "CREATE UNIQUE INDEX uq_service_announcements_project_key_ver ON service_announcements (project_id, announcement_key, version) WHERE scope_kind = 'project'",
        "CREATE UNIQUE INDEX uq_service_announcements_workspace_key_ver ON service_announcements (workspace_id, announcement_key, version) WHERE scope_kind = 'workspace'",
        "CREATE INDEX ix_service_requests_artifact_id ON service_requests (project_id, artifact_id) WHERE artifact_id IS NOT NULL",
        "CREATE INDEX ix_service_requests_manage_scope_created ON service_requests (scope_kind, coalesce(workspace_id, project_id), kind, created_at DESC, id DESC) WHERE scope_kind IN ('workspace','project')",
        "CREATE INDEX ix_service_requests_media_id ON service_requests (project_id, media_id) WHERE media_id IS NOT NULL",
        "CREATE INDEX ix_service_requests_owner_kind_created ON service_requests (requester_id, scope_kind, kind, created_at DESC, id DESC)",
        "CREATE INDEX ix_service_request_events_created_by ON service_request_events (created_by)",
        "CREATE INDEX ix_service_export_files_requester_id ON service_export_files (requester_id)",
        "CREATE INDEX ix_service_api_keys_identity_active ON service_api_keys (identity_id) WHERE revoked = false",
        "CREATE INDEX ix_service_api_keys_scope_created ON service_api_keys (scope_kind, coalesce(owner_identity_id, workspace_id, project_id), created_at DESC, id DESC)",
        "CREATE UNIQUE INDEX uq_service_api_keys_identity_active_name ON service_api_keys (owner_identity_id, identity_id, lower(btrim(name))) WHERE scope_kind = 'identity' AND revoked = false",
        "CREATE UNIQUE INDEX uq_service_api_keys_project_active_name ON service_api_keys (project_id, identity_id, lower(btrim(name))) WHERE scope_kind = 'project' AND revoked = false",
        "CREATE UNIQUE INDEX uq_service_api_keys_workspace_active_name ON service_api_keys (workspace_id, identity_id, lower(btrim(name))) WHERE scope_kind = 'workspace' AND revoked = false",
        "CREATE INDEX ix_service_api_calls_key_rpm_window ON service_api_calls (api_key_id, created_at DESC) WHERE phase = 'started'",
        "CREATE INDEX ix_service_api_calls_run_version_id ON service_api_calls (project_id, run_version_id) WHERE run_version_id IS NOT NULL",
        "CREATE INDEX ix_asset_identities_project_kind ON asset_identities (project_id, asset_kind, id)",
        "CREATE INDEX ix_asset_identities_project_updated ON asset_identities (project_id, updated_at DESC, id)",
        "CREATE INDEX ix_creative_objects_asset_project_created ON creative_objects (project_id, created_at DESC, id) WHERE kind = 'asset'",
        "CREATE INDEX ix_generation_jobs_project_created ON generation_jobs (project_id, created_at DESC, id DESC)",
        "CREATE INDEX ix_generation_jobs_project_ext_task_lower ON generation_jobs (project_id, lower(external_task_id)) WHERE external_task_id IS NOT NULL",
        "CREATE INDEX ix_asset_card_form_versions_project_created ON asset_card_form_versions (project_id, created_at DESC, form_id)",
        "CREATE INDEX ix_asset_card_favorites_actor_active_project ON asset_card_favorites (actor, project_id, asset_id) WHERE active = true",
        "CREATE INDEX ix_creative_canvases_project_episode_created ON creative_canvases (project_id, episode_id, created_at DESC, id)",
        "CREATE INDEX ix_task_notification_events_project_created_seq ON task_notification_events (project_id, created_at DESC, sequence DESC)",
        "CREATE INDEX ix_task_notification_reads_identity_project_event ON task_notification_reads (identity_id, project_id, event_id)",
    )
    for stmt in ddl_indexes:
        op.execute(stmt)

    # Step 5: Upgrade PL/pgSQL trigger functions and install scoped_parent_guard.
    op.execute("DROP TRIGGER commerce_rates_sealed ON commerce_rates")
    op.execute("DROP TRIGGER commerce_rates_sealed ON commerce_plan_versions")
    op.execute("DROP FUNCTION vsc_commerce_rates_sealed()")
    op.execute("DROP FUNCTION vsc_commerce_rates_match(uuid, uuid)")

    op.execute("""
        CREATE OR REPLACE FUNCTION vsc_commerce_rates_match(plan uuid) RETURNS boolean
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
                   OR (item->>'credits_per_unit') !~ '^[1-9][0-9]*$' THEN
                    RETURN false;
                END IF;
            END LOOP;
            IF EXISTS (
                SELECT 1 FROM commerce_rates r
                 WHERE r.plan_id = plan
                   AND (r.scope_kind, r.owner_identity_id, r.workspace_id, r.project_id)
                       IS DISTINCT FROM (p_scope, p_ident, p_ws, p_proj)
            ) THEN
                RETURN false;
            END IF;
            RETURN NOT EXISTS (
                (SELECT (value->>'model_id')::uuid, value->>'unit', (value->>'credits_per_unit')::bigint
                   FROM jsonb_array_elements(wanted)
                 EXCEPT ALL
                 SELECT model_id, unit, credits_per_unit FROM commerce_rates WHERE plan_id = plan)
                UNION ALL
                (SELECT model_id, unit, credits_per_unit FROM commerce_rates WHERE plan_id = plan
                 EXCEPT ALL
                 SELECT (value->>'model_id')::uuid, value->>'unit', (value->>'credits_per_unit')::bigint
                   FROM jsonb_array_elements(wanted))
            );
        EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN
            RETURN false;
        END $$
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION vsc_commerce_rates_sealed() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE member_plan uuid;
        BEGIN
            IF TG_TABLE_NAME = 'commerce_plan_versions' THEN member_plan := NEW.id;
            ELSE member_plan := NEW.plan_id; END IF;
            IF NOT vsc_commerce_rates_match(member_plan) THEN
                RAISE EXCEPTION 'commerce rates must equal the complete fixed pricing document' USING ERRCODE = '23514';
            END IF;
            RETURN NULL;
        END $$
    """)
    op.execute(
        "CREATE CONSTRAINT TRIGGER commerce_rates_sealed AFTER INSERT ON commerce_plan_versions "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_commerce_rates_sealed()"
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER commerce_rates_sealed AFTER INSERT ON commerce_rates "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_commerce_rates_sealed()"
    )

    op.execute("""
        CREATE OR REPLACE FUNCTION vsc_commerce_balance() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF (SELECT COALESCE(SUM(delta), 0) FROM commerce_ledger WHERE bucket_id = NEW.bucket_id) < 0 THEN
                RAISE EXCEPTION 'commercial credit bucket cannot be overdrawn' USING ERRCODE = '23514';
            END IF;
            RETURN NULL;
        END $$
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION vsc_commerce_ledger_lock() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            PERFORM id FROM commerce_buckets WHERE id = NEW.bucket_id FOR UPDATE;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION vsc_service_export_ready() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.status = 'export_ready' AND NOT EXISTS (
                SELECT 1 FROM service_export_files e
                 WHERE e.request_id = NEW.request_id AND e.project_id IS NOT DISTINCT FROM NEW.project_id
            ) THEN
                RAISE EXCEPTION 'export ready requires immutable local file' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION vsc_commerce_identity() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'commerce history cannot be deleted' USING ERRCODE = '23514';
            END IF;
            IF TG_TABLE_NAME = 'commerce_orders' THEN
                IF (to_jsonb(NEW) - ARRAY['status','paid_at','external_id','checkout_url','error_code']) IS DISTINCT FROM
                   (to_jsonb(OLD) - ARRAY['status','paid_at','external_id','checkout_url','error_code']) OR
                   (OLD.external_id IS NOT NULL AND NEW.external_id IS DISTINCT FROM OLD.external_id) OR
                   (OLD.paid_at IS NOT NULL AND NEW.paid_at IS DISTINCT FROM OLD.paid_at) OR
                   (OLD.status = 'refunded' AND NEW.status <> 'refunded') OR
                   (OLD.status = 'paid' AND NEW.status NOT IN ('paid','refund_unknown','refunded')) THEN
                    RAISE EXCEPTION 'order contract or terminal history cannot change' USING ERRCODE = '23514';
                END IF;
            ELSIF TG_TABLE_NAME = 'commerce_reservations' THEN
                IF (to_jsonb(NEW) - ARRAY['status','actual']) IS DISTINCT FROM
                   (to_jsonb(OLD) - ARRAY['status','actual']) OR OLD.status <> 'reserved' THEN
                    RAISE EXCEPTION 'credit reservation contract and terminal settlement are immutable' USING ERRCODE = '23514';
                END IF;
            ELSIF TG_TABLE_NAME = 'commerce_invoices' THEN
                IF (to_jsonb(NEW) - ARRAY['status','gateway','external_id','error_code','document','sha256','voided_at','void_reason']) IS DISTINCT FROM
                   (to_jsonb(OLD) - ARRAY['status','gateway','external_id','error_code','document','sha256','voided_at','void_reason']) OR
                   OLD.status = 'void' OR
                   (OLD.external_id IS NOT NULL AND OLD.external_id IS DISTINCT FROM NEW.external_id) OR
                   (OLD.gateway <> 'unconfigured' AND OLD.gateway IS DISTINCT FROM NEW.gateway) THEN
                    RAISE EXCEPTION 'invoice request or terminal void state cannot change' USING ERRCODE = '23514';
                END IF;
                IF OLD.status = 'issued' THEN
                    IF NEW.status <> 'void' OR
                       NEW.document IS DISTINCT FROM OLD.document OR
                       NEW.sha256 IS DISTINCT FROM OLD.sha256 OR
                       (SELECT status FROM commerce_orders WHERE id = NEW.order_id) <> 'refunded' THEN
                        RAISE EXCEPTION 'issued invoice document is immutable and may only void after order refund' USING ERRCODE = '23514';
                    END IF;
                ELSIF OLD.status = 'failed' AND NEW.status NOT IN ('failed', 'void') THEN
                    RAISE EXCEPTION 'failed invoice may only transition to void before re-issuing' USING ERRCODE = '23514';
                END IF;
            ELSIF TG_TABLE_NAME = 'commerce_settings' THEN
                IF (to_jsonb(NEW) - ARRAY['price_version_id','enabled']) IS DISTINCT FROM
                   (to_jsonb(OLD) - ARRAY['price_version_id','enabled']) THEN
                    RAISE EXCEPTION 'commerce_settings identity and scope columns cannot change' USING ERRCODE = '23514';
                END IF;
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION vsc_scoped_parent_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            p_plan_key text; p_scope text; p_ident uuid; p_ws uuid; p_proj uuid; p_daily boolean;
        BEGIN
            IF TG_TABLE_NAME = 'commerce_plan_versions' THEN
                IF NEW.base_version_id IS NOT NULL THEN
                    SELECT plan_key, scope_kind, owner_identity_id, workspace_id, project_id
                      INTO p_plan_key, p_scope, p_ident, p_ws, p_proj
                      FROM commerce_plan_versions WHERE id = NEW.base_version_id;
                    IF (NEW.plan_key, NEW.scope_kind, NEW.owner_identity_id, NEW.workspace_id, NEW.project_id)
                       IS DISTINCT FROM (p_plan_key, p_scope, p_ident, p_ws, p_proj) THEN
                        RAISE EXCEPTION 'commerce_plan_versions base_version_id must match plan_key and scope' USING ERRCODE = '23514';
                    END IF;
                END IF;
            ELSIF TG_TABLE_NAME = 'commerce_rates' THEN
                SELECT scope_kind, owner_identity_id, workspace_id, project_id
                  INTO p_scope, p_ident, p_ws, p_proj FROM commerce_plan_versions WHERE id = NEW.plan_id;
                IF (NEW.scope_kind, NEW.owner_identity_id, NEW.workspace_id, NEW.project_id)
                   IS DISTINCT FROM (p_scope, p_ident, p_ws, p_proj) THEN
                    RAISE EXCEPTION 'commerce_rates scope must match parent plan' USING ERRCODE = '23514';
                END IF;
            ELSIF TG_TABLE_NAME IN ('commerce_settings', 'commerce_reservations') THEN
                SELECT scope_kind, owner_identity_id, workspace_id, project_id
                  INTO p_scope, p_ident, p_ws, p_proj FROM commerce_plan_versions WHERE id = NEW.price_version_id;
                IF p_scope <> 'platform' AND (NEW.scope_kind, NEW.owner_identity_id, NEW.workspace_id, NEW.project_id)
                   IS DISTINCT FROM (p_scope, p_ident, p_ws, p_proj) THEN
                    RAISE EXCEPTION '% price_version_id scope mismatch', TG_TABLE_NAME USING ERRCODE = '23514';
                END IF;
            ELSIF TG_TABLE_NAME = 'commerce_orders' THEN
                SELECT scope_kind, owner_identity_id, workspace_id, project_id
                  INTO p_scope, p_ident, p_ws, p_proj FROM commerce_plan_versions WHERE id = NEW.plan_id;
                IF p_scope <> 'platform' AND (NEW.scope_kind, NEW.owner_identity_id, NEW.workspace_id, NEW.project_id)
                   IS DISTINCT FROM (p_scope, p_ident, p_ws, p_proj) THEN
                    RAISE EXCEPTION 'commerce_orders plan_id scope mismatch' USING ERRCODE = '23514';
                END IF;
                IF NEW.renewal_of_order_id IS NOT NULL THEN
                    SELECT scope_kind, owner_identity_id, workspace_id, project_id
                      INTO p_scope, p_ident, p_ws, p_proj FROM commerce_orders WHERE id = NEW.renewal_of_order_id;
                    IF (NEW.scope_kind, NEW.owner_identity_id, NEW.workspace_id, NEW.project_id)
                       IS DISTINCT FROM (p_scope, p_ident, p_ws, p_proj) THEN
                        RAISE EXCEPTION 'renewal order scope must match prior order' USING ERRCODE = '23514';
                    END IF;
                END IF;
            ELSIF TG_TABLE_NAME IN ('commerce_payment_events', 'commerce_invoices') THEN
                SELECT scope_kind, owner_identity_id, workspace_id, project_id
                  INTO p_scope, p_ident, p_ws, p_proj FROM commerce_orders WHERE id = NEW.order_id;
                IF (NEW.scope_kind, NEW.owner_identity_id, NEW.workspace_id, NEW.project_id)
                   IS DISTINCT FROM (p_scope, p_ident, p_ws, p_proj) THEN
                    RAISE EXCEPTION '% scope must match parent order', TG_TABLE_NAME USING ERRCODE = '23514';
                END IF;
            ELSIF TG_TABLE_NAME = 'commerce_buckets' THEN
                IF NEW.order_id IS NOT NULL THEN
                    SELECT scope_kind, owner_identity_id, workspace_id, project_id
                      INTO p_scope, p_ident, p_ws, p_proj FROM commerce_orders WHERE id = NEW.order_id;
                    IF (NEW.scope_kind, NEW.owner_identity_id, NEW.workspace_id, NEW.project_id)
                       IS DISTINCT FROM (p_scope, p_ident, p_ws, p_proj) THEN
                        RAISE EXCEPTION 'bucket scope must match parent order' USING ERRCODE = '23514';
                    END IF;
                END IF;
                IF NEW.parent_bucket_id IS NOT NULL THEN
                    SELECT scope_kind, owner_identity_id, workspace_id, project_id
                      INTO p_scope, p_ident, p_ws, p_proj FROM commerce_buckets WHERE id = NEW.parent_bucket_id;
                    IF (NEW.scope_kind, NEW.owner_identity_id, NEW.workspace_id, NEW.project_id)
                       IS DISTINCT FROM (p_scope, p_ident, p_ws, p_proj) THEN
                        RAISE EXCEPTION 'allocated child bucket scope must match parent bucket' USING ERRCODE = '23514';
                    END IF;
                END IF;
            ELSIF TG_TABLE_NAME = 'commerce_ledger' THEN
                SELECT scope_kind, owner_identity_id, workspace_id, project_id
                  INTO p_scope, p_ident, p_ws, p_proj FROM commerce_buckets WHERE id = NEW.bucket_id;
                IF (NEW.scope_kind, NEW.owner_identity_id, NEW.workspace_id, NEW.project_id)
                   IS DISTINCT FROM (p_scope, p_ident, p_ws, p_proj) THEN
                    RAISE EXCEPTION 'ledger entry scope must match bucket scope' USING ERRCODE = '23514';
                END IF;
                IF NEW.reservation_id IS NOT NULL THEN
                    SELECT scope_kind, owner_identity_id, workspace_id, project_id
                      INTO p_scope, p_ident, p_ws, p_proj FROM commerce_reservations WHERE id = NEW.reservation_id;
                    IF (NEW.scope_kind, NEW.owner_identity_id, NEW.workspace_id, NEW.project_id)
                       IS DISTINCT FROM (p_scope, p_ident, p_ws, p_proj) THEN
                        RAISE EXCEPTION 'ledger reservation scope must match funding bucket scope' USING ERRCODE = '23514';
                    END IF;
                END IF;
            ELSIF TG_TABLE_NAME = 'commerce_redemptions' THEN
                SELECT scope_kind, owner_identity_id, workspace_id, project_id
                  INTO p_scope, p_ident, p_ws, p_proj FROM commerce_buckets WHERE id = NEW.bucket_id;
                IF (NEW.scope_kind, NEW.owner_identity_id, NEW.workspace_id, NEW.project_id)
                   IS DISTINCT FROM (p_scope, p_ident, p_ws, p_proj) THEN
                    RAISE EXCEPTION 'redemption scope must match granted bucket scope' USING ERRCODE = '23514';
                END IF;
                SELECT scope_kind, owner_identity_id, workspace_id, project_id, daily
                  INTO p_scope, p_ident, p_ws, p_proj, p_daily FROM commerce_campaigns WHERE id = NEW.campaign_id;
                IF p_scope <> 'platform' AND (NEW.scope_kind, NEW.owner_identity_id, NEW.workspace_id, NEW.project_id)
                   IS DISTINCT FROM (p_scope, p_ident, p_ws, p_proj) THEN
                    RAISE EXCEPTION 'redemption target scope does not match scoped campaign' USING ERRCODE = '23514';
                END IF;
                IF (NOT p_daily AND NEW.period <> 'once') OR (p_daily AND NEW.period <> to_char(NEW.redeemed_day, 'YYYY-MM-DD')) THEN
                    RAISE EXCEPTION 'redemption period must match campaign daily policy and redeemed_day' USING ERRCODE = '23514';
                END IF;
            ELSIF TG_TABLE_NAME IN ('service_request_events', 'service_export_files') THEN
                SELECT scope_kind, owner_identity_id, workspace_id, project_id
                  INTO p_scope, p_ident, p_ws, p_proj FROM service_requests WHERE id = NEW.request_id;
                IF (NEW.scope_kind, NEW.owner_identity_id, NEW.workspace_id, NEW.project_id)
                   IS DISTINCT FROM (p_scope, p_ident, p_ws, p_proj) THEN
                    RAISE EXCEPTION '% scope must match parent service_request', TG_TABLE_NAME USING ERRCODE = '23514';
                END IF;
            ELSIF TG_TABLE_NAME = 'service_api_calls' THEN
                SELECT scope_kind, owner_identity_id, workspace_id, project_id
                  INTO p_scope, p_ident, p_ws, p_proj FROM service_api_keys WHERE id = NEW.api_key_id;
                IF p_scope = 'project' AND (NEW.scope_kind, NEW.project_id) IS DISTINCT FROM ('project', p_proj) THEN
                    RAISE EXCEPTION 'project-scoped API key cannot audit outside its bound project' USING ERRCODE = '23514';
                END IF;
            END IF;
            RETURN NEW;
        END $$
    """)
    for tbl in SCOPED_PARENT_GUARD_TABLES:
        op.execute(
            f"CREATE TRIGGER scoped_parent_guard BEFORE INSERT OR UPDATE ON {tbl} "
            "FOR EACH ROW EXECUTE FUNCTION vsc_scoped_parent_guard()"
        )

    # Step 6: Post-migration rate-seal preflight & conservation assertions.
    conn.execute(text("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM commerce_plan_versions WHERE NOT vsc_commerce_rates_match(id)) THEN
            RAISE EXCEPTION 'post-0059 rates differ from their fixed pricing document' USING ERRCODE = '23514';
        END IF;
    END $$"""))
    after_counts, after_ledger_sum = _snapshot_metrics(conn)
    if after_counts != before_counts or after_ledger_sum != before_ledger_sum:
        raise RuntimeError("0059 migration conservation check failed; aborting transaction")


def downgrade():
    lock_targets = ", ".join(
        DECOUPLED_TABLES
        + (
            "scoped_domain_states",
            "scoped_command_receipts",
            "commerce_invoice_titles",
            "commerce_workspace_transfers",
            "service_api_call_jobs",
            "asset_identities",
            "creative_objects",
            "generation_jobs",
            "asset_card_form_versions",
            "asset_card_favorites",
            "creative_canvases",
            "task_notification_events",
            "task_notification_reads",
        )
    )
    op.execute(f"LOCK TABLE {lock_targets} IN ACCESS EXCLUSIVE MODE")
    non_project_checks = " OR ".join(
        f"EXISTS (SELECT 1 FROM {tbl} WHERE scope_kind <> 'project' OR project_id IS NULL)"
        for tbl in DECOUPLED_TABLES
    )
    op.execute(f"""DO $$ BEGIN
        IF {non_project_checks}
           OR EXISTS (SELECT 1 FROM scoped_domain_states)
           OR EXISTS (SELECT 1 FROM scoped_command_receipts)
           OR EXISTS (SELECT 1 FROM commerce_invoice_titles)
           OR EXISTS (SELECT 1 FROM commerce_invoices WHERE status = 'void')
           OR EXISTS (SELECT 1 FROM commerce_plan_versions WHERE base_version_id IS NOT NULL)
           OR EXISTS (SELECT 1 FROM commerce_reservations WHERE attribution_project_id IS DISTINCT FROM project_id)
           OR EXISTS (SELECT 1 FROM commerce_ledger WHERE reservation_id IS NOT NULL AND attribution_project_id IS DISTINCT FROM project_id) THEN
            RAISE EXCEPTION 'scoped financial or operational history exists; use forward recovery'
                USING ERRCODE = '23514';
        END IF;
    END $$""")

    # 1. Remove scoped_parent_guard triggers & function; restore 0021/0023/0032 trigger functions.
    for tbl in SCOPED_PARENT_GUARD_TABLES:
        op.execute(f"DROP TRIGGER scoped_parent_guard ON {tbl}")
    op.execute("DROP FUNCTION vsc_scoped_parent_guard()")

    op.execute("DROP TRIGGER commerce_rates_sealed ON commerce_rates")
    op.execute("DROP TRIGGER commerce_rates_sealed ON commerce_plan_versions")
    op.execute("DROP FUNCTION vsc_commerce_rates_sealed()")
    op.execute("DROP FUNCTION vsc_commerce_rates_match(uuid)")

    op.execute("""
        CREATE FUNCTION vsc_commerce_rates_match(p uuid, plan uuid) RETURNS boolean
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
        END $$
    """)
    op.execute("""
        CREATE FUNCTION vsc_commerce_rates_sealed() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE member_plan uuid;
        BEGIN
         IF TG_TABLE_NAME='commerce_plan_versions' THEN member_plan:=NEW.id; ELSE member_plan:=NEW.plan_id; END IF;
         IF NOT vsc_commerce_rates_match(NEW.project_id,member_plan) THEN
          RAISE EXCEPTION 'commerce rates must equal the complete fixed pricing document' USING ERRCODE='23514';
         END IF;
         RETURN NULL;
        END $$
    """)
    op.execute(
        "CREATE CONSTRAINT TRIGGER commerce_rates_sealed AFTER INSERT ON commerce_plan_versions "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_commerce_rates_sealed()"
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER commerce_rates_sealed AFTER INSERT ON commerce_rates "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_commerce_rates_sealed()"
    )
    op.execute("""
        CREATE OR REPLACE FUNCTION vsc_commerce_balance() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
         IF (SELECT COALESCE(SUM(delta),0) FROM commerce_ledger WHERE project_id=NEW.project_id AND bucket_id=NEW.bucket_id)<0 THEN
           RAISE EXCEPTION 'commercial credit bucket cannot be overdrawn' USING ERRCODE='23514'; END IF;
         RETURN NULL;
        END $$
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION vsc_commerce_ledger_lock() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
         PERFORM id FROM projects WHERE id=NEW.project_id FOR UPDATE;
         RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION vsc_service_export_ready() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
         IF NEW.status='export_ready' AND NOT EXISTS(SELECT 1 FROM service_export_files e WHERE e.project_id=NEW.project_id AND e.request_id=NEW.request_id) THEN
          RAISE EXCEPTION 'export ready requires immutable local file' USING ERRCODE='23514';
         END IF;
         RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION vsc_commerce_identity() RETURNS trigger LANGUAGE plpgsql AS $$
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
    """)

    # 2. Drop 0059 indexes and new tables.
    new_indexes = (
        "ix_commerce_plan_versions_base_version_id",
        "uq_commerce_plan_versions_platform_key_ver",
        "uq_commerce_plan_versions_project_key_ver",
        "uq_commerce_plan_versions_workspace_key_ver",
        "ix_commerce_rates_model_id",
        "ix_commerce_settings_price_version_id",
        "uq_commerce_settings_platform",
        "uq_commerce_settings_project",
        "uq_commerce_settings_workspace",
        "ix_commerce_orders_actor_unsettled",
        "ix_commerce_orders_plan_id",
        "ix_commerce_orders_renewal_of_order_id",
        "ix_commerce_orders_scope_created",
        "uq_commerce_orders_gateway_external_id",
        "ix_commerce_payment_events_order_id",
        "ix_commerce_buckets_order_id",
        "ix_commerce_buckets_owner_actor_active",
        "ix_commerce_buckets_parent_bucket_id",
        "ix_commerce_buckets_scope_expiry",
        "uq_commerce_buckets_identity_source_key",
        "uq_commerce_buckets_project_source_key",
        "uq_commerce_buckets_workspace_source_key",
        "ix_commerce_reservations_actor_reserved",
        "ix_commerce_reservations_attribution_status_actor",
        "ix_commerce_reservations_price_version_id",
        "ix_commerce_reservations_scope_status_actor",
        "ix_commerce_ledger_attribution_created",
        "ix_commerce_ledger_bucket_id",
        "ix_commerce_ledger_reservation_id",
        "ix_commerce_ledger_scope_created",
        "uq_commerce_ledger_identity_event_key",
        "uq_commerce_ledger_project_event_key",
        "uq_commerce_ledger_workspace_event_key",
        "uq_commerce_campaigns_platform_code",
        "uq_commerce_campaigns_project_code",
        "uq_commerce_campaigns_workspace_code",
        "ix_commerce_redemptions_bucket_id",
        "uq_commerce_redemptions_identity_day",
        "uq_commerce_redemptions_identity_period",
        "uq_commerce_redemptions_project_day",
        "uq_commerce_redemptions_project_period",
        "uq_commerce_redemptions_workspace_day",
        "uq_commerce_redemptions_workspace_period",
        "ix_commerce_invoices_actor_inflight",
        "ix_commerce_invoices_billing_workspace_id",
        "ix_commerce_invoices_scope_created",
        "uq_commerce_invoices_active_order",
        "ix_service_configuration_versions_created_by",
        "uq_service_configuration_versions_platform_ver",
        "uq_service_configuration_versions_project_ver",
        "uq_service_configuration_versions_workspace_ver",
        "ix_service_announcements_created_by",
        "uq_service_announcements_platform_key_ver",
        "uq_service_announcements_project_key_ver",
        "uq_service_announcements_workspace_key_ver",
        "ix_service_requests_artifact_id",
        "ix_service_requests_manage_scope_created",
        "ix_service_requests_media_id",
        "ix_service_requests_owner_kind_created",
        "ix_service_request_events_created_by",
        "ix_service_export_files_requester_id",
        "ix_service_api_keys_identity_active",
        "ix_service_api_keys_scope_created",
        "uq_service_api_keys_identity_active_name",
        "uq_service_api_keys_project_active_name",
        "uq_service_api_keys_workspace_active_name",
        "ix_service_api_calls_key_rpm_window",
        "ix_service_api_calls_run_version_id",
        "ix_asset_identities_project_kind",
        "ix_asset_identities_project_updated",
        "ix_creative_objects_asset_project_created",
        "ix_generation_jobs_project_created",
        "ix_generation_jobs_project_ext_task_lower",
        "ix_asset_card_form_versions_project_created",
        "ix_asset_card_favorites_actor_active_project",
        "ix_creative_canvases_project_episode_created",
        "ix_task_notification_events_project_created_seq",
        "ix_task_notification_reads_identity_project_event",
    )
    for ix_name in new_indexes:
        op.execute(f"DROP INDEX {ix_name}")

    op.execute("DROP TABLE commerce_invoice_titles")
    op.execute("DROP TABLE scoped_command_receipts")
    op.execute("DROP TABLE scoped_domain_states")

    # 3. Drop 0059 constraints and cross-table FKs before restoring composite PKs.
    for cname in (
        "fk_commerce_workspace_transfers_project_id_source_bucke_e21e",
        "fk_commerce_workspace_transfers_project_id_source_entry_0f33",
        "fk_commerce_workspace_transfers_target_project_id_targe_2c32",
        "fk_commerce_workspace_transfers_target_project_id_targe_6227",
    ):
        op.execute(f"ALTER TABLE commerce_workspace_transfers DROP CONSTRAINT {cname}")
    op.execute(
        "ALTER TABLE service_api_call_jobs "
        "DROP CONSTRAINT fk_service_api_call_jobs_project_id_call_event_id_servi_db1a"
    )

    drop_0059_constraints = (
        ("commerce_plan_versions", "fk_commerce_plan_versions_base_version_id_commerce_plan_9d58"),
        ("commerce_rates", "uq_commerce_rates_plan_model_unit"),
        ("commerce_rates", "fk_commerce_rates_plan_id_commerce_plan_versions"),
        ("commerce_rates", "fk_commerce_rates_model_id_provider_models"),
        ("commerce_settings", "fk_commerce_settings_price_version_id_commerce_plan_versions"),
        ("commerce_orders", "fk_commerce_orders_plan_id_commerce_plan_versions"),
        ("commerce_orders", "fk_commerce_orders_renewal_of_order_id_commerce_orders"),
        ("commerce_payment_events", "uq_commerce_payment_events_gateway_event_id"),
        ("commerce_payment_events", "fk_commerce_payment_events_order_id_commerce_orders"),
        ("commerce_buckets", "fk_commerce_buckets_order_id_commerce_orders"),
        ("commerce_buckets", "fk_commerce_buckets_parent_bucket_id_commerce_buckets"),
        ("commerce_buckets", "uq_commerce_buckets_project_id_id"),
        ("commerce_reservations", "fk_commerce_ledger_attribution_project_id_job_id_reserv_6e9d"),
        ("commerce_ledger", "ck_commerce_ledger_attribution_pair"),
        ("commerce_ledger", "fk_commerce_ledger_bucket_id_commerce_buckets"),
        ("commerce_ledger", "fk_commerce_ledger_reservation_id_commerce_reservations"),
        ("commerce_ledger", "fk_commerce_ledger_attribution_project_id_job_id_genera_3fa5"),
        ("commerce_ledger", "uq_commerce_ledger_project_id_id"),
        ("commerce_reservations", "uq_commerce_reservations_attribution_job"),
        ("commerce_reservations", "uq_commerce_reservations_attribution_job_id"),
        ("commerce_reservations", "fk_commerce_reservations_attribution_project_id_projects"),
        ("commerce_reservations", "fk_commerce_reservations_attribution_project_id_job_id__875a"),
        ("commerce_reservations", "fk_commerce_reservations_price_version_id_commerce_plan_2953"),
        ("commerce_campaigns", "ck_commerce_campaigns_window"),
        ("commerce_redemptions", "fk_commerce_redemptions_campaign_id_commerce_campaigns"),
        ("commerce_redemptions", "fk_commerce_redemptions_bucket_id_commerce_buckets"),
        ("commerce_invoices", "ck_commerce_invoices_status"),
        ("commerce_invoices", "ck_commerce_invoices_document"),
        ("commerce_invoices", "fk_commerce_invoices_billing_workspace_id_access_workspaces"),
        ("commerce_invoices", "fk_commerce_invoices_order_id_commerce_orders"),
        ("service_requests", "ck_service_requests_project_attachments"),
        ("service_requests", "ck_service_requests_contact"),
        ("service_request_events", "uq_service_request_events_request_sequence"),
        ("service_request_events", "fk_service_request_events_request_id_service_requests"),
        ("service_export_files", "uq_service_export_files_request_id"),
        ("service_export_files", "fk_service_export_files_request_id_service_requests"),
        ("service_export_files", "fk_service_export_files_request_id_requester_id_service_d82f"),
        ("service_requests", "uq_service_requests_id_requester_id"),
        ("service_api_calls", "uq_service_api_calls_call_id_phase"),
        ("service_api_calls", "ck_service_api_calls_project_run"),
        ("service_api_calls", "fk_service_api_calls_api_key_id_service_api_keys"),
        ("service_api_calls", "uq_service_api_calls_project_id_id"),
    )
    # Note: fk_commerce_ledger_attribution_project_id_job_id_reserv_6e9d lives on commerce_ledger!
    for tbl, cname in drop_0059_constraints:
        actual_tbl = "commerce_ledger" if cname == "fk_commerce_ledger_attribution_project_id_job_id_reserv_6e9d" else tbl
        op.execute(f"ALTER TABLE {actual_tbl} DROP CONSTRAINT {cname}")

    # Restore commerce_invoices.workspace_id from billing_workspace_id before dropping columns.
    op.execute("ALTER TABLE commerce_invoices DISABLE TRIGGER USER")
    op.execute("""
        UPDATE commerce_invoices
           SET workspace_id = billing_workspace_id
         WHERE project_id IS NOT NULL
           AND billing_workspace_id IS NOT NULL
    """)
    op.execute("ALTER TABLE commerce_invoices ENABLE TRIGGER USER")

    for tbl in DECOUPLED_TABLES:
        if tbl == "service_configuration_versions":
            id_fk = "fk_service_configuration_versions_owner_identity_id_acc_352c"
            ws_fk = "fk_service_configuration_versions_workspace_id_access_w_47bb"
        else:
            id_fk = f"fk_{tbl}_owner_identity_id_access_identities"
            ws_fk = f"fk_{tbl}_workspace_id_access_workspaces"
        op.execute(f"ALTER TABLE {tbl} DROP CONSTRAINT {id_fk}")
        op.execute(f"ALTER TABLE {tbl} DROP CONSTRAINT {ws_fk}")
        op.execute(f"ALTER TABLE {tbl} DROP CONSTRAINT ck_{tbl}_scope_target")
        op.execute(f"ALTER TABLE {tbl} ALTER COLUMN project_id SET NOT NULL")
        op.execute(f"ALTER TABLE {tbl} DROP CONSTRAINT pk_{tbl}")
        op.execute(f"ALTER TABLE {tbl} ADD CONSTRAINT pk_{tbl} PRIMARY KEY (project_id, id)")
        op.execute(f"ALTER TABLE {tbl} DROP COLUMN scope_kind")
        op.execute(f"ALTER TABLE {tbl} DROP COLUMN owner_identity_id")
        if tbl != "commerce_invoices":
            op.execute(f"ALTER TABLE {tbl} DROP COLUMN workspace_id")

    op.execute("ALTER TABLE commerce_plan_versions DROP COLUMN base_version_id")
    op.execute("ALTER TABLE commerce_reservations DROP COLUMN attribution_project_id")
    op.execute("ALTER TABLE commerce_ledger DROP COLUMN attribution_project_id")
    op.execute("ALTER TABLE commerce_ledger DROP COLUMN job_id")
    op.execute("ALTER TABLE commerce_redemptions DROP COLUMN redeemed_day")
    op.execute("ALTER TABLE commerce_campaigns ALTER COLUMN starts_at DROP NOT NULL")
    op.execute("ALTER TABLE commerce_invoices DROP COLUMN billing_workspace_id")
    op.execute("ALTER TABLE commerce_invoices DROP COLUMN voided_at")
    op.execute("ALTER TABLE commerce_invoices DROP COLUMN void_reason")
    op.execute("ALTER TABLE service_requests ALTER COLUMN contact DROP DEFAULT")
    op.execute("ALTER TABLE asset_identities DROP COLUMN updated_at")

    # 4. Restore 0021/0023/0038/0043/0057 constraints & indexes.
    restore_constraints = (
        "ALTER TABLE commerce_campaigns ADD CONSTRAINT uq_commerce_campaigns_project_id_code_sha256 UNIQUE (project_id, code_sha256)",
        "ALTER TABLE commerce_campaigns ADD CONSTRAINT ck_commerce_campaigns_limits CHECK (credits > 0 AND credit_expires_at >= ends_at)",
        "ALTER TABLE commerce_plan_versions ADD CONSTRAINT uq_commerce_plan_versions_project_id_plan_key_version UNIQUE (project_id, plan_key, version)",
        "ALTER TABLE commerce_orders ADD CONSTRAINT fk_commerce_orders_project_id_plan_id_commerce_plan_versions FOREIGN KEY (project_id, plan_id) REFERENCES commerce_plan_versions (project_id, id) ON DELETE RESTRICT",
        "ALTER TABLE commerce_orders ADD CONSTRAINT fk_commerce_orders_project_id_renewal_of_order_id_comme_19e0 FOREIGN KEY (project_id, renewal_of_order_id) REFERENCES commerce_orders (project_id, id) ON DELETE RESTRICT",
        "ALTER TABLE commerce_orders ADD CONSTRAINT uq_commerce_orders_project_id_gateway_external_id UNIQUE (project_id, gateway, external_id)",
        "ALTER TABLE commerce_rates ADD CONSTRAINT fk_commerce_rates_project_id_plan_id_commerce_plan_versions FOREIGN KEY (project_id, plan_id) REFERENCES commerce_plan_versions (project_id, id) ON DELETE RESTRICT",
        "ALTER TABLE commerce_rates ADD CONSTRAINT fk_commerce_rates_model_id_provider_models FOREIGN KEY (model_id) REFERENCES provider_models (id)",
        "ALTER TABLE commerce_rates ADD CONSTRAINT uq_commerce_rates_project_id_plan_id_model_id_unit UNIQUE (project_id, plan_id, model_id, unit)",
        "ALTER TABLE commerce_settings ADD CONSTRAINT fk_commerce_settings_project_id_price_version_id_commer_b77e FOREIGN KEY (project_id, price_version_id) REFERENCES commerce_plan_versions (project_id, id) ON DELETE RESTRICT",
        "ALTER TABLE commerce_settings ADD CONSTRAINT uq_commerce_settings_project_id UNIQUE (project_id)",
        "ALTER TABLE commerce_buckets ADD CONSTRAINT fk_commerce_buckets_project_id_order_id_commerce_orders FOREIGN KEY (project_id, order_id) REFERENCES commerce_orders (project_id, id) ON DELETE RESTRICT",
        "ALTER TABLE commerce_buckets ADD CONSTRAINT fk_commerce_buckets_project_id_parent_bucket_id_commerc_f1df FOREIGN KEY (project_id, parent_bucket_id) REFERENCES commerce_buckets (project_id, id) ON DELETE RESTRICT",
        "ALTER TABLE commerce_buckets ADD CONSTRAINT uq_commerce_buckets_project_id_source_key UNIQUE (project_id, source_key)",
        "ALTER TABLE commerce_invoices ADD CONSTRAINT fk_commerce_invoices_project_id_order_id_commerce_orders FOREIGN KEY (project_id, order_id) REFERENCES commerce_orders (project_id, id) ON DELETE RESTRICT",
        "ALTER TABLE commerce_invoices ADD CONSTRAINT fk_commerce_invoices_workspace_id_access_workspaces FOREIGN KEY (workspace_id) REFERENCES access_workspaces (id)",
        "ALTER TABLE commerce_invoices ADD CONSTRAINT uq_commerce_invoices_project_id_order_id UNIQUE (project_id, order_id)",
        "ALTER TABLE commerce_invoices ADD CONSTRAINT ck_commerce_invoices_status CHECK (status IN ('created','unconfigured','submission_unknown','pending','issued','failed'))",
        "ALTER TABLE commerce_invoices ADD CONSTRAINT ck_commerce_invoices_document CHECK ((status='issued') = (document IS NOT NULL AND sha256 IS NOT NULL))",
        "ALTER TABLE commerce_payment_events ADD CONSTRAINT fk_commerce_payment_events_project_id_order_id_commerce_orders FOREIGN KEY (project_id, order_id) REFERENCES commerce_orders (project_id, id) ON DELETE RESTRICT",
        "ALTER TABLE commerce_payment_events ADD CONSTRAINT uq_commerce_payment_events_project_id_gateway_event_id UNIQUE (project_id, gateway, event_id)",
        "ALTER TABLE commerce_redemptions ADD CONSTRAINT fk_commerce_redemptions_project_id_campaign_id_commerce_9be6 FOREIGN KEY (project_id, campaign_id) REFERENCES commerce_campaigns (project_id, id) ON DELETE RESTRICT",
        "ALTER TABLE commerce_redemptions ADD CONSTRAINT fk_commerce_redemptions_project_id_bucket_id_commerce_buckets FOREIGN KEY (project_id, bucket_id) REFERENCES commerce_buckets (project_id, id) ON DELETE RESTRICT",
        "ALTER TABLE commerce_redemptions ADD CONSTRAINT uq_commerce_redemptions_project_id_campaign_id_actor_period UNIQUE (project_id, campaign_id, actor, period)",
        "ALTER TABLE commerce_reservations ADD CONSTRAINT fk_commerce_reservations_project_id_job_id_generation_jobs FOREIGN KEY (project_id, job_id) REFERENCES generation_jobs (project_id, id) ON DELETE RESTRICT",
        "ALTER TABLE commerce_reservations ADD CONSTRAINT fk_commerce_reservations_project_id_price_version_id_co_f1da FOREIGN KEY (project_id, price_version_id) REFERENCES commerce_plan_versions (project_id, id) ON DELETE RESTRICT",
        "ALTER TABLE commerce_reservations ADD CONSTRAINT uq_commerce_reservations_project_id_job_id UNIQUE (project_id, job_id)",
        "ALTER TABLE commerce_ledger ADD CONSTRAINT fk_commerce_ledger_project_id_bucket_id_commerce_buckets FOREIGN KEY (project_id, bucket_id) REFERENCES commerce_buckets (project_id, id) ON DELETE RESTRICT",
        "ALTER TABLE commerce_ledger ADD CONSTRAINT fk_commerce_ledger_project_id_reservation_id_commerce_r_6c18 FOREIGN KEY (project_id, reservation_id) REFERENCES commerce_reservations (project_id, id) ON DELETE RESTRICT",
        "ALTER TABLE commerce_ledger ADD CONSTRAINT uq_commerce_ledger_project_id_event_key UNIQUE (project_id, event_key)",
        "ALTER TABLE commerce_workspace_transfers ADD CONSTRAINT fk_commerce_workspace_transfers_project_id_source_bucke_e21e FOREIGN KEY (project_id, source_bucket_id) REFERENCES commerce_buckets (project_id, id) ON DELETE RESTRICT",
        "ALTER TABLE commerce_workspace_transfers ADD CONSTRAINT fk_commerce_workspace_transfers_project_id_source_entry_0f33 FOREIGN KEY (project_id, source_entry_id) REFERENCES commerce_ledger (project_id, id) ON DELETE RESTRICT",
        "ALTER TABLE commerce_workspace_transfers ADD CONSTRAINT fk_commerce_workspace_transfers_target_project_id_targe_2c32 FOREIGN KEY (target_project_id, target_bucket_id) REFERENCES commerce_buckets (project_id, id)",
        "ALTER TABLE commerce_workspace_transfers ADD CONSTRAINT fk_commerce_workspace_transfers_target_project_id_targe_6227 FOREIGN KEY (target_project_id, target_entry_id) REFERENCES commerce_ledger (project_id, id)",
        "ALTER TABLE service_configuration_versions ADD CONSTRAINT uq_service_configuration_versions_project_id_version UNIQUE (project_id, version)",
        "ALTER TABLE service_announcements ADD CONSTRAINT uq_service_announcements_project_id_announcement_key_version UNIQUE (project_id, announcement_key, version)",
        "ALTER TABLE service_requests ADD CONSTRAINT uq_service_requests_project_id_id_requester_id UNIQUE (project_id, id, requester_id)",
        "ALTER TABLE service_request_events ADD CONSTRAINT fk_service_request_events_project_id_request_id_service_6978 FOREIGN KEY (project_id, request_id) REFERENCES service_requests (project_id, id) ON DELETE RESTRICT",
        "ALTER TABLE service_request_events ADD CONSTRAINT uq_service_request_events_project_id_request_id_sequence UNIQUE (project_id, request_id, sequence)",
        "ALTER TABLE service_export_files ADD CONSTRAINT fk_service_export_files_project_id_request_id_service_requests FOREIGN KEY (project_id, request_id) REFERENCES service_requests (project_id, id) ON DELETE RESTRICT",
        "ALTER TABLE service_export_files ADD CONSTRAINT fk_service_export_files_project_id_request_id_requester_c429 FOREIGN KEY (project_id, request_id, requester_id) REFERENCES service_requests (project_id, id, requester_id)",
        "ALTER TABLE service_export_files ADD CONSTRAINT uq_service_export_files_project_id_request_id UNIQUE (project_id, request_id)",
        "ALTER TABLE service_api_keys ADD CONSTRAINT uq_service_api_keys_id UNIQUE (id)",
        "ALTER TABLE service_api_calls ADD CONSTRAINT fk_service_api_calls_project_id_api_key_id_service_api_keys FOREIGN KEY (project_id, api_key_id) REFERENCES service_api_keys (project_id, id) ON DELETE RESTRICT",
        "ALTER TABLE service_api_calls ADD CONSTRAINT uq_service_api_calls_project_id_call_id_phase UNIQUE (project_id, call_id, phase)",
        "ALTER TABLE service_api_call_jobs ADD CONSTRAINT fk_service_api_call_jobs_project_id_call_event_id_servi_db1a FOREIGN KEY (project_id, call_event_id) REFERENCES service_api_calls (project_id, id) ON DELETE RESTRICT",
    )
    for stmt in restore_constraints:
        op.execute(stmt)

    restore_indexes = (
        "CREATE INDEX ix_commerce_orders_external_id ON commerce_orders (project_id, external_id)",
        "CREATE INDEX ix_commerce_orders_plan_id ON commerce_orders (project_id, plan_id)",
        "CREATE INDEX ix_commerce_orders_renewal_of_order_id ON commerce_orders (project_id, renewal_of_order_id)",
        "CREATE INDEX ix_commerce_rates_model_id ON commerce_rates (project_id, model_id)",
        "CREATE INDEX ix_commerce_rates_plan_id ON commerce_rates (project_id, plan_id)",
        "CREATE INDEX ix_commerce_settings_price_version_id ON commerce_settings (project_id, price_version_id)",
        "CREATE INDEX ix_commerce_buckets_order_id ON commerce_buckets (project_id, order_id)",
        "CREATE INDEX ix_commerce_buckets_parent_bucket_id ON commerce_buckets (project_id, parent_bucket_id)",
        "CREATE INDEX ix_commerce_invoices_external_id ON commerce_invoices (project_id, external_id)",
        "CREATE INDEX ix_commerce_invoices_order_id ON commerce_invoices (project_id, order_id)",
        "CREATE INDEX ix_commerce_invoices_tax_id ON commerce_invoices (project_id, tax_id)",
        "CREATE INDEX ix_commerce_invoices_workspace_id ON commerce_invoices (project_id, workspace_id)",
        "CREATE INDEX ix_commerce_payment_events_event_id ON commerce_payment_events (project_id, event_id)",
        "CREATE INDEX ix_commerce_payment_events_order_id ON commerce_payment_events (project_id, order_id)",
        "CREATE INDEX ix_commerce_redemptions_bucket_id ON commerce_redemptions (project_id, bucket_id)",
        "CREATE INDEX ix_commerce_redemptions_campaign_id ON commerce_redemptions (project_id, campaign_id)",
        "CREATE INDEX ix_commerce_reservations_job_id ON commerce_reservations (project_id, job_id)",
        "CREATE INDEX ix_commerce_reservations_price_version_id ON commerce_reservations (project_id, price_version_id)",
        "CREATE INDEX ix_commerce_ledger_bucket_id ON commerce_ledger (project_id, bucket_id)",
        "CREATE INDEX ix_commerce_ledger_reservation_id ON commerce_ledger (project_id, reservation_id)",
        "CREATE INDEX ix_service_api_keys_identity_id ON service_api_keys (project_id, identity_id)",
        "CREATE INDEX ix_service_api_calls_api_key_id ON service_api_calls (project_id, api_key_id)",
        "CREATE INDEX ix_service_api_calls_call_id ON service_api_calls (project_id, call_id)",
        "CREATE INDEX ix_service_api_calls_run_version_id ON service_api_calls (project_id, run_version_id)",
        "CREATE INDEX ix_service_requests_artifact_id ON service_requests (project_id, artifact_id)",
        "CREATE INDEX ix_service_requests_media_id ON service_requests (project_id, media_id)",
        "CREATE INDEX ix_service_requests_requester_id ON service_requests (project_id, requester_id)",
        "CREATE INDEX ix_service_requests_feedback_owner ON service_requests (project_id, requester_id, kind, created_at, id)",
        "CREATE INDEX ix_service_requests_feedback_manage ON service_requests (project_id, kind, created_at, id)",
        "CREATE INDEX ix_service_export_files_request_id ON service_export_files (project_id, request_id)",
        "CREATE INDEX ix_service_export_files_requester_id ON service_export_files (project_id, requester_id)",
        "CREATE INDEX ix_service_request_events_request_id ON service_request_events (project_id, request_id)",
        "CREATE INDEX ix_task_notification_reads_identity ON task_notification_reads (identity_id)",
    )
    for stmt in restore_indexes:
        op.execute(stmt)

