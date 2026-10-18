"""PostgreSQL resource model. Migrations are the only schema installation path.

Each project-owned foreign key includes project_id. JSON columns hold immutable
parameters/evidence; resource relationships always have explicit foreign keys.
"""
from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Column, DateTime, ForeignKey,
    ForeignKeyConstraint, Index, Integer, LargeBinary, MetaData, Numeric,
    PrimaryKeyConstraint, String, Table, Text, UniqueConstraint, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

SCHEMA_REVISION = "0009_role_memory"

metadata = MetaData(naming_convention={
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
})


def uid(name="id", **kw):
    return Column(name, UUID(as_uuid=False), **kw)


def stamp():
    return Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()"))


def project_table(name, *columns, **kw):
    return Table(name, metadata,
                 Column("project_id", UUID(as_uuid=False), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False),
                 uid(), *columns, PrimaryKeyConstraint("project_id", "id"), **kw)


def ref(table, field, target="id", nullable=False, ondelete="RESTRICT"):
    return (uid(field, nullable=nullable), ForeignKeyConstraint(
        ["project_id", field], [table + ".project_id", table + "." + target], ondelete=ondelete))


projects = Table("projects", metadata,
    uid(primary_key=True), Column("name", Text, nullable=False),
    Column("profile", Text, nullable=False), Column("storage_policy", Text, nullable=False),
    Column("profile_snapshot", JSONB, nullable=False),
    Column("revision", BigInteger, nullable=False, server_default="0"),
    Column("decision_sequence", BigInteger, nullable=False, server_default="0"), stamp(),
    CheckConstraint("storage_policy = 'postgres-series-v1'", name="storage_policy"),
    CheckConstraint("revision >= 0 AND decision_sequence >= 0", name="nonnegative_revision"))

project_revisions = Table("project_revisions", metadata,
    Column("project_id", UUID(as_uuid=False), ForeignKey("projects.id"), primary_key=True),
    Column("revision", BigInteger, primary_key=True),
    Column("actor", Text, nullable=False), Column("action", Text, nullable=False),
    Column("command_key", Text, nullable=False), stamp())

command_receipts = Table("command_receipts", metadata,
    Column("project_id", UUID(as_uuid=False), ForeignKey("projects.id"), primary_key=True),
    Column("idempotency_key", Text, primary_key=True),
    Column("request_sha256", String(64), nullable=False),
    Column("response", JSONB, nullable=False), stamp())

creative_objects = project_table("creative_objects",
    Column("kind", Text, nullable=False), Column("display_code", Text, nullable=False),
    Column("title", Text, nullable=False), stamp(),
    CheckConstraint("kind IN ('work','episode','scene','sequence','shot','asset')", name="object_kind"),
    UniqueConstraint("project_id", "id", "kind"),
    UniqueConstraint("project_id", "kind", "display_code"))


def subtype(name, kind, parent=None, *extra):
    parts = [Column("object_kind", Text, nullable=False, server_default=kind),
             Column("ordinal", Integer, nullable=False),
             CheckConstraint("object_kind = '%s'" % kind, name="typed_object"),
             CheckConstraint("ordinal >= 0", name="ordinal"),
             ForeignKeyConstraint(["project_id", "id", "object_kind"],
                                  ["creative_objects.project_id", "creative_objects.id", "creative_objects.kind"])]
    if parent:
        parts += list(ref(parent, "parent_id"))
        parts += [UniqueConstraint("project_id", "parent_id", "ordinal")]
    else:
        parts += [UniqueConstraint("project_id", "ordinal")]
    return project_table(name, *parts, *extra)


works = subtype("works", "work")
episodes = subtype("episodes", "episode", "works")
scenes = subtype("scenes", "scene", "episodes")
sequences = subtype("sequences", "sequence", "scenes")
shots = subtype("shots", "shot", "sequences", Column("duration_ms", Integer),
                CheckConstraint("duration_ms IS NULL OR duration_ms > 0", name="duration"))
asset_identities = project_table("asset_identities",
    Column("object_kind", Text, nullable=False, server_default="asset"),
    Column("asset_kind", Text, nullable=False),
    CheckConstraint("object_kind = 'asset'", name="typed_object"),
    CheckConstraint("asset_kind IN ('character','location','prop','voice','style','costume')", name="asset_kind"),
    ForeignKeyConstraint(["project_id", "id", "object_kind"],
                         ["creative_objects.project_id", "creative_objects.id", "creative_objects.kind"]))

artifact_versions = project_table("artifact_versions",
    Column("artifact_key", Text, nullable=False), Column("version", Integer, nullable=False),
    Column("artifact_type", Text, nullable=False), Column("stage", Text, nullable=False),
    Column("document", LargeBinary, nullable=False), Column("mime_type", Text, nullable=False),
    Column("sha256", String(64), nullable=False), Column("project_wide", Boolean, nullable=False),
    Column("parser_version", Text, nullable=False), stamp(),
    Column("registration_note", Text, nullable=False, server_default=""),
    uid("supersedes_id", nullable=True),
    ForeignKeyConstraint(["project_id", "supersedes_id"], ["artifact_versions.project_id", "artifact_versions.id"]),
    CheckConstraint("version > 0", name="positive_version"),
    CheckConstraint("encode(sha256(document), 'hex') = sha256", name="document_sha256"),
    UniqueConstraint("project_id", "artifact_key", "version"),
    UniqueConstraint("project_id", "artifact_key", "id"),
    UniqueConstraint("project_id", "id", "sha256"))
artifact_dependencies = Table("artifact_dependencies", metadata,
    uid("project_id", nullable=False), uid("artifact_id", nullable=False), uid("dependency_id", nullable=False),
    PrimaryKeyConstraint("project_id", "artifact_id", "dependency_id"),
    ForeignKeyConstraint(["project_id", "artifact_id"], ["artifact_versions.project_id", "artifact_versions.id"]),
    ForeignKeyConstraint(["project_id", "dependency_id"], ["artifact_versions.project_id", "artifact_versions.id"]),
    CheckConstraint("artifact_id <> dependency_id", name="self_dependency"))
artifact_object_scopes = Table("artifact_object_scopes", metadata,
    uid("project_id", nullable=False), uid("artifact_id", nullable=False), uid("object_id", nullable=False),
    PrimaryKeyConstraint("project_id", "artifact_id", "object_id"),
    ForeignKeyConstraint(["project_id", "artifact_id"], ["artifact_versions.project_id", "artifact_versions.id"]),
    ForeignKeyConstraint(["project_id", "object_id"], ["creative_objects.project_id", "creative_objects.id"]))


def decision_columns():
    return [Column("decision_sequence", BigInteger, nullable=False),
            Column("actor", Text, nullable=False), Column("reason", Text, nullable=False),
            Column("based_on_revision", BigInteger, nullable=False), stamp(),
            UniqueConstraint("project_id", "decision_sequence")]


artifact_decisions = project_table("artifact_decisions", *ref("artifact_versions", "artifact_id"),
    Column("outcome", Text, nullable=False), *decision_columns(),
    UniqueConstraint("project_id", "artifact_id", "id"),
    CheckConstraint("outcome IN ('approve','revoke','reject')", name="outcome"))
