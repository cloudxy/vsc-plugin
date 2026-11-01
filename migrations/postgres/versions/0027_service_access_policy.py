"""Credential network policy and completed local account deactivation events."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0027_service_access_policy'
down_revision = '0026_management'
branch_labels = None
depends_on = None

OLD_STATUSES = "'received','under_review','awaiting_configuration','local_approved','rejected','withdrawn','export_ready','error'"


def upgrade():
    op.add_column('service_api_keys', sa.Column('ip_allowlist', postgresql.JSONB(), nullable=False, server_default='[]'))
    op.add_column('service_api_keys', sa.Column('requests_per_minute', sa.Integer(), nullable=False, server_default='0'))
    op.create_check_constraint(op.f('ck_service_api_keys_network_limits'), 'service_api_keys', "jsonb_typeof(ip_allowlist)='array' AND requests_per_minute BETWEEN 0 AND 10000")
    op.drop_constraint(op.f('ck_service_request_events_status'), 'service_request_events', type_='check')
    op.create_check_constraint(op.f('ck_service_request_events_status'), 'service_request_events', "status IN (" + OLD_STATUSES + ",'account_closed') AND sequence>0")


def downgrade():
    op.drop_constraint(op.f('ck_service_request_events_status'), 'service_request_events', type_='check')
    op.create_check_constraint(op.f('ck_service_request_events_status'), 'service_request_events', "status IN (" + OLD_STATUSES + ") AND sequence>0")
    op.drop_constraint(op.f('ck_service_api_keys_network_limits'), 'service_api_keys', type_='check')
    op.drop_column('service_api_keys', 'requests_per_minute')
    op.drop_column('service_api_keys', 'ip_allowlist')
