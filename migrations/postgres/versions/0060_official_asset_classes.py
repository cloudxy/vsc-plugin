"""Store official scene, space, prop and role-tag classes as sealed rows.

The publication keeps its original role_tag. Classification rows are a
projection of that text, written in the publishing transaction and checked
against the database functions. Existing publications are backfilled here.
Downgrade refuses once any publication or class row exists.
"""
from alembic import op

revision = "0060_official_asset_classes"
down_revision = "0059_platform_scope_decoupling"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("LOCK TABLE official_asset_publications IN SHARE ROW EXCLUSIVE MODE")
    op.execute("""
CREATE TABLE official_class_terms (
	dimension TEXT NOT NULL,
	value TEXT NOT NULL,
	CONSTRAINT pk_official_class_terms PRIMARY KEY (dimension, value),
	CONSTRAINT ck_official_class_terms_dimension CHECK (dimension IN ('scene_type','space','prop_type')),
	CONSTRAINT ck_official_class_terms_value CHECK (length(btrim(value)) BETWEEN 1 AND 80)
)""")
    op.execute("""
CREATE TABLE official_location_aliases (
	source_label TEXT NOT NULL,
	scene_dimension TEXT NOT NULL,
	scene_type TEXT NOT NULL,
	space_dimension TEXT NOT NULL,
	space TEXT NOT NULL,
	CONSTRAINT pk_official_location_aliases PRIMARY KEY (source_label),
	CONSTRAINT ck_official_location_aliases_scene_dimension CHECK (scene_dimension = 'scene_type'),
	CONSTRAINT ck_official_location_aliases_space_dimension CHECK (space_dimension = 'space'),
	CONSTRAINT ck_official_location_aliases_source_label CHECK (length(btrim(source_label)) BETWEEN 1 AND 80),
	CONSTRAINT fk_official_location_aliases_scene FOREIGN KEY(scene_dimension, scene_type) REFERENCES official_class_terms (dimension, value) ON DELETE RESTRICT,
	CONSTRAINT fk_official_location_aliases_space FOREIGN KEY(space_dimension, space) REFERENCES official_class_terms (dimension, value) ON DELETE RESTRICT
)""")
    op.execute("""
CREATE TABLE official_prop_aliases (
	source_label TEXT NOT NULL,
	prop_dimension TEXT NOT NULL,
	prop_type TEXT NOT NULL,
	CONSTRAINT pk_official_prop_aliases PRIMARY KEY (source_label),
	CONSTRAINT ck_official_prop_aliases_prop_dimension CHECK (prop_dimension = 'prop_type'),
	CONSTRAINT ck_official_prop_aliases_source_label CHECK (length(btrim(source_label)) BETWEEN 1 AND 80),
	CONSTRAINT fk_official_prop_aliases_type FOREIGN KEY(prop_dimension, prop_type) REFERENCES official_class_terms (dimension, value) ON DELETE RESTRICT
)""")
    op.execute("""
CREATE TABLE official_class_seals (
	name TEXT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_official_class_seals PRIMARY KEY (name),
	CONSTRAINT ck_official_class_seals_name CHECK (name = 'classification')
)""")
    op.execute("""
CREATE TABLE official_location_classes (
	publication_id UUID NOT NULL,
	scene_dimension TEXT NOT NULL,
	scene_type TEXT NOT NULL,
	space_dimension TEXT NOT NULL,
	space TEXT NOT NULL,
	CONSTRAINT pk_official_location_classes PRIMARY KEY (publication_id),
	CONSTRAINT ck_official_location_classes_scene_dimension CHECK (scene_dimension = 'scene_type'),
	CONSTRAINT ck_official_location_classes_space_dimension CHECK (space_dimension = 'space'),
	CONSTRAINT fk_official_location_classes_publication FOREIGN KEY(publication_id) REFERENCES official_asset_publications (id) ON DELETE RESTRICT,
	CONSTRAINT fk_official_location_classes_scene FOREIGN KEY(scene_dimension, scene_type) REFERENCES official_class_terms (dimension, value) ON DELETE RESTRICT,
	CONSTRAINT fk_official_location_classes_space FOREIGN KEY(space_dimension, space) REFERENCES official_class_terms (dimension, value) ON DELETE RESTRICT
)""")
    op.execute("""
CREATE TABLE official_prop_classes (
	publication_id UUID NOT NULL,
	prop_dimension TEXT NOT NULL,
	prop_type TEXT NOT NULL,
	CONSTRAINT pk_official_prop_classes PRIMARY KEY (publication_id),
	CONSTRAINT ck_official_prop_classes_prop_dimension CHECK (prop_dimension = 'prop_type'),
	CONSTRAINT fk_official_prop_classes_publication FOREIGN KEY(publication_id) REFERENCES official_asset_publications (id) ON DELETE RESTRICT,
	CONSTRAINT fk_official_prop_classes_type FOREIGN KEY(prop_dimension, prop_type) REFERENCES official_class_terms (dimension, value) ON DELETE RESTRICT
)""")
    op.execute("""
CREATE TABLE official_asset_role_tags (
	publication_id UUID NOT NULL,
	ordinal INTEGER NOT NULL,
	value TEXT NOT NULL,
	CONSTRAINT pk_official_asset_role_tags PRIMARY KEY (publication_id, value),
	CONSTRAINT uq_official_asset_role_tags_publication_id_ordinal UNIQUE (publication_id, ordinal),
	CONSTRAINT ck_official_asset_role_tags_ordinal CHECK (ordinal BETWEEN 0 AND 40),
	CONSTRAINT ck_official_asset_role_tags_value CHECK (length(btrim(value)) BETWEEN 1 AND 80 AND value !~ '^(幼年|少年|青年|中年|老年|壮年)(男|女)$'),
	CONSTRAINT fk_official_role_tags_publication FOREIGN KEY(publication_id) REFERENCES official_asset_publications (id) ON DELETE RESTRICT
)""")
    op.execute("""
CREATE FUNCTION vsc_official_character_tags(tag text)
RETURNS TABLE(ordinal integer, label text)
LANGUAGE sql STABLE AS $$
  SELECT min(ord)::integer, part
  FROM (
    SELECT ordinality - 1 AS ord, btrim(piece) AS part
    FROM regexp_split_to_table(coalesce(tag, ''), ' / ') WITH ORDINALITY AS s(piece, ordinality)
  ) parts
  WHERE part <> ''
    AND part !~ '^(幼年|少年|青年|中年|老年|壮年)(男|女)$'
  GROUP BY part
$$""")
    op.execute("""
CREATE FUNCTION vsc_official_location_class(tag text)
RETURNS TABLE(scene_type text, space text)
LANGUAGE plpgsql STABLE AS $$
DECLARE
  raw text := btrim(coalesce(tag, ''));
  first text := btrim(split_part(raw, ' / ', 1));
  second text := btrim(split_part(raw, ' / ', 2));
BEGIN
  IF first <> '' AND second <> ''
     AND EXISTS (SELECT 1 FROM official_class_terms WHERE dimension = 'scene_type' AND value = first)
     AND EXISTS (SELECT 1 FROM official_class_terms WHERE dimension = 'space' AND value = second)
  THEN
    scene_type := first;
    space := second;
    RETURN NEXT;
    RETURN;
  END IF;
  IF EXISTS (SELECT 1 FROM official_location_aliases WHERE source_label = raw) THEN
    RETURN QUERY
      SELECT a.scene_type, a.space FROM official_location_aliases a WHERE a.source_label = raw;
    RETURN;
  END IF;
  scene_type := '未识别';
  space := '未识别';
  RETURN NEXT;
END $$""")
    op.execute("""
CREATE FUNCTION vsc_official_prop_class(tag text) RETURNS text
LANGUAGE plpgsql STABLE AS $$
DECLARE
  raw text := btrim(coalesce(tag, ''));
  first text := btrim(split_part(raw, ' / ', 1));
  candidate text;
  matched text;
BEGIN
  FOREACH candidate IN ARRAY ARRAY[raw, first] LOOP
    IF candidate = '' THEN
      CONTINUE;
    END IF;
    SELECT value INTO matched FROM official_class_terms
      WHERE dimension = 'prop_type' AND official_class_terms.value = candidate;
    IF FOUND THEN
      RETURN matched;
    END IF;
    SELECT prop_type INTO matched FROM official_prop_aliases WHERE source_label = candidate;
    IF FOUND THEN
      RETURN matched;
    END IF;
  END LOOP;
  RETURN '其他';
END $$""")
    op.execute("""
CREATE FUNCTION vsc_official_classes_match(publication uuid) RETURNS boolean
LANGUAGE plpgsql STABLE AS $$
DECLARE
  kind text;
  tag text;
BEGIN
  SELECT asset_kind, role_tag INTO kind, tag FROM official_asset_publications WHERE id = publication;
  IF NOT FOUND THEN
    RETURN false;
  END IF;
  IF kind = 'character' THEN
    RETURN NOT EXISTS (
      (SELECT ordinal, value FROM official_asset_role_tags WHERE publication_id = publication
       EXCEPT SELECT ordinal, label FROM vsc_official_character_tags(tag))
      UNION ALL
      (SELECT ordinal, label FROM vsc_official_character_tags(tag)
       EXCEPT SELECT ordinal, value FROM official_asset_role_tags WHERE publication_id = publication)
    )
    AND NOT EXISTS (SELECT 1 FROM official_location_classes WHERE publication_id = publication)
    AND NOT EXISTS (SELECT 1 FROM official_prop_classes WHERE publication_id = publication);
  ELSIF kind = 'location' THEN
    RETURN NOT EXISTS (SELECT 1 FROM official_asset_role_tags WHERE publication_id = publication)
    AND NOT EXISTS (SELECT 1 FROM official_prop_classes WHERE publication_id = publication)
    AND NOT EXISTS (
      (SELECT scene_type, space FROM official_location_classes WHERE publication_id = publication
       EXCEPT SELECT scene_type, space FROM vsc_official_location_class(tag))
      UNION ALL
      (SELECT scene_type, space FROM vsc_official_location_class(tag)
       EXCEPT SELECT scene_type, space FROM official_location_classes WHERE publication_id = publication)
    );
  ELSIF kind = 'prop' THEN
    RETURN NOT EXISTS (SELECT 1 FROM official_asset_role_tags WHERE publication_id = publication)
    AND NOT EXISTS (SELECT 1 FROM official_location_classes WHERE publication_id = publication)
    AND NOT EXISTS (
      (SELECT prop_type FROM official_prop_classes WHERE publication_id = publication
       EXCEPT SELECT vsc_official_prop_class(tag))
      UNION ALL
      (SELECT vsc_official_prop_class(tag)
       EXCEPT SELECT prop_type FROM official_prop_classes WHERE publication_id = publication)
    );
  END IF;
  RETURN NOT EXISTS (SELECT 1 FROM official_asset_role_tags WHERE publication_id = publication)
    AND NOT EXISTS (SELECT 1 FROM official_location_classes WHERE publication_id = publication)
    AND NOT EXISTS (SELECT 1 FROM official_prop_classes WHERE publication_id = publication);
END $$""")
    op.execute("""
CREATE FUNCTION vsc_official_vocabulary_sealed() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM official_class_seals
    WHERE name = 'classification' AND xmin <> pg_current_xact_id()::xid
  ) THEN
    RAISE EXCEPTION 'official classification vocabulary is sealed' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END $$""")
    op.execute("""
CREATE TRIGGER official_vocabulary_sealed BEFORE INSERT ON official_class_terms
FOR EACH ROW EXECUTE FUNCTION vsc_official_vocabulary_sealed()""")
    op.execute("""
CREATE TRIGGER official_vocabulary_sealed BEFORE INSERT ON official_location_aliases
FOR EACH ROW EXECUTE FUNCTION vsc_official_vocabulary_sealed()""")
    op.execute("""
CREATE TRIGGER official_vocabulary_sealed BEFORE INSERT ON official_prop_aliases
FOR EACH ROW EXECUTE FUNCTION vsc_official_vocabulary_sealed()""")
    op.execute("""
CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON official_class_terms
FOR EACH ROW EXECUTE FUNCTION vsc_reject_mutation()""")
    op.execute("""
CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON official_location_aliases
FOR EACH ROW EXECUTE FUNCTION vsc_reject_mutation()""")
    op.execute("""
CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON official_prop_aliases
FOR EACH ROW EXECUTE FUNCTION vsc_reject_mutation()""")
    op.execute("""
INSERT INTO official_class_terms (dimension, value) VALUES
 ('scene_type', '住宅'),
 ('scene_type', '商业'),
 ('scene_type', '办公'),
 ('scene_type', '医疗'),
 ('scene_type', '教育'),
 ('scene_type', '餐饮'),
 ('scene_type', '其他'),
 ('scene_type', '未识别'),
 ('space', '室内'),
 ('space', '室外'),
 ('space', '半室外'),
 ('space', '未识别'),
 ('prop_type', '武器'),
 ('prop_type', '饰品'),
 ('prop_type', '服饰配件'),
 ('prop_type', '文件/书籍'),
 ('prop_type', '通讯/电子'),
 ('prop_type', '医疗'),
 ('prop_type', '其他')""")
    op.execute("""
INSERT INTO official_location_aliases (source_label, scene_dimension, scene_type, space_dimension, space) VALUES
 ('街巷', 'scene_type', '其他', 'space', '室外'),
 ('街巷夜', 'scene_type', '其他', 'space', '室外'),
 ('石拱桥', 'scene_type', '其他', 'space', '室外'),
 ('山林道', 'scene_type', '其他', 'space', '室外'),
 ('夜雨山道', 'scene_type', '其他', 'space', '室外'),
 ('市集', 'scene_type', '其他', 'space', '室外'),
 ('屋顶天台', 'scene_type', '其他', 'space', '室外'),
 ('废墟', 'scene_type', '其他', 'space', '室外'),
 ('校园', 'scene_type', '其他', 'space', '室外'),
 ('校园夜', 'scene_type', '其他', 'space', '室外'),
 ('宅院厅堂', 'scene_type', '住宅', 'space', '室内'),
 ('宅院厅堂夜', 'scene_type', '住宅', 'space', '室内'),
 ('客栈大堂', 'scene_type', '住宅', 'space', '室内'),
 ('客栈大堂夜', 'scene_type', '住宅', 'space', '室内'),
 ('闺房妆台', 'scene_type', '住宅', 'space', '室内'),
 ('厨房', 'scene_type', '住宅', 'space', '室内'),
 ('豪宅客厅', 'scene_type', '住宅', 'space', '室内'),
 ('卧房', 'scene_type', '住宅', 'space', '室内'),
 ('卧房夜', 'scene_type', '住宅', 'space', '室内'),
 ('民居堂屋', 'scene_type', '住宅', 'space', '室内'),
 ('祠堂', 'scene_type', '住宅', 'space', '室内'),
 ('祠堂夜', 'scene_type', '住宅', 'space', '室内'),
 ('洞府', 'scene_type', '住宅', 'space', '室内'),
 ('医院走廊', 'scene_type', '医疗', 'space', '室内'),
 ('医院病房', 'scene_type', '医疗', 'space', '室内'),
 ('实验楼走廊', 'scene_type', '医疗', 'space', '室内'),
 ('车厢', 'scene_type', '其他', 'space', '室内'),
 ('牢狱', 'scene_type', '其他', 'space', '室内'),
 ('学校课堂', 'scene_type', '教育', 'space', '室内'),
 ('学校礼堂', 'scene_type', '教育', 'space', '室内'),
 ('办公室', 'scene_type', '办公', 'space', '室内'),
 ('未标注', 'scene_type', '未识别', 'space', '未识别'),
 ('其他', 'scene_type', '其他', 'space', '未识别')""")
    op.execute("""
INSERT INTO official_prop_aliases (source_label, prop_dimension, prop_type) VALUES
 ('长枪', 'prop_type', '武器'),
 ('手枪', 'prop_type', '武器'),
 ('长剑', 'prop_type', '武器'),
 ('柳叶刀', 'prop_type', '武器'),
 ('兵器', 'prop_type', '武器'),
 ('中山装', 'prop_type', '服饰配件'),
 ('虎', 'prop_type', '其他'),
 ('飞船', 'prop_type', '其他')""")
    op.execute("INSERT INTO official_class_seals (name) VALUES ('classification')")
    op.execute("""
CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON official_class_seals
FOR EACH ROW EXECUTE FUNCTION vsc_reject_mutation()""")
    op.execute("""
INSERT INTO official_asset_role_tags (publication_id, ordinal, value)
SELECT p.id, tag.ordinal, tag.label
FROM official_asset_publications p
CROSS JOIN LATERAL vsc_official_character_tags(p.role_tag) AS tag
WHERE p.asset_kind = 'character'""")
    op.execute("""
INSERT INTO official_location_classes (publication_id, scene_dimension, scene_type, space_dimension, space)
SELECT p.id, 'scene_type', class.scene_type, 'space', class.space
FROM official_asset_publications p
CROSS JOIN LATERAL vsc_official_location_class(p.role_tag) AS class
WHERE p.asset_kind = 'location'""")
    op.execute("""
INSERT INTO official_prop_classes (publication_id, prop_dimension, prop_type)
SELECT p.id, 'prop_type', vsc_official_prop_class(p.role_tag)
FROM official_asset_publications p
WHERE p.asset_kind = 'prop'""")
    op.execute("""
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM official_asset_publications p WHERE NOT vsc_official_classes_match(p.id)) THEN
    RAISE EXCEPTION 'official class backfill does not match the stored role_tag' USING ERRCODE = '23514';
  END IF;
END $$""")
    op.execute("""
CREATE FUNCTION vsc_official_class_membership() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  kind text;
  created xid;
BEGIN
  SELECT asset_kind, xmin INTO kind, created
  FROM official_asset_publications WHERE id = NEW.publication_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'official class requires its publication' USING ERRCODE = '23503';
  END IF;
  IF created <> pg_current_xact_id()::xid THEN
    RAISE EXCEPTION 'official class membership is sealed with its publication' USING ERRCODE = '23514';
  END IF;
  IF TG_TABLE_NAME = 'official_asset_role_tags' AND kind <> 'character'
     OR TG_TABLE_NAME = 'official_location_classes' AND kind <> 'location'
     OR TG_TABLE_NAME = 'official_prop_classes' AND kind <> 'prop' THEN
    RAISE EXCEPTION 'official class dimension does not match the publication kind' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END $$""")
    for table in ("official_location_classes", "official_prop_classes", "official_asset_role_tags"):
        op.execute(
            "CREATE TRIGGER official_class_membership BEFORE INSERT ON " + table
            + " FOR EACH ROW EXECUTE FUNCTION vsc_official_class_membership()"
        )
        op.execute(
            "CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON " + table
            + " FOR EACH ROW EXECUTE FUNCTION vsc_reject_mutation()"
        )
    op.execute("""
CREATE FUNCTION vsc_official_classes_write() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.asset_kind = 'character' THEN
    INSERT INTO official_asset_role_tags (publication_id, ordinal, value)
    SELECT NEW.id, tag.ordinal, tag.label FROM vsc_official_character_tags(NEW.role_tag) AS tag;
  ELSIF NEW.asset_kind = 'location' THEN
    INSERT INTO official_location_classes (publication_id, scene_dimension, scene_type, space_dimension, space)
    SELECT NEW.id, 'scene_type', class.scene_type, 'space', class.space
    FROM vsc_official_location_class(NEW.role_tag) AS class;
  ELSIF NEW.asset_kind = 'prop' THEN
    INSERT INTO official_prop_classes (publication_id, prop_dimension, prop_type)
    VALUES (NEW.id, 'prop_type', vsc_official_prop_class(NEW.role_tag));
  END IF;
  RETURN NULL;
END $$""")
    op.execute("""
CREATE TRIGGER official_classes_write AFTER INSERT ON official_asset_publications
FOR EACH ROW EXECUTE FUNCTION vsc_official_classes_write()""")
    op.execute("""
CREATE FUNCTION vsc_official_classes_sealed() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  publication uuid;
BEGIN
  IF TG_TABLE_NAME = 'official_asset_publications' THEN
    publication := NEW.id;
  ELSE
    publication := NEW.publication_id;
  END IF;
  IF NOT vsc_official_classes_match(publication) THEN
    RAISE EXCEPTION 'official classes must equal the sealed classification of the publication' USING ERRCODE = '23514';
  END IF;
  RETURN NULL;
END $$""")
    for table in ("official_asset_publications", "official_location_classes", "official_prop_classes", "official_asset_role_tags"):
        op.execute(
            "CREATE CONSTRAINT TRIGGER official_classes_sealed AFTER INSERT ON " + table
            + " DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_official_classes_sealed()"
        )


