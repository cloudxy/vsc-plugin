"""Private account/workspace/platform/project commerce routes."""
import re
from fastapi import HTTPException, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool


def install_commerce_routes(app, router, catalog, etag, actor, read_actor):
    def pg_service(project_id=None):
        if catalog.service is None or (project_id is not None and catalog._reader(project_id) is not None):
            raise HTTPException(409, "商业账本需要原 PostgreSQL 权威存储")
        return catalog.service

    def check_envelope(body):
        if not isinstance(body, dict) or not isinstance(body.get("payload"), dict) or "actor" in body:
            raise HTTPException(422, "操作身份来自可信会话")

    async def write_project(project_id, request, body, method):
        identity = actor(request)
        check_envelope(body)
        payload = body["payload"]
        if "confirmed" in body and "confirmed" not in payload:
            payload = dict(payload, confirmed=body["confirmed"])
        return await run_in_threadpool(
            getattr(pg_service(project_id), method),
            project_id,
            payload,
            actor=identity,
            expected_revision=body.get("expected_revision"),
            idempotency_key=body.get("idempotency_key"),
        )

    async def write_scoped(scope_kind, scope_id, request, body, method, *extra_args):
        identity = actor(request)
        check_envelope(body)
        payload = body["payload"]
        if "confirmed" in body and "confirmed" not in payload:
            payload = dict(payload, confirmed=body["confirmed"])
        return await run_in_threadpool(
            getattr(pg_service(), method),
            scope_kind,
            scope_id,
            *extra_args,
            payload,
            actor=identity,
            expected_revision=body.get("expected_revision"),
            idempotency_key=body.get("idempotency_key"),
        )

    from datetime import datetime, timezone

    def _csv_headers(scope_label):
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        return {
            "Content-Disposition": f'attachment; filename="vsc-ledger-{scope_label}-{day}.csv"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        }

    async def delete_title_scoped(scope_kind, scope_id, request, title_id, body):
        envelope = dict(body) if isinstance(body, dict) else {}
        if "payload" not in envelope:
            envelope["payload"] = {}
        if envelope.get("expected_revision") is None and request.query_params.get("expected_revision") is not None:
            try:
                envelope["expected_revision"] = int(request.query_params["expected_revision"])
            except ValueError:
                raise HTTPException(422, "expected_revision 格式不正确")
        if not envelope.get("idempotency_key") and request.query_params.get("idempotency_key"):
            envelope["idempotency_key"] = request.query_params["idempotency_key"]
        return await write_scoped(scope_kind, scope_id, request, envelope, "delete_commerce_invoice_title_scoped", title_id)
    @router.get("/{project_id}/commerce")
    def summary(project_id: str, request: Request):
        return etag(request, pg_service(project_id).commerce_summary(project_id, actor=read_actor(request)))

    @router.post("/{project_id}/commerce/plans")
    async def plans(project_id: str, request: Request, body: dict):
        return await write_project(project_id, request, body, "configure_commerce_plan")

    @router.post("/{project_id}/commerce/plans/preview-diff")
    def project_plans_diff(project_id: str, request: Request, body: dict):
        identity = actor(request)
        payload = body.get("payload") if isinstance(body, dict) and isinstance(body.get("payload"), dict) else body
        return pg_service(project_id).preview_commerce_plan_diff("project", project_id, payload, actor=identity)

    @router.post("/{project_id}/commerce/orders")
    async def orders(project_id: str, request: Request, body: dict):
        return await write_project(project_id, request, body, "create_commerce_order")

    @router.post("/{project_id}/commerce/orders/refresh")
    async def refresh(project_id: str, request: Request, body: dict):
        return await write_project(project_id, request, body, "refresh_commerce_order")

    @router.post("/{project_id}/commerce/orders/cancel")
    async def cancel(project_id: str, request: Request, body: dict):
        return await write_project(project_id, request, body, "cancel_commerce_order")

    @router.post("/{project_id}/commerce/orders/renew")
    async def renew(project_id: str, request: Request, body: dict):
        return await write_project(project_id, request, body, "renew_commerce_order")

    @router.post("/{project_id}/commerce/orders/refund")
    async def refund(project_id: str, request: Request, body: dict):
        return await write_project(project_id, request, body, "refund_commerce_order")

    @router.post("/{project_id}/commerce/campaigns")
    async def campaigns(project_id: str, request: Request, body: dict):
        return await write_project(project_id, request, body, "configure_commerce_campaign")

    @router.post("/{project_id}/commerce/campaigns/preview-diff")
    def project_campaigns_diff(project_id: str, request: Request, body: dict):
        identity = actor(request)
        payload = body.get("payload") if isinstance(body, dict) and isinstance(body.get("payload"), dict) else body
        return pg_service(project_id).preview_commerce_campaign_diff("project", project_id, payload, actor=identity)

    @router.post("/{project_id}/commerce/redeem")
    async def redeem(project_id: str, request: Request, body: dict):
        return await write_project(project_id, request, body, "redeem_commerce_campaign")

    @router.post("/{project_id}/commerce/allocations")
    async def allocate(project_id: str, request: Request, body: dict):
        return await write_project(project_id, request, body, "allocate_commerce_credits")

    @router.post("/{project_id}/commerce/workspace-transfers")
    async def transfer(project_id: str, request: Request, body: dict):
        return await write_project(project_id, request, body, "transfer_workspace_credits")

    @router.post("/{project_id}/commerce/invoices")
    async def invoices(project_id: str, request: Request, body: dict):
        return await write_project(project_id, request, body, "request_commerce_invoice")

    @router.post("/{project_id}/commerce/invoices/refresh")
    async def invoice_refresh(project_id: str, request: Request, body: dict):
        return await write_project(project_id, request, body, "refresh_commerce_invoice")

    @router.get("/{project_id}/commerce/invoices/{invoice_id}/content")
    def invoice_content(project_id: str, invoice_id: str, request: Request):
        content, sha = pg_service(project_id).commerce_invoice_content(project_id, invoice_id, actor=read_actor(request))
        return Response(
            content,
            media_type="application/pdf",
            headers={
                "Content-Disposition": "attachment; filename=invoice.pdf",
                "ETag": '"' + sha + '"',
                "Cache-Control": "private, no-store",
            },
        )

    @router.get("/{project_id}/commerce/invoice-titles")
    def invoice_titles(project_id: str, request: Request, q: str = ""):
        return etag(request, pg_service(project_id).commerce_invoice_titles(project_id, actor=read_actor(request), query=q))

    @router.post("/{project_id}/commerce/invoice-titles")
    async def save_project_invoice_title(project_id: str, request: Request, body: dict):
        return await write_scoped("project", project_id, request, body, "save_commerce_invoice_title_scoped")

    @router.delete("/{project_id}/commerce/invoice-titles/{title_id}")
    async def delete_project_invoice_title(project_id: str, title_id: str, request: Request, body: dict = None):
        return await delete_title_scoped("project", project_id, request, title_id, body)

    @router.get("/{project_id}/commerce/ledger")
    def project_ledger(
        project_id: str, request: Request, cursor: str = "", limit: int = 50,
        kind: str = "", attribution_project_id: str = "",
    ):
        return etag(
            request,
            pg_service(project_id).commerce_ledger_scoped(
                "project", project_id, actor=read_actor(request), cursor=cursor,
                limit=limit, kind=kind, attribution_project_id=attribution_project_id,
            ),
        )

    @router.get("/{project_id}/commerce/ledger.csv")
    def project_ledger_csv(project_id: str, request: Request, kind: str = "", attribution_project_id: str = ""):
        raw = pg_service(project_id).commerce_ledger_csv_scoped(
            "project", project_id, actor=read_actor(request),
            kind=kind, attribution_project_id=attribution_project_id,
        )
        return Response(raw, media_type="text/csv; charset=utf-8", headers=_csv_headers("project"))

    @router.post("/{project_id}/commerce/quote")
    def quote(project_id: str, request: Request, body: dict):
        return etag(request, pg_service(project_id).preview_commerce_charge(project_id, body.get("payload"), actor=actor(request)))

    # ── Account-scoped routes (/api/v1/account/commerce*) ──
    @app.get("/api/v1/account/commerce")
    def account_summary(request: Request):
        return etag(request, pg_service().commerce_summary_scoped("identity", None, actor=read_actor(request)))

    @app.post("/api/v1/account/commerce/orders")
    async def account_orders(request: Request, body: dict):
        return await write_scoped("identity", None, request, body, "create_commerce_order_scoped")

    @app.post("/api/v1/account/commerce/orders/refresh")
    async def account_refresh(request: Request, body: dict):
        return await write_scoped("identity", None, request, body, "refresh_commerce_order_scoped")

    @app.post("/api/v1/account/commerce/orders/cancel")
    async def account_cancel(request: Request, body: dict):
        return await write_scoped("identity", None, request, body, "cancel_commerce_order_scoped")

    @app.post("/api/v1/account/commerce/orders/renew")
    async def account_renew(request: Request, body: dict):
        return await write_scoped("identity", None, request, body, "renew_commerce_order_scoped")

    @app.post("/api/v1/account/commerce/orders/refund")
    async def account_refund(request: Request, body: dict):
        return await write_scoped("identity", None, request, body, "refund_commerce_order_scoped")

    @app.post("/api/v1/account/commerce/redeem")
    async def account_redeem(request: Request, body: dict):
        return await write_scoped("identity", None, request, body, "redeem_commerce_campaign_scoped")

    @app.post("/api/v1/account/commerce/invoices")
    async def account_invoices(request: Request, body: dict):
        return await write_scoped("identity", None, request, body, "request_commerce_invoice_scoped")

    @app.post("/api/v1/account/commerce/invoices/refresh")
    async def account_invoice_refresh(request: Request, body: dict):
        return await write_scoped("identity", None, request, body, "refresh_commerce_invoice_scoped")

    @app.get("/api/v1/account/commerce/invoices/{invoice_id}/content")
    def account_invoice_content(invoice_id: str, request: Request):
        content, sha = pg_service().commerce_invoice_content_scoped("identity", None, invoice_id, actor=read_actor(request))
        return Response(
            content,
            media_type="application/pdf",
            headers={
                "Content-Disposition": "attachment; filename=invoice.pdf",
                "ETag": '"' + sha + '"',
                "Cache-Control": "private, no-store",
            },
        )

    @app.get("/api/v1/account/commerce/invoice-titles")
    def account_invoice_titles(request: Request, q: str = ""):
        return etag(request, pg_service().commerce_invoice_titles_scoped("identity", None, actor=read_actor(request), query=q))

    @app.post("/api/v1/account/commerce/invoice-titles")
    async def save_account_invoice_title(request: Request, body: dict):
        return await write_scoped("identity", None, request, body, "save_commerce_invoice_title_scoped")

    @app.delete("/api/v1/account/commerce/invoice-titles/{title_id}")
    async def delete_account_invoice_title(title_id: str, request: Request, body: dict = None):
        return await delete_title_scoped("identity", None, request, title_id, body)

    @app.get("/api/v1/account/commerce/ledger")
    def account_ledger(
        request: Request, cursor: str = "", limit: int = 50,
        kind: str = "", attribution_project_id: str = "",
    ):
        return etag(
            request,
            pg_service().commerce_ledger_scoped(
                "identity", None, actor=read_actor(request), cursor=cursor,
                limit=limit, kind=kind, attribution_project_id=attribution_project_id,
            ),
        )

    @app.get("/api/v1/account/commerce/ledger.csv")
    def account_ledger_csv(request: Request, kind: str = "", attribution_project_id: str = ""):
        raw = pg_service().commerce_ledger_csv_scoped(
            "identity", None, actor=read_actor(request),
            kind=kind, attribution_project_id=attribution_project_id,
        )
        return Response(raw, media_type="text/csv; charset=utf-8", headers=_csv_headers("account"))

    # ── Workspace-scoped routes (/api/v1/workspaces/{workspace_id}/commerce*) ──
    @app.get("/api/v1/workspaces/{workspace_id}/commerce")
    def workspace_summary(workspace_id: str, request: Request):
        return etag(request, pg_service().commerce_summary_scoped("workspace", workspace_id, actor=read_actor(request)))

    @app.post("/api/v1/workspaces/{workspace_id}/commerce/plans/preview-diff")
    def workspace_plans_diff(workspace_id: str, request: Request, body: dict):
        identity = actor(request)
        payload = body.get("payload") if isinstance(body, dict) and isinstance(body.get("payload"), dict) else body
        return pg_service().preview_commerce_plan_diff("workspace", workspace_id, payload, actor=identity)

    @app.post("/api/v1/workspaces/{workspace_id}/commerce/plans")
    async def workspace_plans(workspace_id: str, request: Request, body: dict):
        return await write_scoped("workspace", workspace_id, request, body, "configure_commerce_plan_scoped")

    @app.post("/api/v1/workspaces/{workspace_id}/commerce/campaigns/preview-diff")
    def workspace_campaigns_diff(workspace_id: str, request: Request, body: dict):
        identity = actor(request)
        payload = body.get("payload") if isinstance(body, dict) and isinstance(body.get("payload"), dict) else body
        return pg_service().preview_commerce_campaign_diff("workspace", workspace_id, payload, actor=identity)

    @app.post("/api/v1/workspaces/{workspace_id}/commerce/campaigns")
    async def workspace_campaigns(workspace_id: str, request: Request, body: dict):
        return await write_scoped("workspace", workspace_id, request, body, "configure_commerce_campaign_scoped")

    @app.post("/api/v1/workspaces/{workspace_id}/commerce/orders")
    async def workspace_orders(workspace_id: str, request: Request, body: dict):
        return await write_scoped("workspace", workspace_id, request, body, "create_commerce_order_scoped")

    @app.post("/api/v1/workspaces/{workspace_id}/commerce/orders/refresh")
    async def workspace_refresh(workspace_id: str, request: Request, body: dict):
        return await write_scoped("workspace", workspace_id, request, body, "refresh_commerce_order_scoped")

    @app.post("/api/v1/workspaces/{workspace_id}/commerce/orders/cancel")
    async def workspace_cancel(workspace_id: str, request: Request, body: dict):
        return await write_scoped("workspace", workspace_id, request, body, "cancel_commerce_order_scoped")

    @app.post("/api/v1/workspaces/{workspace_id}/commerce/orders/renew")
    async def workspace_renew(workspace_id: str, request: Request, body: dict):
        return await write_scoped("workspace", workspace_id, request, body, "renew_commerce_order_scoped")

    @app.post("/api/v1/workspaces/{workspace_id}/commerce/orders/refund")
    async def workspace_refund(workspace_id: str, request: Request, body: dict):
        return await write_scoped("workspace", workspace_id, request, body, "refund_commerce_order_scoped")

    @app.post("/api/v1/workspaces/{workspace_id}/commerce/redeem")
    async def workspace_redeem(workspace_id: str, request: Request, body: dict):
        return await write_scoped("workspace", workspace_id, request, body, "redeem_commerce_campaign_scoped")

    @app.post("/api/v1/workspaces/{workspace_id}/commerce/allocations")
    async def workspace_allocate(workspace_id: str, request: Request, body: dict):
        return await write_scoped("workspace", workspace_id, request, body, "allocate_commerce_credits_scoped")

    @app.post("/api/v1/workspaces/{workspace_id}/commerce/invoices")
    async def workspace_invoices(workspace_id: str, request: Request, body: dict):
        return await write_scoped("workspace", workspace_id, request, body, "request_commerce_invoice_scoped")

    @app.post("/api/v1/workspaces/{workspace_id}/commerce/invoices/refresh")
    async def workspace_invoice_refresh(workspace_id: str, request: Request, body: dict):
        return await write_scoped("workspace", workspace_id, request, body, "refresh_commerce_invoice_scoped")

    @app.get("/api/v1/workspaces/{workspace_id}/commerce/invoices/{invoice_id}/content")
    def workspace_invoice_content(workspace_id: str, invoice_id: str, request: Request):
        content, sha = pg_service().commerce_invoice_content_scoped("workspace", workspace_id, invoice_id, actor=read_actor(request))
        return Response(
            content,
            media_type="application/pdf",
            headers={
                "Content-Disposition": "attachment; filename=invoice.pdf",
                "ETag": '"' + sha + '"',
                "Cache-Control": "private, no-store",
            },
        )

    @app.get("/api/v1/workspaces/{workspace_id}/commerce/invoice-titles")
    def workspace_invoice_titles(workspace_id: str, request: Request, q: str = ""):
        return etag(request, pg_service().commerce_invoice_titles_scoped("workspace", workspace_id, actor=read_actor(request), query=q))

    @app.post("/api/v1/workspaces/{workspace_id}/commerce/invoice-titles")
    async def save_workspace_invoice_title(workspace_id: str, request: Request, body: dict):
        return await write_scoped("workspace", workspace_id, request, body, "save_commerce_invoice_title_scoped")

    @app.delete("/api/v1/workspaces/{workspace_id}/commerce/invoice-titles/{title_id}")
    async def delete_workspace_invoice_title(workspace_id: str, title_id: str, request: Request, body: dict = None):
        return await delete_title_scoped("workspace", workspace_id, request, title_id, body)

    @app.get("/api/v1/workspaces/{workspace_id}/commerce/ledger")
    def workspace_ledger(
        workspace_id: str, request: Request, cursor: str = "", limit: int = 50,
        kind: str = "", attribution_project_id: str = "",
    ):
        return etag(
            request,
            pg_service().commerce_ledger_scoped(
                "workspace", workspace_id, actor=read_actor(request), cursor=cursor,
                limit=limit, kind=kind, attribution_project_id=attribution_project_id,
            ),
        )

    @app.get("/api/v1/workspaces/{workspace_id}/commerce/ledger.csv")
    def workspace_ledger_csv(workspace_id: str, request: Request, kind: str = "", attribution_project_id: str = ""):
        raw = pg_service().commerce_ledger_csv_scoped(
            "workspace", workspace_id, actor=read_actor(request),
            kind=kind, attribution_project_id=attribution_project_id,
        )
        return Response(raw, media_type="text/csv; charset=utf-8", headers=_csv_headers("workspace"))

    # ── Platform-scoped routes (/api/v1/platform/commerce*) ──
    @app.get("/api/v1/platform/commerce")
    def platform_summary(request: Request):
        return etag(request, pg_service().platform_commerce_summary(actor=read_actor(request)))

    @app.post("/api/v1/platform/commerce/plans/preview-diff")
    def platform_plans_diff(request: Request, body: dict):
        identity = actor(request)
        payload = body.get("payload") if isinstance(body, dict) and isinstance(body.get("payload"), dict) else body
        return pg_service().preview_commerce_plan_diff("platform", None, payload, actor=identity)

    @app.post("/api/v1/platform/commerce/plans")
    async def platform_plans(request: Request, body: dict):
        return await write_scoped("platform", None, request, body, "configure_commerce_plan_scoped")

    @app.post("/api/v1/platform/commerce/campaigns/preview-diff")
    def platform_campaigns_diff(request: Request, body: dict):
        identity = actor(request)
        payload = body.get("payload") if isinstance(body, dict) and isinstance(body.get("payload"), dict) else body
        return pg_service().preview_commerce_campaign_diff("platform", None, payload, actor=identity)

    @app.post("/api/v1/platform/commerce/campaigns")
    async def platform_campaigns(request: Request, body: dict):
        return await write_scoped("platform", None, request, body, "configure_commerce_campaign_scoped")


NOTIFICATION_LIMIT = 128 * 1024


def is_commerce_notification(request):
    return request.method == "POST" and bool(
        re.fullmatch(
            r"/api/v1/commerce-notifications/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/(?:orders/)?[0-9a-fA-F-]{36}",
            request.url.path,
        )
    )


async def _read_notification_bytes(request: Request):
    from vsc.assets.resource_service import ResourceError
    if not is_commerce_notification(request):
        raise HTTPException(404, "回调入口不存在")
    length = request.headers.get("content-length")
    if length is not None:
        try:
            declared = int(length)
        except ValueError:
            raise HTTPException(400, "回调长度不合法")
        if declared < 0 or declared > NOTIFICATION_LIMIT:
            raise HTTPException(413, "支付回调超过128KiB")
    chunks = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > NOTIFICATION_LIMIT:
            raise HTTPException(413, "支付回调超过128KiB")
        chunks.append(chunk)
    return b"".join(chunks), ResourceError


def install_commerce_notification_routes(app, catalog):
    @app.post("/api/v1/commerce-notifications/{gateway_id}/orders/{order_id}")
    async def order_notification(gateway_id: str, order_id: str, request: Request):
        raw, ResourceError = await _read_notification_bytes(request)
        if catalog.service is None:
            raise ResourceError("支付服务未配置", "payment_unconfigured", 503)
        return await run_in_threadpool(
            catalog.service.handle_commerce_order_notification,
            order_id,
            dict(request.headers),
            raw,
            gateway_id=gateway_id,
        )

    @app.post("/api/v1/commerce-notifications/{gateway_id}/{project_id}")
    async def notification(gateway_id: str, project_id: str, request: Request):
        raw, ResourceError = await _read_notification_bytes(request)
        if catalog.service is None:
            raise ResourceError("支付服务未配置", "payment_unconfigured", 503)
        return await run_in_threadpool(
            catalog.service.handle_commerce_notification,
            project_id,
            dict(request.headers),
            raw,
            gateway_id=gateway_id,
        )
