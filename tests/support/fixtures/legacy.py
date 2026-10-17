"""Pin historical Profile content only for legacy behavior regressions."""
from pathlib import Path
from support.paths import ROOT


def freeze_legacy_profile(project):
    """Historical behavior tests pin the actual pre-v2 profile, never default init."""
    import json
    from vsc.project.state import profile_digest
    path = Path(project) / 'vsc.json'
    state = json.loads(path.read_text('utf-8'))
    profile = json.loads((ROOT / 'tests/fixtures/profiles-v1' / (state['profile_id'].split('.')[-1] + '.json')).read_text('utf-8'))
    state.update(profile_snapshot=profile, profile_sha256=profile_digest(profile), profile_version=profile['version'])
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n', 'utf-8')
