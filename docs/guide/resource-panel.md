# 内建资源面板与 PostgreSQL 连续短剧

资源面板是 VSC 自带应用。它展示项目产出、文案、用途和审查记录；`vsc-schema-review` 只用于维护建表 SOP。

## 安装与启动

在工作流根目录执行，依赖与版本由 `pyproject.toml` / `uv.lock` 跟踪：

```bash
uv sync --locked --all-extras
.venv/bin/vsc-panel
```

浏览 `http://127.0.0.1:8765`。无需数据库即可只读查看已有 JSON/SQLite 项目。项目树显示已登记的关系，未登记文件单列；不根据目录猜测角色、镜头或素材用途。传统 CLI 的 Python 标准库运行方式保留。

PostgreSQL 可选依赖与 FFmpeg/ffprobe 是新生产路径的运行依赖；PDF 首页预览另需 Poppler。没有转换器时显示元数据并允许受控下载，不冒充预览成功。

## 新建数据库项目

在 `~/.zshenv` 配置 `VSC_DATABASE_URL`（PostgreSQL 连接）和可选 `VSC_MEDIA_ROOT`（受控媒体根），由启动进程显式加载。不要把连接凭据写进项目或源码。应用启动只检查 schema，不自动建表；首次明确执行迁移：

```bash
.venv/bin/python -B scripts/vsc_schema.py migrate --database-env VSC_DATABASE_URL
.venv/bin/python -B scripts/vsc_state.py init projects/新项目 --title 新项目 --profile vsc.series-pg --owner 实际负责人
.venv/bin/python -B scripts/vsc_resources.py projects
```

新项目只保存 `.vsc-postgres.json` 权威指针，事实在 PostgreSQL；单部项目默认建立 `W001`，可通过 `create_object` 增加部、集、场、序列和镜。指针不保存数据库连接值。旧 Profile 快照不因安装更新而改变。

## 共享应用接口

网页、CLI 和 AI 都调用 `ResourceService`。查询入口包括 `tree`、`artifacts`、`media`、`context`、`status`、`gate`。写入使用明确动作和 JSON 输入：

```bash
.venv/bin/python -B scripts/vsc_resources.py tree PROJECT_UUID
.venv/bin/python -B scripts/vsc_resources.py context PROJECT_UUID SHOT_UUID --purpose video_clip
.venv/bin/python -B scripts/vsc_resources.py asset-context PROJECT_UUID ASSET_UUID --purpose asset_ref
.venv/bin/python -B scripts/vsc_resources.py apply PROJECT_UUID create_object --payload object.json --expected-revision 1 --key create-episode-001 --by 实际负责人
```

`object.json` 示例：

```json
{"kind":"episode","display_code":"E001","title":"第一集","parent_id":"WORK_UUID","ordinal":0}
```

每次写操作返回新 `revision`。并发旧 revision 返回 409；相同幂等键与相同输入返回原结果，不重复写决定。对象关系必须属于同一项目；稳定 UUID 与展示编号分离。

产物正文、版本、摘要和依赖不可变。创建新版本后真实人工批准才能切换当前投影；旧批准和历史用料继续保存。`vsc.*` 产物继续执行已有契约检查。`gate` 使用项目固定 Profile 和当前有效批准版本，不把有文件等同于通过。

## 素材登记、审查与选择

1. 通过上传或 CLI `stage FILE` 暂存字节；系统计算摘要、解码并归档到受控内容寻址位置。登记使用 `staged_upload` 凭据，不能从网页传任意服务器路径。
2. 登记素材的项目语境、来源证据与权利范围。同一 blob 可有不同的素材登记、权利和用途；去重不合并这些语义。
3. 建立用途槽位与候选。槽位由目标对象、用途与非空 `slot_key` 唯一确定；变体、台词覆盖和声轨有显式关系。
4. 技术检查与具名人工审查分别记录。正式选择要求可用字节、适用权利、通过的技术检查和该候选的人工审查，且在同一事务更新当前用途。
5. 拒绝候选、退役用途、停用素材分别操作。记录可反查来源、合成图层、任务、时间线、渲染和历史选择；面板不删除二进制文件。

