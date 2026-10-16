"""Typed, immutable formal adoption of approved experimental outputs."""
from alembic import op
import sqlalchemy as sa

revision = "0004_trial_adoptions"
down_revision = "0003_resource_settings"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("binding_trial_adoptions",
        sa.Column("project_id", sa.UUID(), nullable=False), sa.Column("decision_id", sa.UUID(), nullable=False),
        sa.Column("run_version_id", sa.UUID(), nullable=False), sa.Column("animatic_version_id", sa.UUID(), nullable=False),
        sa.Column("animatic_approval_id", sa.UUID(), nullable=False),
        sa.PrimaryKeyConstraint("project_id", "decision_id", "run_version_id"),
        sa.ForeignKeyConstraint(["project_id", "decision_id"], ["binding_decisions.project_id", "binding_decisions.id"]),
        sa.ForeignKeyConstraint(["project_id", "run_version_id"], ["artifact_versions.project_id", "artifact_versions.id"]),
        sa.ForeignKeyConstraint(["project_id", "animatic_version_id", "animatic_approval_id"],
                                ["artifact_decisions.project_id", "artifact_decisions.artifact_id", "artifact_decisions.id"]))
    for field in ("run_version_id", "animatic_version_id"):
        op.create_index("ix_binding_trial_adoptions_project_" + field, "binding_trial_adoptions", ["project_id", field])
    op.execute("CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON binding_trial_adoptions FOR EACH ROW EXECUTE FUNCTION vsc_reject_mutation()")
    op.execute("""CREATE FUNCTION vsc_trial_adoption_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE selection binding_decisions%ROWTYPE; approval artifact_decisions%ROWTYPE;
        trial artifact_versions%ROWTYPE; animatic artifact_versions%ROWTYPE; media uuid; related boolean; latest uuid;
    BEGIN
      PERFORM 1 FROM projects WHERE id=NEW.project_id FOR UPDATE;
      SELECT * INTO STRICT selection FROM binding_decisions WHERE project_id=NEW.project_id AND id=NEW.decision_id;
      SELECT * INTO STRICT approval FROM artifact_decisions WHERE project_id=NEW.project_id AND id=NEW.animatic_approval_id;
      SELECT * INTO STRICT trial FROM artifact_versions WHERE project_id=NEW.project_id AND id=NEW.run_version_id;
      SELECT * INTO STRICT animatic FROM artifact_versions WHERE project_id=NEW.project_id AND id=NEW.animatic_version_id;
      IF selection.outcome <> 'select' OR approval.outcome <> 'approve'
        OR trial.artifact_type NOT IN ('production-run','vsc.production_run')
        OR convert_from(trial.document,'UTF8')::jsonb->>'phase' IS DISTINCT FROM 'trial'
        OR animatic.artifact_type NOT IN ('animatic','vsc.animatic') THEN
        RAISE EXCEPTION 'invalid trial adoption evidence' USING ERRCODE='23514';
      END IF;
      SELECT id INTO latest FROM artifact_decisions WHERE project_id=NEW.project_id AND artifact_id=NEW.animatic_version_id
        ORDER BY decision_sequence DESC LIMIT 1;
      IF latest IS DISTINCT FROM NEW.animatic_approval_id THEN
        RAISE EXCEPTION 'animatic approval is no longer current' USING ERRCODE='23514';
      END IF;
      SELECT media_id INTO STRICT media FROM binding_candidates WHERE project_id=NEW.project_id AND id=selection.candidate_id;
      WITH RECURSIVE ancestry(id) AS (
        SELECT media UNION SELECT i.media_id FROM ancestry a
        JOIN operation_outputs o ON o.project_id=NEW.project_id AND o.media_id=a.id
        JOIN operation_inputs i ON i.project_id=o.project_id AND i.operation_id=o.operation_id
      ) SELECT EXISTS(SELECT 1 FROM ancestry a JOIN job_outputs o ON o.project_id=NEW.project_id AND o.media_id=a.id
        JOIN generation_jobs j ON j.project_id=o.project_id AND j.id=o.job_id WHERE j.run_version_id=NEW.run_version_id) INTO related;
      IF NOT related THEN
        RAISE EXCEPTION 'trial output does not belong to selection' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END $$""")
    op.execute("CREATE TRIGGER trial_adoption_guard BEFORE INSERT ON binding_trial_adoptions FOR EACH ROW EXECUTE FUNCTION vsc_trial_adoption_guard()")
    op.execute("""CREATE FUNCTION vsc_trial_selection_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE media uuid; role text; missing boolean;
    BEGIN
      IF NEW.outcome <> 'select' THEN RETURN NEW; END IF;
      PERFORM 1 FROM projects WHERE id=NEW.project_id FOR UPDATE;
      SELECT c.media_id,s.role INTO STRICT media,role FROM binding_candidates c
        JOIN binding_slots s ON s.project_id=c.project_id AND s.id=c.slot_id
        WHERE c.project_id=NEW.project_id AND c.id=NEW.candidate_id;
      IF role IN ('identity_face','costume','location_master','location_view','prop','voice_sample','style_reference',
                  'composition','first_frame','last_frame','reference_audio') THEN RETURN NEW; END IF;
      WITH RECURSIVE ancestry(id) AS (
        SELECT media UNION SELECT i.media_id FROM ancestry a
        JOIN operation_outputs o ON o.project_id=NEW.project_id AND o.media_id=a.id
        JOIN operation_inputs i ON i.project_id=o.project_id AND i.operation_id=o.operation_id
      ) SELECT EXISTS(SELECT 1 FROM ancestry a JOIN job_outputs o ON o.project_id=NEW.project_id AND o.media_id=a.id
        JOIN generation_jobs j ON j.project_id=o.project_id AND j.id=o.job_id
        JOIN artifact_versions r ON r.project_id=j.project_id AND r.id=j.run_version_id
        WHERE r.artifact_type IN ('production-run','vsc.production_run')
          AND convert_from(r.document,'UTF8')::jsonb->>'phase'='trial'
          AND NOT EXISTS(SELECT 1 FROM binding_trial_adoptions t WHERE t.project_id=NEW.project_id
              AND t.decision_id=NEW.id AND t.run_version_id=r.id)) INTO missing;
      IF missing THEN RAISE EXCEPTION 'formal trial selection requires explicit adoption' USING ERRCODE='23514'; END IF;
      RETURN NEW;
    END $$""")
    op.execute("CREATE CONSTRAINT TRIGGER trial_selection_guard AFTER INSERT ON binding_decisions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_trial_selection_guard()")


def downgrade():
    op.execute("DROP TRIGGER trial_selection_guard ON binding_decisions")
    op.execute("DROP FUNCTION vsc_trial_selection_guard()")
    op.drop_table("binding_trial_adoptions")
    op.execute("DROP FUNCTION vsc_trial_adoption_guard()")