current_artifact_versions = Table("current_artifact_versions", metadata,
    uid("project_id", nullable=False), Column("artifact_key", Text, nullable=False),
    uid("artifact_id", nullable=False), uid("decision_id", nullable=False),
    PrimaryKeyConstraint("project_id", "artifact_key"),
    ForeignKeyConstraint(["project_id", "artifact_key", "artifact_id"],
                         ["artifact_versions.project_id", "artifact_versions.artifact_key", "artifact_versions.id"]),
    ForeignKeyConstraint(["project_id", "artifact_id", "decision_id"],
                         ["artifact_decisions.project_id", "artifact_decisions.artifact_id", "artifact_decisions.id"]))
asset_spec_versions = project_table("asset_spec_versions", *ref("asset_identities", "asset_id"),
    *ref("artifact_versions", "artifact_id"), Column("variant_key", Text, nullable=False),
    UniqueConstraint("project_id", "asset_id", "id"),
    UniqueConstraint("project_id", "asset_id", "variant_key", "artifact_id"))
artifact_asset_spec_refs = Table("artifact_asset_spec_refs", metadata,
    uid("project_id", nullable=False), uid("artifact_id", nullable=False),
    uid("asset_id", nullable=False), uid("spec_version_id", nullable=False),
    PrimaryKeyConstraint("project_id", "artifact_id", "asset_id"),
    ForeignKeyConstraint(["project_id", "artifact_id"], ["artifact_versions.project_id", "artifact_versions.id"]),
    ForeignKeyConstraint(["project_id", "asset_id", "spec_version_id"],
                         ["asset_spec_versions.project_id", "asset_spec_versions.asset_id", "asset_spec_versions.id"]))

script_lines = project_table("script_lines", *ref("artifact_versions", "script_version_id"),
    *ref("scenes", "scene_id"), *ref("asset_identities", "speaker_id", nullable=True),
    Column("line_key", Text, nullable=False), Column("line_kind", Text, nullable=False),
    Column("text", Text, nullable=False), Column("ordinal", Integer, nullable=False),
    Column("source_sha256", String(64), nullable=False),
    ForeignKeyConstraint(["project_id", "script_version_id", "source_sha256"],
                         ["artifact_versions.project_id", "artifact_versions.id", "artifact_versions.sha256"]),
    CheckConstraint("line_kind IN ('dialogue','narration','action')", name="line_kind"),
    CheckConstraint("ordinal >= 0", name="ordinal"),
    UniqueConstraint("project_id", "script_version_id", "line_key"))
shot_line_coverage = project_table("shot_line_coverage", *ref("artifact_versions", "coverage_version_id"),
    *ref("shots", "shot_id"), *ref("script_lines", "line_id"),
    Column("start_char", Integer, nullable=False), Column("end_char", Integer, nullable=False),
    CheckConstraint("start_char >= 0 AND end_char > start_char", name="character_range"),
    UniqueConstraint("project_id", "coverage_version_id", "shot_id", "line_id", "start_char", "end_char"))

state_versions = project_table("state_versions", *ref("artifact_versions", "artifact_id"),
    *ref("scenes", "scene_id"), *ref("shots", "shot_id", nullable=True),
    *ref("asset_identities", "location_id", nullable=True),
    Column("source_sha256", String(64), nullable=False),
    ForeignKeyConstraint(["project_id", "artifact_id", "source_sha256"],
                         ["artifact_versions.project_id", "artifact_versions.id", "artifact_versions.sha256"]))
state_entity_refs = project_table("state_entity_refs", *ref("state_versions", "state_id"),
    *ref("asset_identities", "asset_id"), *ref("asset_spec_versions", "spec_version_id", nullable=True),
    Column("relation", Text, nullable=False),
    ForeignKeyConstraint(["project_id", "asset_id", "spec_version_id"],
                         ["asset_spec_versions.project_id", "asset_spec_versions.asset_id", "asset_spec_versions.id"]),
    CheckConstraint("relation IN ('present','in_frame','offscreen_voice','held','costume')", name="relation"),
    UniqueConstraint("project_id", "state_id", "asset_id", "relation"))
continuity_edges = project_table("continuity_edges", *ref("shots", "from_shot_id"), *ref("shots", "to_shot_id"),
    *ref("state_versions", "exit_state_id"), *ref("state_versions", "entry_state_id"),
    *ref("artifact_versions", "evidence_version_id"), Column("strategy", Text, nullable=False),
    CheckConstraint("from_shot_id <> to_shot_id", name="distinct_shots"))

media_blobs = Table("media_blobs", metadata, uid(primary_key=True),
    Column("sha256", String(64), nullable=False, unique=True),
    Column("size_bytes", BigInteger, nullable=False), Column("mime_type", Text, nullable=False),
    Column("width", Integer), Column("height", Integer), Column("duration_ms", Integer),
    Column("sample_rate", Integer), Column("probe", JSONB, nullable=False, server_default="{}"), stamp(),
    CheckConstraint("size_bytes >= 0", name="size"),
    CheckConstraint("(width IS NULL OR width > 0) AND (height IS NULL OR height > 0) AND "
                    "(duration_ms IS NULL OR duration_ms >= 0) AND (sample_rate IS NULL OR sample_rate > 0)", name="dimensions"),
    UniqueConstraint("id", "sha256"))
blob_locations = Table("blob_locations", metadata, uid(primary_key=True),
    Column("blob_id", UUID(as_uuid=False), ForeignKey("media_blobs.id"), nullable=False),
    Column("storage", Text, nullable=False), Column("object_key", Text, nullable=False),
    Column("available", Boolean, nullable=False, server_default="true"), stamp(),
    UniqueConstraint("storage", "object_key"), UniqueConstraint("blob_id", "storage", "object_key"))
media_items = project_table("media_items",
    Column("blob_id", UUID(as_uuid=False), ForeignKey("media_blobs.id"), nullable=False),
    Column("name", Text, nullable=False), Column("modality", Text, nullable=False),
    Column("registered_by", Text, nullable=False), stamp(),
    CheckConstraint("modality IN ('image','video','audio','text','document','other')", name="modality"),
    UniqueConstraint("project_id", "id", "blob_id"))
source_versions = project_table("source_versions", Column("source_key", Text, nullable=False),
    Column("version", Integer, nullable=False), Column("kind", Text, nullable=False),
    Column("sha256", String(64), nullable=False), Column("document", LargeBinary, nullable=False),
    Column("evidence_uri", Text), stamp(), UniqueConstraint("project_id", "source_key", "version"),
    UniqueConstraint("project_id", "id", "sha256"),
    CheckConstraint("encode(sha256(document), 'hex') = sha256", name="document_sha256"))
media_sources = project_table("media_sources", *ref("media_items", "media_id"), *ref("source_versions", "source_id"),
    Column("role", Text, nullable=False), Column("citation", JSONB, nullable=False, server_default="{}"),
    UniqueConstraint("project_id", "media_id", "source_id", "role"))
rights_decisions = project_table("rights_decisions", *ref("media_items", "media_id"),
    *ref("source_versions", "source_id", nullable=True), Column("outcome", Text, nullable=False),
    Column("scope", JSONB, nullable=False), Column("expires_at", DateTime(timezone=True)), *decision_columns(),
    CheckConstraint("outcome IN ('owned','licensed','unknown','restricted','revoked')", name="outcome"))
media_lifecycle_decisions = project_table("media_lifecycle_decisions", *ref("media_items", "media_id"),
    Column("outcome", Text, nullable=False), *decision_columns(),
    CheckConstraint("outcome IN ('deprecate','restore')", name="outcome"))
