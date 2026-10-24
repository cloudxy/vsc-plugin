"""Review routes use the same trusted session, revision and original authority."""
from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool


def install_review_routes(router, catalog, etag, actor):
    def service(project_id):
        if catalog._reader(project_id) is not None or catalog.service is None:
            raise HTTPException(409, "原意见处理需要 PostgreSQL 权威，旧项目保持只读")
        return catalog.service

    @router.get("/{project_id}/review-history")
    def history(project_id: str, request: Request, script_note_id: str = None, media_review_id: str = None,
                artifact_note_id: str = None, artifact_id: str = None, media_id: str = None, offset: int = 0,
                limit: int = 24, response_offset: int = 0, response_limit: int = 10):
        return etag(request, service(project_id).get_review_history(project_id, script_note_id=script_note_id,
            media_review_id=media_review_id, artifact_note_id=artifact_note_id, artifact_id=artifact_id, media_id=media_id,
            offset=offset, limit=limit, response_offset=response_offset, response_limit=response_limit))

    @router.post("/{project_id}/artifact-review-notes")
    async def note(project_id: str, request: Request, body: dict):
        return await run_in_threadpool(service(project_id).add_artifact_review_note, project_id, body.get("payload"),
            actor=actor(request), expected_revision=body.get("expected_revision"), idempotency_key=body.get("idempotency_key"))

    @router.post("/{project_id}/review-process")
    async def process(project_id: str, request: Request, body: dict):
        return await run_in_threadpool(service(project_id).process_review, project_id, body.get("payload"),
            actor=actor(request), expected_revision=body.get("expected_revision"), idempotency_key=body.get("idempotency_key"))
