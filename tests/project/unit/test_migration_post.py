"""Post migration projects fixed evidence, preserving draft and rights boundaries."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import uuid

from vsc.project.migration_post import prepare_post_relations


class PreparationFixture:
    def __init__(self, root):
        self.project = root.resolve()
        self.actor = "migration-operator"
        self.target = str(uuid.uuid4())
        self.files, self.media, self.tables, self.ids = {}, {}, {}, {}
        self.documents, self.artifacts, self.operations = {}, {}, {}
        self.objects = {"H1": {"kind": "shot"}}
        self.ids["objects:H1"] = str(uuid.uuid4())
        self.manifest = {"preparation": {}}
        self.blockers = []

    def ident(self, domain, key):
        return str(uuid.uuid5(uuid.UUID(self.target), domain + ":" + str(key)))

    def add(self, table, row, key=None):
        row = dict(row)
        row.setdefault("project_id", self.target)
        row.setdefault("id", self.ident(table, key if key is not None else json.dumps(row, sort_keys=True)))
        existing = next((r for r in self.tables.get(table, []) if r["id"] == row["id"]), None)
        if existing is not None:
            if row != existing:
                raise AssertionError("conflicting fixture fact")
        else:
            self.tables.setdefault(table, []).append(row)
        return {"table": table, "key": {"project_id": self.target, "id": row["id"]}}

    def problem(self, code, evidence, message):
        self.blockers.append({"code": code, "evidence": evidence, "message": message})

    def fixed(self, path, sha=None):
        media = self.media.get(path)
        if not media or sha and media["sha256"] != sha:
            self.problem("missing_fixed_file", str(path), "missing bytes")
            return None
        return media

    def file(self, path, value):
        raw = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True).encode()
        destination = self.project / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
        sha = hashlib.sha256(raw).hexdigest()
        self.files[path] = {"sha256": sha, "size_bytes": len(raw)}
        self.media[path] = {"id": self.ident("media", path), "blob_id": self.ident("blob", sha),
            "name": path, "modality": "audio" if path.endswith(".wav") else "video" if path.endswith((".mp4", ".mov")) else "document",
            "sha256": sha, "registered_by": self.actor}
        return {"path": path, "sha256": sha}


class PostMigrationTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.p = PreparationFixture(Path(temporary.name))

    def no_approvals(self):
        for table in ("rights_decisions", "media_reviews", "binding_decisions", "current_bindings", "timeline_versions", "render_versions"):
            self.assertFalse(self.p.tables.get(table), table)

    def paper_package(self, root="package"):
        texture = self.p.file("texture.png", b"original texture")
        font = self.p.file("font.ttf", b"font")
        license_ref = self.p.file("OFL.txt", b"license evidence only")
        script = self.p.file(root + "/build.py", b"# fixed recipe")
        overlay = self.p.file(root + "/reveal/title.mov", b"alpha overlay")
        doc = {"format": "vsc.manuscript-local-production-assets/v1", "status": "unselected",
            "source_texture": texture, "font": dict(font, license_path=license_ref["path"], license_sha256=license_ref["sha256"], rights_status="unknown"),
            "script": dict(script, path="build.py"), "files": [dict(overlay, path="reveal/title.mov")],
            "reveal_movies": [{"path": "reveal/title.mov"}], "selection": None, "human_review": "not_performed"}
        self.p.file(root + "/production-manifest.json", doc)
        return overlay

    def paper_proof(self):
        source = self.p.file("source.mp4", b"original scene")
        output = self.p.file("proof.mp4", b"tracked proof")
        config = {"format": "vsc.paper-composite-config/draft-v1", "shot_id": "H1", "source": source["path"],
            "source_sha256": source["sha256"], "reveal_movie": "reveal/title.mov", "paper_keyframes": [{"frame": 0, "quad_px": [0, 1]}],
            "hand_keyframes": [], "pen_keyframes": []}
        config_ref = self.p.file("paper/config.json", config)
        evidence = {"format": "vsc.paper-tracking-proof/draft-v1", "shot_id": "H1", "source": source["path"],
            "source_sha256": source["sha256"], "output": output["path"], "output_sha256": output["sha256"],
            "config_sha256": config_ref["sha256"], "selection": None, "approval": None, "human_review": False,
            "frames": [{"source_frame": 1, "homography": [1, 0, 0]}]}
        self.p.file("paper/proof.json", evidence)
        return source, output

    def test_fixed_paper_chain_preserves_bytes_and_unknown_font_rights(self):
        overlay = self.paper_package()
        source, output = self.paper_proof()
        before = {path: (self.p.project / path).read_bytes() for path in self.p.files}
        prepare_post_relations(self.p)
        self.assertEqual(self.p.blockers, [])
        operations = self.p.tables["media_operations"]
        self.assertEqual({row["operation_type"] for row in operations}, {"legacy_manuscript_assets", "legacy_paper_composite"})
        proof = next(row for row in operations if row["operation_type"] == "legacy_paper_composite")
        inputs = [row for row in self.p.tables["operation_inputs"] if row["operation_id"] == proof["id"]]
        self.assertEqual([row["role"] for row in inputs], ["base_video", "paper_lettering", "recipe_evidence"])
        self.assertEqual(inputs[1]["media_id"], self.p.media[overlay["path"]]["id"])
        self.assertEqual(self.p.tables["binding_slots"][0]["role"], "legacy_post_paper")
        font_links = [row for row in self.p.tables["media_sources"] if row["role"] == "legacy_font_license"]
        self.assertTrue(font_links)
        self.assertEqual(font_links[0]["citation"]["rights"], "unknown")
        self.assertEqual(before, {path: (self.p.project / path).read_bytes() for path in self.p.files})
        self.no_approvals()

    def test_license_and_generation_evidence_are_independent_of_human_review(self):
        audio = self.p.file("speech.wav", b"speech")
        license_ref = self.p.file("license.json", {"statement": "unknown commercial clearance"})
        generation = self.p.file("record.json", {"format": "vsc.generation-record/v1"})
        self.p.file("inventory.json", {"format": "local.sound-source-inventory/v1", "sources": [dict(audio,
            id="SRC1", license_status="unknown", license_evidence=license_ref, source_record=generation, human_listened=False)]})
        prepare_post_relations(self.p)
        self.assertEqual({r["role"] for r in self.p.tables["media_sources"]}, {
            "legacy_sound_inventory", "legacy_license_evidence", "legacy_source_record"})
        self.assertEqual(len(self.p.tables["source_versions"]), 3)
        self.no_approvals()

    def test_audio_plan_preserves_repeated_layers_without_claiming_an_output(self):
        audio = self.p.file("source.wav", b"source")
        handoff = self.p.file("handoff.json", {"format": "local.sound-edit-handoff/v1", "source_inventory": [dict(audio, id="SRC")]})
        self.p.file("edit.json", {"format": "vsc.local-resolved-sound-edits/draft-v1", "source_handoff": handoff["path"],
            "source_handoff_sha256": handoff["sha256"], "layers": [{"source_id": "SRC", "gain_db": -4}, {"source_id": "SRC", "gain_db": -9}],
            "selected_takes": None})
        # Real inventories also contain ffprobe's object-valued "format" field.
        self.p.file("probe.json", {"format": {"filename": "source.wav"}})
        prepare_post_relations(self.p)
        inputs = self.p.tables["operation_inputs"]
        self.assertEqual([r["layer_order"] for r in inputs], [0, 1])
        self.assertEqual(inputs[0]["media_id"], inputs[1]["media_id"])
        self.assertNotEqual(inputs[0]["transform"], inputs[1]["transform"])
        self.assertEqual(self.p.tables["media_operations"][0]["status"], "created")
        self.assertFalse(self.p.tables.get("operation_outputs"))
        self.no_approvals()

    def test_visual_draft_uses_only_explicit_shot_and_never_selects(self):
        media = self.p.file("candidate.mp4", b"candidate")
        self.p.file("bindings.json", {"format": "vsc.project-local-edit-bindings/draft-v1", "slots": [
            {"shot_id": "H1", "candidate_inventory_only": [{"media": media, "selected": True}], "selected_item_id": "old-label"},
            {"shot_id": "UNKNOWN", "candidate_inventory_only": [{"media": media}]}]})
        prepare_post_relations(self.p)
        self.assertEqual(len(self.p.tables["binding_candidates"]), 1)
        self.assertEqual(self.p.tables["binding_slots"][0]["role"], "legacy_post_visual")
        self.assertEqual(len(self.p.manifest["preparation"]["legacy_post_unbound"]), 1)
        self.assertEqual(set(self.p.objects), {"H1"})
        self.no_approvals()

    def test_speech_derivative_and_mix_keep_exact_inputs_and_multiple_output_provenance(self):
        source = self.p.file("speech.wav", b"original")
        derivative = self.p.file("edited.wav", b"edited")
        mixed = self.p.file("mixed.wav", b"mix")
        self.p.file("speech-edits.json", {"format": "vsc.speech-edit-candidates/draft-v1", "items": [{
            "source": source["path"], "source_sha256": source["sha256"], "derivative": derivative["path"], "derivative_sha256": derivative["sha256"], "segments": []}]})
        self.p.file("mix.json", {"format": "vsc.local-audio-review-candidate/draft-v1", **mixed,
            "layers": [dict(derivative, start_sample=0), dict(derivative, start_sample=100)], "human_review": False})
        prepare_post_relations(self.p)
        self.assertEqual(self.p.blockers, [])
        self.assertEqual(len(self.p.tables["media_operations"]), 2)
        self.assertEqual(len(self.p.tables["operation_inputs"]), 3)
        self.assertEqual(len(self.p.tables["operation_outputs"]), 2)
        self.no_approvals()

    def test_ambiguous_overlay_and_missing_source_hash_do_not_create_derivation(self):
        self.paper_package("first")
        self.paper_package("second")
        self.paper_proof()
        self.p.file("mix.json", {"format": "vsc.local-audio-review-candidate/draft-v1",
            **self.p.file("mixed.wav", b"candidate"), "layers": [{"path": "texture.png"}]})
        prepare_post_relations(self.p)
        self.assertTrue({"post_overlay_unmapped", "post_reference_unfixed"} <= {r["code"] for r in self.p.blockers})
        self.assertFalse(any(row["operation_type"] in {"legacy_paper_composite", "legacy_audio_derivative"}
            for row in self.p.tables["media_operations"]))
        self.no_approvals()


if __name__ == "__main__":
    unittest.main()
