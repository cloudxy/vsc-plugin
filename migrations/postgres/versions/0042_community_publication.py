"""Local community, fixed governance and distribution receipts; original media stays authoritative."""
from alembic import op
revision='0042_community_publication'
down_revision='0041_overseas_production'
branch_labels=None
depends_on=None
DDL=['\n'
 'CREATE TABLE community_rules (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tversion INTEGER NOT NULL, \n'
 '\ttitle TEXT NOT NULL, \n'
 '\tbody TEXT NOT NULL, \n'
 '\tsha256 VARCHAR(64) NOT NULL, \n'
 '\tcreated_by UUID NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_community_rules PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT uq_community_rules_project_id_version UNIQUE (project_id, version), \n'
 '\tCONSTRAINT ck_community_rules_version CHECK (version>0), \n'
 '\tCONSTRAINT fk_community_rules_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON '
 'DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_community_rules_created_by_access_identities FOREIGN KEY(created_by) REFERENCES '
 'access_identities (id) ON DELETE RESTRICT\n'
 ')\n'
 '\n',
 '\n'
 'CREATE TABLE community_publications (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tcreated_by UUID NOT NULL, \n'
 '\tcurrent_version_id UUID, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_community_publications PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_community_publications_project_id_projects FOREIGN KEY(project_id) REFERENCES projects '
 '(id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_community_publications_created_by_access_identities FOREIGN KEY(created_by) REFERENCES '
 'access_identities (id) ON DELETE RESTRICT\n'
 ')\n'
 '\n',
 '\n'
 'CREATE TABLE community_versions (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tpublication_id UUID NOT NULL, \n'
 '\tversion INTEGER NOT NULL, \n'
 '\ttitle TEXT NOT NULL, \n'
 '\tdescription TEXT NOT NULL, \n'
 '\tscope TEXT NOT NULL, \n'
 '\trule_id UUID NOT NULL, \n'
 '\tmedia_id UUID, \n'
 '\tblob_id UUID, \n'
 '\tblob_sha256 VARCHAR(64), \n'
 '\ttemplate_id UUID, \n'
 '\tcontent_sha256 VARCHAR(64) NOT NULL, \n'
 '\tcreated_by UUID NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_community_versions PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_community_versions_project_id_publication_id_communi_6c67 FOREIGN KEY(project_id, '
 'publication_id) REFERENCES community_publications (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_community_versions_project_id_rule_id_community_rules FOREIGN KEY(project_id, rule_id) '
 'REFERENCES community_rules (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_community_versions_project_id_media_id_media_items FOREIGN KEY(project_id, media_id) '
 'REFERENCES media_items (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_community_versions_project_id_template_id_canvas_templates FOREIGN KEY(project_id, '
 'template_id) REFERENCES canvas_templates (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_community_versions_project_id_publication_id_version UNIQUE (project_id, publication_id, '
 'version), \n'
 '\tCONSTRAINT uq_community_versions_project_id_publication_id_id UNIQUE (project_id, publication_id, id), \n'
 '\tCONSTRAINT fk_community_versions_project_id_media_id_blob_id_media_items FOREIGN KEY(project_id, '
 'media_id, blob_id) REFERENCES media_items (project_id, id, blob_id), \n'
 '\tCONSTRAINT fk_community_versions_blob_id_blob_sha256_media_blobs FOREIGN KEY(blob_id, blob_sha256) '
 'REFERENCES media_blobs (id, sha256), \n'
 "\tCONSTRAINT ck_community_versions_content CHECK (version>0 AND scope IN ('project','workspace') AND "
 'num_nonnulls(media_id,template_id)=1 AND (media_id IS NULL)=(blob_id IS NULL) AND (media_id IS '
 'NULL)=(blob_sha256 IS NULL)), \n'
 '\tCONSTRAINT fk_community_versions_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON '
 'DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_community_versions_created_by_access_identities FOREIGN KEY(created_by) REFERENCES '
 'access_identities (id) ON DELETE RESTRICT\n'
 ')\n'
 '\n',
 '\n'
 'CREATE TABLE community_events (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tversion_id UUID NOT NULL, \n'
 '\tsequence INTEGER NOT NULL, \n'
 '\tstatus TEXT NOT NULL, \n'
 '\treason TEXT NOT NULL, \n'
 '\tcreated_by UUID NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_community_events PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_community_events_project_id_version_id_community_versions FOREIGN KEY(project_id, '
 'version_id) REFERENCES community_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_community_events_project_id_version_id_sequence UNIQUE (project_id, version_id, '
 'sequence), \n'
 '\tCONSTRAINT ck_community_events_status CHECK (sequence>0 AND status IN '
 "('draft','published','withdrawn','restricted')), \n"
 '\tCONSTRAINT fk_community_events_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON '
 'DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_community_events_created_by_access_identities FOREIGN KEY(created_by) REFERENCES '
 'access_identities (id) ON DELETE RESTRICT\n'
 ')\n'
 '\n',
 '\n'
 'CREATE TABLE community_reports (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tversion_id UUID NOT NULL, \n'
 '\trule_id UUID NOT NULL, \n'
 '\treporter_id UUID NOT NULL, \n'
 '\treason TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_community_reports PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_community_reports_project_id_version_id_community_versions FOREIGN KEY(project_id, '
 'version_id) REFERENCES community_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_community_reports_project_id_rule_id_community_rules FOREIGN KEY(project_id, rule_id) '
 'REFERENCES community_rules (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_community_reports_project_id_id_version_id_rule_id UNIQUE (project_id, id, version_id, '
 'rule_id), \n'
 '\tCONSTRAINT fk_community_reports_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON '
 'DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_community_reports_reporter_id_access_identities FOREIGN KEY(reporter_id) REFERENCES '
 'access_identities (id) ON DELETE RESTRICT\n'
 ')\n'
 '\n',
 '\n'
 'CREATE TABLE community_moderation (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tversion_id UUID NOT NULL, \n'
 '\trule_id UUID NOT NULL, \n'
 '\treport_id UUID, \n'
 '\tprevious_decision_id UUID, \n'
 '\taction TEXT NOT NULL, \n'
 '\treason TEXT NOT NULL, \n'
 '\tcreated_by UUID NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_community_moderation PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_community_moderation_project_id_version_id_community_6faf FOREIGN KEY(project_id, '
 'version_id) REFERENCES community_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_community_moderation_project_id_rule_id_community_rules FOREIGN KEY(project_id, rule_id) '
 'REFERENCES community_rules (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_community_moderation_project_id_report_id_community_reports FOREIGN KEY(project_id, '
 'report_id) REFERENCES community_reports (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_community_moderation_project_id_previous_decision_id_3c38 FOREIGN KEY(project_id, '
 'previous_decision_id) REFERENCES community_moderation (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_community_moderation_project_id_report_id_version_id_fd4e FOREIGN KEY(project_id, '
 'report_id, version_id, rule_id) REFERENCES community_reports (project_id, id, version_id, rule_id), \n'
 "\tCONSTRAINT ck_community_moderation_action CHECK (action IN ('restrict','release','dismiss')), \n"
 '\tCONSTRAINT fk_community_moderation_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) '
 'ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_community_moderation_created_by_access_identities FOREIGN KEY(created_by) REFERENCES '
 'access_identities (id) ON DELETE RESTRICT\n'
 ')\n'
 '\n',
 '\n'
 'CREATE TABLE distribution_channels (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tchannel_key TEXT NOT NULL, \n'
 '\tversion INTEGER NOT NULL, \n'
 '\tname TEXT NOT NULL, \n'
 '\tadapter TEXT NOT NULL, \n'
 '\tendpoint TEXT NOT NULL, \n'
 '\tcredential_env TEXT NOT NULL, \n'
 '\tenabled BOOLEAN NOT NULL, \n'
 '\tsha256 VARCHAR(64) NOT NULL, \n'
 '\tcreated_by UUID NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_distribution_channels PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT uq_distribution_channels_project_id_channel_key_version UNIQUE (project_id, channel_key, '
 'version), \n'
 '\tCONSTRAINT ck_distribution_channels_version CHECK (version>0), \n'
 '\tCONSTRAINT fk_distribution_channels_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) '
 'ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_distribution_channels_created_by_access_identities FOREIGN KEY(created_by) REFERENCES '
 'access_identities (id) ON DELETE RESTRICT\n'
 ')\n'
 '\n',
 '\n'
 'CREATE TABLE distribution_requests (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tversion_id UUID NOT NULL, \n'
 '\tchannel_id UUID NOT NULL, \n'
 '\tcaption TEXT NOT NULL, \n'
 '\trequest_sha256 VARCHAR(64) NOT NULL, \n'
 '\trequest_key TEXT NOT NULL, \n'
 '\tcreated_by UUID NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_distribution_requests PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_distribution_requests_project_id_version_id_communit_342a FOREIGN KEY(project_id, '
 'version_id) REFERENCES community_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_distribution_requests_project_id_channel_id_distribu_b9f7 FOREIGN KEY(project_id, '
 'channel_id) REFERENCES distribution_channels (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_distribution_requests_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) '
 'ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_distribution_requests_request_key UNIQUE (request_key), \n'
 '\tCONSTRAINT fk_distribution_requests_created_by_access_identities FOREIGN KEY(created_by) REFERENCES '
 'access_identities (id) ON DELETE RESTRICT\n'
 ')\n'
 '\n',
 '\n'
 'CREATE TABLE distribution_events (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\trequest_id UUID NOT NULL, \n'
 '\tsequence INTEGER NOT NULL, \n'
 '\tstatus TEXT NOT NULL, \n'
 '\tremote_id TEXT, \n'
 '\tpublic_url TEXT, \n'
 '\terror_code TEXT, \n'
 '\tcreated_by UUID NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_distribution_events PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_distribution_events_project_id_request_id_distributi_ac30 FOREIGN KEY(project_id, '
 'request_id) REFERENCES distribution_requests (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_distribution_events_project_id_request_id_sequence UNIQUE (project_id, request_id, '
 'sequence), \n'
 '\tCONSTRAINT ck_distribution_events_status CHECK (sequence>0 AND status IN '
 "('prepared','submitting','submitted','unknown','completed','failed','cancelled')), \n"
 '\tCONSTRAINT fk_distribution_events_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) '
 'ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_distribution_events_created_by_access_identities FOREIGN KEY(created_by) REFERENCES '
 'access_identities (id) ON DELETE RESTRICT\n'
 ')\n'
 '\n',
 '\n'
 'CREATE TABLE template_copy_media (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tcopy_id UUID NOT NULL, \n'
 '\tsource_project_id UUID NOT NULL, \n'
 '\tsource_media_id UUID NOT NULL, \n'
 '\ttarget_media_id UUID NOT NULL, \n'
 '\tblob_id UUID NOT NULL, \n'
 '\tsha256 VARCHAR(64) NOT NULL, \n'
 '\tCONSTRAINT pk_template_copy_media PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_template_copy_media_project_id_copy_id_canvas_templa_c374 FOREIGN KEY(project_id, copy_id) '
 'REFERENCES canvas_template_copies (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_template_copy_media_project_id_target_media_id_media_items FOREIGN KEY(project_id, '
 'target_media_id) REFERENCES media_items (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_template_copy_media_source_project_id_source_media_i_f499 FOREIGN KEY(source_project_id, '
 'source_media_id, blob_id) REFERENCES media_items (project_id, id, blob_id), \n'
 '\tCONSTRAINT fk_template_copy_media_project_id_target_media_id_blob__9b2e FOREIGN KEY(project_id, '
 'target_media_id, blob_id) REFERENCES media_items (project_id, id, blob_id), \n'
 '\tCONSTRAINT fk_template_copy_media_blob_id_sha256_media_blobs FOREIGN KEY(blob_id, sha256) REFERENCES '
 'media_blobs (id, sha256), \n'
 '\tCONSTRAINT uq_template_copy_media_project_id_copy_id_source_media_id UNIQUE (project_id, copy_id, '
 'source_media_id), \n'
 '\tCONSTRAINT fk_template_copy_media_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) '
 'ON DELETE RESTRICT\n'
 ')\n'
 '\n',
 '\n'
 'CREATE TABLE template_copy_domains (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tcopy_id UUID NOT NULL, \n'
 '\tsource_project_id UUID NOT NULL, \n'
 '\tsource_spatial_version_id UUID, \n'
 '\ttarget_spatial_version_id UUID, \n'
 '\tsource_tool_version_id UUID, \n'
 '\ttarget_tool_version_id UUID, \n'
 '\tsource_edit_version_id UUID, \n'
 '\ttarget_edit_version_id UUID, \n'
 '\tCONSTRAINT pk_template_copy_domains PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_template_copy_domains_project_id_copy_id_canvas_temp_f659 FOREIGN KEY(project_id, copy_id) '
 'REFERENCES canvas_template_copies (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_template_copy_domains_project_id_target_spatial_vers_8f63 FOREIGN KEY(project_id, '
 'target_spatial_version_id) REFERENCES spatial_scene_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_template_copy_domains_project_id_target_tool_version_2b00 FOREIGN KEY(project_id, '
 'target_tool_version_id) REFERENCES artifact_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_template_copy_domains_project_id_target_edit_version_1fbd FOREIGN KEY(project_id, '
 'target_edit_version_id) REFERENCES edit_revisions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_template_copy_domains_source_project_id_source_spati_f0cd FOREIGN KEY(source_project_id, '
 'source_spatial_version_id) REFERENCES spatial_scene_versions (project_id, id), \n'
 '\tCONSTRAINT fk_template_copy_domains_source_project_id_source_tool__a9aa FOREIGN KEY(source_project_id, '
 'source_tool_version_id) REFERENCES artifact_versions (project_id, id), \n'
 '\tCONSTRAINT fk_template_copy_domains_source_project_id_source_edit__1dd9 FOREIGN KEY(source_project_id, '
 'source_edit_version_id) REFERENCES edit_revisions (project_id, id), \n'
 '\tCONSTRAINT ck_template_copy_domains_typed_mapping CHECK '
 '(num_nonnulls(source_spatial_version_id,source_tool_version_id,source_edit_version_id)=1 AND '
 '(source_spatial_version_id IS NULL)=(target_spatial_version_id IS NULL) AND (source_tool_version_id IS '
 'NULL)=(target_tool_version_id IS NULL) AND (source_edit_version_id IS NULL)=(target_edit_version_id IS '
 'NULL)), \n'
 '\tCONSTRAINT fk_template_copy_domains_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) '
 'ON DELETE RESTRICT\n'
 ')\n'
 '\n',
 'ALTER TABLE community_publications ADD CONSTRAINT fk_community_current_version FOREIGN KEY(project_id, id, '
 'current_version_id) REFERENCES community_versions (project_id, publication_id, id)',
 'CREATE INDEX ix_community_publications_current_version_id ON community_publications (project_id, '
 'current_version_id)',
 'CREATE INDEX ix_community_versions_blob_id ON community_versions (project_id, blob_id)',
 'CREATE INDEX ix_community_versions_media_id ON community_versions (project_id, media_id)',
 'CREATE INDEX ix_community_versions_publication_id ON community_versions (project_id, publication_id)',
 'CREATE INDEX ix_community_versions_rule_id ON community_versions (project_id, rule_id)',
 'CREATE INDEX ix_community_versions_template_id ON community_versions (project_id, template_id)',
 'CREATE INDEX ix_community_events_version_id ON community_events (project_id, version_id)',
 'CREATE INDEX ix_community_reports_reporter_id ON community_reports (project_id, reporter_id)',
 'CREATE INDEX ix_community_reports_rule_id ON community_reports (project_id, rule_id)',
 'CREATE INDEX ix_community_reports_version_id ON community_reports (project_id, version_id)',
 'CREATE INDEX ix_community_moderation_previous_decision_id ON community_moderation (project_id, '
 'previous_decision_id)',
 'CREATE INDEX ix_community_moderation_report_id ON community_moderation (project_id, report_id)',
 'CREATE INDEX ix_community_moderation_rule_id ON community_moderation (project_id, rule_id)',
 'CREATE INDEX ix_community_moderation_version_id ON community_moderation (project_id, version_id)',
 'CREATE INDEX ix_distribution_requests_channel_id ON distribution_requests (project_id, channel_id)',
 'CREATE INDEX ix_distribution_requests_version_id ON distribution_requests (project_id, version_id)',
 'CREATE INDEX ix_distribution_events_remote_id ON distribution_events (project_id, remote_id)',
 'CREATE INDEX ix_distribution_events_request_id ON distribution_events (project_id, request_id)',
 'CREATE INDEX ix_template_copy_media_blob_id ON template_copy_media (project_id, blob_id)',
 'CREATE INDEX ix_template_copy_media_copy_id ON template_copy_media (project_id, copy_id)',
 'CREATE INDEX ix_template_copy_media_source_media_id ON template_copy_media (project_id, source_media_id)',
 'CREATE INDEX ix_template_copy_media_source_project_id ON template_copy_media (project_id, '
 'source_project_id)',
 'CREATE INDEX ix_template_copy_media_target_media_id ON template_copy_media (project_id, target_media_id)',
 'CREATE INDEX ix_template_copy_domains_copy_id ON template_copy_domains (project_id, copy_id)',
 'CREATE INDEX ix_template_copy_domains_source_edit_version_id ON template_copy_domains (project_id, '
 'source_edit_version_id)',
 'CREATE INDEX ix_template_copy_domains_source_project_id ON template_copy_domains (project_id, '
 'source_project_id)',
 'CREATE INDEX ix_template_copy_domains_source_spatial_version_id ON template_copy_domains (project_id, '
 'source_spatial_version_id)',
 'CREATE INDEX ix_template_copy_domains_source_tool_version_id ON template_copy_domains (project_id, '
 'source_tool_version_id)',
 'CREATE INDEX ix_template_copy_domains_target_edit_version_id ON template_copy_domains (project_id, '
 'target_edit_version_id)',
 'CREATE INDEX ix_template_copy_domains_target_spatial_version_id ON template_copy_domains (project_id, '
 'target_spatial_version_id)',
 'CREATE INDEX ix_template_copy_domains_target_tool_version_id ON template_copy_domains (project_id, '
 'target_tool_version_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON community_rules FOR EACH ROW EXECUTE FUNCTION '
 'vsc_reject_mutation()',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON community_versions FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON community_events FOR EACH ROW EXECUTE FUNCTION '
 'vsc_reject_mutation()',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON community_reports FOR EACH ROW EXECUTE FUNCTION '
 'vsc_reject_mutation()',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON community_moderation FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON distribution_channels FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON distribution_requests FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON distribution_events FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON template_copy_media FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON template_copy_domains FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()']
GUARD="CREATE FUNCTION vsc_community_fixed_guard() RETURNS trigger LANGUAGE plpgsql AS $$\nDECLARE actual text; source uuid; previous uuid; previous_action text;\nBEGIN\n IF TG_TABLE_NAME='community_versions' THEN\n  IF NEW.template_id IS NOT NULL THEN\n   SELECT v.sha256 INTO actual FROM canvas_templates t JOIN creative_canvas_versions v ON v.project_id=t.project_id AND v.id=t.version_id WHERE t.project_id=NEW.project_id AND t.id=NEW.template_id;\n  ELSE\n   SELECT b.sha256 INTO actual FROM media_items m JOIN media_blobs b ON b.id=m.blob_id WHERE m.project_id=NEW.project_id AND m.id=NEW.media_id;\n  END IF;\n  IF actual IS DISTINCT FROM NEW.content_sha256 THEN RAISE EXCEPTION 'publication content mismatch' USING ERRCODE='23514'; END IF;\n ELSIF TG_TABLE_NAME IN ('community_reports','community_moderation') THEN\n  SELECT rule_id INTO source FROM community_versions WHERE project_id=NEW.project_id AND id=NEW.version_id;\n  IF source IS DISTINCT FROM NEW.rule_id THEN RAISE EXCEPTION 'publication rule mismatch' USING ERRCODE='23514'; END IF;\n  IF TG_TABLE_NAME='community_moderation' THEN\n   IF NEW.previous_decision_id IS NOT NULL THEN\n   SELECT version_id,action INTO previous,previous_action FROM community_moderation WHERE project_id=NEW.project_id AND id=NEW.previous_decision_id;\n   IF previous IS DISTINCT FROM NEW.version_id OR (NEW.action='release' AND previous_action<>'restrict') THEN RAISE EXCEPTION 'moderation predecessor mismatch' USING ERRCODE='23514'; END IF;\n   END IF;\n  END IF;\n ELSIF TG_TABLE_NAME IN ('template_copy_media','template_copy_domains') THEN\n  SELECT source_project_id INTO source FROM canvas_template_copies WHERE project_id=NEW.project_id AND id=NEW.copy_id;\n  IF source IS DISTINCT FROM NEW.source_project_id THEN RAISE EXCEPTION 'template source project mismatch' USING ERRCODE='23514'; END IF;\n ELSIF TG_TABLE_NAME='distribution_requests' THEN\n  SELECT media_id INTO source FROM community_versions WHERE project_id=NEW.project_id AND id=NEW.version_id;\n  IF source IS NULL THEN RAISE EXCEPTION 'distribution requires fixed media publication' USING ERRCODE='23514'; END IF;\n END IF;\n RETURN NEW;\nEND $$;\nCREATE TRIGGER community_fixed_guard BEFORE INSERT ON community_versions FOR EACH ROW EXECUTE FUNCTION vsc_community_fixed_guard();\nCREATE TRIGGER community_fixed_guard BEFORE INSERT ON community_reports FOR EACH ROW EXECUTE FUNCTION vsc_community_fixed_guard();\nCREATE TRIGGER community_fixed_guard BEFORE INSERT ON community_moderation FOR EACH ROW EXECUTE FUNCTION vsc_community_fixed_guard();\nCREATE TRIGGER community_fixed_guard BEFORE INSERT ON template_copy_media FOR EACH ROW EXECUTE FUNCTION vsc_community_fixed_guard();\nCREATE TRIGGER community_fixed_guard BEFORE INSERT ON template_copy_domains FOR EACH ROW EXECUTE FUNCTION vsc_community_fixed_guard();\nCREATE TRIGGER community_fixed_guard BEFORE INSERT ON distribution_requests FOR EACH ROW EXECUTE FUNCTION vsc_community_fixed_guard();\n"
LIBRARY_COPY_GUARD="CREATE OR REPLACE FUNCTION vsc_library_has_imported_ancestor(p_project_id uuid, p_media_id uuid)\nRETURNS boolean LANGUAGE sql STABLE AS $$\nWITH RECURSIVE edges AS NOT MATERIALIZED (\n\n SELECT c.project_id AS target_project, t.media_id AS target_media,\n        c.source_project_id AS source_project, s.media_id AS source_media\n FROM asset_card_copy_sources c\n JOIN asset_card_form_versions t ON t.project_id=c.project_id AND t.id=c.target_form_version_id\n JOIN asset_card_form_versions s ON s.project_id=c.source_project_id AND s.id=c.source_form_version_id\n WHERE t.media_id IS NOT NULL AND s.media_id IS NOT NULL\n UNION\n SELECT c.project_id, tv.reference_media_id, c.source_project_id, sv.reference_media_id\n FROM asset_card_copy_sources c\n JOIN asset_card_form_versions t ON t.project_id=c.project_id AND t.id=c.target_form_version_id\n JOIN asset_card_form_versions s ON s.project_id=c.source_project_id AND s.id=c.source_form_version_id\n JOIN voice_spec_versions tv ON tv.project_id=t.project_id AND tv.id=t.voice_spec_id\n JOIN voice_spec_versions sv ON sv.project_id=s.project_id AND sv.id=s.voice_spec_id\n WHERE tv.reference_media_id IS NOT NULL AND sv.reference_media_id IS NOT NULL\n UNION\n SELECT project_id,target_media_id,source_project_id,source_media_id FROM template_copy_media\n\n UNION ALL\n SELECT o.project_id,o.media_id,i.project_id,i.media_id FROM operation_outputs o JOIN operation_inputs i ON i.project_id=o.project_id AND i.operation_id=o.operation_id\n UNION ALL\n SELECT o.project_id,o.media_id,i.project_id,i.media_id FROM job_outputs o JOIN job_input_media i ON i.project_id=o.project_id AND i.job_id=o.job_id\n), ancestors(project_id,media_id) AS (\n SELECT p_project_id,p_media_id\n UNION\n SELECT e.source_project,e.source_media FROM ancestors a JOIN edges e ON e.target_project=a.project_id AND e.target_media=a.media_id\n)\nSELECT EXISTS(SELECT 1 FROM ancestors a JOIN library_reuses r ON r.project_id=a.project_id AND r.media_id=a.media_id WHERE r.library_version_id IS NOT NULL AND r.reuse_mode IN ('reference','derive'))\n$$\n"
LIBRARY_PRIOR_GUARD="\nCREATE OR REPLACE FUNCTION vsc_library_has_imported_ancestor(p_project_id uuid, p_media_id uuid)\nRETURNS boolean LANGUAGE sql STABLE AS $$\nWITH RECURSIVE edges AS NOT MATERIALIZED (\n  SELECT o.media_id AS child, i.media_id AS parent\n    FROM operation_outputs o JOIN operation_inputs i\n      ON i.project_id=o.project_id AND i.operation_id=o.operation_id\n    WHERE o.project_id=p_project_id\n  UNION ALL\n  SELECT o.media_id AS child, i.media_id AS parent\n    FROM job_outputs o JOIN job_input_media i\n      ON i.project_id=o.project_id AND i.job_id=o.job_id\n    WHERE o.project_id=p_project_id\n), ancestors(media_id) AS (\n  SELECT p_media_id\n  UNION\n  SELECT edges.parent FROM ancestors JOIN edges ON edges.child=ancestors.media_id\n)\nSELECT EXISTS (\n  SELECT 1 FROM ancestors a JOIN library_reuses r\n    ON r.project_id=p_project_id AND r.media_id=a.media_id\n    WHERE r.library_version_id IS NOT NULL AND r.reuse_mode IN ('reference','derive')\n)\n$$\n"
def upgrade():
    for statement in DDL:op.execute(statement)
    op.execute(GUARD)
    op.execute(LIBRARY_COPY_GUARD)
def downgrade():
    op.execute("LOCK TABLE community_rules,community_publications,community_versions,community_events,community_reports,community_moderation,distribution_channels,distribution_requests,distribution_events,template_copy_media,template_copy_domains IN ACCESS EXCLUSIVE MODE")
    op.execute("DO $$ BEGIN IF EXISTS(SELECT 1 FROM community_rules) OR EXISTS(SELECT 1 FROM community_publications) OR EXISTS(SELECT 1 FROM community_versions) OR EXISTS(SELECT 1 FROM community_events) OR EXISTS(SELECT 1 FROM community_reports) OR EXISTS(SELECT 1 FROM community_moderation) OR EXISTS(SELECT 1 FROM distribution_channels) OR EXISTS(SELECT 1 FROM distribution_requests) OR EXISTS(SELECT 1 FROM distribution_events) OR EXISTS(SELECT 1 FROM template_copy_media) OR EXISTS(SELECT 1 FROM template_copy_domains) THEN RAISE EXCEPTION 'community history exists; use forward recovery' USING ERRCODE='23514'; END IF; END $$")
    op.execute(LIBRARY_PRIOR_GUARD)
    op.execute("ALTER TABLE community_publications DROP CONSTRAINT fk_community_current_version")
    for table in ['template_copy_domains', 'template_copy_media', 'distribution_events', 'distribution_requests', 'distribution_channels', 'community_moderation', 'community_reports', 'community_events', 'community_versions', 'community_publications', 'community_rules']:op.drop_table(table)
    op.execute("DROP FUNCTION vsc_community_fixed_guard()")
