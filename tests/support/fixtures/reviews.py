"""Reusable synthetic review seeds; no live host or media provider invocation."""
from io import BytesIO
import json
import uuid
import wave

from support.paths import ROOT
from support.fixtures.resources import ResourceFixture, png_bytes


def audio_bytes(value=0):
    stream = BytesIO()
    with wave.open(stream, "wb") as writer:
        writer.setnchannels(1); writer.setsampwidth(2); writer.setframerate(24000)
        writer.writeframes(int(value).to_bytes(2, "little", signed=True) * 2400)
    return stream.getvalue()


class OfflineAudio:
    def __init__(self, content):
        self.content = content
    def submit(self, request):
        from vsc.production.providers import JobHandle
        return JobHandle("fixture", "offline", None, {"offline": True})
    def poll(self, handle):
        from vsc.production.providers import JobStatus
        return JobStatus("succeeded", raw=handle.raw)
    def parse_result(self, raw):
        from vsc.production.providers import GeneratedAsset
        return [GeneratedAsset("audio", inline_bytes=self.content)]


def register_owned_bytes(fixture, data, name, modality):
    staged = fixture.service.storage.stage_upload(BytesIO(data), name)
    return fixture.write("register_media", {"staged_upload": staged["staged_upload"], "name": name,
        "modality": modality, "rights": "unknown", "source": {"kind": "synthetic_test", "content": "owned generated fixture bytes"}})["id"]


def seed_sound_review_source(service, fixture):
    """Use the existing real dialogue prerequisites, then execute an offline WAV take."""
    from vsc.production.resource_worker import ResourceWorker
    character = fixture.write("create_object", {"kind": "asset", "asset_kind": "character", "display_code": "REVIEW-CHAR"})["id"]
    voice = fixture.write("create_object", {"kind": "asset", "asset_kind": "voice", "display_code": "REVIEW-VOICE"})["id"]
    for target, role, data, name, modality in ((character, "identity_face", png_bytes(), "review-face.png", "image"),
            (voice, "voice_sample", audio_bytes(), "review-voice.wav", "audio")):
        media = register_owned_bytes(fixture, data, name, modality)
        fixture.select_media(media, role, target)
    line, voice_spec = str(uuid.uuid4()), str(uuid.uuid4())
    script = fixture.artifact("review-audio-script", "screenplay", {"script_lines": [{"id": line,
        "scene_id": fixture.objects["scene"], "speaker_id": character, "line_key": "L001", "text": "Synthetic line"}]})
    fixture.artifact("review-audio-coverage", "coverage-plan", {"line_coverage": [{"shot_id": fixture.objects["shot"],
        "line_id": line, "start_char": 0, "end_char": len("Synthetic line")}]}, [script])
    fixture.artifact("review-audio-voice", "voice-spec", {"voice_specs": [{"id": voice_spec, "voice_id": voice}],
        "voice_bindings": [{"character_id": character, "voice_spec_id": voice_spec}]})
    service.register_provider({"id": "fixture", "base_url": "https://example.invalid", "auth_ref": "OFFLINE_KEY"}, actor="fixture-human")
    model = service.register_model({"provider_id": "fixture", "model_key": "review-audio-" + uuid.uuid4().hex,
        "model_version": "1", "modality": "audio", "capabilities": {"purposes": ["dialogue_dry"]},
        "default_params": {"voice_map": {voice: {"engine": "fixture", "voice": "voice"}}}}, actor="fixture-human")["id"]
    request = {"prompt": "Synthetic line", "script_line_ids": ["L001"]}
    job = fixture.job("audio", "dialogue_dry", model, request)
    ResourceWorker(service, lambda job, service: OfflineAudio(audio_bytes())).run_once(fixture.p)
    current = service.get_generation_job(fixture.p, job["id"])
    if current["status"] != "succeeded":
        raise AssertionError("offline audio fixture did not produce bytes")
    media = current["outputs"][0]["media_id"]
    from sqlalchemy import select
    from vsc.adapters.persistence.postgres import schema as S
    with service.store.engine.connect() as conn:
        coverage = conn.execute(select(S.shot_line_coverage.c.id).where(S.shot_line_coverage.c.project_id == fixture.p,
            S.shot_line_coverage.c.shot_id == fixture.objects["shot"], S.shot_line_coverage.c.line_id == line)).scalar_one()
    fixed_media = service.get_media(fixture.p, media)
    fixture.write("decide_rights", {"media_id": media, "source_id": fixed_media["sources"][0]["source_id"], "outcome": "owned",
        "scope": {"purposes": ["*"]}, "reason": "owned synthetic WAV fixture"})
    fixture.write("record_media_check", {"media_id": media, "checker": "offline-WAV-fixture", "criteria_version": "1", "outcome": "pass"})
    candidate = fixture.write("propose_binding", {"media_id": media, "target_object_id": fixture.objects["shot"],
        "role": "dialogue_dry", "line_coverage_id": coverage})
    fixture.write("record_review", {"candidate_id": candidate["candidate_id"], "outcome": "pass", "reviewer_type": "human", "reason": "synthetic fixture human"})
    decision = fixture.write("select_candidate", {"candidate_id": candidate["candidate_id"], "reason": "synthetic fixture selects exact line"})
    selection = dict(candidate, decision_id=decision["id"])
    return {"job": job, "media_id": media, "selection": selection, "model_id": model, "request": request}


