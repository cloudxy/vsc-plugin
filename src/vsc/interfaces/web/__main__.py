"""Local panel server, explicitly read-only unless a human identity is supplied."""
import argparse
import secrets
import threading


def main(argv=None):
    parser = argparse.ArgumentParser(description="VSC 内建资源面板")
    parser.add_argument("--projects-root", default="projects")
    parser.add_argument("--media-root")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--human", help="本次实际操作人的身份；启用有确认事件的写入")
    parser.add_argument("--open", action="store_true", help="打开浏览器；已配置写入时使用短时单次本机引导")
    parser.add_argument("--database-env", default="VSC_DATABASE_URL", help="连接配置键，默认从项目 .env 读取")
    args = parser.parse_args(argv)
    from .app import create_app
    from vsc.configuration import get_config
    service = None
    media_root = args.media_root or get_config("VSC_MEDIA_ROOT")
    database_url = get_config(args.database_env)
    if database_url:
        from vsc.adapters.persistence.postgres.store import PostgresResourceStore
        from vsc.assets.resource_service import ResourceService
        from vsc.adapters.storage.local.store import LocalStorage
        service = ResourceService(PostgresResourceStore(database_url), storage=LocalStorage(media_root))
    configured_human = get_config("VSC_PANEL_HUMAN_IDENTITY", "")
    configured_write = get_config("VSC_PANEL_WRITABLE", False) is True
    human = args.human or (configured_human if configured_write else None)
    if human is not None and (not isinstance(human, str) or not human.strip()):
        parser.error("请在 config/.env 填写实际操作人的 VSC_PANEL_HUMAN_IDENTITY")
    if configured_write and not human:
        parser.error("启用操作前需要配置实际操作人")
    token = secrets.token_urlsafe(32) if human else None
    bootstrap_token = secrets.token_urlsafe(32) if token and args.open else None
    config = {"projects_root": args.projects_root, "media_root": media_root, "close_service_on_shutdown": True,
              "human_identity": human, "access_token": token, "bootstrap_token": bootstrap_token,
              "local_auto_session": get_config("VSC_PANEL_REQUIRE_LOGIN", True) is False,
              "background_enabled": bool(human),
              "allowed_origins": ["http://127.0.0.1:" + str(args.port), "http://localhost:" + str(args.port)]}
    if token and not args.open and not config["local_auto_session"]:
        print("本次人工操作身份：" + human)
        print("在面板的操作会话中输入本次凭据（勿写入项目或日志）：" + token)
    print("VSC 资源面板：http://127.0.0.1:" + str(args.port))
    if args.open:
        # Startup owns browser handoff. The fragment never reaches an HTTP access
        # log; the client removes it before its one-time, same-origin exchange.
        import webbrowser
        url = "http://127.0.0.1:" + str(args.port)
        if bootstrap_token:
            url += "/#setup=" + bootstrap_token
        timer = threading.Timer(1.0, webbrowser.open, args=(url,))
        timer.daemon = True
        timer.start()
    import uvicorn
    uvicorn.run(create_app(config, service=service), host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
