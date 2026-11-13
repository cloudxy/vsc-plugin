"""Record immutable creators and explicitly attribute legacy project ownership.

Explicit downgrade discards the new creator metadata. Back up before rollback;
ordinary releases must use forward recovery rather than automatic downgrade.
Backfilled ownership bindings remain on downgrade; rollback must not orphan projects.
"""
from alembic import op
from sqlalchemy import text
import uuid

revision = '0058_project_creator'
down_revision = '0057_service_feedback'
branch_labels = None
depends_on = None


def _bind_legacy_owners():
    conn = op.get_bind()
    conn.execute(text('LOCK TABLE access_identities, access_workspaces, access_projects IN SHARE ROW EXCLUSIVE MODE'))
    missing = conn.execute(text('SELECT id FROM projects p WHERE NOT EXISTS '
        '(SELECT 1 FROM access_projects a WHERE a.project_id=p.id) ORDER BY id')).scalars().all()
    if not missing:
        return
    actor = op.get_context().config.attributes.get('legacy_project_owner_actor')
    if actor is not None:
        if not isinstance(actor, str) or not actor.strip():
            raise RuntimeError('legacy_project_owner_actor must name an existing owner actor')
        owner = conn.execute(text('SELECT id, actor, display_name, active FROM access_identities WHERE actor=:actor'),
            dict(actor=actor)).mappings().one_or_none()
        if owner is None:
            raise RuntimeError('legacy_project_owner_actor does not identify an existing account; '
                'supply an existing owner before migration')
    else:
        owners = conn.execute(text("SELECT i.id, i.actor, i.display_name, i.active FROM access_identities i "
            "JOIN access_workspaces w ON w.created_by=i.id AND w.kind='personal' ORDER BY i.id")).mappings().all()
        if not owners and not conn.scalar(text('SELECT count(*) FROM access_identities')):
            raise RuntimeError('Legacy projects require a retained owner account; create or restore the approved '
                'account and set legacy_project_owner_actor before migration')
        if len(owners) != 1:
            raise RuntimeError('Legacy project ownership is ambiguous for projects ' + ','.join(map(str, missing))
                + '; set Alembic config.attributes["legacy_project_owner_actor"] to the explicitly approved existing actor '
                'or provide reviewed project-to-owner bindings before migration')
        owner = owners[0]
    workspace = conn.scalar(text("SELECT id FROM access_workspaces WHERE kind='personal' AND created_by=:identity"),
        dict(identity=owner['id']))
    if workspace is None:
        workspace = str(uuid.uuid5(uuid.NAMESPACE_URL, 'vsc:personal-workspace:' + str(owner['id'])))
        conn.execute(text("INSERT INTO access_workspaces (id,name,kind,created_by) VALUES (:id,:name,'personal',:owner)"),
            dict(id=workspace, name=owner['display_name'] + '的个人项目', owner=owner['id']))
    conn.execute(text("INSERT INTO access_workspace_members (workspace_id,identity_id,role,active) "
        "VALUES (:workspace,:identity,'owner',:active) ON CONFLICT DO NOTHING"),
        dict(workspace=workspace, identity=owner['id'], active=owner['active']))
    for project_id in missing:
        conn.execute(text("INSERT INTO access_projects (project_id,workspace_id,review_lanes,assigned_by) "
            "VALUES (:project,:workspace,'[]',:owner)"), dict(project=project_id, workspace=workspace, owner=owner['id']))
    conn.execute(text('INSERT INTO access_state (id,revision) VALUES (1,1) '
        'ON CONFLICT (id) DO UPDATE SET revision=access_state.revision+1'))


def upgrade():
    _bind_legacy_owners()
    op.execute('ALTER TABLE projects ADD COLUMN created_by TEXT')
    op.execute("""CREATE FUNCTION vsc_project_creator_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.created_by IS DISTINCT FROM OLD.created_by THEN
                RAISE EXCEPTION 'project creator is immutable' USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END;
    $$""")
    op.execute('CREATE TRIGGER project_creator_immutable BEFORE UPDATE OF created_by ON projects '
        'FOR EACH ROW EXECUTE FUNCTION vsc_project_creator_immutable()')


def downgrade():
    op.execute('DROP TRIGGER project_creator_immutable ON projects')
    op.execute('DROP FUNCTION vsc_project_creator_immutable()')
    op.drop_column('projects', 'created_by')