library_reuses = project_table("library_reuses", *ref("media_items", "media_id"),
    *ref("source_versions", "source_id"), Column("library_key", Text, nullable=False),
    Column("library_version", Text, nullable=False), Column("reuse_mode", Text, nullable=False), stamp())
media_checks = project_table("media_checks", *ref("media_items", "media_id"),
    Column("blob_id", UUID(as_uuid=False), nullable=False), Column("blob_sha256", String(64), nullable=False),
    Column("checker", Text, nullable=False), Column("criteria_version", Text, nullable=False),
    Column("outcome", Text, nullable=False), Column("report", JSONB, nullable=False), stamp(),
    Column("project_revision", BigInteger, nullable=False),
    ForeignKeyConstraint(["project_id", "project_revision"], ["project_revisions.project_id", "project_revisions.revision"], deferrable=True, initially="DEFERRED"),
    ForeignKeyConstraint(["project_id", "media_id", "blob_id"], ["media_items.project_id", "media_items.id", "media_items.blob_id"]),
    ForeignKeyConstraint(["blob_id", "blob_sha256"], ["media_blobs.id", "media_blobs.sha256"]),
    CheckConstraint("outcome IN ('pass','fail','unknown')", name="outcome"))

media_operations = project_table("media_operations", Column("operation_type", Text, nullable=False),
    Column("recipe_version", Text, nullable=False), Column("tool", Text, nullable=False),
    Column("tool_version", Text, nullable=False), Column("parameters", JSONB, nullable=False),
    Column("status", Text, nullable=False), Column("execution", JSONB, nullable=False), stamp(),
    CheckConstraint("status IN ('created','running','succeeded','failed')", name="status"))
operation_inputs = project_table("operation_inputs", *ref("media_operations", "operation_id"),
    *ref("media_items", "media_id"), Column("role", Text, nullable=False),
    Column("layer_order", Integer, nullable=False), Column("start_ms", Integer), Column("end_ms", Integer),
    Column("transform", JSONB, nullable=False), Column("opacity", Numeric(8, 6), nullable=False),
    uid("mask_input_id", nullable=True),
    UniqueConstraint("project_id", "operation_id", "id"),
    ForeignKeyConstraint(["project_id", "operation_id", "mask_input_id"],
                         ["operation_inputs.project_id", "operation_inputs.operation_id", "operation_inputs.id"],
                         deferrable=True, initially="DEFERRED"),
    CheckConstraint("opacity >= 0 AND opacity <= 1", name="opacity"),
    CheckConstraint("mask_input_id IS NULL OR mask_input_id <> id", name="self_mask"),
    CheckConstraint("(start_ms IS NULL OR start_ms >= 0) AND "
                    "(end_ms IS NULL OR (start_ms IS NOT NULL AND end_ms > start_ms))", name="time_range"))
operation_outputs = project_table("operation_outputs", *ref("media_operations", "operation_id"),
    *ref("media_items", "media_id"), Column("role", Text, nullable=False), Column("ordinal", Integer, nullable=False),
    UniqueConstraint("project_id", "media_id"), UniqueConstraint("project_id", "operation_id", "ordinal"))
media_renditions = project_table("media_renditions", *ref("media_items", "media_id"),
    Column("blob_id", UUID(as_uuid=False), ForeignKey("media_blobs.id"), nullable=False),
    Column("purpose", Text, nullable=False), Column("recipe_version", Text, nullable=False),
    Column("tool", Text, nullable=False), Column("tool_version", Text, nullable=False),
    Column("parameters", JSONB, nullable=False), Column("source_blob_id", UUID(as_uuid=False), nullable=False),
    Column("source_sha256", String(64), nullable=False),
    ForeignKeyConstraint(["project_id", "media_id", "source_blob_id"], ["media_items.project_id", "media_items.id", "media_items.blob_id"]),
    ForeignKeyConstraint(["source_blob_id", "source_sha256"], ["media_blobs.id", "media_blobs.sha256"]),
    Column("request_sha256", String(64), nullable=False), stamp(),
    UniqueConstraint("project_id", "media_id", "purpose", "request_sha256"))

binding_slots = project_table("binding_slots", *ref("creative_objects", "target_object_id"),
    Column("role", Text, nullable=False), Column("slot_key", Text, nullable=False),
    *ref("asset_identities", "identity_asset_id", nullable=True),
    *ref("asset_spec_versions", "variant_spec_id", nullable=True),
    *ref("shot_line_coverage", "line_coverage_id", nullable=True),
    Column("track_key", Text), stamp(),
    CheckConstraint("length(slot_key) > 0", name="slot_key"),
    UniqueConstraint("project_id", "target_object_id", "role", "slot_key"))
binding_candidates = project_table("binding_candidates", *ref("binding_slots", "slot_id"), *ref("media_items", "media_id"),
    *ref("artifact_versions", "spec_version_id", nullable=True), Column("context_sha256", String(64)),
    Column("proposer", Text, nullable=False), stamp(), UniqueConstraint("project_id", "slot_id", "id"))
media_reviews = project_table("media_reviews", *ref("binding_candidates", "candidate_id"),
    *ref("media_checks", "check_id", nullable=True), Column("reviewer", Text, nullable=False),
    Column("reviewer_type", Text, nullable=False), Column("criteria_version", Text, nullable=False),
    Column("context_sha256", String(64)), Column("outcome", Text, nullable=False),
    Column("reason", Text, nullable=False), Column("evidence", JSONB, nullable=False), stamp(),
    Column("project_revision", BigInteger, nullable=False),
    UniqueConstraint("project_id", "candidate_id", "id"),
    ForeignKeyConstraint(["project_id", "project_revision"], ["project_revisions.project_id", "project_revisions.revision"], deferrable=True, initially="DEFERRED"),
    CheckConstraint("reviewer_type IN ('human','ai','tool')", name="reviewer_type"),
    CheckConstraint("outcome IN ('pass','fail','needs_changes')", name="outcome"))
binding_decisions = project_table("binding_decisions", *ref("binding_slots", "slot_id"),
    uid("candidate_id", nullable=False), Column("outcome", Text, nullable=False), *decision_columns(),
    ForeignKeyConstraint(["project_id", "slot_id", "candidate_id"],
                         ["binding_candidates.project_id", "binding_candidates.slot_id", "binding_candidates.id"]),
    UniqueConstraint("project_id", "slot_id", "candidate_id", "id"),
    CheckConstraint("outcome IN ('select','reject','retire')", name="outcome"))
binding_selection_delegations = Table("binding_selection_delegations", metadata,
    uid("project_id", nullable=False), uid("decision_id", nullable=False),
    uid("slot_id", nullable=False), uid("candidate_id", nullable=False), uid("review_id", nullable=False),
    uid("delegation_artifact_id", nullable=False), uid("approval_decision_id", nullable=False),
    PrimaryKeyConstraint("project_id", "decision_id"),
    ForeignKeyConstraint(["project_id", "slot_id", "candidate_id", "decision_id"],
        ["binding_decisions.project_id", "binding_decisions.slot_id", "binding_decisions.candidate_id", "binding_decisions.id"]),
    ForeignKeyConstraint(["project_id", "candidate_id", "review_id"],
        ["media_reviews.project_id", "media_reviews.candidate_id", "media_reviews.id"]),
    ForeignKeyConstraint(["project_id", "delegation_artifact_id", "approval_decision_id"],
        ["artifact_decisions.project_id", "artifact_decisions.artifact_id", "artifact_decisions.id"]))
