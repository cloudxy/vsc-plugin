"""Bounded desk projection in one project-scoped, read-only snapshot."""
import json
from sqlalchemy import text
from .values import checked_id, clean
from .workbench import CTE, QUERIES, S_OBJECTS
from vsc.assets.assisted_desk import present
from vsc.assets.resource_service import Conflict


def query_assisted_desk(store, project_id, *, bucket="review", object_id=None, limit=24, offset=0, revision=None):
    p = checked_id(project_id)
    params = dict(p=p, scope=checked_id(object_id) if object_id else None, bucket=bucket, limit=limit, offset=offset)
    from .media_recycle import recycled_ids
    recycled = recycled_ids(p).compile()
    params.update(recycled.params)
    # Original typed queries keep scope semantics (including ancestor specifications).
    envelope = CTE + ", recycled AS (" + str(recycled) + """),
      versions AS (""" + QUERIES["versions"] + """),
      candidates AS (""" + QUERIES["candidates"] + """),
      jobs AS (""" + QUERIES["jobs"] + """),
      materials AS (""" + QUERIES["materials"] + """),
      readable_versions AS (
        SELECT * FROM versions WHERE kind NOT LIKE 'vsc.legacy-%'
          AND kind <> 'vsc.migration-manifest/v1'
          AND replace(replace(kind,'vsc.',''),'_','-') NOT IN
            ('timeline','render-plan','coverage-plan','generation-record',
             'production-run','selected-takes','delivery-manifest','animatic')
      ),
      desk AS (
        SELECT CASE WHEN status='draft' THEN 'review' ELSE 'results' END bucket,
          'artifact:'||id id,'artifact' kind,title,status,
          jsonb_build_object('kind','artifact','id',id,'version_id',id,'sha256',sha256) ref,
          CAST(:scope AS uuid) object_id, version, kind content_kind
        FROM readable_versions v WHERE (status='approved' AND EXISTS(
          SELECT 1 FROM current_artifact_versions current WHERE current.project_id=:p AND current.artifact_id=v.id))
          OR (status='draft' AND NOT EXISTS(
          SELECT 1 FROM artifact_versions newer JOIN artifact_versions own ON own.project_id=newer.project_id
          AND own.artifact_key=newer.artifact_key WHERE own.project_id=:p AND own.id=v.id
          AND newer.version>own.version))
        UNION ALL
        SELECT 'review','candidate:'||c.id,'candidate',c.title,c.status,
          jsonb_build_object('kind','media','id',c.media_id,'candidate_id',c.id,'version_id',c.artifact_id),
          c.object_id,NULL,c.kind FROM candidates c WHERE c.status='candidate'
          AND c.media_id NOT IN (SELECT media_id FROM recycled)
        UNION ALL
        SELECT 'progress','job:'||id,'job',title,status,
          jsonb_build_object('kind','job','id',id),coalesce(shot_id,asset_id),NULL,kind
        FROM jobs WHERE status<>'succeeded'
        UNION ALL
        SELECT CASE WHEN j.status='succeeded' THEN 'review' ELSE 'progress' END,
          'edit-preview:'||j.id,'preview','字幕修改结果',j.status,
          jsonb_build_object('kind','artifact','id',j.source_artifact_id,
            'version_id',j.source_artifact_id,'artifact_note_id',j.note_id),
          CAST(:scope AS uuid),NULL,'subtitle'
        FROM edit_preview_jobs j WHERE j.project_id=:p
          AND j.source_artifact_id IN (SELECT id FROM scoped_versions)
        UNION ALL
        SELECT 'results','media:'||id,'media',title,status,
          jsonb_build_object('kind','media','id',id),CAST(:scope AS uuid),NULL,kind
        FROM materials WHERE id NOT IN (SELECT media_id FROM recycled)
          AND kind IN ('image','audio','video')
          AND (id NOT IN (SELECT media_id FROM render_caption_inputs WHERE project_id=:p)
            OR id IN (SELECT media_id FROM render_outputs WHERE project_id=:p AND role='delivery'))
      ) """
    with store.engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn, conn.begin():
        conn.execute(text("SET TRANSACTION READ ONLY"))
        project = store._project(conn, p)
        if revision is not None and revision != project["revision"]:
            raise Conflict("工作台内容已更新，请重新读取", "desk_revision_changed")
        scope = store._one(conn, S_OBJECTS(), p, object_id) if object_id else None
        counts = {name: 0 for name in ("review", "progress", "results")}
        for row in conn.execute(text(envelope + "SELECT bucket,count(*) total FROM desk GROUP BY bucket"), params).mappings():
            counts[row["bucket"]] = row["total"]
        rows = conn.execute(text(envelope + """SELECT * FROM desk WHERE bucket=:bucket
          ORDER BY CASE status WHEN 'failed' THEN 0 WHEN 'submission_unknown' THEN 1 ELSE 2 END,
          CASE WHEN kind='media' AND ref->>'id' IN (
            SELECT media_id::text FROM render_outputs WHERE project_id=:p AND role='delivery')
            THEN 0 WHEN kind='artifact' THEN 1 ELSE 2 END,
          title,id LIMIT :limit OFFSET :offset"""), params).mappings()
        items = [present(clean(dict(row))) for row in rows]
        # Only inspect bounded documents on this page, never fetch every project's
        # full text merely to label its navigation. Larger/opaque formats use type/key.
        artifact_ids = [item["ref"]["id"] for item in items if item["kind"] == "artifact"]
        if artifact_ids:
            from sqlalchemy import select, case, func
            from .schema import artifact_versions
            titles = {}
            for artifact_id, document in conn.execute(select(artifact_versions.c.id,
                case((func.octet_length(artifact_versions.c.document) <= 262144,
                      artifact_versions.c.document), else_=None)).where(
                    artifact_versions.c.project_id == p, artifact_versions.c.id.in_(artifact_ids))):
                try:
                    content = json.loads(document) if document else None
                except (ValueError, UnicodeError):
                    continue
                if isinstance(content, dict):
                    title = content.get("title") or content.get("标题")
                    if isinstance(title, str) and title.strip():
                        titles[str(artifact_id)] = title.strip()[:240]
            for item in items:
                item["title"] = titles.get(item["ref"]["id"], item["title"])
        total = counts[bucket]
        ancestors = [dict(r) for r in conn.execute(text(CTE + """SELECT o.id,o.kind,o.title,o.display_code
          FROM creative_objects o WHERE o.project_id=:p AND o.id IN (SELECT parent_id FROM ancestors)
          ORDER BY CASE o.kind WHEN 'work' THEN 0 WHEN 'episode' THEN 1 WHEN 'scene' THEN 2 ELSE 3 END"""), params).mappings()]
        return clean(dict(project_id=p, revision=project["revision"], bucket=bucket, read_only=False,
            items=items, counts=counts, total=total, offset=offset, limit=limit,
            next_offset=offset+len(items) if offset+len(items)<total else None,
            scope=scope, ancestors=ancestors, snapshot="repeatable_read"))
