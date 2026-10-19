"""CLI and AI entry to the same resource use cases as the built-in panel."""
import argparse
import json
from pathlib import Path
import sys
from vsc.bootstrap import service_from_environment
from vsc.configuration import get_config

WRITE_ACTIONS = {
    "create_object", "create_artifact", "decide_artifact", "register_media", "propose_binding", "record_review",
    "select_candidate", "reject_candidate", "retire_binding", "decide_media_lifecycle", "decide_rights",
    "record_media_check", "create_media_operation", "create_preview_job", "create_generation_job",
    "update_generation_job", "freeze_timeline", "freeze_render", "configure_budget",
    "propose_local_production", "enqueue_local_production", "generate_script_suggestions",
    "resume_script_suggestions", "create_source_intake", "create_parse_job", "run_parse_job",
    "prepare_parse_import", "import_parse_job", "classify_resource",
}




def main(argv=None):
    parser = argparse.ArgumentParser(description="VSC 资源关系与固定镜头输入")
    parser.add_argument("--database-env", default="VSC_DATABASE_URL")
    parser.add_argument("--media-root")
    sub = parser.add_subparsers(dest="command", required=True)
    delegation = sub.add_parser("validate-delegation-file")
    delegation.add_argument("file")
    from vsc.project.migration import migration_parser, run_migration_args
    migration_parser(sub)
    sub.add_parser("projects")
    preview = sub.add_parser("local-preview")
    preview.add_argument("project_id")
    preview.add_argument("--payload", required=True)
    create = sub.add_parser("create")
    create.add_argument("--name", required=True)
    create.add_argument("--by", required=True)
    create.add_argument("--directory", help="建立本地 PostgreSQL 权威指针，不写 JSON 状态副本")
    for name in ("tree", "artifacts", "media", "status", "budget"):
        p = sub.add_parser(name)
        p.add_argument("project_id")
    browse = sub.add_parser("resource-model", help="查询分镜、分类、需求与地点关系")
    browse.add_argument("project_id")
    browse.add_argument("--section", choices=("resources", "categories", "designs", "requirements", "locations"), default="resources")
    browse.add_argument("--object-id")
    browse.add_argument("--category")
    browse.add_argument("--query", default="")
    browse.add_argument("--offset", type=int, default=0)
    browse.add_argument("--limit", type=int, default=100)
    sources = sub.add_parser("source-workspace", help="读取来源、解析任务和校对预览")
    sources.add_argument("project_id")
    sources.add_argument("--job-id")
    sources.add_argument("--preview", action="store_true")
    context = sub.add_parser("context")
    context.add_argument("project_id")
    context.add_argument("shot_id")
    context.add_argument("--purpose")
    asset_context = sub.add_parser("asset-context")
    asset_context.add_argument("project_id")
    asset_context.add_argument("asset_id")
    asset_context.add_argument("--purpose", default="asset_ref")
    artifact = sub.add_parser("artifact")
    artifact.add_argument("project_id")
    artifact.add_argument("artifact_id")
    export = sub.add_parser("render-export")
    export.add_argument("project_id")
    export.add_argument("timeline_id")
    export.add_argument("--out", required=True)
    export.add_argument("--remotion-out", help="同时准备含固定媒体的本地 Remotion 工程")
    export.add_argument("--draft-subtitles", action="store_true", help="仅预览字幕交接缺口，明确标记not_verified")
    apply = sub.add_parser("apply")
    apply.add_argument("project_id")
    apply.add_argument("action", choices=sorted(WRITE_ACTIONS))
    apply.add_argument("--payload", required=True, help="UTF-8 JSON 文件")
    apply.add_argument("--expected-revision", required=True, type=int)
    apply.add_argument("--key", required=True)
    apply.add_argument("--by", required=True)
    upload = sub.add_parser("stage")
    upload.add_argument("file")
    gate = sub.add_parser("gate")
    gate.add_argument("project_id")
    gate.add_argument("stage")
    gate.add_argument("--scope")
    registry = sub.add_parser("registry")
    registry.add_argument("kind", choices=["provider", "model", "route"])
    registry.add_argument("--payload", required=True)
    registry.add_argument("--by", required=True)
    worker = sub.add_parser("worker", help="显式执行一个已授权生成任务；可能调用在线 Provider")
    worker.add_argument("--project-id")
    worker.add_argument("--poll", action="store_true")
    worker.add_argument("--resume", help="只恢复已有成功响应的输出转存，不重复提交")
    previews = sub.add_parser("preview-worker")
    previews.add_argument("--project-id")
    previews.add_argument("--maximum", type=int, default=20)
    previews.add_argument("--retry-failed", action="store_true")
    previews.add_argument("--stale-after-seconds", type=int, default=300)
    args = parser.parse_args(argv)
    if args.command == "validate-delegation-file":
        from vsc.assets.review_delegation import errors
        problems = errors(Path(args.file).read_bytes())
        print(json.dumps({"passed": not problems, "errors": problems}, ensure_ascii=False))
        if problems:
            raise SystemExit(1)
        return
    from vsc.assets.resource_service import ResourceError
    service = None
    try:
        if args.command == "migrate":
            if args.action in ("import", "compare", "cutover"):
                service = service_from_environment(args.database_env, args.media_root)
            result = run_migration_args(args, service.store if service else None)
        elif args.command == "stage":
            from vsc.adapters.storage.local.store import LocalStorage
            storage = LocalStorage(args.media_root or get_config("VSC_MEDIA_ROOT"))
            with Path(args.file).open("rb") as stream:
                result = storage.stage_upload(stream, Path(args.file).name)
        else:
            service = service_from_environment(args.database_env, args.media_root)
            if args.command == "projects":
                result = service.list_projects()
            elif args.command == "local-preview":
                result = service.preview_local_production(args.project_id, json.loads(Path(args.payload).read_text("utf-8")))
            elif args.command == "create":
                from vsc.project.pg_workflow import create_project
                result = create_project(service, args.name, args.by, args.directory, args.database_env)
            elif args.command == "tree":
                result = service.get_project_tree(args.project_id)
            elif args.command == "artifacts":
                result = service.list_artifacts(args.project_id)
            elif args.command == "media":
                result = service.list_resources(args.project_id)
            elif args.command == "budget":
                result = service.budget_status(args.project_id)
            elif args.command == "source-workspace":
                result = (service.preview_parse_job(args.project_id, args.job_id) if args.preview else
                          service.get_parse_job(args.project_id, args.job_id)) if args.job_id else service.get_source_workspace(args.project_id)
            elif args.command == "resource-model":
                if args.section == "resources":
                    result = service.browse_resources(args.project_id, object_id=args.object_id, category=args.category,
                        query=args.query, offset=args.offset, limit=args.limit)
                elif args.section == "categories":
                    result = service.get_resource_taxonomy(args.project_id)
                else:
                    method = {"designs": service.get_shot_designs, "requirements": service.get_resource_requirements,
                              "locations": service.get_scene_locations}[args.section]
                    result = method(args.project_id, object_id=args.object_id)
            elif args.command == "context":
                result = service.compile_shot_context(args.project_id, args.shot_id, args.purpose)
            elif args.command == "asset-context":
                result = service.compile_asset_context(args.project_id, args.asset_id, args.purpose)
            elif args.command == "artifact":
                result = service.get_artifact_version(args.project_id, args.artifact_id)
            elif args.command == "render-export":
                from vsc.post.resource_export import export_render_package
                result = export_render_package(service, args.project_id, args.timeline_id, args.out, formal_subtitles=not args.draft_subtitles)
                if args.remotion_out:
                    from vsc.post.resource_export import scaffold_render_package
                    result["editor"] = scaffold_render_package(args.out, args.remotion_out)
            elif args.command == "registry":
                result = getattr(service, "register_" + args.kind)(json.loads(Path(args.payload).read_text("utf-8")), actor=args.by)
            elif args.command == "worker":
                from vsc.production.resource_worker import ResourceWorker
                from vsc.adapters.providers.worker_factory import worker_adapter_factory
                from vsc.adapters.storage.transfer import download_https
                worker = ResourceWorker(service, worker_adapter_factory, download=download_https)
                if args.resume and not args.project_id:
                    raise ResourceError("恢复转存需要 --project-id")
                result = worker.finalize(args.project_id, args.resume) if args.resume else worker.run_once(args.project_id, poll=args.poll)
            elif args.command == "preview-worker":
                from vsc.post.previews import PreviewWorker
                result = PreviewWorker(service, service.storage).run_pending(project_id=args.project_id, maximum=args.maximum,
                    retry_failed=args.retry_failed, stale_after_seconds=args.stale_after_seconds)
            elif args.command in {"status", "gate"}:
                from vsc.project.pg_workflow import workflow_status, check_gate
                result = workflow_status(service, args.project_id) if args.command == "status" else check_gate(service, args.project_id, args.stage, args.scope)
            else:
                payload = json.loads(Path(args.payload).read_text("utf-8"))
                result = getattr(service, args.action)(args.project_id, payload, expected_revision=args.expected_revision,
                    idempotency_key=args.key, actor=args.by)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        if args.command == "gate" and not result["passed"]:
            raise SystemExit(1)
    except (ResourceError, OSError, ValueError) as error:
        print(json.dumps({"error": getattr(error, "code", "invalid_input"), "message": str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
    finally:
        if service:
            service.store.close()


if __name__ == "__main__":
    main()
