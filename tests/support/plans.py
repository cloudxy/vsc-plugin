"""Small logical plan fixtures; callers receive a new dictionary each time."""


def remotion_plan():
    return {
        "format": "vsc.remotion-render-plan/v1", "project_id": "rain-letter",
        "composition": {"id": "ep-001", "width": 1080, "height": 1920, "fps": 30, "duration_in_frames": 180},
        "segments": [
            {"id": "SH-001", "kind": "video", "source": "takes/SH-001.mp4", "source_shot_id": "SH-001", "from_frame": 0, "duration_in_frames": 180, "fade_in_frames": 6},
            {"id": "AUD-001", "kind": "audio", "source": "audio/bgm.mp3", "from_frame": 0, "duration_in_frames": 180},
            {"id": "CAP-001", "kind": "caption", "text": "门外是谁？", "from_frame": 120, "duration_in_frames": 45},
        ],
    }
