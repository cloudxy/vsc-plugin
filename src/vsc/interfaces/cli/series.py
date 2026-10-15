"""Compatible SQLite-series CLI over domain use cases."""
import argparse
import json
import sqlite3
import sys
from pathlib import Path
from vsc.adapters.persistence.sqlite import series as db
from vsc.project.state import write_json
from vsc.production.context import (SeriesError, MEDIA_ROLES, RIGHTS, MODALITIES,
    series_state, build_shot_context, repair_mirror, validate_context, validate_context_file)
from vsc.assets.registry import (import_media, decide_media_rights, bind_media,
    decide_binding, retire_binding)
from vsc.story.boundaries import link_boundary

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("context"); command.add_argument("project"); command.add_argument("--shot", required=True)
    command.add_argument("--out")
    command = sub.add_parser("import-media"); command.add_argument("project"); command.add_argument("--id", required=True)
    command.add_argument("--file", required=True); command.add_argument("--modality", choices=MODALITIES, required=True)
    command.add_argument("--rights", choices=RIGHTS, required=True); command.add_argument("--origin", required=True)
    command.add_argument("--parent", action="append", default=[]); command.add_argument("--relation"); command.add_argument("--parameters")
    command.add_argument("--job"); command.add_argument("--original-uri")
    command = sub.add_parser("bind-media"); command.add_argument("project"); command.add_argument("--id", required=True)
    command.add_argument("--target", required=True); command.add_argument("--media", required=True)
    command.add_argument("--role", choices=MEDIA_ROLES, required=True); command.add_argument("--variant")
    command = sub.add_parser("decide-binding"); command.add_argument("project"); command.add_argument("id")
    command.add_argument("--status", choices=("approved", "rejected"), required=True)
    command.add_argument("--by", required=True); command.add_argument("--reason", required=True)
    command = sub.add_parser("retire-binding"); command.add_argument("project"); command.add_argument("id")
    command.add_argument("--by", required=True); command.add_argument("--reason", required=True)
    command = sub.add_parser("decide-media-rights"); command.add_argument("project"); command.add_argument("id")
    command.add_argument("--rights", choices=RIGHTS, required=True)
    command.add_argument("--by", required=True); command.add_argument("--reason", required=True)
    command = sub.add_parser("media-list"); command.add_argument("project"); command.add_argument("--target")
    command = sub.add_parser("repair-mirror"); command.add_argument("project")
    command = sub.add_parser("validate-context"); command.add_argument("project"); command.add_argument("file")
    command = sub.add_parser("validate-context-file"); command.add_argument("file")
    command = sub.add_parser("link-boundary"); command.add_argument("project")
    command.add_argument("--from-shot", required=True); command.add_argument("--to-shot", required=True)
    command.add_argument("--strategy", choices=("continuous", "intentional_jump"), required=True)
    command.add_argument("--by", required=True); command.add_argument("--reason", required=True)
    command.add_argument("--replace", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "context":
            context = build_shot_context(args.project, args.shot)
            if args.out:
                target = Path(args.out)
                if target.exists(): raise SeriesError("上下文输出已存在，拒绝覆盖")
                write_json(target, context)
            else:
                print(json.dumps(context, ensure_ascii=False, indent=2))
        elif args.command == "import-media":
            params = json.loads(args.parameters) if args.parameters else None
            print(json.dumps(import_media(args.project, args.id, args.file, args.modality,
                args.rights, args.origin, args.parent, args.relation, params, args.job, args.original_uri), ensure_ascii=False))
        elif args.command == "bind-media":
            bind_media(args.project, args.id, args.target, args.media, args.role, args.variant)
            print("OK 媒体绑定已登记为 draft")
        elif args.command == "decide-binding":
            decide_binding(args.project, args.id, args.status, args.by, args.reason)
            print("OK 媒体绑定决定已记录")
        elif args.command == "retire-binding":
            retire_binding(args.project, args.id, args.by, args.reason)
            print("OK 旧媒体绑定已退役")
        elif args.command == "decide-media-rights":
            decide_media_rights(args.project, args.id, args.rights, args.by, args.reason)
            print("OK 媒体权属决定已记录")
        elif args.command == "media-list":
            series_state(args.project)
            with db.connect(args.project) as connection:
                if args.target:
                    rows = connection.execute("SELECT * FROM media_bindings WHERE target_id=? ORDER BY id", (args.target,)).fetchall()
                else:
                    rows = connection.execute("SELECT * FROM media_assets ORDER BY id").fetchall()
                print(json.dumps([dict(row) for row in rows], ensure_ascii=False, indent=2))
        elif args.command == "validate-context":
            validate_context(args.project, args.file)
            print("OK 镜头上下文与当前批准版本一致")
        elif args.command == "validate-context-file":
            validate_context_file(json.loads(Path(args.file).read_text("utf-8")))
            print("OK 镜头上下文结构与摘要有效")
        elif args.command == "link-boundary":
            link_boundary(args.project, args.from_shot, args.to_shot, args.strategy, args.by, args.reason, args.replace)
            print("OK 跨集边界决定已记录")
        else:
            repair_mirror(args.project)
            print("OK vsc.json 只读镜像已从数据库恢复")
    except (SeriesError, db.SeriesStoreError, sqlite3.Error, ValueError, OSError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