def downgrade():
    op.execute("LOCK TABLE official_asset_publications IN ACCESS EXCLUSIVE MODE")
    op.execute("""
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM official_asset_publications)
     OR EXISTS (SELECT 1 FROM official_location_classes)
     OR EXISTS (SELECT 1 FROM official_prop_classes)
     OR EXISTS (SELECT 1 FROM official_asset_role_tags) THEN
    RAISE EXCEPTION 'official classifications exist; use forward recovery' USING ERRCODE = '23514';
  END IF;
END $$""")
    for table in ("official_asset_publications", "official_location_classes", "official_prop_classes", "official_asset_role_tags"):
        op.execute("DROP TRIGGER official_classes_sealed ON " + table)
    op.execute("DROP TRIGGER official_classes_write ON official_asset_publications")
    for table in ("official_location_classes", "official_prop_classes", "official_asset_role_tags"):
        op.execute("DROP TRIGGER official_class_membership ON " + table)
        op.execute("DROP TRIGGER immutable_record ON " + table)
    for table in ("official_class_terms", "official_location_aliases", "official_prop_aliases"):
        op.execute("DROP TRIGGER official_vocabulary_sealed ON " + table)
        op.execute("DROP TRIGGER immutable_record ON " + table)
    op.execute("DROP TRIGGER immutable_record ON official_class_seals")
    op.execute("DROP FUNCTION vsc_official_classes_sealed()")
    op.execute("DROP FUNCTION vsc_official_classes_write()")
    op.execute("DROP FUNCTION vsc_official_class_membership()")
    op.execute("DROP FUNCTION vsc_official_classes_match(uuid)")
    op.execute("DROP FUNCTION vsc_official_vocabulary_sealed()")
    op.execute("DROP FUNCTION vsc_official_prop_class(text)")
    op.execute("DROP FUNCTION vsc_official_location_class(text)")
    op.execute("DROP FUNCTION vsc_official_character_tags(text)")
    op.execute("DROP TABLE official_asset_role_tags")
    op.execute("DROP TABLE official_prop_classes")
    op.execute("DROP TABLE official_location_classes")
    op.execute("DROP TABLE official_prop_aliases")
    op.execute("DROP TABLE official_location_aliases")
    op.execute("DROP TABLE official_class_seals")
    op.execute("DROP TABLE official_class_terms")