current_bindings = Table("current_bindings", metadata, uid("project_id", nullable=False),
    uid("slot_id", nullable=False), uid("candidate_id", nullable=False), uid("decision_id", nullable=False),
    PrimaryKeyConstraint("project_id", "slot_id"),
    ForeignKeyConstraint(["project_id", "slot_id", "candidate_id"],
                         ["binding_candidates.project_id", "binding_candidates.slot_id", "binding_candidates.id"]),
    ForeignKeyConstraint(["project_id", "slot_id", "candidate_id", "decision_id"],
                         ["binding_decisions.project_id", "binding_decisions.slot_id", "binding_decisions.candidate_id", "binding_decisions.id"]))

# One immutable adoption fact per selection decision and source trial run.
# A processed take can have several trial origins; do not collapse that M:N.
binding_trial_adoptions = Table("binding_trial_adoptions", metadata,
    uid("project_id", nullable=False), uid("decision_id", nullable=False),
    uid("run_version_id", nullable=False), uid("animatic_version_id", nullable=False),
    uid("animatic_approval_id", nullable=False),
    PrimaryKeyConstraint("project_id", "decision_id", "run_version_id"),
    ForeignKeyConstraint(["project_id", "decision_id"], ["binding_decisions.project_id", "binding_decisions.id"]),
    ForeignKeyConstraint(["project_id", "run_version_id"], ["artifact_versions.project_id", "artifact_versions.id"]),
    ForeignKeyConstraint(["project_id", "animatic_version_id", "animatic_approval_id"],
                         ["artifact_decisions.project_id", "artifact_decisions.artifact_id", "artifact_decisions.id"]))

providers = Table("providers", metadata, Column("id", Text, primary_key=True),
    Column("name", Text, nullable=False), Column("modality", Text, nullable=False),
    Column("base_url", Text, nullable=False), Column("auth_ref", Text, nullable=False),
    Column("enabled", Boolean, nullable=False), Column("rate_limit", JSONB, nullable=False), stamp())
provider_models = Table("provider_models", metadata, uid(primary_key=True),
    Column("provider_id", Text, ForeignKey("providers.id"), nullable=False),
    Column("model_key", Text, nullable=False), Column("modality", Text, nullable=False),
    Column("model_version", Text, nullable=False), Column("capabilities", JSONB, nullable=False),
    Column("default_params", JSONB, nullable=False), Column("cost_rule", JSONB, nullable=False),
    Column("enabled", Boolean, nullable=False), UniqueConstraint("provider_id", "model_key", "model_version"),
    UniqueConstraint("id", "provider_id", "model_version", "modality"))
provider_configurations = Table("provider_configurations", metadata,
    Column("provider_id", Text, ForeignKey("providers.id"), primary_key=True),
    Column("supplier", Text, nullable=False), Column("product", Text, nullable=False),
    Column("plan", Text, nullable=False), Column("region", Text, nullable=False),
    Column("execution", Text, nullable=False), Column("tool_id", Text),
    Column("previous_model_id", UUID(as_uuid=False), ForeignKey("provider_models.id"), unique=True),
    Column("actor", Text, nullable=False), stamp())
provider_routes = Table("provider_routes", metadata, uid(primary_key=True),
    Column("modality", Text, nullable=False), Column("purpose", Text, nullable=False),
    Column("preferred_provider", Text, ForeignKey("providers.id"), nullable=False),
    Column("fallback_provider", Text, ForeignKey("providers.id")),
    Column("priority", Integer, nullable=False), Column("enabled", Boolean, nullable=False),
    Column("preferred_model_id", UUID(as_uuid=False)), Column("preferred_model_version", Text),
    ForeignKeyConstraint(["preferred_model_id", "preferred_provider", "preferred_model_version", "modality"],
        ["provider_models.id", "provider_models.provider_id", "provider_models.model_version", "provider_models.modality"]),
    CheckConstraint("(preferred_model_id IS NULL) = (preferred_model_version IS NULL)", name="model_version_pair"))
generation_jobs = project_table("generation_jobs", *ref("artifact_versions", "run_version_id"),
    *ref("shots", "shot_id", nullable=True), *ref("asset_identities", "asset_id", nullable=True),
    Column("purpose", Text, nullable=False), Column("modality", Text, nullable=False),
    Column("candidate_no", Integer, nullable=False), Column("provider_id", Text, ForeignKey("providers.id"), nullable=False),
    Column("model_id", UUID(as_uuid=False), ForeignKey("provider_models.id"), nullable=False),
    Column("model_version", Text, nullable=False), Column("external_task_id", Text),
    Column("request_payload", JSONB, nullable=False), Column("request_sha256", String(64), nullable=False),
    Column("context_sha256", String(64), nullable=False), Column("idempotency_key", Text, nullable=False),
    Column("status", Text, nullable=False), Column("attempt", Integer, nullable=False),
    Column("claim_owner", Text), Column("claim_until", DateTime(timezone=True)),
    Column("cost", Numeric(18, 6)), Column("latency_ms", Integer), Column("raw_response", JSONB), stamp(),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint("project_id", "idempotency_key"),
    UniqueConstraint("provider_id", "external_task_id"),
    ForeignKeyConstraint(["model_id", "provider_id", "model_version", "modality"],
                         ["provider_models.id", "provider_models.provider_id", "provider_models.model_version", "provider_models.modality"]),
    CheckConstraint("(shot_id IS NULL) <> (asset_id IS NULL)", name="single_target"),
    CheckConstraint("candidate_no >= 0 AND attempt >= 0", name="attempt"),
    CheckConstraint("(cost IS NULL OR cost >= 0) AND (latency_ms IS NULL OR latency_ms >= 0)", name="measurements"),
    CheckConstraint("status IN ('created','submitted','running','succeeded','failed','submission_unknown','cancelled')", name="status"))
Index("uq_generation_jobs_target_candidate", generation_jobs.c.project_id, generation_jobs.c.run_version_id,
      func.coalesce(generation_jobs.c.shot_id, generation_jobs.c.asset_id), generation_jobs.c.purpose,
      generation_jobs.c.candidate_no, unique=True)
job_events = project_table("job_events", *ref("generation_jobs", "job_id"),
    Column("event_type", Text, nullable=False), Column("evidence", JSONB, nullable=False), stamp())
job_input_media = project_table("job_input_media", *ref("generation_jobs", "job_id"),
    *ref("media_items", "media_id"), *ref("binding_decisions", "binding_decision_id", nullable=True),
    Column("blob_id", UUID(as_uuid=False), nullable=False), Column("blob_sha256", String(64), nullable=False),
    Column("role", Text, nullable=False), Column("ordinal", Integer, nullable=False),
    ForeignKeyConstraint(["project_id", "media_id", "blob_id"], ["media_items.project_id", "media_items.id", "media_items.blob_id"]),
    ForeignKeyConstraint(["blob_id", "blob_sha256"], ["media_blobs.id", "media_blobs.sha256"]),
    UniqueConstraint("project_id", "job_id", "role", "ordinal"))
