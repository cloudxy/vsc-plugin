"""Role memory routes; decisions only cross the existing human session guard."""
from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool

from vsc.assets.role_memory import verified_memory_decision


def install_memory_routes(router, catalog, etag, actor):
    def legacy(project_id):
        # Resolution happens before selecting a route. A PG pointer or a PG
        # failure can never turn into a legacy memory write.
        reader = catalog._reader(project_id)
        return reader.root if reader else None

    def service():
        if not getattr(catalog, "service", None):
            raise HTTPException(503, "PostgreSQL角色记忆权威不可用")
        return catalog.service

    @router.get("/{project_id}/role-memories")
    def memories(project_id: str, request: Request, role: str = None, scope: str = None):
        path = legacy(project_id)
        if path:
            from vsc.project.role_runtime_legacy import list_memories
            return etag(request, list_memories(path, role=role, scope=scope))
        return etag(request, service().list_role_memories(project_id, role=role, scope=scope))

    @router.get("/{project_id}/role-dispatches/{dispatch_id}")
    def dispatch(project_id: str, dispatch_id: str, request: Request):
        return etag(request, service().get_role_dispatch(project_id, dispatch_id))

    @router.post("/{project_id}/role-memory-proposals")
    async def propose(project_id: str, request: Request, body: dict):
        identity = actor(request)
        path = legacy(project_id)
        if path:
            from vsc.project.role_runtime_legacy import mutate_memory
            return await run_in_threadpool(mutate_memory, path, "propose", body.get("payload", {}),
                actor=identity, expected_revision=body.get("expected_revision"), idempotency_key=body.get("idempotency_key"))
        return await run_in_threadpool(service().propose_role_memory, project_id, body.get("payload", {}),
            actor=identity, expected_revision=body.get("expected_revision"), idempotency_key=body.get("idempotency_key"))

    @router.post("/{project_id}/role-memory-decisions")
    async def decide(project_id: str, request: Request, body: dict):
        identity = actor(request)
        if body.get("confirmed") is not True:
            raise HTTPException(422, "请确认已阅读该固定版本及来源后再作出记忆决定")
        path = legacy(project_id)
        if path:
            from vsc.project.role_runtime_legacy import mutate_memory
            return await run_in_threadpool(mutate_memory, path, "decide", body.get("payload", {}),
                human_decision=verified_memory_decision(identity), actor=identity,
                expected_revision=body.get("expected_revision"), idempotency_key=body.get("idempotency_key"))
        return await run_in_threadpool(service().decide_role_memory, project_id, body.get("payload", {}),
            human_decision=verified_memory_decision(identity), actor=identity,
            expected_revision=body.get("expected_revision"), idempotency_key=body.get("idempotency_key"))
