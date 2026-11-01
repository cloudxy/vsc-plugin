"""Identity, organization grants, revocable links and original-review submissions."""
from sqlalchemy import Table,Column,Text,Boolean,BigInteger,Integer,DateTime,ForeignKey,ForeignKeyConstraint,CheckConstraint,UniqueConstraint,Index,text
from sqlalchemy.dialects.postgresql import UUID,JSONB

ACCESS_IMMUTABLE=("access_commands",)

def declare_access(metadata):
    def uid(name='id',**kw):return Column(name,UUID(as_uuid=False),**kw)
    def stamp():return Column('created_at',DateTime(timezone=True),nullable=False,server_default=text('now()'))
    def identity(name,nullable=False):return Column(name,UUID(as_uuid=False),ForeignKey('access_identities.id',ondelete='RESTRICT'),nullable=nullable)
    def project():return Column('project_id',UUID(as_uuid=False),ForeignKey('projects.id',ondelete='RESTRICT'),nullable=False)
    state=Table('access_state',metadata,Column('id',Integer,primary_key=True),Column('revision',BigInteger,nullable=False,server_default='0'),CheckConstraint('id=1 AND revision>=0',name='singleton'))
    identities=Table('access_identities',metadata,uid(primary_key=True),Column('subject_key',Text,nullable=False,unique=True),Column('actor',Text,nullable=False,unique=True),Column('display_name',Text,nullable=False),Column('preferences',JSONB,nullable=False),Column('active',Boolean,nullable=False,server_default='true'),stamp())
    credentials=Table('access_credentials',metadata,uid(primary_key=True),identity('identity_id'),Column('secret_sha256',Text,nullable=False,unique=True),Column('revoked',Boolean,nullable=False,server_default='false'),stamp(),CheckConstraint("secret_sha256 ~ '^[0-9a-f]{64}$'",name='sha256'))
    workspaces=Table('access_workspaces',metadata,uid(primary_key=True),Column('name',Text,nullable=False),Column('kind',Text,nullable=False),uid('parent_id',nullable=True),identity('created_by'),stamp(),ForeignKeyConstraint(['parent_id'],['access_workspaces.id']),CheckConstraint("kind IN ('personal','studio','substudio') AND ((kind='substudio')=(parent_id IS NOT NULL))",name='kind'))
    members=Table('access_workspace_members',metadata,Column('workspace_id',UUID(as_uuid=False),ForeignKey('access_workspaces.id'),primary_key=True),Column('identity_id',UUID(as_uuid=False),ForeignKey('access_identities.id'),primary_key=True),Column('role',Text,nullable=False),Column('active',Boolean,nullable=False),stamp(),CheckConstraint("role IN ('owner','editor','reviewer','viewer')",name='role'))
    projects=Table('access_projects',metadata,Column('project_id',UUID(as_uuid=False),ForeignKey('projects.id'),primary_key=True),Column('workspace_id',UUID(as_uuid=False),ForeignKey('access_workspaces.id'),nullable=False),Column('review_lanes',JSONB,nullable=False),identity('assigned_by'),stamp())
    project_members=Table('access_project_members',metadata,Column('project_id',UUID(as_uuid=False),ForeignKey('access_projects.project_id'),primary_key=True),Column('identity_id',UUID(as_uuid=False),ForeignKey('access_identities.id'),primary_key=True),Column('role',Text,nullable=False),Column('active',Boolean,nullable=False),stamp(),CheckConstraint("role IN ('owner','editor','reviewer','viewer')",name='role'))
    invitations=Table('access_invitations',metadata,uid(primary_key=True),Column('workspace_id',UUID(as_uuid=False),ForeignKey('access_workspaces.id')),Column('project_id',UUID(as_uuid=False),ForeignKey('access_projects.project_id')),Column('role',Text,nullable=False),Column('secret_sha256',Text,nullable=False,unique=True),Column('expires_at',DateTime(timezone=True),nullable=False),Column('revoked',Boolean,nullable=False,server_default='false'),identity('created_by'),identity('accepted_by',True),stamp(),CheckConstraint('(workspace_id IS NULL) <> (project_id IS NULL)',name='one_scope'),CheckConstraint("role IN ('editor','reviewer','viewer')",name='role'),CheckConstraint("secret_sha256 ~ '^[0-9a-f]{64}$'",name='sha256'))
    shares=Table('access_shares',metadata,uid(primary_key=True),project(),uid('canvas_id',nullable=False),uid('canvas_version_id',nullable=False),Column('mode',Text,nullable=False),Column('secret_sha256',Text,nullable=False,unique=True),Column('expires_at',DateTime(timezone=True),nullable=False),Column('revoked',Boolean,nullable=False,server_default='false'),identity('created_by'),stamp(),ForeignKeyConstraint(['project_id','canvas_id'],['creative_canvases.project_id','creative_canvases.id']),ForeignKeyConstraint(['project_id','canvas_id','canvas_version_id'],['creative_canvas_versions.project_id','creative_canvas_versions.canvas_id','creative_canvas_versions.id']),UniqueConstraint('project_id','id'),CheckConstraint("mode IN ('view','edit')",name='mode'),CheckConstraint("secret_sha256 ~ '^[0-9a-f]{64}$'",name='sha256'))
    share_media=Table('access_share_media',metadata,Column('project_id',UUID(as_uuid=False),nullable=False,primary_key=True),uid('share_id',primary_key=True),uid('media_id',primary_key=True),ForeignKeyConstraint(['project_id','share_id'],['access_shares.project_id','access_shares.id']),ForeignKeyConstraint(['project_id','media_id'],['media_items.project_id','media_items.id']))
    commands=Table('access_commands',metadata,Column('key',Text,primary_key=True),identity('identity_id',True),Column('action',Text,nullable=False),Column('request_sha256',Text,nullable=False),Column('revision',BigInteger,nullable=False,unique=True),Column('response',JSONB,nullable=False),stamp())
    reviews=Table('access_review_submissions',metadata,project(),uid(primary_key=True),uid('candidate_id',nullable=False),Column('lane',Text,nullable=False),uid('supersedes_id'),identity('submitted_by'),uid('review_id'),stamp(),UniqueConstraint('project_id','id'),ForeignKeyConstraint(['project_id','candidate_id'],['binding_candidates.project_id','binding_candidates.id']),ForeignKeyConstraint(['project_id','candidate_id','review_id'],['media_reviews.project_id','media_reviews.candidate_id','media_reviews.id']),ForeignKeyConstraint(['project_id','supersedes_id'],['access_review_submissions.project_id','access_review_submissions.id']),CheckConstraint("lane IN ('character','storyboard','video')",name='lane'))
    Index('uq_access_personal_workspace',workspaces.c.created_by,unique=True,postgresql_where=text("kind='personal'"))
    Index('uq_access_review_pending',reviews.c.project_id,reviews.c.candidate_id,unique=True,postgresql_where=text('review_id IS NULL'))
    tables=[state,identities,credentials,workspaces,members,projects,project_members,invitations,shares,share_media,commands,reviews]
    for table in tables:
        for col in table.c:
            if col.foreign_keys and not col.primary_key:Index('ix_'+table.name+'_'+col.name,col)
    return {table.name:table for table in tables}


