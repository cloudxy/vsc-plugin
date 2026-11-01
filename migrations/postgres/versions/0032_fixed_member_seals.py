"""Seal share-media and pricing-rate membership at the creating transaction."""
from alembic import op
revision="0032_fixed_member_seals"
down_revision="0031_text_tool_copies"
branch_labels=None
depends_on=None
# Frozen snapshot: do not import mutable application SQL into historical migrations.
DDL=['LOCK TABLE access_shares, access_share_media, commerce_plan_versions, commerce_rates IN SHARE ROW '
 'EXCLUSIVE MODE',
 'CREATE FUNCTION vsc_access_share_members_match(p uuid, s uuid) RETURNS boolean\n'
 'LANGUAGE sql STABLE AS $$\n'
 'WITH expected AS (\n'
 ' SELECT DISTINCT n.media_id FROM access_shares a JOIN creative_canvas_nodes n\n'
 ' ON n.project_id=a.project_id AND n.version_id=a.canvas_version_id\n'
 ' WHERE a.project_id=p AND a.id=s AND n.media_id IS NOT NULL\n'
 '), actual AS (\n'
 ' SELECT media_id FROM access_share_media WHERE project_id=p AND share_id=s\n'
 ')\n'
 'SELECT EXISTS(SELECT 1 FROM access_shares WHERE project_id=p AND id=s)\n'
 ' AND NOT EXISTS((SELECT media_id FROM expected EXCEPT SELECT media_id FROM actual)\n'
 ' UNION ALL (SELECT media_id FROM actual EXCEPT SELECT media_id FROM expected))\n'
 '$$',
 'CREATE FUNCTION vsc_access_share_members_sealed() RETURNS trigger LANGUAGE plpgsql AS $$\n'
 'DECLARE member_share uuid;\n'
 'BEGIN\n'
 " IF TG_TABLE_NAME='access_shares' THEN member_share:=NEW.id; ELSE member_share:=NEW.share_id; END IF;\n"
 ' IF NOT vsc_access_share_members_match(NEW.project_id,member_share) THEN\n'
 "  RAISE EXCEPTION 'share media must equal the complete fixed canvas version' USING ERRCODE='23514';\n"
 ' END IF;\n'
 ' RETURN NULL;\n'
 'END $$',
 'CREATE CONSTRAINT TRIGGER access_share_members_sealed AFTER INSERT ON access_shares DEFERRABLE INITIALLY '
 'DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_access_share_members_sealed()',
 'CREATE CONSTRAINT TRIGGER access_share_members_sealed AFTER INSERT ON access_share_media DEFERRABLE '
 'INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_access_share_members_sealed()',
 'DO $$ BEGIN\n'
 ' IF EXISTS(SELECT 1 FROM access_shares WHERE NOT vsc_access_share_members_match(project_id,id)) THEN\n'
 "  RAISE EXCEPTION 'existing share media differs from its fixed canvas version; migration requires explicit "
 "repair' USING ERRCODE='23514';\n"
 ' END IF;\n'
 'END $$',
 'CREATE FUNCTION vsc_commerce_rates_match(p uuid, plan uuid) RETURNS boolean\n'
 'LANGUAGE plpgsql STABLE AS $$\n'
 'DECLARE wanted jsonb; item jsonb;\n'
 'BEGIN\n'
 " SELECT document->'rates' INTO wanted FROM commerce_plan_versions WHERE project_id=p AND id=plan;\n"
 " IF jsonb_typeof(wanted) IS DISTINCT FROM 'array' THEN RETURN false; END IF;\n"
 ' IF jsonb_array_length(wanted) NOT BETWEEN 1 AND 200 THEN RETURN false; END IF;\n'
 ' FOR item IN SELECT value FROM jsonb_array_elements(wanted) LOOP\n'
 "  IF jsonb_typeof(item) IS DISTINCT FROM 'object' THEN RETURN false; END IF;\n"
 "  IF (item-ARRAY['model_id','unit','credits_per_unit'])<>'{}'::jsonb\n"
 "   OR jsonb_typeof(item->'model_id') IS DISTINCT FROM 'string'\n"
 "   OR jsonb_typeof(item->'unit') IS DISTINCT FROM 'string'\n"
 "   OR jsonb_typeof(item->'credits_per_unit') IS DISTINCT FROM 'number'\n"
 "   OR (item->>'credits_per_unit') !~ '^[1-9][0-9]*$' THEN RETURN false; END IF;\n"
 ' END LOOP;\n'
 ' RETURN NOT EXISTS(\n'
 "  (SELECT (value->>'model_id')::uuid, value->>'unit', (value->>'credits_per_unit')::bigint\n"
 '   FROM jsonb_array_elements(wanted)\n'
 '   EXCEPT ALL SELECT model_id, unit, credits_per_unit FROM commerce_rates WHERE project_id=p AND '
 'plan_id=plan)\n'
 '  UNION ALL\n'
 '  (SELECT model_id, unit, credits_per_unit FROM commerce_rates WHERE project_id=p AND plan_id=plan\n'
 "   EXCEPT ALL SELECT (value->>'model_id')::uuid, value->>'unit', (value->>'credits_per_unit')::bigint\n"
 '   FROM jsonb_array_elements(wanted))\n'
 ' );\n'
 'EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN RETURN false;\n'
 'END $$',
 'CREATE FUNCTION vsc_commerce_rates_sealed() RETURNS trigger LANGUAGE plpgsql AS $$\n'
 'DECLARE member_plan uuid;\n'
 'BEGIN\n'
 " IF TG_TABLE_NAME='commerce_plan_versions' THEN member_plan:=NEW.id; ELSE member_plan:=NEW.plan_id; END "
 'IF;\n'
 ' IF NOT vsc_commerce_rates_match(NEW.project_id,member_plan) THEN\n'
 "  RAISE EXCEPTION 'commerce rates must equal the complete fixed pricing document' USING ERRCODE='23514';\n"
 ' END IF;\n'
 ' RETURN NULL;\n'
 'END $$',
 'CREATE CONSTRAINT TRIGGER commerce_rates_sealed AFTER INSERT ON commerce_plan_versions DEFERRABLE '
 'INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_commerce_rates_sealed()',
 'CREATE CONSTRAINT TRIGGER commerce_rates_sealed AFTER INSERT ON commerce_rates DEFERRABLE INITIALLY '
 'DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_commerce_rates_sealed()',
 'DO $$ BEGIN\n'
 ' IF EXISTS(SELECT 1 FROM commerce_plan_versions WHERE NOT vsc_commerce_rates_match(project_id,id)) THEN\n'
 "  RAISE EXCEPTION 'existing rates differ from their fixed pricing document; migration requires explicit "
 "repair' USING ERRCODE='23514';\n"
 ' END IF;\n'
 'END $$']

def upgrade():
    for statement in DDL:op.execute(statement)

def downgrade():
    op.execute("DROP TRIGGER access_share_members_sealed ON access_share_media")
    op.execute("DROP TRIGGER access_share_members_sealed ON access_shares")
    op.execute("DROP TRIGGER commerce_rates_sealed ON commerce_rates")
    op.execute("DROP TRIGGER commerce_rates_sealed ON commerce_plan_versions")
    op.execute("DROP FUNCTION vsc_access_share_members_sealed()")
    op.execute("DROP FUNCTION vsc_access_share_members_match(uuid,uuid)")
    op.execute("DROP FUNCTION vsc_commerce_rates_sealed()")
    op.execute("DROP FUNCTION vsc_commerce_rates_match(uuid,uuid)")
