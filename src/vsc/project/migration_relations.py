"""Evidence adapters for legacy production and asset reference relationships."""
from collections import Counter, defaultdict
import hashlib
from pathlib import Path
import uuid

from vsc.project import migration as M
from vsc.project.migration_prepare import _document


def _refs(value):
    """Yield only explicit fixed file references, without interpreting names."""
    if isinstance(value, dict):
        if isinstance(value.get("path"), str) and isinstance(value.get("sha256"), str):
            yield value
        for nested in value.values():
            yield from _refs(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _refs(nested)


def _candidate(p, target, role, slot_key, media, spec=None, context=None):
    slot = p.add("binding_slots", {"target_object_id": target, "role": role, "slot_key": slot_key}, (target, role, slot_key))
    payload = {"slot_id": slot["key"]["id"], "media_id": media["id"], "spec_version_id": spec, "proposer": p.actor}
    if context:
        payload["context_sha256"] = context
    candidate = p.add("binding_candidates", payload, (slot["key"]["id"], media["id"], spec, context))
    p.candidates[(slot_key, media["name"])] = candidate["key"]["id"]
    return slot, candidate


def prepare_media_relations(p):
    documents = {}
    for path, item in p.files.items():
        if Path(path).suffix.lower() == ".json" and item["size_bytes"] <= 64 * 1024 * 1024:
            documents[path] = _document(M._safe(p.project, path))
    records, tasks = {}, {}
    artifact_by_document = defaultdict(list)
    for old, doc in p.documents.items():
        artifact_by_document[M._digest(doc)].append(old)
    for path, doc in documents.items():
        if doc.get("format") == "vsc.generation-record/v1":
            key = M._digest(doc)
            records.setdefault(key, {"document": doc, "paths": []})["paths"].append(path)
        elif isinstance(doc.get("binding"), dict) and isinstance(doc.get("record"), dict) and doc["record"].get("format") == "vsc.generation-record/v1":
            tasks[M._digest(doc["record"])] = {"path": path, "document": doc}
    # Run and batch join uses the saved SHA and the producer's explicit output
    # arguments; it does not infer shots from the resulting file names.
    producers, journals = {}, {}
    for path, doc in documents.items():
        if doc.get("format") == "vsc.production-journal/v1":
            journals[doc.get("id")] = (path, doc)
    from vsc.production.production import record_path
    for old, run in p.documents.items():
        if run.get("format") != "vsc.production-run/v1" or old not in p.artifacts:
            continue
        batch_ref = run.get("batch", {})
        batch_media = p.fixed(batch_ref.get("path"), batch_ref.get("sha256")) if batch_ref else None
        if batch_ref and not batch_media:
            continue
        batch_path = batch_media.get("resolved_path", batch_ref.get("path")) if batch_media else None
        batch = documents.get(batch_path, {})
        if batch.get("format") != "vsc.production-batch/v1":
            continue
        journal = journals.get(batch.get("id"))
        for job in batch.get("jobs", []):
            try:
                path = record_path(job)
            except (KeyError, TypeError):
                p.problem("batch_job_incomplete", "artifacts:" + old, "旧batch任务缺少明确输出参数")
                continue
            doc = documents.get(path)
            record_key = M._digest(doc) if doc and doc.get("format") == "vsc.generation-record/v1" else None
            context = {"run_id": old, "run": run, "job": job, "journal": journal, "record_path": path}
            if record_key:
                producers.setdefault(record_key, []).append(context)
            if journal:
                entry = journal[1].get("jobs", {}).get(job.get("id"))
                if entry:
                    context["journal_entry"] = entry
                    p.manifest["preparation"].setdefault("production_journal_jobs", []).append({
                        "run_id": old, "job_id": job.get("id"), "journal_path": journal[0], "status": entry.get("status"),
                        "record_path": path if doc else None, "record_sha256": p.files[path]["sha256"] if path in p.files else None})
    output_producers, job_ids, counters = {}, {}, Counter()
    record_outputs = {}
    for record_key, record in records.items():
        doc, paths = record["document"], record["paths"]
        kind, engine = doc.get("kind"), doc.get("engine", {})
        if kind not in {"image", "video", "audio", "speech"}:
            p.warnings.append({"code": "non_media_generation", "path": paths[0]})
            continue
        original_artifacts = [old for old in artifact_by_document.get(record_key, []) if old in p.artifacts]
        source_path = paths[0]
        source = p.add("source_versions", {"source_key": "legacy.generation:" + record_key, "version": 1,
            "kind": "generation-record", "document": {"legacy_file": source_path}, "sha256": p.files[source_path]["sha256"], "evidence_uri": source_path}, record_key)
        inputs = list(_refs(doc.get("inputs", {})))
        operation = p.add("media_operations", {"operation_type": "legacy_generation", "recipe_version": "generation-record/v1",
            "tool": str(engine.get("provider") or "legacy-unrecorded"), "tool_version": str(engine.get("version") or "legacy-unversioned"),
            "parameters": {"engine": engine, "inputs": doc.get("inputs", {}), "purpose": doc.get("purpose")},
            "status": doc.get("status") if doc.get("status") in {"created", "running", "succeeded", "failed"} else "created",
            "execution": {"record_paths": paths, "record_sha256": p.files[source_path]["sha256"], "original_status": doc.get("status"),
                          "historical_only": True, "runs": [c["run_id"] for c in producers.get(record_key, [])]}}, record_key)
        op_id = operation["key"]["id"]
        p.operations[record_key] = op_id
        for ordinal, ref in enumerate(inputs):
            media = p.fixed(ref["path"], ref["sha256"])
            if media:
                p.add("operation_inputs", {"operation_id": op_id, "media_id": media["id"],
                    "role": str(ref.get("role") or ref.get("purpose") or "reference"), "layer_order": ordinal,
                    "transform": {k: v for k, v in ref.items() if k not in {"path", "sha256"}}, "opacity": 1}, (record_key, ordinal))
        outputs = []
        for ordinal, ref in enumerate(doc.get("outputs", [])):
            media = p.fixed(ref.get("path"), ref.get("sha256"))
            if not media:
                continue
            if media["id"] in output_producers and output_producers[media["id"]] != op_id:
                # Distinct recorded executions may produce identical byte paths.
                # Preserve their separate media contexts while sharing the blob.
                contextual = dict(media, id=p.ident("generation_media", (record_key, media["name"])))
                p.add("media_items", {k: contextual[k] for k in ("id", "blob_id", "name", "modality", "registered_by")})
                media = contextual
            output_producers[media["id"]] = op_id
            outputs.append((ref, media))
            p.add("operation_outputs", {"operation_id": op_id, "media_id": media["id"], "role": str(ref.get("asset_kind") or kind), "ordinal": ordinal}, (record_key, ordinal))
            p.add("media_sources", {"media_id": media["id"], "source_id": source["key"]["id"], "role": "generation_output",
                "citation": {"path": ref["path"], "sha256": ref["sha256"], "original_uri": ref.get("source_url"), "record_paths": paths}}, (record_key, ordinal))
        record_outputs[record_key] = outputs
        target_code = doc.get("shot_id")
        target = p.ids.get("objects:" + str(target_code)) if p.objects.get(target_code, {}).get("kind") == "shot" else None
        target_kind = "shot" if target else None
        contexts = producers.get(record_key, [])
        task = tasks.get(record_key)
        binding = task["document"]["binding"] if task else None
        complete = bool(target and binding and M._digest(binding) == engine.get("request_sha256") and engine.get("model") and original_artifacts and contexts)
        if not complete:
            p.manifest["preparation"]["legacy_unbound"].append({"record_paths": paths, "record_sha256": p.files[source_path]["sha256"],
                "reason": "没有真实镜头目标或完整固定请求证据", "scheduling_eligible": False})
        else:
            provider = str(engine.get("provider"))
            p.add("providers", {"id": provider, "name": provider, "modality": "multimodal", "base_url": "", "auth_ref": "legacy-unconfigured", "enabled": False, "rate_limit": {}})
            version = str(engine.get("version") or "legacy-unversioned")
            modality = "audio" if kind == "speech" else kind
            model_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "legacy-model:" + M._json([provider, engine["model"], version, modality])))
            p.add("provider_models", {"id": model_id, "provider_id": provider, "model_key": engine["model"], "modality": modality,
                "model_version": version, "capabilities": {"historical_only": True}, "default_params": {}, "cost_rule": {}, "enabled": False})
            run_id = p.ids["artifacts:" + contexts[0]["run_id"]]
            purpose = str(doc.get("purpose") or "legacy_generation")
            candidate_key = run_id, target, purpose
            number = counters[candidate_key]
            counters[candidate_key] += 1
            job_id = p.ident("jobs", record_key)
            request = {"legacy_request": binding, "legacy_record_sha256": p.files[source_path]["sha256"], "historical_only": True}
            job = {"id": job_id, "run_version_id": run_id, target_kind + "_id": target, "purpose": purpose, "modality": modality,
                "candidate_no": number, "provider_id": provider, "model_id": model_id, "model_version": version,
                "external_task_id": engine.get("task_id"), "request_payload": request, "request_sha256": M._digest(request),
                "context_sha256": doc.get("inputs", {}).get("anchors_sha256") or M._digest(binding),
                "idempotency_key": "legacy:" + p.target + ":" + record_key, "status": doc.get("status", "submission_unknown"),
                "attempt": max((c.get("journal_entry", {}).get("attempts", 0) for c in contexts), default=0), "raw_response": task["document"]}
            if job["status"] not in {"created", "submitted", "running", "succeeded", "failed", "submission_unknown", "cancelled"}:
                job["status"] = "submission_unknown"
            p.add("generation_jobs", job)
            job_ids[record_key] = job_id
            p.add("job_events", {"job_id": job_id, "event_type": "legacy_import", "evidence": {"record_paths": paths, "task_path": task["path"], "historical_only": True}}, record_key)
            for ordinal, ref in enumerate(inputs):
                media = p.fixed(ref["path"], ref["sha256"])
                if media:
                    p.add("job_input_media", {"job_id": job_id, "media_id": media["id"], "blob_id": media["blob_id"], "blob_sha256": media["sha256"],
                        "role": str(ref.get("role") or "reference"), "ordinal": ordinal}, (record_key, ordinal))
            fixed_versions = list(doc.get("inputs", {}).get("basis_artifacts", []))
            for context in contexts:
                fixed_versions.extend(context["run"].get("approved_inputs", []))
            for ref in fixed_versions:
                if isinstance(ref, dict) and ref.get("id") in p.artifacts:
                    artifact = p.artifacts[ref["id"]]
                    if artifact["sha256"] != ref.get("sha256"):
                        p.problem("job_input_sha_mismatch", source_path, "生成任务输入版本SHA不符")
                    else:
                        p.add("job_input_versions", {"job_id": job_id, "artifact_id": artifact["id"], "sha256": artifact["sha256"], "role": "legacy_input"}, (record_key, artifact["id"]))
            for ref, media in outputs:
                p.add("job_outputs", {"job_id": job_id, "media_id": media["id"], "asset_type": media["modality"], "original_uri": ref.get("source_url")}, (record_key, media["id"]))
    # Asset bible references are proposals with exact spec/version provenance.
    # A named reference or an approved bible is not a final take selection.
    for old, doc in p.documents.items():
        if doc.get("format") != "vsc.asset-bible/v1" or old not in p.artifacts:
            continue
        for entity in doc.get("entities", []) + doc.get("styles", []):
            target = p.ids.get("objects:" + str(entity.get("id")))
            if not target:
                continue
            for ordinal, ref in enumerate(entity.get("references", [])):
                media = p.fixed(ref.get("path"), ref.get("sha256"))
                if not media:
                    continue
                role = "legacy_reference:" + str(ref.get("purpose") or "unspecified")
                slot_key = "asset-reference:" + str(entity["id"]) + ":" + str(ref.get("plan_id") or ordinal)
                _candidate(p, target, role, slot_key, media, p.artifacts[old]["id"])
    # Preserve human production review separately from final selection.
    for index, review in enumerate(p.state.get("production_reviews", [])):
        old = review.get("run_id")
        if old not in p.artifacts or p.artifacts[old]["sha256"] != review.get("run_sha256"):
            p.problem("review_run_mismatch", "production_reviews:" + str(index), "人工审核没有匹配原固定运行包")
            continue
        related = [(key, c) for key, contexts in producers.items() for c in contexts
                   if c["run_id"] == old and c["job"].get("id") == review.get("job_id")]
        context = related[0][1] if related else None
        target_code = context["job"].get("args", {}).get("shot") if context else None
        target = p.ids.get("objects:" + str(target_code)) or p.ids.get("objects:" + str(p.work_code))
        if not target:
            p.problem("review_scope_unmapped", "production_reviews:" + str(index), "项目范围审核需要明确技术审核容器")
            continue
        if not review.get("by") or review.get("outcome") not in {"accepted", "rejected"}:
            p.problem("review_evidence_missing", "production_reviews:" + str(index), "人工审核缺少原操作人或结论")
            continue
        for path, sha in review.get("outputs_sha256", {}).items():
            media = p.fixed(path, sha)
            if not media:
                continue
            slot_key = str(old) + ":" + str(review.get("job_id"))
            slot, candidate = _candidate(p, target, "legacy_review", slot_key, media, p.artifacts[old]["id"], review["run_sha256"])
            p.add("media_reviews", {"candidate_id": candidate["key"]["id"], "reviewer": review["by"], "reviewer_type": "human",
                "criteria_version": "legacy-production-review/v1", "context_sha256": review["run_sha256"],
                "outcome": "pass" if review["outcome"] == "accepted" else "fail", "reason": review.get("reason", ""),
                "evidence": {"legacy_review": review, "legacy_review_index": index, "legacy_scope": "project" if not target_code else target_code,
                    "execution_eligible": False, "journal": context.get("journal_entry") if context else None},
                "project_revision": p.snapshot["source"]["revision"], **({"created_at": review["at"]} if review.get("at") else {})}, (index, path))
    p.manifest["preparation"]["generation_records"] = {"unique": len(records), "typed_jobs": len(job_ids),
        "operations": len(p.operations), "registered": sum(1 for a in p.state.get("artifacts", []) if a["type"] == "vsc.generation_record")}
