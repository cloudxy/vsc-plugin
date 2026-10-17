# 按职责组织的命令入口

每个 Python 文件只负责加载工作区并调用所属模块的 `main`。业务实现和测试直接使用 `src/vsc/` 的领域包；工程维护实现放在 `tools/maintenance/`。顶层保留此索引，命令归入下表目录。

| 目录 | 职责 | 主要入口 |
| --- | --- | --- |
| `kernel/` | 工作流路由、契约、宿主与规范派生 | `catalog.py`、`hosts.py`、`views.py` |
| `project/` | 项目状态、产物、依赖影响与 schema 维护 | `state.py`、`artifacts.py`、`impact.py`、`schema.py` |
| `story/` | 剧本与叙事、镜头衔接、连续性校验 | `script.py`、`sequence.py`、`scripts/story/consistency.py` |
| `assets/` | 素材库、资源登记与场镜关系查阅 | `library.py`、`resources.py`、`workbench.py` |
| `production/` | 计划、运行、任务、调度、预算与质量 | `plan.py`、`run.py`、`jobs.py`、`quality.py` |
| `providers/<服务方>/` | 供应商直接调用；新增供应商拥有独立目录 | `volcengine/ark.py`、`volcengine/speech.py`、`volcengine/audio.py`、`xai/grok.py` |
| `media/` | 本机媒体检查、工具检查与临时声轨 | `qa.py`、`toolchain.py`、`scripts/media/temp_voice.py`、`scripts/media/procedural_audio.py` |
| `post/` | 选片、剪辑导出、字幕与交付 | `selection.py`、`export.py`、`scripts/post/remotion_plan.py`、`delivery.py` |
| `knowledge/` | 创作方法、规格、学习与检索 | `craft.py`、`recipes.py`、`learning.py`、`search.py` |
| `maintenance/` | 官方更新、Vendor、Git 钩子与本地 CI | `provider_sync.py`、`scripts/maintenance/vendor_sync.py`、`local_ci.py`、`pre_commit.py` |

从工作流根目录运行：

```sh
python3 -B scripts/kernel/catalog.py doctor
python3 -B scripts/project/state.py status projects/作品名
python3 -B scripts/assets/workbench.py PROJECT_ID --section overview
python3 -B scripts/maintenance/provider_sync.py --help
```

新增命令先确定归属与真实 `main`；只有可导入函数的库直接留在所属包。调用方使用分组路径，Python 代码通过严格的 `script_path("project/state.py")` 定位；不增加顶层命令、旧路径别名、软链接或兼容导入。布局检查覆盖入口归属、工作区外启动和路径逃逸；打包时维持相同子目录。

全项目目录职责、依赖与验证见[代码结构指南](../docs/guide/code-structure.md)。
