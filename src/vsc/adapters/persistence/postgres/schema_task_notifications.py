"""Read-only task discoveries and identity-scoped reading receipts."""
from sqlalchemy import Column,Text,BigInteger,Identity,ForeignKey,UniqueConstraint,CheckConstraint,Index,Computed

ORIGINS={
    'generation':('generation_job_id','generation_jobs'),
    'editing':('edit_render_job_id','edit_render_jobs'),
    'spatial':('spatial_export_id','spatial_exports'),
    'spatial_plan':('spatial_plan_task_id','spatial_plan_tasks'),
    'lyrics':('lyrics_request_id','artifact_versions'),
    'import':('media_import_item_id','media_import_items'),
    'text':('text_attempt_id','text_tool_attempts'),
    'text_batch':('text_batch_id','text_tool_batches'),
    'canvas':('canvas_turn_id','canvas_agent_turns'),
    'intelligent':('intelligent_task_id','intelligent_tasks'),
}

def declare_task_notifications(project_table,ref,uid,stamp):
    columns=[]
    for field,table in ORIGINS.values():columns.extend(ref(table,field,nullable=True))
    only_one='num_nonnulls('+','.join(field for field,_ in ORIGINS.values())+')=1'
    matches=' OR '.join("(kind='%s' AND %s IS NOT NULL)"%(kind,field) for kind,(field,_) in ORIGINS.items())
    from sqlalchemy.dialects.postgresql import UUID
    events=project_table('task_notification_events',Column('sequence',BigInteger,Identity(),nullable=False),
        Column('kind',Text,nullable=False),*columns,
        Column('origin_id',UUID(as_uuid=False),Computed('coalesce('+','.join(field for field,_ in ORIGINS.values())+')',persisted=True)),
        Column('source_token',Text,nullable=False),Column('observed_status',Text,nullable=False),stamp(),
        UniqueConstraint('project_id','sequence'),UniqueConstraint('project_id','kind','origin_id','source_token'),
        CheckConstraint(only_one+' AND ('+matches+')',name='typed_origin'),
        CheckConstraint("source_token ~ '^[0-9a-f]{64}$' AND length(observed_status) BETWEEN 1 AND 40",name='observation'))
    reads=project_table('task_notification_reads',Column('identity_id',UUID(as_uuid=False),ForeignKey('access_identities.id'),nullable=False),
        *ref('task_notification_events','event_id'),stamp(),UniqueConstraint('project_id','identity_id','event_id'))
    for field,_ in ORIGINS.values():Index('ix_task_notification_events_'+field,events.c.project_id,events.c[field])
    Index('ix_task_notification_reads_event',reads.c.project_id,reads.c.event_id)
    Index('ix_task_notification_reads_identity',reads.c.identity_id)
    return {table.name:table for table in (events,reads)}

TASK_NOTIFICATION_GUARD="""
CREATE FUNCTION vsc_task_notification_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actual_status text;
BEGIN
 IF NEW.kind='lyrics' AND NOT EXISTS(SELECT 1 FROM artifact_versions WHERE project_id=NEW.project_id AND id=NEW.lyrics_request_id AND artifact_type='lyrics-request') THEN
  RAISE EXCEPTION 'notification requires an original lyrics request' USING ERRCODE='23514';
 END IF;
 IF NEW.kind='generation' THEN SELECT status INTO actual_status FROM generation_jobs WHERE project_id=NEW.project_id AND id=NEW.generation_job_id;
 ELSIF NEW.kind='editing' THEN SELECT status INTO actual_status FROM edit_render_jobs WHERE project_id=NEW.project_id AND id=NEW.edit_render_job_id;
 ELSIF NEW.kind='spatial' THEN SELECT status INTO actual_status FROM spatial_exports WHERE project_id=NEW.project_id AND id=NEW.spatial_export_id;
 ELSIF NEW.kind='spatial_plan' THEN SELECT status INTO actual_status FROM spatial_plan_tasks WHERE project_id=NEW.project_id AND id=NEW.spatial_plan_task_id;
 ELSIF NEW.kind='import' THEN SELECT status INTO actual_status FROM media_import_items WHERE project_id=NEW.project_id AND id=NEW.media_import_item_id;
 ELSIF NEW.kind='text' THEN SELECT status INTO actual_status FROM text_tool_attempts WHERE project_id=NEW.project_id AND id=NEW.text_attempt_id;
 ELSIF NEW.kind='text_batch' THEN SELECT status INTO actual_status FROM text_tool_batches WHERE project_id=NEW.project_id AND id=NEW.text_batch_id;
 ELSIF NEW.kind='canvas' THEN SELECT status INTO actual_status FROM canvas_agent_turns WHERE project_id=NEW.project_id AND id=NEW.canvas_turn_id;
 ELSIF NEW.kind='intelligent' THEN SELECT status INTO actual_status FROM intelligent_tasks WHERE project_id=NEW.project_id AND id=NEW.intelligent_task_id;
 ELSIF NEW.kind='lyrics' THEN SELECT coalesce(convert_from(r.document,'UTF8')::jsonb->>'status',CASE WHEN q.created_at + interval '180 seconds'<now() THEN 'submission_unknown' ELSE 'running' END) INTO actual_status FROM artifact_versions q LEFT JOIN artifact_versions r ON r.project_id=q.project_id AND r.artifact_key='lyrics-result:'||q.id::text WHERE q.project_id=NEW.project_id AND q.id=NEW.lyrics_request_id;
 END IF;
 IF actual_status IS DISTINCT FROM NEW.observed_status THEN RAISE EXCEPTION 'notification must match an original task observation' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER task_notification_origin BEFORE INSERT ON task_notification_events FOR EACH ROW EXECUTE FUNCTION vsc_task_notification_guard();
CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON task_notification_events FOR EACH ROW EXECUTE FUNCTION vsc_reject_mutation();
CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON task_notification_reads FOR EACH ROW EXECUTE FUNCTION vsc_reject_mutation();
"""
