"""Working choices and episode-local references, separate from formal approvals."""
from sqlalchemy import Column, Integer, Text, String, ForeignKeyConstraint, UniqueConstraint, CheckConstraint, Index

WORKING_STATE_TABLES = (
    'working_selection_versions', 'current_working_selections', 'episode_assets',
    'episode_asset_forms', 'episode_asset_form_versions', 'classic_draft_media',
    'workbench_run_inputs', 'edit_revision_working_selections',
)
WORKING_STATE_IMMUTABLE = (
    'working_selection_versions', 'episode_asset_form_versions', 'classic_draft_media',
    'workbench_run_inputs', 'edit_revision_working_selections',
)


def declare_working_state(project_table, ref, uid, stamp):
    selections = project_table('working_selection_versions', *ref('shots', 'shot_id'),
        Column('output_kind', Text, nullable=False), Column('version', Integer, nullable=False),
        *ref('binding_candidates', 'candidate_id', nullable=True),
        *ref('generation_jobs', 'source_job_id', nullable=True),
        Column('event_kind', Text, nullable=False), Column('trim_in_ms', Integer), Column('trim_out_ms', Integer),
        Column('created_by', Text, nullable=False), stamp(),
        UniqueConstraint('project_id', 'shot_id', 'output_kind', 'version'),
        UniqueConstraint('project_id', 'shot_id', 'output_kind', 'id'),
        CheckConstraint("output_kind IN ('image','video') AND version>0 AND event_kind IN ('select','clear','trim','auto_select')", name='shape'),
        CheckConstraint("(event_kind='clear') = (candidate_id IS NULL)", name='clear_candidate'),
        CheckConstraint("(trim_in_ms IS NULL AND trim_out_ms IS NULL) OR (trim_in_ms>=0 AND trim_out_ms>trim_in_ms)", name='trim_range'),
        CheckConstraint('(trim_in_ms IS NULL) = (trim_out_ms IS NULL)', name='trim_pair'),
        CheckConstraint("(candidate_id IS NOT NULL AND output_kind='video') = (trim_in_ms IS NOT NULL AND trim_out_ms IS NOT NULL)", name='video_trim'),
        CheckConstraint("event_kind <> 'auto_select' OR source_job_id IS NOT NULL", name='auto_source'))
    heads = project_table('current_working_selections', *ref('shots', 'shot_id'),
        Column('output_kind', Text, nullable=False), uid('selection_version_id', nullable=False),
        UniqueConstraint('project_id', 'shot_id', 'output_kind'),
        ForeignKeyConstraint(['project_id','shot_id','output_kind','selection_version_id'],
            ['working_selection_versions.project_id','working_selection_versions.shot_id','working_selection_versions.output_kind','working_selection_versions.id']))
    assets = project_table('episode_assets', *ref('episodes', 'episode_id'),
        Column('asset_key', Text, nullable=False), Column('name', Text, nullable=False),
        Column('asset_kind', Text, nullable=False), Column('revision', Integer, nullable=False), stamp(),
        UniqueConstraint('project_id','episode_id','asset_key'),
        CheckConstraint("revision>0 AND length(asset_key)>0 AND length(name)>0 AND asset_kind IN ('character','location','prop','voice','style','costume','object','creature','vehicle','plant')", name='shape'))
    forms = project_table('episode_asset_forms', *ref('episode_assets','episode_asset_id'),
        Column('form_key',Text,nullable=False), Column('name',Text,nullable=False),
        uid('current_version_id',nullable=True), stamp(),
        UniqueConstraint('project_id','episode_asset_id','form_key'),
        CheckConstraint('length(form_key)>0 AND length(name)>0',name='names'))
    versions = project_table('episode_asset_form_versions', *ref('episode_asset_forms','form_id'),
        Column('version',Integer,nullable=False), Column('asset_name',Text,nullable=False),
        Column('form_name',Text,nullable=False), uid('source_asset_id',nullable=True), uid('spec_id',nullable=True),
        uid('media_id',nullable=True), uid('blob_id',nullable=True), Column('blob_sha256',String(64)),
        Column('created_by',Text,nullable=False), stamp(),
        UniqueConstraint('project_id','form_id','version'), UniqueConstraint('project_id','form_id','id'),
        ForeignKeyConstraint(['project_id','source_asset_id','spec_id'],['asset_spec_versions.project_id','asset_spec_versions.asset_id','asset_spec_versions.id']),
        ForeignKeyConstraint(['project_id','media_id','blob_id'],['media_items.project_id','media_items.id','media_items.blob_id']),
        ForeignKeyConstraint(['blob_id','blob_sha256'],['media_blobs.id','media_blobs.sha256']),
        CheckConstraint('version>0 AND (source_asset_id IS NULL) = (spec_id IS NULL)',name='source_pair'),
        CheckConstraint('(media_id IS NULL) = (blob_id IS NULL) AND (media_id IS NULL) = (blob_sha256 IS NULL)',name='media_tuple'))
    forms.append_constraint(ForeignKeyConstraint(['project_id','id','current_version_id'],
        ['episode_asset_form_versions.project_id','episode_asset_form_versions.form_id','episode_asset_form_versions.id'],
        name='fk_episode_form_current_version',use_alter=True))
    refs = project_table('classic_draft_media', *ref('artifact_versions','draft_version_id'),
        Column('ordinal',Integer,nullable=False), Column('role',Text,nullable=False),
        Column('reference_key',Text,nullable=False), Column('display_name',Text,nullable=False),
        uid('media_id',nullable=False), uid('blob_id',nullable=False), Column('blob_sha256',String(64),nullable=False),
        *ref('episode_asset_form_versions','episode_asset_form_version_id',nullable=True),
        *ref('artifact_versions','annotation_artifact_id',nullable=True),
        ForeignKeyConstraint(['project_id','media_id','blob_id'],['media_items.project_id','media_items.id','media_items.blob_id']),
        ForeignKeyConstraint(['blob_id','blob_sha256'],['media_blobs.id','media_blobs.sha256']),
        UniqueConstraint('project_id','draft_version_id','ordinal'),
        UniqueConstraint('project_id','draft_version_id','role','media_id'),
        UniqueConstraint('project_id','draft_version_id','reference_key'),
        CheckConstraint('ordinal>=0 AND length(role)>0 AND length(reference_key)>0',name='shape'))
    runs = project_table('workbench_run_inputs', *ref('artifact_versions','run_version_id'),
        *ref('shots','shot_id'), uid('draft_version_id',nullable=False), Column('draft_sha256',String(64),nullable=False),
        Column('output_kind',Text,nullable=False), uid('base_selection_version_id',nullable=True),
        ForeignKeyConstraint(['project_id','draft_version_id','draft_sha256'],['artifact_versions.project_id','artifact_versions.id','artifact_versions.sha256']),
        ForeignKeyConstraint(['project_id','shot_id','output_kind','base_selection_version_id'],
            ['working_selection_versions.project_id','working_selection_versions.shot_id','working_selection_versions.output_kind','working_selection_versions.id']),
        CheckConstraint("output_kind IN ('image','video','audio') AND (output_kind<>'audio' OR base_selection_version_id IS NULL)",name='output_kind'),
        UniqueConstraint('project_id','run_version_id','shot_id'))
    edits = project_table('edit_revision_working_selections', *ref('edit_revisions','edit_version_id'),
        Column('clip_key',Text,nullable=False), *ref('working_selection_versions','selection_version_id'),
        ForeignKeyConstraint(['project_id','edit_version_id','clip_key'],['edit_revision_media.project_id','edit_revision_media.edit_version_id','edit_revision_media.clip_key']),
        UniqueConstraint('project_id','edit_version_id','clip_key'))
    result = {t.name:t for t in (selections,heads,assets,forms,versions,refs,runs,edits)}
    for table in result.values():
        for column in table.c:
            if column.name.endswith('_id') and column.name not in {'project_id','id'}:
                Index('ix_'+table.name+'_'+column.name,table.c.project_id,column)
    return result
