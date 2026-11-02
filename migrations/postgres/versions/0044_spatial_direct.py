"""Keep the user's scene generation intent on its original planning task."""
from alembic import op
import sqlalchemy as sa

revision = '0044_spatial_direct'
down_revision = '0043_task_notifications'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('spatial_plan_tasks', sa.Column('apply_mode', sa.Text(), nullable=False,
                                                server_default=sa.text("'review'")))
    op.create_check_constraint(op.f('ck_spatial_plan_tasks_apply_mode'), 'spatial_plan_tasks',
                               "apply_mode IN ('review','direct')")


def downgrade():
    op.execute('LOCK TABLE spatial_plan_tasks IN ACCESS EXCLUSIVE MODE')
    op.execute("DO $$ BEGIN IF EXISTS(SELECT 1 FROM spatial_plan_tasks WHERE apply_mode='direct') THEN RAISE EXCEPTION 'direct scene generation history exists; use forward recovery' USING ERRCODE='23514'; END IF; END $$")
    op.drop_constraint(op.f('ck_spatial_plan_tasks_apply_mode'), 'spatial_plan_tasks', type_='check')
    op.drop_column('spatial_plan_tasks', 'apply_mode')