# Canonical trigger specification; migration 0032 freezes these statements.
# Installation requires the complete canvas and access schema, in one transaction.
ACCESS_MEMBER_SEAL_DDL = (
    """CREATE FUNCTION vsc_access_share_members_match(p uuid, s uuid) RETURNS boolean
LANGUAGE sql STABLE AS $$
WITH expected AS (
 SELECT DISTINCT n.media_id FROM access_shares a JOIN creative_canvas_nodes n
 ON n.project_id=a.project_id AND n.version_id=a.canvas_version_id
 WHERE a.project_id=p AND a.id=s AND n.media_id IS NOT NULL
), actual AS (
 SELECT media_id FROM access_share_media WHERE project_id=p AND share_id=s
)
SELECT EXISTS(SELECT 1 FROM access_shares WHERE project_id=p AND id=s)
 AND NOT EXISTS((SELECT media_id FROM expected EXCEPT SELECT media_id FROM actual)
 UNION ALL (SELECT media_id FROM actual EXCEPT SELECT media_id FROM expected))
$$""",
    """CREATE FUNCTION vsc_access_share_members_sealed() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE member_share uuid;
BEGIN
 IF TG_TABLE_NAME='access_shares' THEN member_share:=NEW.id; ELSE member_share:=NEW.share_id; END IF;
 IF NOT vsc_access_share_members_match(NEW.project_id,member_share) THEN
  RAISE EXCEPTION 'share media must equal the complete fixed canvas version' USING ERRCODE='23514';
 END IF;
 RETURN NULL;
END $$""",
    "CREATE CONSTRAINT TRIGGER access_share_members_sealed AFTER INSERT ON access_shares DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_access_share_members_sealed()",
    "CREATE CONSTRAINT TRIGGER access_share_members_sealed AFTER INSERT ON access_share_media DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_access_share_members_sealed()",
)
ACCESS_MEMBER_SEAL_PREFLIGHT = """DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM access_shares WHERE NOT vsc_access_share_members_match(project_id,id)) THEN
  RAISE EXCEPTION 'existing share media differs from its fixed canvas version; migration requires explicit repair' USING ERRCODE='23514';
 END IF;
END $$"""


def install_access_member_seals(connection):
    """Install the canonical invariant without rewriting historical share facts."""
    connection.exec_driver_sql('LOCK TABLE access_shares, access_share_media IN SHARE ROW EXCLUSIVE MODE')
    for statement in ACCESS_MEMBER_SEAL_DDL:
        connection.exec_driver_sql(statement)
    connection.exec_driver_sql(ACCESS_MEMBER_SEAL_PREFLIGHT)
