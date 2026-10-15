# VSC 测试工程

测试使用 Python 标准库 `unittest`，兼容当前 Python 3.9，无额外测试框架依赖。统一入口是 [run.py](run.py)，分组、归属、非 import 输入及共享影响规则以 [config.json](config.json) 为准。现有 `test_*.py` 单文件入口和标准 `unittest discover -s tests` 仍可使用；维护与最终门禁使用统一入口，以同时检查配置完整性。

## 目录与职责

```text
tests/
  run.py                  # 薄命令入口
  config.json             # 测试模块归属、分层、显式输入与共享影响策略
  unit/                   # 新提取的纯规则与测试运行器回归
  support/
    runner.py             # 发现、配置校验、影响选择、计时、报告
    plans.py              # 每次返回独立逻辑规格的工厂
    legacy.py             # 历史 Profile 夹具；与通用路径引导分开
    project.py            # 项目与固定运行夹具
    production.py         # 离线生产夹具，无 test_* 方法
    media.py              # 每个进程只生成一次的小型不可变媒体字节
    review.py             # 审片文档工厂
  fixtures/profiles-v1/   # 历史 Profile 固定证据
  test_*.py               # 保留的既有测试；每个模块已在 config 中归属
  _paths.py               # 统一路径引导，无业务状态依赖
```

配置分为 `unit`（规则／内存替身，允许临时文件）、`integration`（数据库、媒体工具、适配器及模块接缝）和 `system`（CLI／Git／完整工作流）。混合模块可按类或方法覆盖层级；层级表示验证方式，不代表运行速度。既有文件逐步随实际修改提取，移动时保持测试 ID 与配置同步，避免只搬目录造成兼容导入变化。

## 修改期间的运行方式

从仓库根目录执行：

```bash
# 先查看影响范围，不运行 setUp、测试方法或媒体生成
python3 -B tests/run.py --files scripts/subtitles.py --list
python3 -B tests/run.py --changed --list

# 运行确定受影响的模块、类或方法
python3 -B tests/run.py --test unit.test_render_plan test_subtitles
python3 -B tests/run.py --test test_vsc_integrity.Integrity.test_changed_or_deleted_version_is_rejected_by_gate_and_context

# 按实际变更选择；--since 包含该 revision 之后及工作区的变更
python3 -B tests/run.py --files tests/support/production.py
python3 -B tests/run.py --since HEAD~1 --list

# 仅规则组；配置校验不会运行测试
python3 -B tests/run.py --layer unit
python3 -B tests/run.py --check-config

# 保存耗时与选择原因，报告写系统临时目录
python3 -B tests/run.py --test test_media_qa --durations 10 --report /tmp/vsc-test-report.json
```

`--changed` 取 `HEAD` 到当前工作区的暂存／未暂存差异及未跟踪文件。多个路径取影响并集；导入的公共夹具改变时包含其所有消费者。纯文档变更列出无需代码测试的原因，仍须做对应链接／引用检查。

影响选择结合本地 Python import 传递图、CLI／动态装载中的脚本文件名，以及配置中的非 import 来源。契约校验器从 `workflow/contracts.json` 解析，连接到内核／产物校验消费者，不复制一份校验器名单。配置和共享流程声明等广泛输入会选择较大范围；先用 `--list` 看计划。明确的小范围开发回归可用 `--test`，最终门禁覆盖全部。

未知路径、无消费者的代码、失效配置、删除后无法确认关系的文件会报错，要求补映射或显式选择；不会以“0 tests”假装验证成功。静态图不能证明运行时不存在额外依赖：新增 CLI、动态调用或数据输入时须同步补配置并审阅计划。

## 最终门禁

完成所有改动后，现有 pre-push 调用 `scripts/vsc_local_ci.py`，其中通过 `tests/run.py --all` 运行全部已发现测试并校验配置。启用钩子时不提前手动重复全量；未启用钩子时只在最终推送前执行一次本地 CI。门禁同时检查内核、项目兼容、素材库、Vendor 和文档等。

配置要求每个发现到的测试模块有负责人和默认层级，覆盖项必须命中真实类／方法，每个测试 ID 唯一。新增文件没有配置、移动后残留旧配置、拼错类名或发现导入失败，都会阻止运行。测试运行器的失败退出码和配置错误会传递给本地 CI。

输出分别列出测试方法数与 `subTest` 场景数。合并方法后场景仍逐一执行、失败时带名称；不要用方法数下降宣称覆盖等价或性能提升。耗时报告包含总耗时、每方法耗时、跳过数量和选择原因；类级夹具与运行器开销反映在总耗时中，不计入某个方法。

## 夹具与真实媒体规则

- 公共准备逻辑放 `support/`，新测试直接引用夹具，不从另一个 `TestCase` 借用生命周期方法。保留的旧夹具引用由影响图追踪。
- `production_media()` 仅缓存本次进程中的不可变 `bytes`，四类样本只生成一次；各测试的目录、数据库、预算和任务状态独立。缓存不保存探测结果，也不跨进程掩盖字节变化。
- 审片范围／ID／模式等规则在 unit 组显式替换技术报告复检接缝；真实媒体绑定、解码、范围、响度、损坏、篡改和过期版本在 integration 组通过实际工具验证。
- 生产代码的媒体复检行为保持真实执行；测试用合成报告和替身只能作为规则夹具，不能登记成项目质量证据。
- 并发、预算、防重复提交、崩溃恢复和迁移语义继续保留独立场景。新工程配置不会调用生成平台或安装工具；各测试原有工具缺失跳过规则仍生效。

## 本轮整理的覆盖对应

| 原覆盖 | 当前组织 |
|---|---|
| Remotion 范围、音量、错误类型、路径 4 个方法 | `unit/test_render_plan.py` 的 5 个具名场景；原各条错误断言保留 |
| 批准快照被修改／删除 | 完整性组同一准备基线的 2 个场景；分别恢复字节，均检查 Gate 与上下文消费 |
| 语音发音词条、无权限不重试 | `unit/test_voice_validation.py`；不再为这两个场景初始化数据库 |
| 审片范围、镜头／片段 ID、legacy／sample、成片版本 | `unit/test_media_review.py`；真实 structured 完整审片和篡改复检继续在 `test_media_qa.py` |
| 生产／正式运行／检查三组媒体样本 | 共用 `support/media.py` 的单进程字节工厂，工作目录仍各自创建 |

更完整的模块与 PostgreSQL 改造仍以[资源面板升级提案](../docs/plans/2026-10-15-project-resource-panel-engineering-upgrade.md)为候选；本次只实施测试工程调整。