def seed_review_browser(service, video_bytes):
    """Seed six entry points in an isolated schema; supplied MP4 must be synthetic.

    Render-output registration is a UI fixture, not evidence of a production
    render execution. The audio worker alone executes locally with fixed WAVs.
    """
    fixture = ResourceFixture(service)
    draft = {"scenes": [{"id": "SC1", "actions": [{"id": "A1", "text": "手按门把"}], "dialogue": [
        {"id": "L1", "speaker": "C1", "text": "我现在必须离开这里"}], "silence": []}]}
    service.save_script_draft(fixture.p, {"content": draft}, actor="fixture-human")
    script_note = fixture.write("add_script_note", {"base_draft_revision": 1, "scene_id": "SC1", "line_id": "L1", "body": "解释太多，保留行动与离开的意思"})["id"]
    audio = seed_sound_review_source(service, fixture)
    sound_review = fixture.write("record_review", {"candidate_id": audio["selection"]["candidate_id"], "outcome": "needs_changes",
        "reason": "只重做本镜声音，保留画面", "reviewer_type": "human"})["id"]
    director = fixture.artifact("review-browser-design", "shot-plan", {"design_units": [{"design_key": "clear-action",
        "scene_id": fixture.objects["scene"], "picture": "合成镜头：关键行动尚不清楚", "shots": [{"shot_id": fixture.objects["shot"]}]}]})
    asset = fixture.write("create_object", {"kind": "asset", "asset_kind": "prop", "display_code": "REVIEW-CUP"})["id"]
    specification = fixture.artifact("review-browser-spec", "asset-bible", {"description": "合成道具规格：反光金属杯",
        "asset_specs": [{"asset_id": asset, "variant_key": "default"}]})
    media = register_owned_bytes(fixture, video_bytes, "review-browser-video.mp4", "video")
    selected = fixture.select_media(media, "video_take")
    items = [{"shot_id": fixture.objects["shot"], "track_key": "video", "offset_frame": 0, "duration_frames": 360,
        "media": [{"media_id": media, "binding_decision_id": selected["decision_id"], "role": "video_take", "source_out_frame": 360}]}]
    timeline = fixture.artifact("review-browser-timeline", "timeline", {"items": items})
    fixed = fixture.write("freeze_timeline", {"artifact_id": timeline, "episode_id": fixture.objects["episode"], "items": items, "fps_num": 30})
    plan = json.loads((ROOT / "templates/remotion-render-plan.json").read_text()); plan["project_id"] = fixture.p
    artifact = fixture.artifact("review-browser-render-plan", "render-plan", plan)
    rendered = register_owned_bytes(fixture, video_bytes, "review-browser-render-output.mp4", "video")
    fixture.write("freeze_render", {"artifact_id": artifact, "timeline_id": fixed["id"], "tool": "synthetic-ui-fixture", "tool_version": "1",
        "outputs": [{"media_id": rendered}]})
    return {"fixture": fixture, "project_id": fixture.p, "script_note_id": script_note,
        "audio_media_id": audio["media_id"], "sound_review_id": sound_review, "sound": audio,
        "director_artifact_id": director, "asset_artifact_id": specification, "render_media_id": rendered}
