# VSC 测试工程

测试使用 Python 标准库 `unittest`，兼容 Python 3.9，无额外测试框架依赖。统一入口是 [run.py](run.py)，分组、归属、非 import 输入及共享影响规则以 [config.json](config.json) 为准。测试文件实际存放在 `tests/<领域>/<验证层级>/test_*.py`，通过统一入口按领域、层级、模块或具体方法运行。

## 目录与职责

```text
tests/
  run.py                  # 薄命令入口
  config.json             # 测试模块归属、分层、显式输入与共享影响策略
  assets/unit/            # 应用校验与受控存储
  assets/integration/     # 素材登记、复用、权属与真实 PostgreSQL
  kernel/integration/     # 内核路由、宿主入口与派生视图
  knowledge/
    unit/                 # 轻量检索
    integration/          # 方法试用、规格包与晋升
  maintenance/
    unit/                 # Vendor 路由规则
    integration/          # Vendor 生命周期、本地 CI
    system/               # 真实 Git 提交／恢复流程
  post/
    unit/                 # 字幕、渲染规格与审片规则
    integration/          # 真实媒体 QA、烧录、编辑器输出与交付
  production/
    unit/                 # Provider 契约、凭证与语音规则
    integration/          # 生成任务、预算、恢复、声音与选片
  project/unit/           # 权威指针、冻结与固定 Profile Gate
  project/integration/    # 网页、PostgreSQL、显式迁移
  project/system/         # 状态、批准、迁移与全流程
  story/
    unit/                 # 身份、状态、锚点和连续性规则
    integration/          # 连续性 CLI、表演与集场衔接
    system/               # 衔接产物经项目 CLI 登记与批准
  testing/unit/           # 测试发现、目录约束、选择与报告的回归
  support/
    runner.py             # 发现、配置校验、影响选择、计时、报告
    paths.py              # 唯一仓库根与 scripts 导入引导
    fixtures/             # 公共准备代码；不能导入测试模块
      consistency.py      # 连续性模板与独立副本工厂
      handoffs.py          # 覆盖、选片、声音与交付文档构造
      legacy.py            # 固定历史 Profile
      project.py           # 项目与固定运行
      production.py        # 离线生产候选与执行替身
      media.py             # 单进程不可变媒体字节
      plans.py             # 逻辑渲染／媒体计划
      review.py            # 审片文档
      vendor.py            # Vendor 策略数据
  fixtures/profiles-v1/   # 历史 Profile 固定证据
```

先按领域查找归属，再按 `unit`（规则／内存替身，允许临时文件）、`integration`（数据库、媒体工具、适配器及模块接缝）、`system`（CLI／Git／完整工作流）区分验证方式。层级表示测试范围，不承诺固定速度。目录只建立实际使用的层级，不预建空目录。

领域与层级必须和配置中的 `owner`、`layer` 一致；根目录平铺测试、额外嵌套、错误归属和混合层级 `overrides` 均会被拒绝。原连续性与媒体 QA 的混合文件已拆开。每层 Python 包保留 `__init__.py`，支持递归发现；缺少包标记导致未发现的文件会明确报错。

## 修改期间的运行方式

从仓库根目录执行：

```bash
# 先查看影响范围，不运行 setUp、测试方法或媒体生成
python3 -B tests/run.py --files scripts/subtitles.py --list
python3 -B tests/run.py --changed --list

# 运行确定受影响的模块、类或方法
python3 -B tests/run.py --test post.unit.test_render_plan post.unit.test_subtitles
python3 -B tests/run.py --test project.system.test_vsc_integrity.Integrity.test_changed_or_deleted_version_is_rejected_by_gate_and_context

# 按领域或领域内的层级运行
python3 -B tests/run.py --test post
python3 -B tests/run.py --test production.integration

# 按实际变更选择；--since 包含该 revision 之后及工作区的变更
python3 -B tests/run.py --files tests/support/fixtures/production.py
python3 -B tests/run.py --since HEAD~1 --list

# 仅规则组；配置校验不会运行测试
python3 -B tests/run.py --layer unit
python3 -B tests/run.py --check-config

# 保存耗时与选择原因，报告写系统临时目录
python3 -B tests/run.py --test post.integration.test_media_qa --durations 10 --report /tmp/vsc-test-report.json
```

原选择名（如 `--test test_subtitles`、`--test unit.test_render_plan`）通过配置中的 `aliases` 映射到新模块，具体类／方法后缀也可保留；拆分文件的旧名会覆盖原来两层的全部用例。别名只用于命令选择和迁移影响识别，Python 导入统一使用新路径。旧的 `python3 tests/test_*.py` 文件路径已移除；新文档使用统一入口。标准 `python3 -B -m unittest discover -s tests` 仍递归发现新目录，维护和门禁用统一入口同时检查配置。