写入面板由实际使用者运行 `vsc-panel --human 实际负责人`，再使用本次控制台凭据建立操作会话。操作身份来自会话，选择与停用需要确认。默认只读。服务仅绑定本机地址，并验证 Host、Origin、CSRF；文本采用自然中文换行并按纯文本安全展示。

## 制作与预览任务

模型注册通过 `registry provider|model|route --payload FILE --by 人员`。业务请求使用统一图像／视频／音频契约，不包含 SDK 参数或临时 URL。模型版本、能力、默认参数、批准的运行计划、固定媒体和版本关系都会进入任务快照。

正式 Profile 还要求先通过 `apply PROJECT_UUID configure_budget` 配置项目原生单位额度，输入为 `{"limits":{"remote_jobs":100,"images":30,"video_seconds":120,"speech_chars":2000,"audio_jobs":30,"vision_jobs":0},"reason":"经负责人确认的试点上限"}`。`budget PROJECT_UUID` 查询占用；实际提交在项目锁内预留，未知结果继续占用。实际用量和货币成本没有证据时保留未知，不把上限当实测值。

```bash
# 明确执行一个已批准运行计划中的任务；此命令可能产生在线调用
.venv/bin/python -B scripts/vsc_resources.py worker --project-id PROJECT_UUID
# 轮询已有外部任务，不重新 POST
.venv/bin/python -B scripts/vsc_resources.py worker --project-id PROJECT_UUID --poll
# 已有成功响应但转存中断时，只恢复下载／归档
.venv/bin/python -B scripts/vsc_resources.py worker --project-id PROJECT_UUID --resume JOB_UUID
# 本地预览转换队列
.venv/bin/python -B scripts/vsc_resources.py preview-worker --maximum 20
```

提交前持久记录意图，结果未知不自动重提。Provider 成功响应先入库，再下载临时 URL 或解码内联数据；输出完成转存和摘要检查后任务才成功。生成输出保持未知权利／未选用，人工确认后才能下游引用。

预览队列支持缩略图、视频海报、波形、H.264 代理视频和 PDF 首页。配方、工具版本、来源摘要绑定到 `media_renditions`，不污染源 blob 的事实；预览不会成为获批生产素材。崩溃后的租约恢复有 attempt 围栏，失败任务明确重试。

首个人物参考图／场景母版从已批准身份规格编译 `asset-context`，无需已有自身参考；图像资产任务显式给 `asset_id`，镜头任务给 `shot_id`，数据库约束二选一。资产准备守剧本 Gate，镜头生产守预演 Gate，两者都需要正式 run 和预算。声音复刻能力没有实现时仍保持不可用。

已冻结时间线通过 `render-export PROJECT_UUID TIMELINE_UUID --out DIRECTORY` 导出可迁移的渲染输入包，媒体按固定选择决定与 SHA 复制，原批准计划中的字幕、转场和样式保留。可加 `--remotion-out EDITOR_DIRECTORY` 一并准备含固定媒体的 Remotion 工程，或用 `remotion_plan.py scaffold PLAN OUTPUT` 接续已有编辑器。导出是只读投影，成功不代表浏览器渲染或人工审片已经通过。

## 旧项目迁移与权威切换

已有项目默认只读浏览，不自动迁移。`vsc_resources.py migrate PROJECT ACTION` 支持 `preview`、`backup`、`freeze`、`import`、`compare`、`cutover`、`status`；详见命令 `--help` 与 [迁移指南](resource-migration.md)。

迁移使用逐项证据与 typed-row 映射。缺少部／层级、来源、权利、历史决定或任务输入时报告缺口，不能用目录推断或 AI 批准补齐。导入核对前不切换；冻结阻止旧写，切换后旧入口拒绝写入，数据库不可用时不回退 JSON/SQLite。

## 验证边界

新关系库使用真实隔离 PostgreSQL 测试；测试库变量是 `VSC_TEST_DATABASE_URL`，随机 schema 在测试后删除。受影响测试按领域运行：

```bash
.venv/bin/python -B tests/run.py --test assets.integration.test_resource_store project.integration.test_resource_panel_postgres production.integration.test_resource_worker
```

本次工程验证不调用火山方舟。离线 Provider、真实媒体工具和合成规模数据验证关系与执行行为；用户提供脚本后的线上生成、音色／风格／叙事连续性和成片人审仍是制作验收。
