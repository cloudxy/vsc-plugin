"""Project-local post evidence mapped to historical, non-executable relations.

Inputs, outputs and draft uses come from explicit document fields and hashes.
This adapter never selects a take, approves a review, clears rights, or freezes a
timeline. Relative manuscript paths follow that manifest's documented package
root; no shot, source, or purpose is inferred from a file name.
"""
from collections import Counter
from pathlib import Path

from vsc.project import migration as M
from vsc.project.migration_prepare import _document


class PostRelations:
    def __init__(self, preparation):
        self.p = preparation
        self.documents = {}
        for path, file in self.p.files.items():
            if Path(path).suffix.lower() == ".json" and file["size_bytes"] <= 64 * 1024 * 1024:
                self.documents[path] = _document(M._safe(self.p.project, path))
        self.counts = Counter()
        self.sources = {}

    def evidence(self, path, sha=None):
        p = self.p
        media = p.fixed(path, sha or p.files.get(path, {}).get("sha256"))
        if not media:
            return None
        key = path, media["sha256"]
        if key not in self.sources:
            self.sources[key] = p.add("source_versions", {
                "source_key": "legacy.post:" + str(path), "version": 1,
                "kind": "legacy-post-evidence", "sha256": media["sha256"],
                "document": {"legacy_file": media.get("resolved_path", path)}, "evidence_uri": path}, key)["key"]["id"]
        return self.sources[key]

    def link(self, media, path, role, citation=None, sha=None):
        source = self.evidence(path, sha)
        if source:
            self.p.add("media_sources", {"media_id": media["id"], "source_id": source, "role": role,
                "citation": dict(citation or {}, evidence_path=path, rights="unknown", historical_only=True)},
                (media["id"], source, role, M._digest(citation or {})))

    def fixed(self, path, sha):
        if not isinstance(path, str) or not isinstance(sha, str) or len(sha) != 64:
            self.p.problem("post_reference_unfixed", str(path), "后期关系必须明确原路径与完整SHA")
            return None
        return self.p.fixed(path, sha)

    def operation(self, path, document, kind, executed=False, variant=None):
        sha = self.p.files[path]["sha256"]
        operation = self.p.add("media_operations", {"operation_type": kind,
            "recipe_version": document["format"], "tool": "legacy-local-post",
            "tool_version": str(document.get("versions", {}).get("Pillow") or "legacy-unrecorded"),
            "parameters": {"document": document, "evidence_path": path, "evidence_sha256": sha},
            "status": "succeeded" if executed else "created",
            "execution": {"historical_only": True, "original_status": document.get("status"),
                "execution_eligible": False, "human_review": document.get("human_review"),
                "selection": document.get("selection"), "approval": document.get("approval")}}, (kind, path, sha, variant))
        self.counts[kind] += 1
        return operation["key"]["id"]

    def input(self, operation, media, role, ordinal, transform=None):
        self.p.add("operation_inputs", {"operation_id": operation, "media_id": media["id"],
            "role": role, "layer_order": ordinal, "transform": transform or {}, "opacity": 1},
            (operation, ordinal))

    def output(self, operation, media, ordinal, evidence):
        # One project registration has one derivation. A distinct recorded
        # execution retains a separate registration while sharing its bytes.
        occupied = any(row["media_id"] == media["id"] and row["operation_id"] != operation
            for row in self.p.tables.get("operation_outputs", []))
        if occupied:
            media = dict(media, id=self.p.ident("post_media", (operation, media["id"])))
            self.p.add("media_items", {k: media[k] for k in ("id", "blob_id", "name", "modality", "registered_by")})
        self.p.add("operation_outputs", {"operation_id": operation, "media_id": media["id"],
            "role": "legacy_post_candidate", "ordinal": ordinal}, (operation, ordinal))
        self.link(media, evidence, "legacy_post_output")
        return media

    def candidate(self, target_code, role, slot_key, media, evidence, spec=None):
        p = self.p
        target = p.ids.get("objects:" + str(target_code))
        if not target or p.objects.get(target_code, {}).get("kind") != "shot":
            p.manifest["preparation"].setdefault("legacy_post_unbound", []).append({
                "evidence_path": evidence, "target_code": target_code, "media_id": media["id"],
                "reason": "no_fixed_shot_identity", "execution_eligible": False})
            return
        slot = p.add("binding_slots", {"target_object_id": target, "role": role, "slot_key": slot_key}, (target, role, slot_key))
        p.add("binding_candidates", {"slot_id": slot["key"]["id"], "media_id": media["id"],
            "spec_version_id": spec, "context_sha256": p.files[evidence]["sha256"], "proposer": p.actor},
            (slot["key"]["id"], media["id"], spec))
        self.counts["draft_candidates"] += 1

    def source_inventory(self, path, document):
        for item in document.get("sources", document.get("source_inventory", [])):
            media = self.fixed(item.get("path"), item.get("sha256"))
            if not media:
                continue
            self.link(media, path, "legacy_sound_inventory", item)
            for field, role in (("license_evidence", "legacy_license_evidence"), ("source_record", "legacy_source_record")):
                ref = item.get(field)
                if isinstance(ref, dict) and ref.get("path") and ref.get("sha256"):
                    self.link(media, ref["path"], role, {"source_id": item.get("id"),
                        "license_status": item.get("license_status"), "human_listened": item.get("human_listened")}, ref["sha256"])
            self.counts["sound_sources"] += 1

    @staticmethod
    def package_path(manifest, relative):
        return (Path(manifest).parent / relative).as_posix()

    def manuscript(self, path, document):
        inputs = []
        for field in ("source_texture", "font", "basis_bible"):
            ref = document.get(field, {})
            if isinstance(ref, dict) and ref.get("path") and ref.get("sha256"):
                media = self.fixed(ref["path"], ref["sha256"])
                if media:
                    inputs.append((field, media, {}))
        script = document.get("script", {})
        if script.get("path") and script.get("sha256"):
            media = self.fixed(self.package_path(path, script["path"]), script["sha256"])
            if media:
                inputs.append(("recipe_script", media, {}))
        outputs = []
        for ref in document.get("files", []):
            media = self.fixed(self.package_path(path, ref["path"]), ref.get("sha256"))
            if media:
                outputs.append(media)
        if not outputs:
            return
        op = self.operation(path, document, "legacy_manuscript_assets", executed=True)
        for ordinal, (role, media, transform) in enumerate(inputs):
            self.input(op, media, role, ordinal, transform)
        for ordinal, media in enumerate(outputs):
            self.output(op, media, ordinal, path)
        font = document.get("font", {})
        if font.get("license_path") and font.get("license_sha256"):
            for media in outputs:
                self.link(media, font["license_path"], "legacy_font_license", {
                    "license_recorded": font.get("license_recorded"), "rights_status": font.get("rights_status", "unknown")},
                    font["license_sha256"])

    def paper(self, path, document):
        config_paths = [key for key, doc in self.documents.items() if doc.get("format") == "vsc.paper-composite-config/draft-v1"
            and self.p.files[key]["sha256"] == document.get("config_sha256")]
        if not config_paths:
            self.p.problem("post_config_missing", path, "纸张合成缺少固定SHA的原配方")
            return
        config_path = sorted(config_paths)[0]
        config = self.documents[config_path]
        if (config.get("source"), config.get("source_sha256"), config.get("shot_id")) != (
                document.get("source"), document.get("source_sha256"), document.get("shot_id")):
            self.p.problem("post_config_mismatch", path, "合成配方、原片与镜头证据不一致")
            return
        source = self.fixed(document.get("source"), document.get("source_sha256"))
        output = self.fixed(document.get("output"), document.get("output_sha256"))
        if not source or not output:
            return
        overlays = {}
        for manifest_path, manifest in self.documents.items():
            if manifest.get("format") != "vsc.manuscript-local-production-assets/v1":
                continue
            if config.get("reveal_movie") not in {r.get("path") for r in manifest.get("reveal_movies", [])}:
                continue
            for ref in manifest.get("files", []):
                if ref.get("path") == config["reveal_movie"]:
                    overlay_path = self.package_path(manifest_path, ref["path"])
                    overlays[overlay_path, ref.get("sha256")] = ref
        if len(overlays) != 1:
            self.p.problem("post_overlay_unmapped", path, "合成字层须由唯一固定素材包明确引用，不能按文件名猜测")
            return
        overlay_path, overlay_sha = next(iter(overlays))
        overlay = self.fixed(overlay_path, overlay_sha)
        config_media = self.p.fixed(config_path, document["config_sha256"])
        if not overlay or not config_media:
            return
        op = self.operation(path, document, "legacy_paper_composite", executed=True)
        self.input(op, source, "base_video", 0)
        self.input(op, overlay, "paper_lettering", 1, {"paper_keyframes": config.get("paper_keyframes", []),
            "hand_keyframes": config.get("hand_keyframes", []), "pen_keyframes": config.get("pen_keyframes", [])})
        self.input(op, config_media, "recipe_evidence", 2)
        result = self.output(op, output, 0, path)
        self.candidate(document.get("shot_id"), "legacy_post_paper", "paper:" + path, result, path)

    def visual(self, path, document):
        for ordinal, slot in enumerate(document.get("slots", [])):
            refs = list(slot.get("candidate_inventory_only") or [])
            if isinstance(slot.get("local_title_candidate_only"), dict):
                refs.append({"media": slot["local_title_candidate_only"]})
            for index, item in enumerate(refs):
                ref = item.get("media", {})
                if not ref.get("path") or not ref.get("sha256"):
                    continue
                media = self.fixed(ref["path"], ref["sha256"])
                if not media:
                    continue
                artifact = self.p.artifacts.get(item.get("artifact_id"))
                if item.get("artifact_id") and (not artifact or artifact["sha256"] != item.get("artifact_sha256")):
                    self.p.problem("post_candidate_spec_mismatch", path, "草稿候选的固定产物版本不符")
                    continue
                self.candidate(slot.get("shot_id"), "legacy_post_visual", "visual:%s:%s" % (path, ordinal),
                    media, path, artifact["id"] if artifact else None)
                self.link(media, path, "legacy_post_proposal", {"slot_ordinal": ordinal,
                    "candidate_ordinal": index, "draft_slot": slot, "formal_selection_created": False})

    def audio_plan(self, path, document):
        handoff = self.fixed(document.get("source_handoff"), document.get("source_handoff_sha256"))
        if not handoff:
            return
        handoff_path = handoff.get("resolved_path", document["source_handoff"])
        inventory = self.documents.get(handoff_path, {}).get("source_inventory", [])
        by_id = {}
        for ref in inventory:
            if ref.get("id") in by_id and by_id[ref["id"]] != ref:
                self.p.problem("post_sound_source_ambiguous", path, "同一逻辑声源有冲突的固定输入")
                return
            by_id[ref.get("id")] = ref
        op = self.operation(path, document, "legacy_audio_edit_plan")
        for ordinal, layer in enumerate(document.get("layers", [])):
            ref = by_id.get(layer.get("source_id"))
            if not ref:
                self.p.problem("post_sound_source_missing", path, "声音层没有声明于固定执行映射的源素材")
                continue
            media = self.fixed(ref.get("path"), ref.get("sha256"))
            if media:
                self.input(op, media, "legacy_post_audio", ordinal, layer)
                self.link(media, path, "legacy_audio_proposal", {"layer_ordinal": ordinal, "layer": layer})
                self.counts["audio_layers"] += 1

    def audio_derivative(self, path, document):
        fmt = document["format"]
        if fmt == "vsc.speech-edit-candidates/draft-v1":
            items = document.get("items", [])
        else:
            items = [{"source_layers": document.get("layers", []), "derivative": document.get("path"),
                "derivative_sha256": document.get("sha256")}]
        for index, item in enumerate(items):
            output = self.fixed(item.get("derivative"), item.get("derivative_sha256"))
            if not output:
                continue
            refs = item.get("source_layers", [{"path": item.get("source"), "sha256": item.get("source_sha256")}])
            inputs = [(ref, self.fixed(ref.get("path"), ref.get("sha256"))) for ref in refs]
            if not inputs or any(media is None for _, media in inputs):
                continue
            operation_doc = dict(document, item_ordinal=index)
            op = self.operation(path, operation_doc, "legacy_audio_derivative", executed=True, variant=index)
            for ordinal, (ref, media) in enumerate(inputs):
                self.input(op, media, "legacy_audio_source", ordinal, ref)
            self.output(op, output, 0, path)

    def run(self):
        # Package derivations precede tracked composites, so lineage naturally
        # connects textures/fonts to letter layers and then to candidate video.
        order = {"vsc.manuscript-local-production-assets/v1": 0, "vsc.paper-tracking-proof/draft-v1": 1}
        seen = set()
        for path, document in sorted(self.documents.items(), key=lambda pair: (order.get(str(pair[1].get("format")), 2), pair[0])):
            fmt = document.get("format")
            if not isinstance(fmt, str):
                continue
            token = fmt, self.p.files[path]["sha256"]
            if token in seen:
                continue
            seen.add(token)
            if fmt in {"local.sound-source-inventory/v1", "local.sound-edit-handoff/v1"}:
                self.source_inventory(path, document)
            elif fmt == "vsc.manuscript-local-production-assets/v1":
                self.manuscript(path, document)
            elif fmt == "vsc.paper-tracking-proof/draft-v1":
                self.paper(path, document)
            elif fmt == "vsc.project-local-edit-bindings/draft-v1":
                self.visual(path, document)
            elif fmt == "vsc.local-resolved-sound-edits/draft-v1":
                self.audio_plan(path, document)
            elif fmt in {"vsc.speech-edit-candidates/draft-v1", "vsc.local-audio-review-candidate/draft-v1"}:
                self.audio_derivative(path, document)
        self.p.manifest["preparation"]["post_relations"] = dict(self.counts)


def prepare_post_relations(preparation):
    PostRelations(preparation).run()
