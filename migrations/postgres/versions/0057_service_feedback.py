"""Persist feedback classification without rewriting historical requests."""
from alembic import op

revision = '0057_service_feedback'
down_revision = '0056_library_media_lifecycle'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('ALTER TABLE service_requests ADD COLUMN feedback_category TEXT')
    op.execute("ALTER TABLE service_requests ADD CONSTRAINT ck_service_requests_feedback_category CHECK (feedback_category IS NULL OR (kind='feedback' AND feedback_category IN ('feature','quality','billing','ux','bug')))")
    op.execute('CREATE INDEX ix_service_requests_feedback_owner ON service_requests (project_id, requester_id, kind, created_at, id)')
    op.execute('CREATE INDEX ix_service_requests_feedback_manage ON service_requests (project_id, kind, created_at, id)')


def downgrade():
    op.execute('LOCK TABLE service_requests IN ACCESS EXCLUSIVE MODE')
    op.execute("DO $$ BEGIN IF EXISTS(SELECT 1 FROM service_requests WHERE feedback_category IS NOT NULL) THEN RAISE EXCEPTION 'feedback classifications exist; use forward recovery' USING ERRCODE='23514'; END IF; END $$")
    op.drop_index('ix_service_requests_feedback_manage',table_name='service_requests')
    op.drop_index('ix_service_requests_feedback_owner',table_name='service_requests')
    op.drop_constraint(op.f('ck_service_requests_feedback_category'),'service_requests',type_='check')
    op.drop_column('service_requests','feedback_category')
