"""Synthetic relational project fixture, with explicit test human decisions."""
from io import BytesIO
import struct
import uuid
import zlib


def png_bytes():
    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"\x00" + b"\x30\x70\x60" * 2 + b"\x00" + b"\x30\x70\x60" * 2)) + chunk(b"IEND", b"")


class ResourceFixture:
    def __init__(self, service, profile_snapshot=None):
        self.service = service
        profile_snapshot = profile_snapshot or {"profile_id": "vsc.synthetic", "version": "1", "stages": []}
        self.p = service.create_project({"name": "合成离线制作样本", "profile": profile_snapshot["profile_id"],
            "profile_snapshot": profile_snapshot}, actor="fixture-human")["id"]
        self.objects = {}
        parent = None
        for kind in ("work", "episode", "scene", "sequence", "shot"):
            row = self.write("create_object", {"kind": kind, "parent_id": parent, "display_code": kind.upper(), "ordinal": 0})
            parent = self.objects[kind] = row["id"]
        self.artifact("shot-spec", "shot-plan", {"spec": "固定镜头规格"})
        self.artifact("scene-state", "scene-state", {"state_versions": [{"scene_id": self.objects["scene"], "shot_id": self.objects["shot"], "entities": []}]})

    def write(self, action, payload, key=None):
        return getattr(self.service, action)(self.p, payload,
            expected_revision=self.service.get_project(self.p)["revision"],
            idempotency_key=key or uuid.uuid4().hex, actor="fixture-human")

    def artifact(self, key, kind, document, dependency_ids=None):
        payload = {"artifact_key": key, "artifact_type": kind, "document": document, "dependency_ids": dependency_ids or []}
        for field in ("script_lines", "asset_specs", "state_versions", "line_coverage", "voice_specs", "voice_bindings"):
            if field in document:
                payload[field] = document[field]
        artifact = self.write("create_artifact", payload)
        self.write("decide_artifact", {"artifact_id": artifact["id"], "reason": "合成测试中模拟的明确人工决定"})
        return artifact["id"]

    def select_media(self, media_id, role, target=None):
        media = self.service.get_media(self.p, media_id)
        self.write("decide_rights", {"media_id": media_id, "source_id": media["sources"][0]["source_id"],
            "outcome": "owned", "scope": {"purposes": ["*"]}, "reason": "本地合成夹具拥有字节权利"})
        self.write("record_media_check", {"media_id": media_id, "checker": "ffmpeg-fixture", "criteria_version": "1", "outcome": "pass"})
        candidate = self.write("propose_binding", {"target_object_id": target or self.objects["shot"], "media_id": media_id, "role": role, "slot_key": "main"})
        self.write("record_review", {"candidate_id": candidate["candidate_id"], "outcome": "pass", "reviewer_type": "human", "reason": "合成测试模拟选择"})
        decision = self.write("select_candidate", {"candidate_id": candidate["candidate_id"], "reason": "合成测试模拟人工选择"})
        return dict(candidate, decision_id=decision["id"])

    def job(self, modality, purpose, model_id, request=None, candidate_no=0):
        context = self.service.compile_shot_context(self.p, self.objects["shot"], purpose)
        assert context["ready"], context["gaps"]
        request = dict({"shot_id": self.objects["shot"], "purpose": purpose, "modality": modality,
                        "prompt": "合成离线测试", "params": {}, "reference_media_ids": []}, **(request or {}))
        pins = [{"id": row["id"], "sha256": row["sha256"]} for row in context["artifacts"]]
        run = self.artifact("run-" + uuid.uuid4().hex, "production-run", {"approved_inputs": pins,
            "series_batch": {"jobs": [{"candidate_no": candidate_no, "request": request}]}}, [row["id"] for row in pins])
        context = self.service.compile_shot_context(self.p, self.objects["shot"], purpose)
        return self.write("create_generation_job", {"shot_id": self.objects["shot"], "purpose": purpose,
            "modality": modality, "model_id": model_id, "run_version_id": run, "candidate_no": candidate_no,
            "request_payload": request, "context_sha256": context["sha256"]})
