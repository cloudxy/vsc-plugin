"""Script workspace routes: draft read/compare plus a session-bound autosave seam.

Submit, approval and note decisions flow through the shared write endpoints in
app.py; autosave is intentionally not a revision-bumping formal write, so it
gets its own POST route with the working copy's optimistic draft_revision.
"""
from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool


def install_script_routes(router, catalog, etag, actor):
    def service():
        value = getattr(catalog, "service", None)
        if value is None:
            raise HTTPException(422, "剧本工作区需要已连接的 PostgreSQL 权威")
        return value

    @router.get("/{project_id}/script-draft")
    def script_draft(project_id: str, request: Request, scope_key: str = ""):
        return etag(request, service().get_script_draft(project_id, scope_key))

    @router.get("/{project_id}/script-draft/compare")
    def script_compare(project_id: str, request: Request, scope_key: str = "", base: str = None):
        return etag(request, service().compare_script_draft(project_id, scope_key, base))

    @router.get("/{project_id}/script-draft/impact")
    def script_impact(project_id: str, request: Request, scope_key: str = ""):
        return etag(request, service().script_revision_impact(project_id, scope_key))

    @router.post("/{project_id}/script-draft/autosave")
    async def script_autosave(project_id: str, request: Request, body: dict):
        identity = actor(request)
        payload = body.get("payload") if isinstance(body, dict) else None
        if not isinstance(payload, dict):
            raise HTTPException(422, "需要 payload 对象")
        if "actor" in payload:
            raise HTTPException(422, "操作身份来自本机会话，正文不能指定 actor")
        return await run_in_threadpool(service().save_script_draft, project_id, payload, actor=identity)

    @router.post("/{project_id}/script-draft/generate-suggestions")
    async def generate(project_id: str, request: Request, body: dict):
        identity = actor(request)
        return await run_in_threadpool(service().generate_script_suggestions, project_id, body.get("payload"),
            actor=identity, expected_revision=body.get("expected_revision"),
            idempotency_key=body.get("idempotency_key"))

    @router.get("/{project_id}/script-suggestion-runs/{run_id}")
    def suggestion_run(project_id: str, run_id: str, request: Request):
        return etag(request, service().store.get_script_suggestion_run(project_id, run_id))

    @router.post("/{project_id}/script-suggestion-runs/{run_id}/resume")
    async def resume(project_id: str, run_id: str, request: Request, body: dict):
        return await run_in_threadpool(service().resume_script_suggestions, project_id, {"run_id": run_id},
            actor=actor(request), expected_revision=body.get("expected_revision"),
            idempotency_key=body.get("idempotency_key"))
