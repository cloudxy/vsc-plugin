"""Immutable, explicitly delegated AI candidate selections.

Revision ID: 0002_review_delegation
Revises: 0001_resource_graph
"""
from alembic import op

revision = "0002_review_delegation"
down_revision = "0001_resource_graph"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE media_reviews ADD CONSTRAINT uq_media_reviews_project_id_candidate_id_id UNIQUE(project_id,candidate_id,id)")
    op.execute("""CREATE TABLE binding_selection_delegations (
        project_id UUID NOT NULL, decision_id UUID NOT NULL,
        slot_id UUID NOT NULL, candidate_id UUID NOT NULL, review_id UUID NOT NULL,
        delegation_artifact_id UUID NOT NULL, approval_decision_id UUID NOT NULL,
        CONSTRAINT pk_binding_selection_delegations PRIMARY KEY(project_id,decision_id),
        CONSTRAINT fk_binding_selection_delegations_project_id_slot_id_can_af76
            FOREIGN KEY(project_id,slot_id,candidate_id,decision_id)
            REFERENCES binding_decisions(project_id,slot_id,candidate_id,id),
        CONSTRAINT fk_binding_selection_delegations_project_id_candidate_i_d722
            FOREIGN KEY(project_id,candidate_id,review_id) REFERENCES media_reviews(project_id,candidate_id,id),
        CONSTRAINT fk_binding_selection_delegations_project_id_delegation__23df
            FOREIGN KEY(project_id,delegation_artifact_id,approval_decision_id)
            REFERENCES artifact_decisions(project_id,artifact_id,id))""")
    op.execute("CREATE INDEX ix_binding_selection_delegations_project_delegation_artifact_id ON binding_selection_delegations(project_id,delegation_artifact_id)")
    op.execute("CREATE INDEX ix_binding_selection_delegations_project_review_id ON binding_selection_delegations(project_id,review_id)")
    op.execute("""CREATE FUNCTION vsc_delegation_approval_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE policy jsonb; kind text;
    BEGIN
        SELECT artifact_type, convert_from(document,'UTF8')::jsonb INTO kind, policy
        FROM artifact_versions WHERE project_id=NEW.project_id AND id=NEW.artifact_id
            AND artifact_type='vsc.review_delegation';
        IF kind IS NOT NULL THEN
            PERFORM 1 FROM projects WHERE id=NEW.project_id FOR UPDATE;
            IF NEW.actor IS DISTINCT FROM policy->>'grantor_actor'
                OR NEW.actor IS NOT DISTINCT FROM policy->>'delegate_actor' THEN
                RAISE EXCEPTION 'delegation grantor required' USING ERRCODE='23514';
            END IF;
        END IF;
        RETURN NEW;
    END $$""")
    op.execute("CREATE TRIGGER delegation_approval_guard BEFORE INSERT ON artifact_decisions FOR EACH ROW EXECUTE FUNCTION vsc_delegation_approval_guard()")
    op.execute("""CREATE FUNCTION vsc_delegated_selection_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE policy jsonb; selection binding_decisions%ROWTYPE; review media_reviews%ROWTYPE;
        approval artifact_decisions%ROWTYPE; slot binding_slots%ROWTYPE; source artifact_versions%ROWTYPE;
        latest_id uuid; human_outcome text; covered boolean;
    BEGIN
        PERFORM 1 FROM projects WHERE id=NEW.project_id FOR UPDATE;
        SELECT * INTO STRICT selection FROM binding_decisions WHERE project_id=NEW.project_id AND id=NEW.decision_id;
        SELECT * INTO STRICT review FROM media_reviews WHERE project_id=NEW.project_id AND id=NEW.review_id;
        SELECT * INTO STRICT approval FROM artifact_decisions WHERE project_id=NEW.project_id AND id=NEW.approval_decision_id;
        SELECT * INTO STRICT source FROM artifact_versions WHERE project_id=NEW.project_id AND id=NEW.delegation_artifact_id;
        SELECT * INTO STRICT slot FROM binding_slots WHERE project_id=NEW.project_id AND id=NEW.slot_id;
        IF source.artifact_type <> 'vsc.review_delegation' OR source.project_wide THEN
            RAISE EXCEPTION 'invalid delegation policy' USING ERRCODE='23514';
        END IF;
        policy := convert_from(source.document,'UTF8')::jsonb;
        IF policy->>'format' IS DISTINCT FROM 'vsc.review-delegation/v1'
            OR policy->>'action' IS DISTINCT FROM 'select_candidate'
            OR policy->'final_release_authorized' IS DISTINCT FROM 'false'::jsonb
            OR policy->>'project_id' IS DISTINCT FROM NEW.project_id::text
            OR selection.outcome <> 'select' OR review.reviewer_type <> 'ai' OR review.outcome <> 'pass'
            OR review.reviewer IS DISTINCT FROM selection.actor
            OR policy->>'delegate_actor' IS DISTINCT FROM selection.actor
            OR policy->>'grantor_actor' IS NOT DISTINCT FROM selection.actor
            OR approval.outcome <> 'approve' OR approval.actor IS DISTINCT FROM policy->>'grantor_actor'
            OR jsonb_typeof(policy->'allowed_roles') IS DISTINCT FROM 'array'
            OR NOT coalesce(policy->'allowed_roles' ? slot.role, false)
            OR policy->>'expires_at' IS NULL
            OR (policy->>'expires_at')::timestamptz <= clock_timestamp() THEN
            RAISE EXCEPTION 'delegated selection not authorized' USING ERRCODE='23514';
        END IF;
        SELECT id INTO latest_id FROM artifact_decisions WHERE project_id=NEW.project_id AND artifact_id=source.id
            ORDER BY decision_sequence DESC LIMIT 1;
        IF latest_id IS DISTINCT FROM approval.id THEN
            RAISE EXCEPTION 'delegation approval is no longer current' USING ERRCODE='23514';
        END IF;
        SELECT id INTO latest_id FROM media_reviews WHERE project_id=NEW.project_id AND candidate_id=NEW.candidate_id
            AND reviewer=selection.actor AND reviewer_type='ai' ORDER BY project_revision DESC,id DESC LIMIT 1;
        IF latest_id IS DISTINCT FROM review.id OR review.context_sha256 IS DISTINCT FROM
            (SELECT context_sha256 FROM binding_candidates WHERE project_id=NEW.project_id AND id=NEW.candidate_id) THEN
            RAISE EXCEPTION 'delegated review is stale' USING ERRCODE='23514';
        END IF;
        SELECT outcome INTO human_outcome FROM media_reviews WHERE project_id=NEW.project_id AND candidate_id=NEW.candidate_id
            AND reviewer_type='human' ORDER BY project_revision DESC,id DESC LIMIT 1;
        IF human_outcome IS NOT NULL AND human_outcome <> 'pass' THEN
            RAISE EXCEPTION 'human review veto' USING ERRCODE='23514';
        END IF;
        WITH RECURSIVE edges AS (
            SELECT parent_id,id FROM episodes WHERE project_id=NEW.project_id UNION ALL
            SELECT parent_id,id FROM scenes WHERE project_id=NEW.project_id UNION ALL
            SELECT parent_id,id FROM sequences WHERE project_id=NEW.project_id UNION ALL
            SELECT parent_id,id FROM shots WHERE project_id=NEW.project_id
        ), scopes(id) AS (
            SELECT object_id FROM artifact_object_scopes WHERE project_id=NEW.project_id AND artifact_id=source.id
            UNION SELECT edges.id FROM edges JOIN scopes ON edges.parent_id=scopes.id
        ) SELECT EXISTS(SELECT 1 FROM scopes WHERE id=slot.target_object_id) INTO covered;
        IF NOT covered THEN
            RAISE EXCEPTION 'delegation object scope mismatch' USING ERRCODE='23514';
        END IF;
        RETURN NEW;
    END $$""")
    op.execute("CREATE TRIGGER delegated_selection_guard BEFORE INSERT ON binding_selection_delegations FOR EACH ROW EXECUTE FUNCTION vsc_delegated_selection_guard()")
    op.execute("CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON binding_selection_delegations FOR EACH ROW EXECUTE FUNCTION vsc_reject_mutation()")


def downgrade():
    op.execute("DROP TABLE binding_selection_delegations")
    op.execute("DROP TRIGGER delegation_approval_guard ON artifact_decisions")
    op.execute("DROP FUNCTION vsc_delegated_selection_guard()")
    op.execute("DROP FUNCTION vsc_delegation_approval_guard()")
    op.execute("ALTER TABLE media_reviews DROP CONSTRAINT uq_media_reviews_project_id_candidate_id_id")
