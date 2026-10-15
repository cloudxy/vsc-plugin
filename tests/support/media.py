"""Generate small, immutable media samples once per test process."""
from functools import lru_cache
from pathlib import Path
import subprocess
import tempfile
from types import MappingProxyType


@lru_cache(maxsize=1)
def production_media():
    """Return bytes, never shared writable paths; each test owns its working copy."""
    with tempfile.TemporaryDirectory(prefix="vsc-test-media-") as temp:
        folder = Path(temp)
        commands = {
            "png": ["-f", "lavfi", "-i", "color=red:size=16x16", "-frames:v", "1", "frame.png"],
            "jpeg": ["-f", "lavfi", "-i", "color=red:size=16x16", "-frames:v", "1", "frame.jpeg"],
            "mp4": ["-f", "lavfi", "-i", "color=blue:size=16x16:rate=5", "-t", "0.4",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "clip.mp4"],
            "wav": ["-f", "lavfi", "-i", "sine=frequency=440", "-t", "0.1", "voice.wav"],
        }
        samples = {}
        for kind, args in commands.items():
            output = folder / args[-1]
            subprocess.run(["ffmpeg", "-nostdin", "-v", "error", *args[:-1], str(output)],
                           check=True, capture_output=True, timeout=30)
            samples[kind] = output.read_bytes()
    return MappingProxyType(samples)
