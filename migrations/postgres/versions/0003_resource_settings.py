"""Immutable provider identities and precise model defaults.

Each configuration row identifies one provider snapshot; previous_model_id is
unique so concurrent edits cannot fork the current configuration. Routes remain
the authority for defaults, with a typed model/provider/version/modality FK.
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_resource_settings"
down_revision = "0002_review_delegation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("provider_configurations",
        sa.Column("provider_id", sa.Text(), sa.ForeignKey("providers.id"), primary_key=True),
        sa.Column("supplier", sa.Text(), nullable=False), sa.Column("product", sa.Text(), nullable=False),
        sa.Column("plan", sa.Text(), nullable=False), sa.Column("region", sa.Text(), nullable=False),
        sa.Column("execution", sa.Text(), nullable=False), sa.Column("tool_id", sa.Text()),
        sa.Column("previous_model_id", sa.UUID(), sa.ForeignKey("provider_models.id"), unique=True),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")))
    op.add_column("provider_routes", sa.Column("preferred_model_id", sa.UUID()))
    op.add_column("provider_routes", sa.Column("preferred_model_version", sa.Text()))
    op.create_foreign_key("fk_provider_routes_preferred_model", "provider_routes", "provider_models",
        ["preferred_model_id", "preferred_provider", "preferred_model_version", "modality"],
        ["id", "provider_id", "model_version", "modality"])
    op.create_check_constraint("model_version_pair", "provider_routes",
        "(preferred_model_id IS NULL) = (preferred_model_version IS NULL)")
    op.execute("CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON provider_configurations FOR EACH ROW EXECUTE FUNCTION vsc_reject_mutation()")
    # Locks on the provider/model rows serialize registration and task creation.
    # Connection snapshots must survive disable/re-enable and all task states.
    op.execute("""CREATE FUNCTION vsc_provider_snapshot_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF (to_jsonb(NEW) - 'enabled') IS DISTINCT FROM (to_jsonb(OLD) - 'enabled')
        AND (EXISTS(SELECT 1 FROM provider_configurations WHERE provider_id=OLD.id)
          OR EXISTS(SELECT 1 FROM generation_jobs WHERE provider_id=OLD.id)) THEN
        RAISE EXCEPTION 'provider snapshot is immutable; create a new configuration' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END $$""")
    op.execute("CREATE TRIGGER provider_snapshot_guard BEFORE UPDATE ON providers FOR EACH ROW EXECUTE FUNCTION vsc_provider_snapshot_guard()")
    op.execute("""CREATE FUNCTION vsc_model_snapshot_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF (to_jsonb(NEW) - 'enabled') IS DISTINCT FROM (to_jsonb(OLD) - 'enabled') THEN
        RAISE EXCEPTION 'model snapshot is immutable; create a new version' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END $$""")
    op.execute("CREATE TRIGGER model_snapshot_guard BEFORE UPDATE ON provider_models FOR EACH ROW EXECUTE FUNCTION vsc_model_snapshot_guard()")


def downgrade():
    op.execute("DROP TRIGGER model_snapshot_guard ON provider_models")
    op.execute("DROP FUNCTION vsc_model_snapshot_guard()")
    op.execute("DROP TRIGGER provider_snapshot_guard ON providers")
    op.execute("DROP FUNCTION vsc_provider_snapshot_guard()")
    op.drop_constraint("ck_provider_routes_model_version_pair", "provider_routes", type_="check")
    op.drop_constraint("fk_provider_routes_preferred_model", "provider_routes", type_="foreignkey")
    op.drop_column("provider_routes", "preferred_model_version")
    op.drop_column("provider_routes", "preferred_model_id")
    op.drop_table("provider_configurations")
