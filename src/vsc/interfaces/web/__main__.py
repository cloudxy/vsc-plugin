"""Local panel server, explicitly read-only unless a human identity is supplied."""
import argparse
import os
import secrets


def main(argv=None):
    parser = argparse.ArgumentParser(description="VSC 内建资源面板")
    parser.add_argument("--projects-root", default="projects")
    parser.add_argument("--media-root")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--human", help="本次实际操作人的身份；启用有确认事件的写入")
    parser.add_argument("--database-env", default="VSC_DATABASE_URL", help="PostgreSQL 连接环境变量名")
    args = parser.parse_args(argv)
    from .app import create_app
    service = None
    media_root = args.media_root or os.environ.get("VSC_MEDIA_ROOT", ".vsc-resource-media")
    database_url = os.environ.get(args.database_env)
    if database_url:
        from vsc.adapters.persistence.postgres.store import PostgresResourceStore
        from vsc.assets.resource_service import ResourceService
        from vsc.adapters.storage.local.store import LocalStorage
        service = ResourceService(PostgresResourceStore(database_url), storage=LocalStorage(media_root))
    token = secrets.token_urlsafe(32) if args.human else None
    config = {"projects_root": args.projects_root, "media_root": media_root, "close_service_on_shutdown": True,
              "human_identity": args.human, "access_token": token,
              "allowed_origins": ["http://127.0.0.1:" + str(args.port), "http://localhost:" + str(args.port)]}
    if token:
        print("本次人工操作身份：" + args.human)
        print("在面板的操作会话中输入本次凭据（勿写入项目或日志）：" + token)
    print("VSC 资源面板：http://127.0.0.1:" + str(args.port))
    import uvicorn
    uvicorn.run(create_app(config, service=service), host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
