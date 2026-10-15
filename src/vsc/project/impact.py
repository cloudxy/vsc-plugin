#!/usr/bin/env python3
"""Read-only consumers and rework ranges for a fixed artifact version."""
import argparse
import json
from pathlib import Path
from vsc.project.state import project_state
from vsc.project.artifacts import validate_artifact


def impact(project, state, identifier):
    if identifier not in {a['id'] for a in state['artifacts']}: raise ValueError('产物不存在')
    reached = {identifier}; found = []
    while True:
        pending = [a for a in state['artifacts'] if a['id'] not in reached and
            (set(a.get('depends_on', [])) & reached or any(v.get('id') in reached for v in a.get('asset_versions', {}).values()))]
        if not pending: break
        for artifact in pending:
            reached.add(artifact['id'])
            found.append({'id':artifact['id'], 'type':artifact['type'], 'scope':artifact.get('scope','project'),
                          'status':artifact['status'], 'problems':validate_artifact(project,state,artifact)})
    return {'format':'vsc.rework-impact/v1', 'artifact_id':identifier, 'consumers':found,
            'note':'只读影响报告；实际返工登记新版本，不改历史快照'}


def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('project'); parser.add_argument('artifact_id')
    args=parser.parse_args()
    print(json.dumps(impact(args.project,project_state(Path(args.project)),args.artifact_id),ensure_ascii=False,indent=2))


if __name__=='__main__': main()
