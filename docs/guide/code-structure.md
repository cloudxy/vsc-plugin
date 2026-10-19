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
| `scripts/<职责>/` | 实际 CLI 入口；加载工作区并直接调用所属模块的 `main` |
| `tests/<领域>/<层级>/` | 按责任和验证边界组织的测试 |

`scripts/` 顶层只放职责索引。命令按 `kernel/project/story/assets/production/providers/media/post/knowledge/maintenance` 分组，供应商命令再按实际服务方分目录。完整入口表见 [scripts 索引](../../scripts/README.md)。命令通过明确的 Python import 指向实现，不维护另一份旧模块映射。

文件归属由其负责的规则决定：固定镜头上下文属于 `production/context.py`，素材登记属于 `assets/registry.py`，跨镜衔接属于 `story/boundaries.py`，命令参数编排属于 `interfaces/cli/series.py`。调用方和测试直接导入这些模块。资产身份与参考规格在 `assets/specification.py`，场景状态及镜头连续性在 `story/consistency.py`。库模块不再在 scripts 中建立无命令行为的文件。

工作流声明、运行接口与实现各自维护自己的职责：`workflow/` 保存共享路由及契约，`profiles/` 保存阶段策略，`templates/` 保存交换格式样本，`skills/` 和 `agents/` 保存专业执行方法。宿主发现入口由 `scripts/kernel/hosts.py` 从这些来源生成。`migrations/` 只保存版本化数据库迁移；项目、素材字节、vendor 源码与本机状态分别归入其既有私有目录。

新增文件须明确所属目录、消费者和验证范围。共享代码应进入真正拥有规则的模块，禁止通过根目录转发文件或动态 facade 横跨多个领域。`tools/maintenance/` 只承担工程维护；可见命令统一归 `scripts/maintenance/`。测试只把源码根和工作区根加入 Python 路径，按领域／层级使用当前模块 ID。

v0.25.0 直接切换到分组命令路径，旧顶层脚本、模块别名、series 动态 facade 和旧测试选择别名均已删除。调用方应使用本文及 CLI 指南中的当前路径；安装包保持相同目录层级。作品固定版本、人工决定与存储权威沿既有协议保持。

## 依赖

Python 最低版本为 3.9。旧项目文件状态与内核路由保留标准库入口；应用初始化配置统一依赖 Dynaconf，入口为 `src/vsc/configuration.py`，默认值位于 `config/default/settings.toml`，本机值位于根目录 `.env`。数据库、媒体与素材库消费者通过该入口读取，禁止重复维护 dotenv 解析或默认值。新资源面板、PostgreSQL 和 S3 存储按需安装。

```bash
uv sync --locked --extra web --extra postgres --extra test
```

`pyproject.toml` 声明依赖边界，`uv.lock` 固定解析结果。修改依赖后更新锁文件。安装 S3 适配所需依赖时增加 `--extra storage`；字幕排版依赖使用 `--extra media`，其 Pillow 版本与字幕渲染器保持一致。完整本机验证使用 `uv sync --locked --all-extras`。

可用 `uv build --wheel` 构建安装包。安装包包含 Python 模块及只读工作流声明、模板和 PostgreSQL 迁移。使用完整创作工作区时，设置 `VSC_WORKFLOW_ROOT` 指向本仓库根目录，以复用宿主入口、本机 Vendor 和现有作品。密钥仍由进程环境传入，不能写入包或作品。

独立安装包的规范文件在虚拟环境的 `share/vsc-workflow/`。首次检查宿主发现入口前，运行该目录中的 `scripts/kernel/hosts.py sync`，再运行 `scripts/kernel/catalog.py doctor`；入口由既有生成器建立，不在 wheel 中保存多份角色或技能副本。数据库升级仍显式执行，安装和启动不会自动迁移正式 schema。

独立安装包包含根说明、插件版本声明和派生视图。首次使用其工作流声明时运行 `python -B -m vsc.kernel.hosts sync` 生成宿主发现入口，再运行 `python -B -m vsc.kernel.catalog doctor`；它们按当前工作流根定位，不依赖终端所在目录。完整工作区按 `VSC_WORKFLOW_ROOT` 选定根目录后执行相同检查。

## 验证

修改时根据源文件选择受影响测试：

```bash
python3 -B tests/run.py --files src/vsc/production/context.py --list
python3 -B tests/run.py --files src/vsc/production/context.py
```

测试影响分析同时识别领域包、维护工具、分组入口、共享夹具和动态契约校验器。脚本拥有独立 `scripts` 命名空间，避免与测试的领域包混淆；布局测试阻止顶层入口或动态别名重新堆积。最后提交并推送时才执行一次全量本地 CI，详见 [维护指南](maintenance.md)。
