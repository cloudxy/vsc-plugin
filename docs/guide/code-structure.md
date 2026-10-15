# 工作流代码结构与安装

工作流规范由 `workflow/`、`profiles/`、`skills/` 和 `agents/` 维护。可执行功能由 `src/vsc/` 实现；技能文件只说明操作流程。

| 路径 | 责任 |
| --- | --- |
| `src/vsc/kernel/` | 契约、内核路由、宿主发现与规范视图 |
| `src/vsc/project/` | 项目状态、不可变产物版本、依赖影响与资源目录 |
| `src/vsc/story/` | 剧本、场次与镜头覆盖、表现、场景状态及连续性 |
| `src/vsc/assets/` | 身份规格、来源、素材登记、关系与审查应用服务 |
| `src/vsc/production/` | Provider 统一契约、固定镜头上下文、任务、调度与预算 |
| `src/vsc/post/` | 选片、时间线、字幕、渲染规格与交付 |
| `src/vsc/knowledge/` | 创作方法、制作规格和检索 |
| `src/vsc/adapters/` | PostgreSQL/SQLite/旧 JSON、存储、供应商、媒体探测与剪辑引擎适配 |
| `src/vsc/interfaces/` | CLI 和内置 FastAPI 资源面板 |
| `migrations/postgres/` | PostgreSQL 的唯一版本化迁移历史 |
| `tools/maintenance/` | Vendor、本地 CI、Git 提交检查等工程维护工具 |
| `scripts/` | 已发布命令的兼容入口 |
| `tests/<领域>/<层级>/` | 按责任和验证边界组织的测试 |

`scripts/` 保留原命令路径、参数和退出码。原模块名和领域包导入指向同一个模块对象；原调用方的全局补丁和缓存不会出现两份。`src/vsc/module-map.json` 记录兼容路径。新增功能进入领域模块，由 CLI 或 Web 接口调用。

系列项目的原 `vsc_series.py` 已拆分为 `production/context.py`、`assets/registry.py`、`story/boundaries.py` 和 `interfaces/cli/series.py`；`production/series.py` 保留旧 API。资产身份与参考规格在 `assets/specification.py`，场景状态及镜头连续性在 `story/consistency.py`。

## 依赖

Python 最低版本为 3.9。旧项目状态、内核路由和离线校验仅使用标准库。新资源面板、PostgreSQL 和 S3 存储按需安装。

```bash
uv sync --locked --extra web --extra postgres --extra test
```

`pyproject.toml` 声明依赖边界，`uv.lock` 固定解析结果。修改依赖后更新锁文件。安装 S3 适配所需依赖时增加 `--extra storage`；字幕排版依赖使用 `--extra media`，其 Pillow 版本与字幕渲染器保持一致。完整本机验证使用 `uv sync --locked --all-extras`。

可用 `uv build --wheel` 构建安装包。安装包包含 Python 模块及只读工作流声明、模板和 PostgreSQL 迁移。使用完整创作工作区时，设置 `VSC_WORKFLOW_ROOT` 指向本仓库根目录，以复用宿主入口、本机 Vendor 和现有作品。密钥仍由进程环境传入，不能写入包或作品。

## 验证

修改时根据源文件选择受影响测试：

```bash
python3 -B tests/run.py --files src/vsc/production/context.py --list
python3 -B tests/run.py --files src/vsc/production/context.py
```

测试影响分析同时识别领域包、维护工具、兼容入口、共享夹具和动态契约校验器。最后提交并推送时才执行一次全量本地 CI，详见 [维护指南](maintenance.md)。
