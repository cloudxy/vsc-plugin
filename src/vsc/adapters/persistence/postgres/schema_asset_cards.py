"""Project asset working cards pin original identity, specification and media facts."""
from sqlalchemy import Column,Text,Integer,String,Boolean,ForeignKeyConstraint,UniqueConstraint,CheckConstraint,Index

ASSET_CARD_TABLES=('asset_card_states','asset_card_forms','asset_card_form_versions','asset_card_copy_sources','asset_card_favorites')
ASSET_CARD_IMMUTABLE=('asset_card_form_versions','asset_card_copy_sources')

def declare_asset_cards(project_table,ref,uid,stamp):
    states=project_table('asset_card_states',*ref('asset_identities','asset_id'),Column('revision',Integer,nullable=False),UniqueConstraint('project_id','asset_id'),CheckConstraint('revision>0',name='revision'))
    forms=project_table('asset_card_forms',*ref('asset_identities','asset_id'),Column('form_key',Text,nullable=False),Column('name',Text,nullable=False),uid('current_version_id',nullable=True),stamp(),UniqueConstraint('project_id','asset_id','form_key'),UniqueConstraint('project_id','asset_id','id'),CheckConstraint('length(form_key)>0 AND length(name)>0',name='names'))
    versions=project_table('asset_card_form_versions',*ref('asset_card_forms','form_id'),Column('version',Integer,nullable=False),*ref('asset_spec_versions','spec_id'),Column('asset_name',Text,nullable=False),Column('form_name',Text,nullable=False),uid('media_id',nullable=True),uid('blob_id',nullable=True),Column('blob_sha256',String(64)),*ref('voice_spec_versions','voice_spec_id',nullable=True),Column('created_by',Text,nullable=False),stamp(),UniqueConstraint('project_id','form_id','version'),UniqueConstraint('project_id','form_id','id'),ForeignKeyConstraint(['project_id','media_id','blob_id'],['media_items.project_id','media_items.id','media_items.blob_id']),ForeignKeyConstraint(['blob_id','blob_sha256'],['media_blobs.id','media_blobs.sha256']),CheckConstraint('version>0 AND (media_id IS NULL)=(blob_id IS NULL) AND (media_id IS NULL)=(blob_sha256 IS NULL)',name='media_tuple'))
    forms.append_constraint(ForeignKeyConstraint(['project_id','id','current_version_id'],['asset_card_form_versions.project_id','asset_card_form_versions.form_id','asset_card_form_versions.id'],name='fk_asset_card_current_form',use_alter=True))
    copies=project_table('asset_card_copy_sources',*ref('asset_card_form_versions','target_form_version_id'),uid('source_project_id',nullable=False),uid('source_form_version_id',nullable=False),Column('created_by',Text,nullable=False),stamp(),ForeignKeyConstraint(['source_project_id','source_form_version_id'],['asset_card_form_versions.project_id','asset_card_form_versions.id']),UniqueConstraint('project_id','target_form_version_id'),CheckConstraint('project_id<>source_project_id',name='separate_project'))
    favorites=project_table('asset_card_favorites',*ref('asset_identities','asset_id'),Column('actor',Text,nullable=False),Column('active',Boolean,nullable=False),UniqueConstraint('project_id','asset_id','actor'))
    tables={t.name:t for t in (states,forms,versions,copies,favorites)}
    for table in tables.values():
        for column in table.c:
            if column.name.endswith('_id') and column.name not in ('project_id','id'):Index('ix_'+table.name+'_'+column.name,table.c.project_id,column)
    return tables
