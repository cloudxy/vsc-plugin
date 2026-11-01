"""Fixed local-tool outputs copied into target episodes using the same original blob."""
from alembic import op
revision="0033_creative_tool_imports"
down_revision="0032_fixed_member_seals"
branch_labels=None
depends_on=None
DDL=['\n'
 'CREATE TABLE creative_tool_imports (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tepisode_id UUID NOT NULL, \n'
 '\tmedia_id UUID NOT NULL, \n'
 '\tblob_id UUID NOT NULL, \n'
 '\tsource_project_id UUID NOT NULL, \n'
 '\tsource_artifact_id UUID NOT NULL, \n'
 '\tsource_media_id UUID NOT NULL, \n'
 '\tsha256 TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_creative_tool_imports PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_creative_tool_imports_project_id_episode_id_episodes FOREIGN KEY(project_id, '
 'episode_id) REFERENCES episodes (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_creative_tool_imports_source_project_id_source_artif_81f9 FOREIGN '
 'KEY(source_project_id, source_artifact_id) REFERENCES artifact_versions (project_id, id) ON DELETE '
 'RESTRICT, \n'
 '\tCONSTRAINT fk_creative_tool_imports_source_project_id_source_media_9b44 FOREIGN '
 'KEY(source_project_id, source_media_id, blob_id) REFERENCES media_items (project_id, id, blob_id) ON '
 'DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_creative_tool_imports_project_id_media_id_blob_id_me_0e09 FOREIGN KEY(project_id, '
 'media_id, blob_id) REFERENCES media_items (project_id, id, blob_id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_creative_tool_imports_blob_id_sha256_media_blobs FOREIGN KEY(blob_id, sha256) '
 'REFERENCES media_blobs (id, sha256) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_creative_tool_imports_project_id_episode_id_source_p_2b2d UNIQUE (project_id, '
 'episode_id, source_project_id, source_artifact_id, source_media_id), \n'
 '\tCONSTRAINT ck_creative_tool_imports_different_project CHECK (project_id <> source_project_id), \n'
 '\tCONSTRAINT fk_creative_tool_imports_project_id_projects FOREIGN KEY(project_id) REFERENCES projects '
 '(id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT ck_creative_tool_imports_sha256_format CHECK (sha256 IS NULL OR sha256 ~ '
 "'^[0-9a-f]{64}$')\n"
 ')\n'
 '\n',
 'CREATE INDEX ix_creative_tool_imports_blob ON creative_tool_imports (blob_id, sha256)',
 'CREATE INDEX ix_creative_tool_imports_episode_id ON creative_tool_imports (project_id, episode_id)',
 'CREATE INDEX ix_creative_tool_imports_media_id ON creative_tool_imports (project_id, media_id)',
 'CREATE INDEX ix_creative_tool_imports_source_artifact_id ON creative_tool_imports (source_project_id, '
 'source_artifact_id)',
 'CREATE INDEX ix_creative_tool_imports_source_media_id ON creative_tool_imports (source_project_id, '
 'source_media_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON creative_tool_imports FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()']
def upgrade():
    for sql in DDL:op.execute(sql)
def downgrade():
    op.drop_table("creative_tool_imports")
