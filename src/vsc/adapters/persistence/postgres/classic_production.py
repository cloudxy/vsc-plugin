"""Classic mode work drafts reuse artifact versions and command receipts."""
from sqlalchemy import select
import json
from vsc.assets.resource_service import Conflict, ResourceError
from vsc.assets.classic_production import DRAFT_TYPE, draft_key
from . import schema as S
from .values import checked_id, clean


class ClassicProductionRepository:
    def next_classic_candidate(self, project_id, shot_id, purpose):
        from sqlalchemy import func
        with self.engine.connect() as conn:
            self._one(conn, S.shots, project_id, checked_id(shot_id))
            latest = conn.scalar(select(func.max(S.generation_jobs.c.candidate_no)).where(
                S.generation_jobs.c.project_id == project_id, S.generation_jobs.c.shot_id == shot_id,
                S.generation_jobs.c.purpose == purpose))
            return 0 if latest is None else latest + 1

    def _shot_episode_id(self, conn, project_id, shot_id):
        shot = self._one(conn, S.shots, project_id, checked_id(shot_id))
        seq = self._one(conn, S.sequences, project_id, shot["parent_id"])
        scene = self._one(conn, S.scenes, project_id, seq["parent_id"])
        return scene["parent_id"]

    def _episode_shot_rows(self, conn, project_id, episode_id):
        from .project_management import hidden_object_ids
        hidden = hidden_object_ids(conn, project_id)
        rows = conn.execute(
            select(
                S.shots.c.id,
                S.shots.c.ordinal,
                S.shots.c.parent_id,
                S.creative_objects.c.title,
                S.creative_objects.c.display_code,
                S.scenes.c.ordinal.label("scene_ordinal"),
                S.sequences.c.ordinal.label("sequence_ordinal"),
            )
            .join(S.creative_objects, (S.creative_objects.c.project_id == S.shots.c.project_id) & (S.creative_objects.c.id == S.shots.c.id))
            .join(S.sequences, (S.sequences.c.project_id == S.shots.c.project_id) & (S.sequences.c.id == S.shots.c.parent_id))
            .join(S.scenes, (S.scenes.c.project_id == S.sequences.c.project_id) & (S.scenes.c.id == S.sequences.c.parent_id))
            .where(S.shots.c.project_id == project_id, S.scenes.c.parent_id == episode_id)
            .order_by(S.scenes.c.ordinal, S.sequences.c.ordinal, S.shots.c.ordinal, S.shots.c.id)
        ).mappings()
        return [dict(r) for r in rows if r["id"] not in hidden]

    def _classic_episode_video_summary(self, conn, project_id, shot_id):
        from sqlalchemy import and_, func, union
        from .classic_preferences import favorite_identity
        from .media_recycle import recycled_ids
        episode_id = self._shot_episode_id(conn, project_id, shot_id)
        shot_rows = self._episode_shot_rows(conn, project_id, episode_id)
        shot_ids = [r["id"] for r in shot_rows]
        if not shot_ids:
            return {"episode_id": episode_id, "previewable_video_count": 0, "favorite_video_count": 0}
        candidates = select(S.binding_candidates.c.media_id).join(
            S.binding_slots,
            and_(S.binding_slots.c.project_id == S.binding_candidates.c.project_id, S.binding_slots.c.id == S.binding_candidates.c.slot_id),
        ).where(S.binding_candidates.c.project_id == project_id, S.binding_slots.c.target_object_id.in_(shot_ids))
        outputs = select(S.job_outputs.c.media_id).join(
            S.generation_jobs,
            and_(S.generation_jobs.c.project_id == S.job_outputs.c.project_id, S.generation_jobs.c.id == S.job_outputs.c.job_id),
        ).where(
            S.job_outputs.c.project_id == project_id,
            S.generation_jobs.c.shot_id.in_(shot_ids),
            S.generation_jobs.c.modality == "video",
            S.generation_jobs.c.purpose != "depth",
        )
        ids = union(candidates, outputs).subquery()
        recycled = recycled_ids(project_id)
        previewable = conn.execute(
            select(func.count())
            .select_from(S.media_items)
            .where(
                S.media_items.c.project_id == project_id,
                S.media_items.c.modality == "video",
                S.media_items.c.id.in_(select(ids.c.media_id)),
                S.media_items.c.id.not_in(recycled),
            )
        ).scalar_one()
        identity = favorite_identity(self, conn)
        fav_count = 0
        if identity:
            fav_count = conn.execute(
                select(func.count())
                .select_from(S.classic_media_favorites.join(S.media_items, (S.media_items.c.project_id == S.classic_media_favorites.c.project_id) & (S.media_items.c.id == S.classic_media_favorites.c.media_id)))
                .where(
                    S.classic_media_favorites.c.project_id == project_id,
                    S.classic_media_favorites.c.identity_id == identity,
                    S.classic_media_favorites.c.active.is_(True),
                    S.media_items.c.modality == "video",
                    S.media_items.c.id.in_(select(ids.c.media_id)),
                    S.media_items.c.id.not_in(recycled),
                )
            ).scalar_one()
        return {"episode_id": episode_id, "previewable_video_count": int(previewable), "favorite_video_count": int(fav_count)}

    def classic_storyboard_references(self, project_id, *, episode_id=None):
        from sqlalchemy import and_
        from .project_management import hidden_object_ids
        from .media_recycle import recycled_ids
        with self.engine.connect() as conn:
            project = self._project(conn, project_id)
            self._access_require(conn, project_id, "read")
            hidden = hidden_object_ids(conn, project_id)
            episodes = [
                dict(row)
                for row in conn.execute(
                    select(S.creative_objects.c.id, S.creative_objects.c.title, S.creative_objects.c.display_code, S.episodes.c.ordinal)
                    .join(S.episodes, (S.episodes.c.project_id == S.creative_objects.c.project_id) & (S.episodes.c.id == S.creative_objects.c.id))
                    .where(S.creative_objects.c.project_id == project_id)
                    .order_by(S.episodes.c.ordinal, S.episodes.c.id)
                ).mappings()
                if row["id"] not in hidden
            ]
            chosen_ep = checked_id(episode_id) if episode_id else (episodes[0]["id"] if episodes else None)
            if chosen_ep and all(ep["id"] != chosen_ep for ep in episodes):
                self._one(conn, S.episodes, project_id, chosen_ep)
            shots = self._episode_shot_rows(conn, project_id, chosen_ep) if chosen_ep else []
            shot_ids = [s["id"] for s in shots]
            recycled = recycled_ids(project_id)
            items = []
            if shot_ids:
                selections = {
                    row["shot_id"]: dict(row)
                    for row in conn.execute(
                        select(S.working_selection_versions.c.shot_id, S.binding_candidates.c.media_id, S.binding_candidates.c.id.label("candidate_id"))
                        .join(S.current_working_selections, and_(
                            S.current_working_selections.c.project_id == S.working_selection_versions.c.project_id,
                            S.current_working_selections.c.selection_version_id == S.working_selection_versions.c.id,
                        ))
                        .join(S.binding_candidates, and_(
                            S.binding_candidates.c.project_id == S.working_selection_versions.c.project_id,
                            S.binding_candidates.c.id == S.working_selection_versions.c.candidate_id,
                        ))
                        .where(
                            S.working_selection_versions.c.project_id == project_id,
                            S.working_selection_versions.c.shot_id.in_(shot_ids),
                            S.working_selection_versions.c.output_kind == "image",
                        )
                    ).mappings()
                }
                cand_rows = list(
                    conn.execute(
                        select(
                            S.binding_slots.c.target_object_id.label("shot_id"),
                            S.binding_candidates.c.id.label("candidate_id"),
                            S.media_items.c.id.label("media_id"),
                            S.media_items.c.name,
                            S.media_blobs.c.sha256,
                            S.media_blobs.c.width,
                            S.media_blobs.c.height,
                        )
                        .select_from(
                            S.binding_candidates
                            .join(S.binding_slots, and_(S.binding_slots.c.project_id == S.binding_candidates.c.project_id, S.binding_slots.c.id == S.binding_candidates.c.slot_id))
                            .join(S.media_items, and_(S.media_items.c.project_id == S.binding_candidates.c.project_id, S.media_items.c.id == S.binding_candidates.c.media_id))
                            .join(S.media_blobs, S.media_blobs.c.id == S.media_items.c.blob_id)
                        )
                        .where(
                            S.binding_candidates.c.project_id == project_id,
                            S.binding_slots.c.target_object_id.in_(shot_ids),
                            S.media_items.c.modality == "image",
                            S.media_items.c.id.not_in(recycled),
                        )
                        .order_by(S.binding_candidates.c.created_at.desc(), S.binding_candidates.c.id.desc())
                    ).mappings()
                )
                by_shot = {}
                for r in cand_rows:
                    by_shot.setdefault(r["shot_id"], []).append(dict(r))
                for index, shot in enumerate(shots, 1):
                    sel = selections.get(shot["id"])
                    seen_media = set()
                    images = []
                    for c in by_shot.get(shot["id"], []):
                        if c["media_id"] in seen_media:
                            continue
                        seen_media.add(c["media_id"])
                        images.append({
                            "media_id": c["media_id"],
                            "candidate_id": c["candidate_id"],
                            "name": c["name"],
                            "sha256": c["sha256"],
                            "width": c["width"],
                            "height": c["height"],
                            "selected": bool(sel and sel["media_id"] == c["media_id"]),
                        })
                    images.sort(key=lambda entry: (0 if entry["selected"] else 1))
                    items.append({
                        "shot_id": shot["id"],
                        "serial_number": index,
                        "title": shot["title"],
                        "display_code": shot["display_code"],
                        "selected_media_id": sel["media_id"] if sel else (images[0]["media_id"] if images else None),
                        "images": images,
                    })
            return clean({"project_id": project_id, "episode_id": chosen_ep, "episodes": episodes, "items": items, "revision": project["revision"]})

    def classic_video_review_overview(self, project_id, *, episode_id=None):
        from sqlalchemy import and_
        from .project_management import hidden_object_ids
        from .media_recycle import recycled_ids
        with self.engine.connect() as conn:
            project = self._project(conn, project_id)
            self._access_require(conn, project_id, "read")
            hidden = hidden_object_ids(conn, project_id)
            episodes = [
                dict(row)
                for row in conn.execute(
                    select(S.creative_objects.c.id, S.creative_objects.c.title, S.creative_objects.c.display_code, S.episodes.c.ordinal)
                    .join(S.episodes, (S.episodes.c.project_id == S.creative_objects.c.project_id) & (S.episodes.c.id == S.creative_objects.c.id))
                    .where(S.creative_objects.c.project_id == project_id)
                    .order_by(S.episodes.c.ordinal, S.episodes.c.id)
                ).mappings()
                if row["id"] not in hidden
            ]
            chosen_ep = checked_id(episode_id) if episode_id else (episodes[0]["id"] if episodes else None)
            ep_row = next((ep for ep in episodes if ep["id"] == chosen_ep), None)
            shots = self._episode_shot_rows(conn, project_id, chosen_ep) if chosen_ep else []
            shot_ids = [s["id"] for s in shots]
            recycled = recycled_ids(project_id)
            clips = []
            if shot_ids:
                selections = {
                    row["shot_id"]: dict(row)
                    for row in conn.execute(
                        select(
                            S.working_selection_versions.c.shot_id,
                            S.working_selection_versions.c.trim_in_ms,
                            S.working_selection_versions.c.trim_out_ms,
                            S.binding_candidates.c.id.label("candidate_id"),
                            S.media_items.c.id.label("media_id"),
                            S.media_items.c.name,
                            S.media_blobs.c.sha256,
                            S.media_blobs.c.duration_ms,
                            S.media_blobs.c.width,
                            S.media_blobs.c.height,
                        )
                        .select_from(
                            S.working_selection_versions
                            .join(S.current_working_selections, and_(
                                S.current_working_selections.c.project_id == S.working_selection_versions.c.project_id,
                                S.current_working_selections.c.selection_version_id == S.working_selection_versions.c.id,
                            ))
                            .join(S.binding_candidates, and_(
                                S.binding_candidates.c.project_id == S.working_selection_versions.c.project_id,
                                S.binding_candidates.c.id == S.working_selection_versions.c.candidate_id,
                            ))
                            .join(S.media_items, and_(
                                S.media_items.c.project_id == S.binding_candidates.c.project_id,
                                S.media_items.c.id == S.binding_candidates.c.media_id,
                            ))
                            .join(S.media_blobs, S.media_blobs.c.id == S.media_items.c.blob_id)
                        )
                        .where(
                            S.working_selection_versions.c.project_id == project_id,
                            S.working_selection_versions.c.shot_id.in_(shot_ids),
                            S.working_selection_versions.c.output_kind == "video",
                            S.media_items.c.id.not_in(recycled),
                        )
                    ).mappings()
                }
                fallback_by_shot = {}
                for row in conn.execute(
                    select(
                        S.binding_slots.c.target_object_id.label("shot_id"),
                        S.binding_candidates.c.id.label("candidate_id"),
                        S.media_items.c.id.label("media_id"),
                        S.media_items.c.name,
                        S.media_blobs.c.sha256,
                        S.media_blobs.c.duration_ms,
                        S.media_blobs.c.width,
                        S.media_blobs.c.height,
                    )
                    .select_from(
                        S.binding_candidates
                        .join(S.binding_slots, and_(S.binding_slots.c.project_id == S.binding_candidates.c.project_id, S.binding_slots.c.id == S.binding_candidates.c.slot_id))
                        .join(S.media_items, and_(S.media_items.c.project_id == S.binding_candidates.c.project_id, S.media_items.c.id == S.binding_candidates.c.media_id))
                        .join(S.media_blobs, S.media_blobs.c.id == S.media_items.c.blob_id)
                    )
                    .where(
                        S.binding_candidates.c.project_id == project_id,
                        S.binding_slots.c.target_object_id.in_(shot_ids),
                        S.media_items.c.modality == "video",
                        S.media_items.c.id.not_in(recycled),
                    )
                    .order_by(S.binding_candidates.c.created_at.desc(), S.binding_candidates.c.id.desc())
                ).mappings():
                    fallback_by_shot.setdefault(row["shot_id"], dict(row))
                candidate_ids = [
                    (selections.get(s["id"]) or fallback_by_shot.get(s["id"], {})).get("candidate_id")
                    for s in shots
                ]
                candidate_ids = [cid for cid in candidate_ids if cid]
                reviews_by_cand = {}
                submissions_by_cand = {}
                if candidate_ids:
                    for r in conn.execute(
                        select(S.media_reviews)
                        .where(S.media_reviews.c.project_id == project_id, S.media_reviews.c.candidate_id.in_(candidate_ids))
                        .order_by(S.media_reviews.c.created_at.desc(), S.media_reviews.c.id.desc())
                    ).mappings():
                        reviews_by_cand.setdefault(r["candidate_id"], []).append(dict(r))
                    for sub_row in conn.execute(
                        select(S.access_review_submissions)
                        .where(
                            S.access_review_submissions.c.project_id == project_id,
                            S.access_review_submissions.c.lane == "video",
                            S.access_review_submissions.c.candidate_id.in_(candidate_ids),
                        )
                        .order_by(S.access_review_submissions.c.created_at.desc(), S.access_review_submissions.c.id.desc())
                    ).mappings():
                        submissions_by_cand.setdefault(sub_row["candidate_id"], []).append(dict(sub_row))
                for index, shot in enumerate(shots, 1):
                    chosen = selections.get(shot["id"]) or fallback_by_shot.get(shot["id"])
                    if not chosen:
                        continue
                    cid = chosen["candidate_id"]
                    subs = submissions_by_cand.get(cid, [])
                    pending_sub = next((s for s in subs if not s.get("review_id")), None)
                    all_revs = reviews_by_cand.get(cid, [])
                    acked_rev_ids = {(r.get("evidence") or {}).get("review_id") for r in all_revs if r["criteria_version"] == "team-read-ack-v1"}
                    revs = [r for r in all_revs if r["criteria_version"] != "team-read-ack-v1"]
                    clips.append({
                        "index": len(clips) + 1,
                        "serial_number": index,
                        "shot_id": shot["id"],
                        "shot_title": shot["title"],
                        "display_code": shot["display_code"],
                        "candidate_id": cid,
                        "media_id": chosen["media_id"],
                        "name": chosen["name"],
                        "sha256": chosen["sha256"],
                        "duration_ms": chosen.get("duration_ms") or 0,
                        "width": chosen.get("width"),
                        "height": chosen.get("height"),
                        "selected": shot["id"] in selections,
                        "pending_submission_id": pending_sub["id"] if pending_sub else None,
                        "latest_outcome": "pending" if pending_sub else (revs[0]["outcome"] if revs else "unreviewed"),
                        "reviews": [
                            {
                                "id": rv["id"],
                                "outcome": rv["outcome"],
                                "reason": rv["reason"],
                                "created_by": rv["reviewer"],
                                "reviewer": rv["reviewer"],
                                "created_at": rv["created_at"],
                                "read_ack": rv["id"] in acked_rev_ids or bool((rv.get("evidence") or {}).get("read_ack")),
                            }
                            for rv in revs
                        ],
                    })
            return clean({
                "project_id": project_id,
                "episode_id": chosen_ep,
                "episode_title": ep_row["title"] if ep_row else "第1集",
                "episodes": episodes,
                "clips": clips,
                "revision": project["revision"],
            })

    def collect_classic_episode_videos(self, project_id, *, episode_id=None, scope="all"):
        from sqlalchemy import and_, union
        from .classic_preferences import favorite_identity
        from .project_management import hidden_object_ids
        from .media_recycle import recycled_ids
        with self.engine.connect() as conn:
            self._project(conn, project_id)
            self._access_require(conn, project_id, "read")
            hidden = hidden_object_ids(conn, project_id)
            episodes = [
                dict(row)
                for row in conn.execute(
                    select(S.creative_objects.c.id, S.creative_objects.c.title, S.episodes.c.ordinal)
                    .join(S.episodes, (S.episodes.c.project_id == S.creative_objects.c.project_id) & (S.episodes.c.id == S.creative_objects.c.id))
                    .where(S.creative_objects.c.project_id == project_id)
                    .order_by(S.episodes.c.ordinal, S.episodes.c.id)
                ).mappings()
                if row["id"] not in hidden
            ]
            chosen_ep = checked_id(episode_id) if episode_id else (episodes[0]["id"] if episodes else None)
            ep_row = next((ep for ep in episodes if ep["id"] == chosen_ep), None)
            shots = self._episode_shot_rows(conn, project_id, chosen_ep) if chosen_ep else []
            shot_map = {s["id"]: s for s in shots}
            shot_ids = [s["id"] for s in shots]
            if not shot_ids:
                return {"episode_id": chosen_ep, "episode_title": ep_row["title"] if ep_row else "第1集", "items": []}
            recycled = recycled_ids(project_id)
            if scope == "selected":
                rows = conn.execute(
                    select(S.working_selection_versions.c.shot_id, S.binding_candidates.c.media_id)
                    .join(S.current_working_selections, and_(
                        S.current_working_selections.c.project_id == S.working_selection_versions.c.project_id,
                        S.current_working_selections.c.selection_version_id == S.working_selection_versions.c.id,
                    ))
                    .join(S.binding_candidates, and_(
                        S.binding_candidates.c.project_id == S.working_selection_versions.c.project_id,
                        S.binding_candidates.c.id == S.working_selection_versions.c.candidate_id,
                    ))
                    .where(
                        S.working_selection_versions.c.project_id == project_id,
                        S.working_selection_versions.c.shot_id.in_(shot_ids),
                        S.working_selection_versions.c.output_kind == "video",
                        S.binding_candidates.c.media_id.not_in(recycled),
                    )
                ).mappings()
                by_shot = {r["shot_id"]: r["media_id"] for r in rows}
                items = [{"shot_id": s["id"], "shot_title": s["title"], "media_id": by_shot[s["id"]]} for s in shots if s["id"] in by_shot]
                return {"episode_id": chosen_ep, "episode_title": ep_row["title"] if ep_row else "第1集", "items": items}
            candidates = select(S.binding_slots.c.target_object_id.label("shot_id"), S.binding_candidates.c.media_id).join(
                S.binding_slots,
                and_(S.binding_slots.c.project_id == S.binding_candidates.c.project_id, S.binding_slots.c.id == S.binding_candidates.c.slot_id),
            ).where(S.binding_candidates.c.project_id == project_id, S.binding_slots.c.target_object_id.in_(shot_ids))
            outputs = select(S.generation_jobs.c.shot_id.label("shot_id"), S.job_outputs.c.media_id).join(
                S.generation_jobs,
                and_(S.generation_jobs.c.project_id == S.job_outputs.c.project_id, S.generation_jobs.c.id == S.job_outputs.c.job_id),
            ).where(
                S.job_outputs.c.project_id == project_id,
                S.generation_jobs.c.shot_id.in_(shot_ids),
                S.generation_jobs.c.modality == "video",
                S.generation_jobs.c.purpose != "depth",
            )
            pairs = union(candidates, outputs).subquery()
            fav_ids = None
            if scope == "favorites":
                identity = favorite_identity(self, conn)
                if not identity:
                    return {"episode_id": chosen_ep, "episode_title": ep_row["title"] if ep_row else "第1集", "items": []}
                fav_ids = set(
                    conn.execute(
                        select(S.classic_media_favorites.c.media_id).where(
                            S.classic_media_favorites.c.project_id == project_id,
                            S.classic_media_favorites.c.identity_id == identity,
                            S.classic_media_favorites.c.active.is_(True),
                        )
                    ).scalars()
                )
            video_ids = set(
                conn.execute(
                    select(S.media_items.c.id).where(
                        S.media_items.c.project_id == project_id,
                        S.media_items.c.modality == "video",
                        S.media_items.c.id.not_in(recycled),
                    )
                ).scalars()
            )
            order_index = {s["id"]: idx for idx, s in enumerate(shots)}
            raw_pairs = [
                (r["shot_id"], r["media_id"])
                for r in conn.execute(select(pairs.c.shot_id, pairs.c.media_id)).mappings()
                if r["media_id"] in video_ids and (fav_ids is None or r["media_id"] in fav_ids)
            ]
            raw_pairs.sort(key=lambda p: (order_index.get(p[0], 9999), p[1]))
            seen = set()
            items = []
            for sid, mid in raw_pairs:
                if mid in seen:
                    continue
                seen.add(mid)
                items.append({"shot_id": sid, "shot_title": shot_map.get(sid, {}).get("title") or sid[:8], "media_id": mid})
            return {"episode_id": chosen_ep, "episode_title": ep_row["title"] if ep_row else "第1集", "items": items}

    def list_working_candidates(self, project_id, shot_id, output_kind, *, offset=0, limit=24, filter_kind='all'):
        from sqlalchemy import and_, func, union, exists
        from .classic_preferences import favorite_identity, local_media_predicate
        from .media_recycle import recycled_ids

        with self.engine.connect() as conn:
            project = self._project(conn, project_id)
            self._access_require(conn, project_id, 'read')
            self._one(conn, S.shots, project_id, checked_id(shot_id))
            candidates = select(S.binding_candidates.c.media_id).join(S.binding_slots, and_(
                S.binding_slots.c.project_id == S.binding_candidates.c.project_id,
                S.binding_slots.c.id == S.binding_candidates.c.slot_id)).where(
                S.binding_candidates.c.project_id == project_id,
                S.binding_slots.c.target_object_id == shot_id)
            outputs = select(S.job_outputs.c.media_id).join(S.generation_jobs, and_(
                S.generation_jobs.c.project_id == S.job_outputs.c.project_id,
                S.generation_jobs.c.id == S.job_outputs.c.job_id)).where(
                S.job_outputs.c.project_id == project_id, S.generation_jobs.c.shot_id == shot_id,
                S.generation_jobs.c.modality == output_kind, S.generation_jobs.c.purpose != 'depth',
                S.generation_jobs.c.request_payload['operation'].as_string().is_distinct_from('subject_detect'))
            ids = union(candidates, outputs).subquery()
            query = self._media_query(project_id).where(S.media_items.c.modality == output_kind,
                S.media_items.c.id.in_(select(ids.c.media_id)),
                S.media_items.c.id.not_in(recycled_ids(project_id)))
            identity = favorite_identity(self, conn)
            favorite = exists(select(S.classic_media_favorites.c.id).where(
                S.classic_media_favorites.c.project_id == project_id,
                S.classic_media_favorites.c.identity_id == identity,
                S.classic_media_favorites.c.media_id == S.media_items.c.id,
                S.classic_media_favorites.c.active.is_(True)))
            if filter_kind == 'favorites': query = query.where(favorite)
            if filter_kind == 'local': query = query.where(local_media_predicate(project_id))
            total = conn.execute(select(func.count()).select_from(query.subquery())).scalar_one()
            rows = [dict(row) for row in conn.execute(query.order_by(
                S.media_items.c.created_at.desc(), S.media_items.c.id).offset(offset).limit(limit)).mappings()]
            page_ids = [row['id'] for row in rows]
            selection = conn.execute(select(S.working_selection_versions, S.binding_candidates.c.media_id)
                .join(S.current_working_selections, and_(
                    S.current_working_selections.c.project_id == S.working_selection_versions.c.project_id,
                    S.current_working_selections.c.selection_version_id == S.working_selection_versions.c.id))
                .outerjoin(S.binding_candidates, and_(
                    S.binding_candidates.c.project_id == S.working_selection_versions.c.project_id,
                    S.binding_candidates.c.id == S.working_selection_versions.c.candidate_id))
                .where(S.working_selection_versions.c.project_id == project_id,
                    S.working_selection_versions.c.shot_id == shot_id,
                    S.working_selection_versions.c.output_kind == output_kind)).mappings().first()
            candidate_by_media, job_by_media, review_status_by_cand = {}, {}, {}
            favorites = {r['media_id']: r for r in conn.execute(select(S.classic_media_favorites).where(
                S.classic_media_favorites.c.project_id == project_id,
                S.classic_media_favorites.c.identity_id == identity,
                S.classic_media_favorites.c.media_id.in_(page_ids))).mappings()}
            local_ids = set(conn.execute(select(S.media_items.c.id).where(S.media_items.c.project_id == project_id,
                S.media_items.c.id.in_(page_ids), local_media_predicate(project_id))).scalars())
            if page_ids:
                for row in conn.execute(select(S.binding_candidates).join(S.binding_slots, and_(
                    S.binding_slots.c.project_id == S.binding_candidates.c.project_id,
                    S.binding_slots.c.id == S.binding_candidates.c.slot_id)).where(
                    S.binding_candidates.c.project_id == project_id,
                    S.binding_slots.c.target_object_id == shot_id,
                    S.binding_candidates.c.media_id.in_(page_ids)).order_by(
                        S.binding_candidates.c.created_at, S.binding_candidates.c.id)).mappings():
                    candidate_by_media[row['media_id']] = row['id']
                cand_ids = list(set(candidate_by_media.values()))
                if cand_ids:
                    lane_name = 'storyboard' if output_kind == 'image' else 'video'
                    for sub_row in conn.execute(
                        select(S.access_review_submissions, S.media_reviews.c.outcome)
                        .outerjoin(S.media_reviews, and_(
                            S.media_reviews.c.project_id == S.access_review_submissions.c.project_id,
                            S.media_reviews.c.id == S.access_review_submissions.c.review_id,
                        ))
                        .where(
                            S.access_review_submissions.c.project_id == project_id,
                            S.access_review_submissions.c.lane == lane_name,
                            S.access_review_submissions.c.candidate_id.in_(cand_ids),
                        )
                        .order_by(S.access_review_submissions.c.created_at.desc(), S.access_review_submissions.c.id.desc())
                    ).mappings():
                        review_status_by_cand.setdefault(
                            sub_row['candidate_id'],
                            {'submission_id': sub_row['id'], 'status': sub_row['outcome'] or 'pending'},
                        )
                for row in conn.execute(select(S.job_outputs.c.media_id,
                    S.generation_jobs.c.id, S.generation_jobs.c.status, S.generation_jobs.c.request_payload,
                    S.generation_jobs.c.raw_response).join(S.generation_jobs, and_(
                        S.generation_jobs.c.project_id == S.job_outputs.c.project_id,
                        S.generation_jobs.c.id == S.job_outputs.c.job_id)).where(
                    S.job_outputs.c.project_id == project_id, S.generation_jobs.c.shot_id == shot_id,
                    S.job_outputs.c.media_id.in_(page_ids)).order_by(
                        S.generation_jobs.c.created_at, S.generation_jobs.c.id)).mappings():
                    job_by_media[row['media_id']] = row
            items = []
            for row in rows:
                selected = bool(selection and selection['media_id'] == row['id'])
                job = job_by_media.get(row['id'], {})
                sample=None
                if job.get('request_payload',{}).get('draft') is True:
                    from vsc.production.video_samples import sample_deadline
                    try:sample={'expires_at':sample_deadline((job.get('raw_response') or {}).get('created_at')).isoformat()}
                    except ResourceError as error:sample={'unavailable':str(error)}
                cid = selection['candidate_id'] if selected else candidate_by_media.get(row['id'])
                rev_meta = review_status_by_cand.get(cid, {})
                items.append({key: row.get(key) for key in (
                    'id', 'name', 'modality', 'sha256', 'duration_ms', 'width', 'height', 'created_at')})
                items[-1].update(media_id=row['id'], candidate_id=cid, job_id=job.get('id'),
                    job_status=job.get('status'), selected=selected,
                    review_status=rev_meta.get('status'),
                    review_submission_id=rev_meta.get('submission_id'),
                    native_sample=sample, favorite=favorites.get(row['id'], {}).get('active', False),
                    favorite_version=favorites.get(row['id'], {}).get('version', 0),
                    local=row['id'] in local_ids, can_favorite=bool(identity),
                    selection_version_id=selection['id'] if selection else None,
                    trim_in_ms=selection['trim_in_ms'] if selected else 0,
                    trim_out_ms=selection['trim_out_ms'] if selected else row.get('duration_ms'))
            return clean({'items': items, 'total': total,
                'next_offset': offset + len(items) if offset + len(items) < total else None,
                'revision': project['revision']})

    def list_classic_drafts(self, project_id, shot_id):
        with self.engine.connect() as conn:
            project = self._project(conn, checked_id(project_id))
            self._one(conn, S.shots, project["id"], checked_id(shot_id))
            rows = conn.execute(select(S.artifact_versions).where(
                S.artifact_versions.c.project_id == project["id"], S.artifact_versions.c.artifact_type == DRAFT_TYPE,
                S.artifact_versions.c.artifact_key.like("classic:" + shot_id + ":%"))
                .order_by(S.artifact_versions.c.version)).mappings()
            latest = {}
            for row in rows:
                latest[row["artifact_key"]] = {key: row[key] for key in ("id", "version", "sha256", "document", "created_at")}
                latest[row["artifact_key"]]["document"] = json.loads(row["document"])
            return clean({"items": list(latest.values()), "revision": project["revision"]})

    def save_classic_draft(self, project_id, payload, *, build_document, **kw):
        def work(conn, project):
            document = build_document(project_id, payload["document"])
            key = draft_key(document["shot_id"], document["mode"])
            current = conn.execute(select(S.artifact_versions.c.id).where(
                S.artifact_versions.c.project_id == project["id"], S.artifact_versions.c.artifact_key == key)
                .order_by(S.artifact_versions.c.version.desc()).limit(1)).scalar()
            if (str(current) if current else None) != payload.get("base_draft_id"):
                raise Conflict("此模式已有更新草稿；输入保留，请先读取比较", "classic_draft_conflict")
            dependencies = [document['tool_settings']['mask_export_id']] if document['mode'] in {'image_inpaint','image_watermark'} and document.get('tool_settings',{}).get('mask_export_id') else []
            if document['mode'] == 'digital_human' and document.get('subject_selection'):
                from .workbench_generation import subject_sources
                dependencies.append(subject_sources(self, conn, project['id'], document)['dependency_id'])
            from .professional_inputs import resolve_professional_inputs
            dependencies.extend(resolve_professional_inputs(self,conn,project,document)['dependency_ids'])
            artifact = self._create_artifact(conn, project, {"artifact_key": key, "artifact_type": DRAFT_TYPE,
                "stage": "production", "document": document, "object_ids": [document["shot_id"]], "supersedes_id": current,
                "dependency_ids":dependencies})
            self._project_classic_draft_media(conn, project, artifact, document)
            return artifact
        return self._mutate(project_id, "save_classic_draft", payload, callback=work, **kw)

    def import_classic_frame_media(self, project_id, payload, actor, *, storage, **kw):
        from sqlalchemy import insert, select
        from .asset_cards import AssetCardsRepository
        from .copy_lineage import assert_copy_source
        from .project_management import hidden_object_ids, management_project_guard
        from .values import new_id
        source_project = checked_id(payload["source_project_id"])
        source = payload["source"]
        command_key = kw["idempotency_key"]

        def work(conn, project):
            self._access_require(conn, source_project, "read")
            management_project_guard(conn, source_project)
            hidden = hidden_object_ids(conn, source_project)
            shot = self._one(conn, S.shots, project["id"], payload["shot_id"])
            source_media = checked_id(source["media_id"])
            form_id = workflow_id = unit_key = purpose = None
            if source["kind"] == "asset_form":
                fixed = self._one(conn, S.asset_card_form_versions, source_project, source["form_version_id"])
                form = self._one(conn, S.asset_card_forms, source_project, fixed["form_id"])
                if (str(form["asset_id"]) != checked_id(source["asset_id"]) or str(fixed["media_id"]) != source_media
                        or str(form["asset_id"]) in hidden or form["current_version_id"] != fixed["id"]):
                    raise Conflict("素材形态已变化或不可用，请刷新资产列表", "classic_frame_source_changed")
                form_id = fixed["id"]
                title = fixed["asset_name"] + (" · " + fixed["form_name"] if fixed["form_name"] else "")
            elif source["kind"] == "storyboard":
                source_shot_id = checked_id(source["shot_id"])
                if source_shot_id in hidden:
                    raise Conflict("来源镜号已回收，请刷新分镜列表", "classic_frame_source_changed")
                source_shot_obj = self._one(conn, S.creative_objects, source_project, source_shot_id)
                exists_cand = conn.execute(
                    select(S.binding_candidates.c.id)
                    .join(S.binding_slots, (S.binding_slots.c.project_id == S.binding_candidates.c.project_id) & (S.binding_slots.c.id == S.binding_candidates.c.slot_id))
                    .where(
                        S.binding_candidates.c.project_id == source_project,
                        S.binding_slots.c.target_object_id == source_shot_id,
                        S.binding_candidates.c.media_id == source_media,
                    )
                    .limit(1)
                ).scalar_one_or_none()
                if not exists_cand:
                    raise Conflict("来源分镜图已变化或不属于该镜号", "classic_frame_source_changed")
                title = "分镜 · " + str(source_shot_obj.get("title") or source_shot_id[:8])
            else:
                station = AssetCardsRepository(self)._blocking_projection(source_project, hidden)
                query = select(station).where(station.c.source_rank == 1,
                    station.c.workflow_id == checked_id(source["workflow_id"]),
                    station.c.version_id == checked_id(source["version_id"]),
                    station.c.episode_id == checked_id(source["episode_id"]),
                    station.c.unit_key == source["unit_key"], station.c.media_id == source_media)
                query = query.where(station.c.spatial_export_id == checked_id(source["spatial_export_id"]) if source["spatial_export_id"] else station.c.spatial_export_id.is_(None))
                fixed = conn.execute(query).mappings().first()
                if not fixed:
                    raise Conflict("固定站位已变化或不可用，请刷新资产列表", "classic_frame_source_changed")
                workflow_id = fixed["version_id"]
                unit_key = fixed["unit_key"]
                purpose = "blocking"
                title = fixed["name"]
            item = self._media(conn, source_project, source_media)
            if item["modality"] != "image":
                raise ResourceError("首尾帧只接受图片", "classic_frame_media_type")
            rights = assert_copy_source(self, conn, source_project, source_media)
            _, gaps = self._usable(conn, source_project, source_media, payload["role"])
            blocked = [gap for gap in gaps if gap != "technical_check_missing"]
            if blocked:
                raise ResourceError("素材当前不可用于首尾帧：" + ", ".join(blocked), "classic_frame_source_unavailable")
            location = next((value for value in item["locations"] if value["available"]), None)
            if not location:
                raise ResourceError("素材没有可用副本", "classic_frame_source_unavailable")
            registered = self._register_media(conn, project, dict(item, id=new_id(), storage=location["storage"], object_key=location["object_key"],
                rights=rights["outcome"] if rights else "unknown", rights_scope=rights["scope"] if rights else {"purposes": []},
                rights_expires_at=rights["expires_at"] if rights else None,
                source={"kind": "classic-frame-reference", "content": {"source_project_id": source_project, "source_media_id": source_media, "sha256": item["sha256"], "shot_id": shot["id"], "role": payload["role"]}}), actor)
            byte_check = self._record_canvas_copy_byte_check(conn, project, registered["id"], storage)
            if byte_check.get("status") == "invalid":
                raise ResourceError("原素材本地文件缺失或损坏，请检查来源副本", "classic_frame_source_bytes_invalid")
            if byte_check.get("status") not in {"verified", "unavailable"}:
                raise ResourceError("素材检查状态无效，请重试", "classic_frame_source_unavailable")
            if payload["role"] in {"first_frame", "last_frame"} and source["kind"] != "storyboard":
                conn.execute(insert(S.classic_frame_media_links).values(id=new_id(), project_id=project["id"],
                    target_media_id=registered["id"], source_project_id=source_project, source_media_id=source_media,
                    blob_id=registered["blob_id"], sha256=item["sha256"], source_form_version_id=form_id,
                    source_workflow_version_id=workflow_id, source_unit_key=unit_key, source_purpose=purpose,
                    shot_id=shot["id"], role=payload["role"], command_key=command_key, created_by=actor))
            return {"media_id": registered["id"], "sha256": item["sha256"], "name": (title or item["name"])[:200],
                "modality": "image", "byte_check": byte_check, "shot_id": shot["id"], "role": payload["role"],
                "source_project_id": source_project, "source_media_id": source_media}

        return self._mutate(project_id, "import_classic_frame_media", payload, actor=actor, callback=work,
            _related_projects=(project_id, source_project), **kw)

    def generate_workbench(self, project_id, payload, *, build_preview, actor, canvas_auto_authorization=None, **kw):
        from sqlalchemy import insert
        from .values import new_id
        from .workbench_generation import RUN_TYPE

        def work(conn, project):
            preview = build_preview(project_id, payload["request"])
            if not preview["ready"]:
                raise ResourceError("输入或模型仍有缺项，请在当前页补齐", "classic_not_ready")
            if preview["preview_sha256"] != payload["preview_sha256"]:
                raise Conflict("输入、模型或报价已改变，请确认更新后的报价", "classic_preview_changed")
            if preview["artifact"]["artifact_type"] != RUN_TYPE:
                raise ResourceError("生成入口只接受固定工作请求", "working_run_type")
            authorization = None
            if canvas_auto_authorization is not None:
                authorization = self._validate_canvas_auto_generation(conn, project, payload["request"], preview, actor, canvas_auto_authorization)
            artifact = self._create_artifact(conn, project, preview["artifact"])
            document = preview["artifact"]["document"]
            draft = document["workbench_draft"]
            shots = {item["request"]["shot_id"] for item in document["series_batch"]["jobs"]}
            for shot in shots:
                output_kind = next(item["request"]["modality"] for item in document["series_batch"]["jobs"]
                                   if item["request"]["shot_id"] == shot)
                selection = conn.execute(select(S.current_working_selections.c.selection_version_id).where(
                    S.current_working_selections.c.project_id == project_id,
                    S.current_working_selections.c.shot_id == shot,
                    S.current_working_selections.c.output_kind == output_kind)).scalar_one_or_none()
                conn.execute(insert(S.workbench_run_inputs).values(project_id=project_id, id=new_id(),
                    run_version_id=artifact["id"], shot_id=shot,
                    draft_version_id=draft["id"], draft_sha256=draft["sha256"],
                    output_kind=output_kind, base_selection_version_id=selection))
            self.decide_artifact(project_id, {"artifact_id": artifact["id"], "outcome": "approve",
                "reason": authorization["reason"] if authorization is not None else "用户在制作页确认固定输入与报价并点击生成"}, actor=actor,
                _transaction=(conn, project), **{key: value for key, value in kw.items() if key != '_transaction'})
            jobs = []
            for item in document["series_batch"]["jobs"]:
                if item.get('depends_on'):
                    from vsc.production.bounded import depth_dependency_tasks
                    depth_dependency_tasks(document)
                    continue
                request = item["request"]
                jobs.append(self._create_generation_job(conn, project, {
                    "shot_id": request["shot_id"], "purpose": request["purpose"],
                    "modality": request["modality"], "model_id": item["model_id"],
                    "candidate_no": item["candidate_no"], "run_version_id": artifact["id"],
                    "context_sha256": request["context_sha256"], "request_payload": request}))
            return {"id": artifact["id"], "run_version_id": artifact["id"],
                    "jobs": jobs, "status": "queued"}
        return self._mutate(project_id, "generate_workbench", payload, actor=actor, callback=work, **kw)

    def propose_classic_run(self, project_id, payload, *, build_preview, **kw):
        def work(conn, project):
            preview = build_preview(project_id, payload["request"])
            if not preview["ready"]:
                raise ResourceError("经典草稿仍有输入或执行能力缺口", "classic_not_ready")
            if preview["preview_sha256"] != payload["preview_sha256"]:
                raise Conflict("草稿、固定输入、模型或报价已改变，请重新预览", "classic_preview_changed")
            return self._create_artifact(conn, project, preview["artifact"])
        return self._mutate(project_id, "propose_classic_run", payload, callback=work, **kw)

    def list_classic_reference_edits(self,project_id,shot_id):
        from vsc.production.image_tools import EDIT_TYPE
        with self.engine.connect() as conn:
            self._one(conn,S.shots,project_id,checked_id(shot_id));latest={}
            for row in conn.execute(select(S.artifact_versions).where(S.artifact_versions.c.project_id==project_id,S.artifact_versions.c.artifact_type==EDIT_TYPE,S.artifact_versions.c.artifact_key.like('classic-edit:'+shot_id+':%')).order_by(S.artifact_versions.c.version)).mappings():
                latest[row['artifact_key']]={k:row[k] for k in ('id','version','sha256')};latest[row['artifact_key']]['document']=json.loads(row['document'])
            return clean({'items':list(latest.values())})

    def save_classic_reference_edit(self,project_id,payload,**kw):
        from vsc.production.image_tools import EDIT_TYPE
        def work(conn,project):
            p=project['id'];self._one(conn,S.shots,p,checked_id(payload['shot_id']));d=payload['document'];media=self._media(conn,p,checked_id(d['source_media_id']))
            if media['sha256']!=d['source_sha256'] or media['modality']!=d['source_modality']:raise Conflict('标注源媒体已改变')
            key='classic-edit:'+payload['shot_id']+':'+payload['mode']+':'+d['id']
            prior=conn.execute(select(S.artifact_versions.c.id).where(S.artifact_versions.c.project_id==p,S.artifact_versions.c.artifact_key==key).order_by(S.artifact_versions.c.version.desc()).limit(1)).scalar_one_or_none()
            if prior!=payload['base_edit_id']:raise Conflict('标注已有新版本；保留本地稿，读取后比较','reference_edit_conflict')
            document={'shot_id':payload['shot_id'],'mode':payload['mode'],'edit':d}
            return self._create_artifact(conn,project,{'artifact_key':key,'artifact_type':EDIT_TYPE,'stage':'production','document':document,'object_ids':[payload['shot_id']],'supersedes_id':prior})
        return self._mutate(project_id,'save_classic_reference_edit',payload,callback=work,**kw)

    def export_classic_reference_edit(self,project_id,payload,*,build,**kw):
        from vsc.production.image_tools import EDIT_TYPE,OUTPUT_TYPE
        def work(conn,project):
            p=project['id'];artifact=self._one(conn,S.artifact_versions,p,checked_id(payload['edit_version_id']))
            if artifact['artifact_type']!=EDIT_TYPE:raise ResourceError('需要保存的参考标注版本')
            doc=json.loads(artifact['document']);d=doc['edit'];media=self._media(conn,p,d['source_media_id'])
            if media['sha256']!=d['source_sha256']:raise Conflict('固定源媒体摘要变化')
            key='classic-edit-output:'+artifact['id'];prior=conn.execute(select(S.artifact_versions).where(S.artifact_versions.c.project_id==p,S.artifact_versions.c.artifact_key==key)).mappings().first()
            if prior:return dict(json.loads(prior['document']),id=prior['id'],already_exported=True)
            outputs=[]
            for item in build(d):
                registered=self._register_media(conn,project,{**item['media'],'rights':'unknown','source':{'kind':'local-reference-edit','content':{'edit_version_id':artifact['id'],'edit_sha256':artifact['sha256'],'source_media_id':media['id'],'source_sha256':media['sha256'],'time_ms':d['time_ms']}}},kw['actor'])
                outputs.append({'media_id':registered['id'],'sha256':registered['sha256'],'role':item['role']})
            operation=self.create_media_operation(p,{'operation_type':'reference-annotation','recipe_version':'reference-edit/v1','tool':'vsc-local-reference-editor','tool_version':'1','parameters':{'edit_version_id':artifact['id'],'edit_sha256':artifact['sha256'],'time_ms':d['time_ms']},'inputs':[{'media_id':media['id'],'role':'source','start_ms':d['time_ms'] if media['modality']=='video' else None}],'outputs':outputs},_transaction=(conn,project),**kw)
            result={'shot_id':doc['shot_id'],'mode':doc['mode'],'edit_version_id':artifact['id'],'edit_sha256':artifact['sha256'],'source_media_id':media['id'],'source_sha256':media['sha256'],'time_ms':d['time_ms'],'outputs':outputs,'operation_id':operation['id']}
            registered=self._create_artifact(conn,project,{'artifact_key':key,'artifact_type':OUTPUT_TYPE,'stage':'production','document':result,'object_ids':[doc['shot_id']],'dependency_ids':[artifact['id']]})
            return dict(result,id=registered['id'],already_exported=False)
        return self._mutate(project_id,'export_classic_reference_edit',payload,callback=work,**kw)

    def change_classic_shots(self,project_id,payload,**kw):
        from sqlalchemy import update
        from .project_management import hidden_object_ids
        from .values import new_id
        def work(conn,project):
            p=project['id'];parent=checked_id(payload.get('parent_id'));self._one(conn,S.sequences,p,parent)
            hidden=hidden_object_ids(conn,p)
            all_rows=list(conn.execute(select(S.shots.c.id,S.shots.c.ordinal).where(S.shots.c.project_id==p,S.shots.c.parent_id==parent).order_by(S.shots.c.ordinal)).mappings())
            rows=[r for r in all_rows if r['id'] not in hidden]
            if payload['action']=='create':
                title=payload.get('title','').strip()
                if not title or len(title)>200:raise ResourceError('请填写200字以内的镜号名称')
                return self._create_object(conn,project,{'kind':'shot','parent_id':parent,'title':title,'display_code':'SHOT-'+new_id()[:8],'ordinal':max((r['ordinal'] for r in all_rows),default=-1)+1})
            ids=payload.get('shot_ids')
            if not isinstance(ids,list) or len(ids)!=len(set(ids)) or set(ids)!={r['id'] for r in rows}:raise ResourceError('排序必须包含同镜组全部镜号，不能跨组')
            start=max((r['ordinal'] for r in all_rows),default=-1)+len(all_rows)+1
            for index,row in enumerate(all_rows):conn.execute(update(S.shots).where(S.shots.c.project_id==p,S.shots.c.id==row['id']).values(ordinal=start+index))
            for index,identifier in enumerate(ids):conn.execute(update(S.shots).where(S.shots.c.project_id==p,S.shots.c.id==identifier).values(ordinal=index))
            return {'shot_ids':ids,'parent_id':parent}
        return self._mutate(project_id,'change_classic_shots',payload,callback=work,**kw)

    def classic_candidate_configuration(self,project_id,shot_id,media_id):
        with self.engine.connect() as conn:
            self._one(conn,S.shots,project_id,checked_id(shot_id));self._one(conn,S.media_items,project_id,checked_id(media_id))
            row=conn.execute(select(S.generation_jobs).join(S.job_outputs,(S.job_outputs.c.project_id==S.generation_jobs.c.project_id)&(S.job_outputs.c.job_id==S.generation_jobs.c.id)).where(S.generation_jobs.c.project_id==project_id,S.generation_jobs.c.shot_id==shot_id,S.generation_jobs.c.status=='succeeded',S.job_outputs.c.media_id==media_id).order_by(S.generation_jobs.c.created_at.desc()).limit(1)).mappings().first()
            return clean(dict(row)) if row else None