job_input_versions = project_table("job_input_versions", *ref("generation_jobs", "job_id"),
    *ref("artifact_versions", "artifact_id"), Column("sha256", String(64), nullable=False),
    Column("role", Text, nullable=False),
    ForeignKeyConstraint(["project_id", "artifact_id", "sha256"],
                         ["artifact_versions.project_id", "artifact_versions.id", "artifact_versions.sha256"]),
    UniqueConstraint("project_id", "job_id", "artifact_id", "role"))
job_outputs = project_table("job_outputs", *ref("generation_jobs", "job_id"), *ref("media_items", "media_id"),
    Column("asset_type", Text, nullable=False), Column("original_uri", Text),
    UniqueConstraint("project_id", "job_id", "media_id"))

budget_limit_versions = Table("budget_limit_versions", metadata,
    Column("project_id", UUID(as_uuid=False), ForeignKey("projects.id"), nullable=False),
    Column("revision", BigInteger, nullable=False), Column("unit", Text, nullable=False),
    Column("amount", BigInteger, nullable=False), Column("actor", Text, nullable=False), stamp(),
    Column("reason", Text, nullable=False),
    PrimaryKeyConstraint("project_id", "revision", "unit"),
    CheckConstraint("amount >= 0", name="nonnegative_amount"),
    CheckConstraint("unit IN ('remote_jobs','images','video_seconds','audio_jobs','speech_chars','vision_jobs')", name="native_unit"))
job_budget_reservations = project_table("job_budget_reservations", *ref("generation_jobs", "job_id"),
    Column("unit", Text, nullable=False), Column("bound", BigInteger, nullable=False),
    Column("actual", BigInteger), Column("status", Text, nullable=False),
    Column("limit_revision", BigInteger, nullable=False), stamp(),
    ForeignKeyConstraint(["project_id", "limit_revision", "unit"],
                         ["budget_limit_versions.project_id", "budget_limit_versions.revision", "budget_limit_versions.unit"]),
    UniqueConstraint("project_id", "job_id", "unit"),
    CheckConstraint("bound >= 0 AND (actual IS NULL OR actual >= 0)", name="nonnegative_units"),
    CheckConstraint("status IN ('reserved','settled','released')", name="status"))

voice_spec_versions = project_table("voice_spec_versions", *ref("asset_identities", "voice_id"),
    *ref("artifact_versions", "artifact_id"), *ref("media_items", "reference_media_id", nullable=True),
    Column("diction", JSONB, nullable=False), Column("post_chain", JSONB, nullable=False))
character_voice_bindings = project_table("character_voice_bindings", *ref("asset_identities", "character_id"),
    *ref("voice_spec_versions", "voice_spec_id"), *ref("artifact_versions", "scope_version_id"),
    UniqueConstraint("project_id", "character_id", "scope_version_id"))
timeline_versions = project_table("timeline_versions", *ref("artifact_versions", "artifact_id"),
    *ref("episodes", "episode_id"), Column("fps_num", Integer, nullable=False),
    Column("fps_den", Integer, nullable=False), CheckConstraint("fps_num > 0 AND fps_den > 0", name="fps"))
timeline_items = project_table("timeline_items", *ref("timeline_versions", "timeline_id"),
    *ref("shots", "shot_id", nullable=True), Column("track_key", Text, nullable=False),
    Column("ordinal", Integer, nullable=False), Column("offset_frame", Integer, nullable=False),
    Column("duration_frames", Integer, nullable=False), Column("envelope", JSONB, nullable=False),
    CheckConstraint("offset_frame >= 0 AND duration_frames > 0", name="frame_range"),
    UniqueConstraint("project_id", "timeline_id", "track_key", "ordinal"))
timeline_item_media = project_table("timeline_item_media", *ref("timeline_items", "item_id"),
    *ref("media_items", "media_id"), *ref("binding_decisions", "binding_decision_id"),
    Column("blob_id", UUID(as_uuid=False), nullable=False), Column("blob_sha256", String(64), nullable=False),
    Column("role", Text, nullable=False), Column("source_in_frame", Integer, nullable=False),
    Column("source_out_frame", Integer, nullable=False),
    ForeignKeyConstraint(["project_id", "media_id", "blob_id"], ["media_items.project_id", "media_items.id", "media_items.blob_id"]),
    ForeignKeyConstraint(["blob_id", "blob_sha256"], ["media_blobs.id", "media_blobs.sha256"]),
    CheckConstraint("source_in_frame >= 0 AND source_out_frame > source_in_frame", name="trim"))
render_versions = project_table("render_versions", *ref("timeline_versions", "timeline_id"),
    *ref("artifact_versions", "artifact_id"), *ref("artifact_versions", "subtitle_version_id", nullable=True),
    *ref("artifact_versions", "style_version_id", nullable=True),
    Column("tool", Text, nullable=False), Column("tool_version", Text, nullable=False),
    Column("parameters", JSONB, nullable=False), stamp())
render_inputs = project_table("render_inputs", *ref("render_versions", "render_id"),
    *ref("media_items", "media_id"), *ref("binding_decisions", "binding_decision_id", nullable=True),
    Column("blob_id", UUID(as_uuid=False), nullable=False), Column("blob_sha256", String(64), nullable=False),
    Column("role", Text, nullable=False),
    ForeignKeyConstraint(["project_id", "media_id", "blob_id"], ["media_items.project_id", "media_items.id", "media_items.blob_id"]),
    ForeignKeyConstraint(["blob_id", "blob_sha256"], ["media_blobs.id", "media_blobs.sha256"]))
render_outputs = project_table("render_outputs", *ref("render_versions", "render_id"),
    *ref("media_items", "media_id"), Column("role", Text, nullable=False),
    UniqueConstraint("project_id", "render_id", "media_id"))

