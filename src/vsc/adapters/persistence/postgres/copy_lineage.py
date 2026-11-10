"""Live rights along typed asset/template copies and original media derivations."""
from datetime import datetime,timezone
from sqlalchemy import text,select
from . import schema as S

_COPY_EDGES = """
 SELECT c.project_id AS target_project, t.media_id AS target_media,
        c.source_project_id AS source_project, s.media_id AS source_media
 FROM asset_card_copy_sources c
 JOIN asset_card_form_versions t ON t.project_id=c.project_id AND t.id=c.target_form_version_id
 JOIN asset_card_form_versions s ON s.project_id=c.source_project_id AND s.id=c.source_form_version_id
 WHERE t.media_id IS NOT NULL AND s.media_id IS NOT NULL
 UNION
 SELECT c.project_id, tv.reference_media_id, c.source_project_id, sv.reference_media_id
 FROM asset_card_copy_sources c
 JOIN asset_card_form_versions t ON t.project_id=c.project_id AND t.id=c.target_form_version_id
 JOIN asset_card_form_versions s ON s.project_id=c.source_project_id AND s.id=c.source_form_version_id
 JOIN voice_spec_versions tv ON tv.project_id=t.project_id AND tv.id=t.voice_spec_id
 JOIN voice_spec_versions sv ON sv.project_id=s.project_id AND sv.id=s.voice_spec_id
 WHERE tv.reference_media_id IS NOT NULL AND sv.reference_media_id IS NOT NULL
 UNION
 SELECT project_id,target_media_id,source_project_id,source_media_id FROM template_copy_media
 UNION
 SELECT project_id,target_media_id,source_project_id,source_media_id FROM canvas_direct_copy_media
"""
_EDGES = """WITH RECURSIVE copy_edges AS ("""+_COPY_EDGES+"""), edges AS (
 SELECT target_project,target_media,source_project,source_media,true AS copied,false AS canvas FROM copy_edges
 UNION
 SELECT project_id,target_media_id,source_project_id,source_media_id,true,true FROM canvas_project_media_links
 UNION
 SELECT project_id,target_media_id,source_project_id,source_media_id,true,true FROM classic_frame_media_links
 UNION
 SELECT o.project_id,o.media_id,i.project_id,i.media_id,false,false
 FROM operation_outputs o JOIN operation_inputs i ON i.project_id=o.project_id AND i.operation_id=o.operation_id
 UNION
 SELECT o.project_id,o.media_id,i.project_id,i.media_id,false,false
 FROM job_outputs o JOIN job_input_media i ON i.project_id=o.project_id AND i.job_id=o.job_id
), ancestors(project_id,media_id,copied,crossed_canvas) AS (
 SELECT CAST(:project AS uuid),CAST(:media AS uuid),false,false
 UNION
 SELECT e.source_project,e.source_media,a.copied OR e.copied,a.crossed_canvas OR e.canvas FROM ancestors a
 JOIN edges e ON e.target_project=a.project_id AND e.target_media=a.media_id
) SELECT project_id,media_id,copied,crossed_canvas FROM ancestors
"""

# crossed_canvas marks an identical-byte cross-project reference. The edge is
# either a canvas node or a classic first/last frame. A generated or edited
# output is not implicitly the same technical inspection as its input.
_CANVAS_IDENTICAL_ANCESTOR_GAPS = """WITH RECURSIVE copy_edges AS ("""+_COPY_EDGES+"""), edges AS (
 SELECT target_project,target_media,source_project,source_media,false AS canvas FROM copy_edges
 UNION
 SELECT project_id,target_media_id,source_project_id,source_media_id,true FROM canvas_project_media_links
 UNION
 SELECT project_id,target_media_id,source_project_id,source_media_id,true FROM classic_frame_media_links
 UNION
 SELECT o.project_id,o.media_id,i.project_id,i.media_id,false
 FROM operation_outputs o JOIN operation_inputs i ON i.project_id=o.project_id AND i.operation_id=o.operation_id
 UNION
 SELECT o.project_id,o.media_id,i.project_id,i.media_id,false
 FROM job_outputs o JOIN job_input_media i ON i.project_id=o.project_id AND i.job_id=o.job_id
), same_bytes AS (
 SELECT e.* FROM edges e
 JOIN media_items child ON child.project_id=e.target_project AND child.id=e.target_media
 JOIN media_items parent ON parent.project_id=e.source_project AND parent.id=e.source_media
 WHERE child.blob_id=parent.blob_id
), ancestors(project_id,media_id,crossed_canvas) AS (
 SELECT CAST(:project AS uuid),CAST(:media AS uuid),false
 UNION
 SELECT e.source_project,e.source_media,a.crossed_canvas OR e.canvas FROM ancestors a
 JOIN same_bytes e ON e.target_project=a.project_id AND e.target_media=a.media_id
), source AS (
 SELECT DISTINCT project_id,media_id FROM ancestors
 WHERE crossed_canvas AND (project_id<>CAST(:project AS uuid) OR media_id<>CAST(:media AS uuid))
)
SELECT EXISTS(
 SELECT 1 FROM source a WHERE (SELECT l.outcome FROM media_lifecycle_decisions l
 WHERE l.project_id=a.project_id AND l.media_id=a.media_id ORDER BY l.decision_sequence DESC LIMIT 1)='deprecate'
) AS deprecated,
EXISTS(
 SELECT 1 FROM source a JOIN media_checks c ON c.project_id=a.project_id AND c.media_id=a.media_id
 WHERE c.outcome<>'pass' AND NOT EXISTS (
  SELECT 1 FROM media_checks newer WHERE newer.project_id=c.project_id AND newer.media_id=c.media_id
  AND newer.checker=c.checker AND newer.criteria_version=c.criteria_version
  AND (newer.project_revision,newer.id)>(c.project_revision,c.id)
 )
) AS failed
"""

