"""测试共用路径：被测 CLI 位于 scripts/，在此统一加入导入路径。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def freeze_legacy_profile(project):
    """Historical behavior tests pin the actual pre-v2 profile, never default init."""
    import json
    from vsc_state import profile_digest
    path = Path(project) / 'vsc.json'
    state = json.loads(path.read_text('utf-8'))
    profile = json.loads((ROOT / 'tests/fixtures/profiles-v1' / (state['profile_id'].split('.')[-1] + '.json')).read_text('utf-8'))
    state.update(profile_snapshot=profile, profile_sha256=profile_digest(profile), profile_version=profile['version'])
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n', 'utf-8')