preview_jobs = project_table("preview_jobs", *ref("media_items", "media_id"),
    Column("purpose", Text, nullable=False), Column("recipe_version", Text, nullable=False),
    Column("status", Text, nullable=False), Column("attempt", Integer, nullable=False, server_default="0"),
    Column("request_sha256", String(64), nullable=False), Column("error", Text), stamp(),
    Column("claim_until", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint("status IN ('created','running','succeeded','failed')", name="status"),
    UniqueConstraint("project_id", "media_id", "purpose", "request_sha256"))

# Foreign-key traversal and pagination indexes: inverse usage must not scan JSON.
# Creative projections: every row belongs to one immutable relation document.
# Stable identity stays in asset_identities; repeated physical uses have separate IDs.
asset_use_instances = project_table("asset_use_instances", *ref("artifact_versions", "artifact_id"),
    *ref("asset_identities", "asset_id"), *ref("asset_spec_versions", "spec_version_id", nullable=True),
    *ref("state_versions", "state_id", nullable=True), *ref("scenes", "scene_id"),
    *ref("shots", "shot_id", nullable=True), Column("instance_key", Text, nullable=False),
    Column("label", Text, nullable=False), Column("state", JSONB, nullable=False),
    ForeignKeyConstraint(["project_id", "asset_id", "spec_version_id"],
        ["asset_spec_versions.project_id", "asset_spec_versions.asset_id", "asset_spec_versions.id"]),
    UniqueConstraint("project_id", "artifact_id", "instance_key"))
instance_interactions = project_table("instance_interactions", *ref("artifact_versions", "artifact_id"),
    *ref("asset_use_instances", "subject_id"), *ref("asset_use_instances", "object_id"),
    Column("relation", Text, nullable=False), Column("hand", Text),
    Column("parameters", JSONB, nullable=False),
    CheckConstraint("subject_id <> object_id", name="distinct_instances"),
    CheckConstraint("relation IN ('holds','wears','touches','supports','targets','restores','consumes')", name="relation"))
script_line_dispositions = project_table("script_line_dispositions", *ref("artifact_versions", "artifact_id"),
    *ref("script_lines", "line_id"), Column("reason", Text, nullable=False),
    Column("disposition", Text, nullable=False),
    CheckConstraint("disposition IN ('omit','defer')", name="disposition"),
    UniqueConstraint("project_id", "artifact_id", "line_id"))
execution_instances = project_table("execution_instances", *ref("artifact_versions", "artifact_id"),
    *ref("artifact_versions", "method_artifact_id", nullable=True), *ref("script_lines", "line_id", nullable=True),
    *ref("voice_spec_versions", "voice_spec_id", nullable=True),
    Column("execution_key", Text, nullable=False), Column("label", Text, nullable=False),
    Column("domain", Text, nullable=False), Column("parameters", JSONB, nullable=False),
    CheckConstraint("domain IN ('combat','dance','vfx','voice','acting','action')", name="domain"),
    UniqueConstraint("project_id", "artifact_id", "execution_key"))
execution_shots = project_table("execution_shots", *ref("execution_instances", "execution_id"),
    *ref("shots", "shot_id"), UniqueConstraint("project_id", "execution_id", "shot_id"))
execution_participants = project_table("execution_participants", *ref("execution_instances", "execution_id"),
    *ref("asset_use_instances", "instance_id"), Column("role", Text, nullable=False),
    UniqueConstraint("project_id", "execution_id", "instance_id", "role"))
execution_materials = project_table("execution_materials", *ref("execution_instances", "execution_id"),
    *ref("media_items", "media_id"), Column("role", Text, nullable=False),
    UniqueConstraint("project_id", "execution_id", "media_id", "role"))
execution_slots = project_table("execution_slots", *ref("execution_instances", "execution_id"),
    *ref("binding_slots", "slot_id"), Column("role", Text, nullable=False),
    UniqueConstraint("project_id", "execution_id", "slot_id", "role"))
sound_cues = project_table("sound_cues", *ref("artifact_versions", "artifact_id"),
    *ref("creative_objects", "scope_object_id"), *ref("script_lines", "line_id", nullable=True),
    *ref("voice_spec_versions", "voice_spec_id", nullable=True),
    *ref("execution_instances", "execution_id", nullable=True),
    *ref("artifact_versions", "subtitle_version_id", nullable=True), *ref("artifact_versions", "lipsync_version_id", nullable=True),
    Column("cue_key", Text, nullable=False), Column("label", Text, nullable=False),
    Column("cue_kind", Text, nullable=False), Column("parameters", JSONB, nullable=False),
    CheckConstraint("cue_kind IN ('dialogue','narration','ambience','foley','sfx','music','silence')", name="cue_kind"),
    UniqueConstraint("project_id", "artifact_id", "cue_key"))
cue_shots = project_table("cue_shots", *ref("sound_cues", "cue_id"), *ref("shots", "shot_id"),
    Column("start_ms", Integer), Column("end_ms", Integer),
    CheckConstraint("(start_ms IS NULL AND end_ms IS NULL) OR (start_ms IS NOT NULL AND end_ms IS NOT NULL AND start_ms >= 0 AND end_ms > start_ms)", name="range"),
    UniqueConstraint("project_id", "cue_id", "shot_id"))
cue_slots = project_table("cue_slots", *ref("sound_cues", "cue_id"), *ref("binding_slots", "slot_id"),
    UniqueConstraint("project_id", "cue_id", "slot_id"))
cue_timeline_items = project_table("cue_timeline_items", *ref("sound_cues", "cue_id"),
    *ref("timeline_items", "item_id"), UniqueConstraint("project_id", "cue_id", "item_id"))

quality_observations = project_table("quality_observations", *ref("artifact_versions", "artifact_id"),
    *ref("generation_jobs", "job_id"), *ref("media_items", "media_id", nullable=True),
    *ref("artifact_versions", "method_artifact_id", nullable=True), *ref("artifact_versions", "criteria_artifact_id"),
    Column("result", Text, nullable=False), Column("defect_code", Text), Column("observation", Text, nullable=False),
    Column("position", JSONB, nullable=False), Column("effort_seconds", Integer), Column("wait_seconds", Integer),
    Column("cost_amount", Numeric(20,6)), Column("cost_unit", Text), Column("cost_basis", Text, nullable=False),
    CheckConstraint("result IN ('usable','failed','unknown')", name="result"),
    CheckConstraint("cost_basis IN ('actual','estimate','unknown')", name="cost_basis"),
    CheckConstraint("(effort_seconds IS NULL OR effort_seconds >= 0) AND (wait_seconds IS NULL OR wait_seconds >= 0) AND (cost_amount IS NULL OR cost_amount >= 0)", name="nonnegative"))
method_evaluations = project_table("method_evaluations", *ref("artifact_versions", "artifact_id"),
    *ref("artifact_versions", "method_artifact_id"), *ref("artifact_versions", "trial_run_id"),
    *ref("media_items", "baseline_media_id"), *ref("media_items", "output_media_id"),
    *ref("artifact_versions", "criteria_artifact_id"), Column("result", Text, nullable=False),
    Column("environment_sha256", String(64), nullable=False),
    CheckConstraint("result IN ('pass','fail','unknown')", name="result"))

# 剧本工作副本是资源图中唯一允许 UPDATE 的表：自动保存就地更新，提交确认才冻结不可变 artifact 版本。
# draft_revision 是该表自己的乐观并发序号，不占用 projects.revision（正式版本不受自动保存影响）。
script_drafts = project_table("script_drafts",
    Column("scope_key", Text, nullable=False, server_default=""),
    Column("content", JSONB, nullable=False),
    uid("base_artifact_id", nullable=True),
    uid("submitted_artifact_id", nullable=True),
    Column("draft_revision", BigInteger, nullable=False, server_default="1"),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_by", Text, nullable=False), stamp(),
    ForeignKeyConstraint(["project_id", "base_artifact_id"], ["artifact_versions.project_id", "artifact_versions.id"]),
    ForeignKeyConstraint(["project_id", "submitted_artifact_id"], ["artifact_versions.project_id", "artifact_versions.id"]),
    CheckConstraint("draft_revision >= 1", name="draft_revision"),
    UniqueConstraint("project_id", "scope_key"))
script_notes = project_table("script_notes",
    Column("scope_key", Text),  # 0007：批注绑定范围；NULL 为历史未归属批注，不猜测迁移
    Column("base_draft_revision", BigInteger), Column("base_content_sha256", String(64)),
    uid("base_artifact_id", nullable=True),
    Column("scene_id", Text, nullable=False), Column("line_id", Text),
    Column("body", Text, nullable=False), Column("author", Text, nullable=False), stamp(),
    ForeignKeyConstraint(["project_id", "base_artifact_id"], ["artifact_versions.project_id", "artifact_versions.id"],
                         name="fk_script_notes_base_artifact", ondelete="RESTRICT"),
    CheckConstraint("(base_draft_revision IS NULL AND base_content_sha256 IS NULL AND base_artifact_id IS NULL) OR "
                    "(base_draft_revision IS NOT NULL AND base_draft_revision >= 1 AND base_content_sha256 IS NOT NULL AND "
                    "base_content_sha256 ~ '^[0-9a-f]{64}$')", name="baseline"))
# 0007：可逐处接受／拒绝／撤销的修改建议；接受要求 base_draft_revision 仍等于当前工作副本修订。
script_suggestions = project_table("script_suggestions",
    Column("scope_key", Text, nullable=False, server_default=""),
    Column("base_draft_revision", BigInteger, nullable=False),
    Column("scene_id", Text, nullable=False), Column("line_id", Text),
    Column("kind", Text, nullable=False), Column("field", Text, nullable=False, server_default="text"),
    Column("before_value", Text), Column("after_value", Text, nullable=False),
    Column("reason", Text, nullable=False), Column("origin", Text, nullable=False, server_default="manual"),
    Column("author", Text, nullable=False), stamp(),
    CheckConstraint("kind IN ('action','dialogue','silence')", name="kind"),
    CheckConstraint("field IN ('text','speaker')", name="field"))
script_suggestion_decisions = project_table("script_suggestion_decisions",
    *ref("script_suggestions", "suggestion_id"),
    Column("outcome", Text, nullable=False), Column("actor", Text, nullable=False),
    Column("reason", Text, nullable=False), Column("applied_revision", BigInteger), stamp(),
    CheckConstraint("outcome IN ('accept','reject','undo_accept')", name="outcome"))
script_note_decisions = project_table("script_note_decisions", *ref("script_notes", "note_id"),
    Column("outcome", Text, nullable=False), Column("actor", Text, nullable=False),
    Column("reason", Text, nullable=False), stamp(),
    CheckConstraint("outcome IN ('resolve','dismiss','reopen')", name="outcome"))

CREATIVE_TABLES = ("quality_observations", "method_evaluations", "asset_use_instances", "instance_interactions", "script_line_dispositions",
    "execution_instances", "execution_shots", "execution_participants", "execution_materials", "execution_slots",
    "sound_cues", "cue_shots", "cue_slots", "cue_timeline_items")
for _name in CREATIVE_TABLES:
    _tab = metadata.tables[_name]
    for _col in _tab.c:
        if _col.name.endswith("_id") and _col.name != "project_id":
            Index("ix_%s_project_%s" % (_name, _col.name), _tab.c.project_id, _col)

for table_name, fields in {
    "project_revisions": ("action",),
    "job_budget_reservations": ("status",),
    "artifact_object_scopes": ("object_id",), "artifact_dependencies": ("dependency_id",),
    "script_lines": ("scene_id", "speaker_id"), "shot_line_coverage": ("shot_id", "line_id"),
    "asset_spec_versions": ("asset_id",), "state_versions": ("scene_id", "shot_id"),
    "state_entity_refs": ("asset_id",), "media_items": ("blob_id", "modality"),
    "media_sources": ("media_id", "source_id"), "rights_decisions": ("media_id",),
    "media_lifecycle_decisions": ("media_id",), "operation_inputs": ("media_id", "operation_id"),
    "operation_outputs": ("operation_id",), "media_renditions": ("media_id",),
    "binding_slots": ("target_object_id",), "binding_candidates": ("media_id", "slot_id"),
    "media_reviews": ("candidate_id",), "binding_decisions": ("candidate_id",),
    "binding_selection_delegations": ("delegation_artifact_id", "review_id"),
    "binding_trial_adoptions": ("run_version_id", "animatic_version_id"),
    "job_input_media": ("media_id",), "job_input_versions": ("artifact_id",),
    "job_outputs": ("media_id",), "generation_jobs": ("status", "shot_id", "asset_id"),
    "artifact_asset_spec_refs": ("asset_id", "spec_version_id"),
    "timeline_item_media": ("media_id",), "render_inputs": ("media_id",),
    "render_outputs": ("media_id",), "preview_jobs": ("status",),
    "script_notes": ("scene_id", "base_artifact_id"), "script_note_decisions": ("note_id",),
    "script_suggestions": ("scope_key",), "script_suggestion_decisions": ("suggestion_id",),
}.items():
    table = metadata.tables[table_name]
    for field in fields:
        Index("ix_%s_project_%s" % (table_name, field), table.c.project_id, table.c[field])

# Role dispatches and memories: immutable evidence, typed project-scoped references.
role_dispatches = project_table("role_dispatches",
    Column("context_id", Text, nullable=False), Column("role_id", Text, nullable=False),
    Column("role_sha256", String(64), nullable=False), Column("context_sha256", String(64), nullable=False),
    Column("host", Text, nullable=False), Column("instance_id", Text, nullable=False),
    Column("actor", Text, nullable=False), Column("review_mode", Text, nullable=False),
    *ref("creative_objects", "scope_object_id", nullable=True),
    Column("packet", JSONB, nullable=False), Column("expires_at", DateTime(timezone=True), nullable=False), stamp(),
    UniqueConstraint("project_id", "context_id"),
    CheckConstraint("review_mode IN ('work','design','fresh','followup')", name="review_mode"))
dispatch_inputs = Table("dispatch_inputs", metadata,
    uid("project_id", nullable=False), *ref("role_dispatches", "dispatch_id"),
    *ref("artifact_versions", "artifact_id"),
    PrimaryKeyConstraint("project_id", "dispatch_id", "artifact_id"))
dispatch_consumptions = project_table("dispatch_consumptions",
    *ref("role_dispatches", "dispatch_id"), Column("instance_id", Text, nullable=False),
    Column("actor", Text, nullable=False), Column("context_sha256", String(64), nullable=False), stamp(),
    UniqueConstraint("project_id", "dispatch_id"))
dispatch_returns = project_table("dispatch_returns",
    *ref("role_dispatches", "dispatch_id"), Column("return_key", Text, nullable=False),
    Column("result_sha256", String(64), nullable=False), Column("result", JSONB, nullable=False),
    Column("summary", Text), Column("expires_at", DateTime(timezone=True)),
    Column("closed", Boolean, nullable=False), stamp(),
    UniqueConstraint("project_id", "dispatch_id", "return_key"),
    CheckConstraint("summary IS NULL OR (length(summary) <= 2200 AND expires_at IS NOT NULL)", name="summary_expiry"))
role_memories = project_table("role_memories",
    Column("owner_role", Text, nullable=False), Column("scope", Text, nullable=False),
    *ref("creative_objects", "scope_object_id", nullable=True),
    Column("kind", Text, nullable=False), *ref("role_dispatches", "producer_dispatch_id", nullable=True),
    Column("proposal_key", Text, nullable=False), Column("request_sha256", String(64), nullable=False), Column("origin", Text, nullable=False), stamp(),
    UniqueConstraint("project_id", "producer_dispatch_id", "proposal_key"),
    CheckConstraint("scope IN ('role','project')", name="scope"),
    CheckConstraint("kind IN ('fact','lesson','check_method','judgment','recommendation','preference','decision')", name="kind"),
    CheckConstraint("origin IN ('agent_proposed','unverified_proposal')", name="origin"))
role_memory_versions = project_table("role_memory_versions",
    *ref("role_memories", "memory_id"), Column("version", Integer, nullable=False),
    *ref("role_dispatches", "producer_dispatch_id", nullable=True),
    Column("content", Text, nullable=False), Column("content_sha256", String(64), nullable=False),
    Column("sensitivity", Text, nullable=False), Column("confidence", Text, nullable=False),
    Column("association_complete", Boolean, nullable=False), Column("tags", JSONB, nullable=False), stamp(),
    UniqueConstraint("project_id", "memory_id", "version"),
    UniqueConstraint("project_id", "id", "content_sha256"),
    CheckConstraint("version > 0 AND length(content) BETWEEN 1 AND 6000", name="content_version"),
    CheckConstraint("sensitivity IN ('public','project','restricted')", name="sensitivity"))
role_memory_artifacts = Table("role_memory_artifacts", metadata,
    uid("project_id", nullable=False), *ref("role_memory_versions", "memory_version_id"),
    uid("artifact_id", nullable=False), Column("source_sha256", String(64), nullable=False),
    ForeignKeyConstraint(["project_id", "artifact_id", "source_sha256"], ["artifact_versions.project_id", "artifact_versions.id", "artifact_versions.sha256"]),
    PrimaryKeyConstraint("project_id", "memory_version_id", "artifact_id"))
role_memory_sources = Table("role_memory_sources", metadata,
    uid("project_id", nullable=False), *ref("role_memory_versions", "memory_version_id"),
    uid("source_id", nullable=False), Column("source_sha256", String(64), nullable=False),
    ForeignKeyConstraint(["project_id", "source_id", "source_sha256"], ["source_versions.project_id", "source_versions.id", "source_versions.sha256"]),
    PrimaryKeyConstraint("project_id", "memory_version_id", "source_id"))
role_memory_targets = Table("role_memory_targets", metadata,
    uid("project_id", nullable=False), *ref("role_memory_versions", "memory_version_id"),
    *ref("creative_objects", "object_id"), PrimaryKeyConstraint("project_id", "memory_version_id", "object_id"))
role_memory_decisions = project_table("role_memory_decisions",
    uid("memory_version_id", nullable=False), Column("outcome", Text, nullable=False),
    Column("content_sha256", String(64), nullable=False), Column("actor", Text, nullable=False),
    Column("confirmation_id", Text, nullable=False), Column("reason", Text, nullable=False),
    Column("based_on_revision", BigInteger, nullable=False), Column("decision_sequence", BigInteger, nullable=False), stamp(),
    UniqueConstraint("project_id", "confirmation_id"),
    UniqueConstraint("project_id", "id", "memory_version_id"),
    ForeignKeyConstraint(["project_id", "memory_version_id", "content_sha256"], ["role_memory_versions.project_id", "role_memory_versions.id", "role_memory_versions.content_sha256"]),
    CheckConstraint("outcome IN ('approved','rejected','retired')", name="outcome"))
dispatch_memory_refs = Table("dispatch_memory_refs", metadata,
    uid("project_id", nullable=False), *ref("role_dispatches", "dispatch_id"),
    *ref("role_memory_versions", "memory_version_id"), uid("decision_id", nullable=False),
    ForeignKeyConstraint(["project_id", "decision_id", "memory_version_id"], ["role_memory_decisions.project_id", "role_memory_decisions.id", "role_memory_decisions.memory_version_id"]),
    PrimaryKeyConstraint("project_id", "dispatch_id", "memory_version_id"))
dispatch_sources = Table("dispatch_sources", metadata,
    uid("project_id", nullable=False), *ref("role_dispatches", "dispatch_id"),
    *ref("source_versions", "source_id"), PrimaryKeyConstraint("project_id", "dispatch_id", "source_id"))
dispatch_media_refs = Table("dispatch_media_refs", metadata,
    uid("project_id", nullable=False), *ref("role_dispatches", "dispatch_id"),
    *ref("media_items", "media_id"), *ref("binding_decisions", "binding_decision_id"),
    Column("role", Text, nullable=False), PrimaryKeyConstraint("project_id", "dispatch_id", "media_id", "role"))
dispatch_result_artifacts = Table("dispatch_result_artifacts", metadata,
    uid("project_id", nullable=False), *ref("dispatch_returns", "return_id"),
    *ref("artifact_versions", "artifact_id"), PrimaryKeyConstraint("project_id", "return_id", "artifact_id"))
script_suggestion_runs = project_table("script_suggestion_runs",
    *ref("script_drafts", "draft_id"), Column("scope_key", Text, nullable=False),
    Column("base_draft_revision", BigInteger, nullable=False), Column("base_content_sha256", String(64), nullable=False),
    Column("input_document", JSONB, nullable=False), Column("goal", Text, nullable=False),
    Column("backend", Text, nullable=False), Column("status", Text, nullable=False),
    Column("result", JSONB), Column("error_code", Text), stamp(), Column("finished_at", DateTime(timezone=True)),
    CheckConstraint("base_draft_revision > 0", name="positive_revision"),
    CheckConstraint("status IN ('running','completed','stale','failed','submission_unknown')", name="status"))
Index("ix_script_suggestion_runs_project_draft_id", script_suggestion_runs.c.project_id, script_suggestion_runs.c.draft_id)
MEMORY_TABLES = ("role_dispatches", "dispatch_inputs", "dispatch_sources", "dispatch_media_refs", "dispatch_result_artifacts", "dispatch_consumptions", "dispatch_returns", "role_memories",
    "role_memory_versions", "role_memory_artifacts", "role_memory_sources", "role_memory_targets", "role_memory_decisions", "dispatch_memory_refs")
for _name, _fields in {
    "role_dispatches": ("role_id", "scope_object_id"), "dispatch_consumptions": ("dispatch_id",),
    "dispatch_returns": ("dispatch_id",), "role_memories": ("owner_role", "scope_object_id"),
    "role_memory_versions": ("memory_id",), "role_memory_artifacts": ("artifact_id",),
    "role_memory_sources": ("source_id",), "role_memory_targets": ("object_id",),
    "role_memory_decisions": ("memory_version_id",), "dispatch_inputs": ("artifact_id",),
    "dispatch_memory_refs": ("memory_version_id",),
}.items():
    for _field in _fields:
        Index("ix_%s_project_%s" % (_name, _field), metadata.tables[_name].c.project_id, metadata.tables[_name].c[_field])

APPEND_ONLY_TABLES = CREATIVE_TABLES + MEMORY_TABLES + (
    "script_notes", "script_note_decisions", "script_suggestions", "script_suggestion_decisions",
    "provider_configurations",
    "budget_limit_versions",
    "project_revisions", "command_receipts", "artifact_versions", "artifact_dependencies",
    "artifact_object_scopes", "artifact_decisions", "asset_spec_versions", "artifact_asset_spec_refs", "script_lines",
    "shot_line_coverage", "state_versions", "state_entity_refs", "continuity_edges",
    "media_blobs", "media_items", "source_versions", "media_sources", "rights_decisions",
    "media_lifecycle_decisions", "media_checks", "library_reuses", "binding_candidates",
    "media_reviews", "binding_decisions", "binding_selection_delegations", "binding_trial_adoptions", "job_events", "job_input_media", "job_input_versions",
    "job_outputs", "voice_spec_versions", "character_voice_bindings", "timeline_versions",
    "timeline_items", "timeline_item_media", "render_versions", "render_inputs", "render_outputs",
)

for _table in metadata.tables.values():
    for _column in _table.c:
        if _column.name.endswith("sha256"):
            _table.append_constraint(CheckConstraint(
                "%s IS NULL OR %s ~ '^[0-9a-f]{64}$'" % (_column.name, _column.name),
                name=_column.name + "_format"))