def source_projects_for_copy(conn,project_id):
    """Collect source locks before target lock; UNION terminates historical cycles."""
    sql="""WITH RECURSIVE copy_projects AS (
      SELECT project_id,source_project_id FROM asset_card_copy_sources
      UNION SELECT project_id,source_project_id FROM template_copy_media
      UNION SELECT project_id,source_project_id FROM canvas_direct_copies
      UNION SELECT project_id,source_project_id FROM canvas_project_media_links
      UNION SELECT project_id,source_project_id FROM classic_frame_media_links
    ), projects(id) AS (
      SELECT CAST(:project AS uuid)
      UNION SELECT e.source_project_id FROM projects p JOIN copy_projects e ON e.project_id=p.id
    ) SELECT id FROM projects"""
    ids={str(x) for x in conn.execute(text(sql),{'project':project_id}).scalars()}
    from .shared_library import library_project_lock_ids
    # A copied library import retains the library's original publication locks too.
    for p in tuple(ids):ids.update(str(x) for x in library_project_lock_ids(conn,p))
    return sorted(ids)

def _library_copy_gaps(store,conn,p,mid):
    from .shared_library import _version_gaps
    versions=conn.execute(select(S.library_entry_versions).join(S.library_reuses,S.library_entry_versions.c.id==S.library_reuses.c.library_version_id).where(S.library_reuses.c.project_id==p,S.library_reuses.c.media_id==mid,S.library_reuses.c.reuse_mode.in_(['reference','derive']))).mappings()
    return [gap for version in versions for gap in _version_gaps(store,conn,version,(version['allowed_purposes'] or [''])[0])]

def copy_media_gaps(store,conn,project_id,media_id,purpose,_seen=None,_cache=None):
    """No grants from a copied rights snapshot override current source decisions.

    purpose=None is the copy-time validity check: it preserves an existing scope
    without adding a new licensed purpose. Final use always supplies its purpose.
    """
    from .shared_library import library_media_gaps
    rows=conn.execute(text(_EDGES),{'project':project_id,'media':media_id}).mappings().all();gaps=set()
    for row in rows:
        if not row['copied'] and purpose is not None:continue
        p,mid=str(row['project_id']),str(row['media_id']);rights=store._latest(conn,S.rights_decisions,p,'media_id',mid)
        if not rights or rights['outcome'] not in {'owned','licensed','unknown'}:gaps.add('copy_source_rights_restricted')
        elif rights['expires_at'] and rights['expires_at']<=datetime.now(timezone.utc):gaps.add('copy_source_rights_expired')
        elif purpose is not None:
            if rights['outcome']=='unknown':
                if row['crossed_canvas'] and store._unknown_inheritance_source(conn,p,mid,rights):
                    _, inherited=store._usable(conn,p,mid,purpose,_grid_seen=_seen,_grid_cache=_cache)
                    gaps.update('copy_source_'+gap for gap in inherited if gap!='technical_check_missing')
                else:gaps.add('copy_source_rights_unknown')
            elif purpose not in rights['scope'].get('purposes',[]) and '*' not in rights['scope'].get('purposes',[]):gaps.add('copy_source_rights_scope_mismatch')
        if purpose is not None:gaps.update(library_media_gaps(store,conn,p,mid,purpose))
        else:gaps.update(_library_copy_gaps(store,conn,p,mid))
    if any(row['copied'] for row in rows):
        state=conn.execute(text(_CANVAS_IDENTICAL_ANCESTOR_GAPS),{'project':project_id,'media':media_id}).mappings().one()
        if state['deprecated']:gaps.add('copy_source_media_deprecated')
        if state['failed']:gaps.add('copy_source_technical_check_failed')
    return sorted(gaps)

def assert_copy_source(store,conn,project_id,media_id):
    """Validate current source plus ancestors without broadening licensed scope."""
    from vsc.assets.resource_service import ResourceError
    from .shared_library import library_media_gaps
    rights=store._latest(conn,S.rights_decisions,project_id,'media_id',media_id)
    gaps=copy_media_gaps(store,conn,project_id,media_id,None)
    if rights and rights['outcome'] not in {'owned','licensed','unknown'}:gaps.append('copy_source_rights_restricted')
    if rights and rights['expires_at'] and rights['expires_at']<=datetime.now(timezone.utc):gaps.append('copy_source_rights_expired')
    if gaps:raise ResourceError('来源素材当前不可复制：'+', '.join(sorted(set(gaps))),'copy_source_rights_unavailable')
    return rights