`--changed` 取 `HEAD` 到当前工作区的暂存／未暂存差异及未跟踪文件。多个路径取影响并集；导入的公共夹具改变时包含其所有消费者。纯文档变更列出无需代码测试的原因，仍须做对应链接／引用检查。

影响选择结合本地 Python import 传递图、CLI／动态装载中的脚本文件名，以及配置中的非 import 来源。契约校验器从 `workflow/contracts.json` 解析，连接到内核／产物校验消费者，不复制一份校验器名单。配置和共享流程声明等广泛输入会选择较大范围；先用 `--list` 看计划。明确的小范围开发回归可用 `--test`，最终门禁覆盖全部。

未知路径、无消费者的代码、失效配置、删除后无法确认关系的文件会报错，要求补映射或显式选择；不会以“0 tests”假装验证成功。静态图不能证明运行时不存在额外依赖：新增 CLI、动态调用或数据输入时须同步补配置并审阅计划。

## 最终门禁

完成所有改动后，现有 pre-push 调用 `scripts/vsc_local_ci.py`，其中通过 `tests/run.py --all` 运行全部已发现测试并校验配置。启用钩子时不提前手动重复全量；未启用钩子时只在最终推送前执行一次本地 CI。门禁同时检查内核、项目兼容、素材库、Vendor 和文档等。

配置 v2 要求每个发现到的测试模块有领域归属和层级，模块路径与配置一致，别名目标存在，每个测试 ID 唯一。新增文件没有配置、移动后残留旧配置、平铺回根目录或发现导入失败，都会阻止运行。测试文件和公共夹具禁止导入其他 `test_*` 模块；需要共享的准备逻辑进入 `support/fixtures/`。测试运行器的失败退出码和配置错误会传递给本地 CI。

输出分别列出测试方法数与 `subTest` 场景数。合并方法后场景仍逐一执行、失败时带名称；不要用方法数下降宣称覆盖等价或性能提升。耗时报告包含总耗时、每方法耗时、跳过数量和选择原因；类级夹具与运行器开销反映在总耗时中，不计入某个方法。

## 夹具与真实媒体规则

- 公共准备逻辑放 `support/fixtures/`，测试直接引用夹具；跨测试文件借用已清除，并由结构检查阻止重新引入。
- `production_media()` 仅缓存本次进程中的不可变 `bytes`，四类样本只生成一次；各测试的目录、数据库、预算和任务状态独立。缓存不保存探测结果，也不跨进程掩盖字节变化。
- 审片范围／ID／模式等规则在 unit 组显式替换技术报告复检接缝；真实媒体绑定、解码、范围、响度、损坏、篡改和过期版本在 integration 组通过实际工具验证。
- 生产代码的媒体复检行为保持真实执行；测试用合成报告和替身只能作为规则夹具，不能登记成项目质量证据。
- 并发、预算、防重复提交、崩溃恢复和迁移语义继续保留独立场景。新工程配置不会调用生成平台或安装工具；各测试原有工具缺失跳过规则仍生效。

## 本轮整理的覆盖对应

| 原覆盖 | 当前组织 |
|---|---|
| Remotion 范围、音量、错误类型、路径 4 个方法 | `post/unit/test_render_plan.py` 的 5 个具名场景；原各条错误断言保留 |
| 批准快照被修改／删除 | 完整性组同一准备基线的 2 个场景；分别恢复字节，均检查 Gate 与上下文消费 |
| 语音发音词条、无权限不重试 | `production/unit/test_voice_validation.py`；不再为这两个场景初始化数据库 |
| 审片范围、镜头／片段 ID、legacy／sample、成片版本 | `post/unit/test_media_review.py`；真实 structured 完整审片和篡改复检在 `post/integration/test_media_qa.py` |
| 生产／正式运行／检查三组媒体样本 | 共用 `support/fixtures/media.py` 的单进程字节工厂，工作目录仍各自创建 |

后续模块与 PostgreSQL 改造已按[工程升级方案](../docs/plans/2026-10-15-project-resource-panel-engineering-upgrade.md)实施，见[资源面板指南](../docs/guide/resource-panel.md)。原测试整理的对应记录保留。

## 可选数据库与网页验证

核心测试使用标准库；网页／PostgreSQL 专项使用 `uv sync --locked --all-extras` 声明的依赖。`VSC_TEST_DATABASE_URL` 必须显式指向允许创建临时 schema 的测试实例，测试自行创建随机 schema 并清理。缺少变量或依赖会报告 skipped，不能当作真实数据库验证通过。新预览专项使用实际 FFmpeg／Poppler；离线 Provider 替身不产生线上计费。

影响分析覆盖 `src/vsc/`、`tools/maintenance/` 与兼容 `scripts/`。修改期间只运行受影响模块；最终提交／推送由钩子运行一次全量，不额外重复。
