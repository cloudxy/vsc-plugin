# 内建资源面板与 PostgreSQL 连续短剧

资源面板是 VSC 自带应用。首页以工作台呈现待审文案、可播放结果、意见和制作进度；`vsc-schema-review` 只用于维护建表 SOP。

## 从作品和待办开始

主导航提供四个入口：

| 入口 | 用途 |
| --- | --- |
| 工作台 | 在“待我审阅”“制作进度”“已有结果”之间切换，选择一项后直接阅读或播放，在旁边记录意见与回看本轮结果 |
| 项目 | 选择已有作品；登录后建立 PostgreSQL 项目，再进入“创意与原稿”整理输入 |
| 素材库 | 浏览当前项目的素材，打开分类资产、全部素材或关系画布 |
| 回收站 | 查看已回收登记并恢复，或先预览同字节重复登记的回收影响 |

剧本编辑、场镜设计、候选比较、剪辑交付、文案版本和关系画布集中在“专业工具”。原有对象和版本深链保留，工作台链接可固定项目、范围、对象与版本。正文、列表和意见分别滚动；窄屏通过“返回列表”“作品”“意见与结果”切换。

“记录意见”只保存原话；有受控执行能力的对象提供“修改后给我看”。批量审核只处理本页实际勾选的固定文案版本，逐项返回结果，不自动采用候选或发布成片。对象已有新版本时先核对当前内容；已有旧基线结果保留供比较，不覆盖新稿。

## 安装与启动

在工作流根目录执行，依赖与版本由 `pyproject.toml` / `uv.lock` 跟踪：

```bash
uv sync --locked --all-extras
.venv/bin/vsc-panel
```

浏览 `http://127.0.0.1:8765`。无需数据库即可只读查看已有 JSON/SQLite 项目。项目树显示已登记的关系，未登记文件单列；不根据目录猜测角色、镜头或素材用途。传统 CLI 的 Python 标准库运行方式保留。

默认启动为只读，后台制作不启动。需要编辑时，可由实际负责人运行 `.venv/bin/vsc-panel --human 实际负责人 --open`；也可在 `config/.env` 显式配置 `VSC_PANEL_WRITABLE=true` 和 `VSC_PANEL_HUMAN_IDENTITY`，以后通过 `.venv/bin/vsc-panel --open` 启动。`--open` 使用短时、单次、本机同源引导建立会话，页面随即清除引导信息。未带 `--open` 时沿原入口输入本次控制台凭据。登录不能把只读启动或旧项目变成可写项目。

结构导航的所有分支初始收拢。点击箭头展开或收拢，点击节点名称筛选文案与素材；展开按钮支持键盘操作。同项目刷新保留手动展开状态，切换项目重新收拢。

“文案与版本”中的版本列表与正文分别滚动。点击列表项会标记正在阅读的版本；标题使用可读名称，版本和批准状态辅助区分。JSON 文案按字段、段落和条目展示，长内容保持完整；正文直接起读，技术信息按需展开。固定版本的批准、退回与局部制作方案入队仍遵循原会话、版本和确认规则。

PostgreSQL 可选依赖与 FFmpeg/ffprobe 是新生产路径的运行依赖；PDF 首页预览另需 Poppler。没有转换器时显示元数据并允许受控下载，不冒充预览成功。

## 新建数据库项目

在工作区 `config/.env` 配置 `VSC_DATABASE_URL`（应用独立读写账号的 PostgreSQL 连接）和可选 `VSC_MEDIA_ROOT`（受控媒体根），由 Dynaconf 在启动时自动读取。新工作区可复制 `config/.env.example`；真实文件不提交、不打包。MCP 正式库使用独立只读账号，不影响应用的增删改查与显式结构迁移能力。应用启动只检查 schema，不自动建表；首次明确执行迁移：

```bash
.venv/bin/python -B scripts/project/schema.py migrate --database-env VSC_DATABASE_URL
.venv/bin/python -B scripts/project/state.py init projects/新项目 --title 新项目 --profile vsc.series-pg --owner 实际负责人
.venv/bin/python -B scripts/assets/resources.py projects
```

新项目只保存 `.vsc-postgres.json` 权威指针，事实在 PostgreSQL；单部项目默认建立 `W001`，可通过 `create_object` 增加部、集、场、序列和镜。指针不保存数据库连接值。旧 Profile 快照不因安装更新而改变。

## 共享应用接口

网页、CLI 和 AI 都调用 `ResourceService`。查询入口包括 `tree`、`artifacts`、`media`、`context`、`status`、`gate`。写入使用明确动作和 JSON 输入：

```bash
.venv/bin/python -B scripts/assets/resources.py tree PROJECT_UUID
.venv/bin/python -B scripts/assets/resources.py context PROJECT_UUID SHOT_UUID --purpose video_clip
.venv/bin/python -B scripts/assets/resources.py asset-context PROJECT_UUID ASSET_UUID --purpose asset_ref
.venv/bin/python -B scripts/assets/resources.py apply PROJECT_UUID create_object --payload object.json --expected-revision 1 --key create-episode-001 --by 实际负责人
```

`object.json` 示例：

```json
{"kind":"episode","display_code":"E001","title":"第一集","parent_id":"WORK_UUID","ordinal":0}
```

每次写操作返回新 `revision`。并发旧 revision 返回 409；相同幂等键与相同输入返回原结果，不重复写决定。对象关系必须属于同一项目；稳定 UUID 与展示编号分离。

产物正文、版本、摘要和依赖不可变。创建新版本后真实人工批准才能切换当前投影；旧批准和历史用料继续保存。`vsc.*` 产物继续执行已有契约检查。`gate` 使用项目固定 Profile 和当前有效批准版本，不把有文件等同于通过。

## 剧本工作区与人工确认（v0.27.0）

从“专业工具 → 剧本编辑”进入可变工作副本与人工确认流程：

1. **编辑与自动保存**：场次、行动、对白、静默逐行编辑，防抖自动保存到同一工作副本（`script_drafts`），有自己的 `draft_revision` 乐观并发序号；不产生正式文案版本，也不占用项目 revision。并发写入过期修订会以 409 报 `draft_revision_conflict`，页面提示先对比并加载最新，不静默覆盖他人内容。
2. **批注**：行级批注锚定场次／行身份，解决、忽略与重开都是显式决定；批注不进入剧本正文，解决批注也不等于批准剧本。
3. **差异比较与修订影响**：与已批准基线（或指定版本）比较场次增删移与行级文本／说话人/引用/静默字段变化，提交前可核对实际改动；待确认面板同时列出该修订影响的覆盖镜头、声音 Cue 与时间线用料（缺关系标为待核实）。
3a. **修改建议**：填写目标后，通过已登录的本机 Grok Build 生成局部建议；这是文本宿主调用，与 Imagine 图片／视频供应商分开。调用固定稿次、正文摘要与稳定场／行身份，先记调用和结果；相同目标与稿次恢复原调用，明确新增一轮才使用新调用额度。同批不重叠建议可逐处接受和撤销；普通编辑或目标字段变化会阻断旧建议。接受建议不等于批准剧本。
4. **提交人工确认**：当前内容在同一事务冻结为不可变 `screenplay` 版本并停在"待人工确认"；批准／退回走既有 artifact 决定（须确认会话与说明）。批准后该范围才能登记后续阶段（导演设计、资产规格、预演等）的正式产物——未确认时统一以 `script_confirmation_required` 拒绝，CLI、网页与 API 同一入口；在途任务与既有 Gate 规则不变。分集剧本按集确认；项目级产物需要项目级剧本确认。
5. 创作工作台概览的"剧本确认"区块显示各范围草稿修订、状态（编辑中／待人工确认／已批准／已退回）与批注数。

隔离 Chromium 已走通空稿选择来源／场次、建议接受、比较、冻结正文确认、102集导航、切换保稿、500／并发冲突恢复和390像素布局。浏览器使用合成输入与离线建议夹具；Grok Build文本调用另有真实接口验收，不能抵扣实际作品的创作判断。

## 按原意见处理与回看

意见保留在正在审阅的对象上，处理记录连接原建议、局部方案或专业派单；刷新后仍从同一位置回看。不会因为提出建议、派单或任务成功就自动解决意见、批准文案或采用素材。

- 剧本行批注：点击“按此意见提出局部修改”，固定所见稿次、正文摘要和场／行身份，在原差异区逐处接受或拒绝。普通恢复复用原调用；“明确新一轮局部修改”才发起新调用。原意见超过自动建议的2000字范围时完整保留，并提示另写一条聚焦本行的意见。
- 声音候选：在原素材意见下点击“按原参数重做本镜声音”，先预览一个镜头的目标和影响，再提交待审方案。用途沿原音频任务锁定，批准后才能入队；新输出回到原意见区供试听和决定采用。声线、演法等额外要求需声音负责人落实，原参数重做不代表已经理解并实现这些变化。
- 导演设计、资产规格与实例：在固定文案阅读区选择所见位置、填写原意见，再交给对应专业角色。派单固定原版本和范围，专业执行者沿原 context consume／return 接续，返回实际原类型的新产物后才能出现“回看专业修改结果”。当前提供可执行派单与结果关联，不自动启动外部 AI 宿主。
- 成片字幕与剪辑：意见绑定所见渲染、输出、媒体摘要和帧范围。满足下节条件的单条字幕位置修改可直接启动后台预览并回到原意见；其他剪辑要求继续交给后期角色。新结果仍须重新预览和审片。

局部方案、任务和新媒体的状态来自原权威记录；结果未知时先核实，不通过刷新重复调用。旧 JSON／SQLite 项目继续只读。当前工作台、修改预览与回收需要显式迁移到 `0012_assisted_workflow`；应用启动只检查，不自动迁移，连接配置、端口、库名及原权限配置保持原值。

## 单条字幕修改到新预览

在可编辑样片上选择一条字幕，填写“上移”“下移”“顶部”“居中”或“底部”中的一个明确方向，点击“修改后给我看”。本地后台执行器固定原计划、字节和整条字幕区间，生成草稿计划及可播放的局部预览，结果回到原意见。关闭网页后任务仍可继续；重新打开可恢复查看。

首版需要已登记且可核验的无字幕合成底片（clean master）、原字幕字体和固定渲染计划；底片的画幅、时长、时间基准和无字幕生产回执必须匹配计划，相关来源与权利检查须有效。使用正式字幕包时还会核验其原剧本、Cue、音频与采用关系。缺底片、字体或执行工具时显示具体缺项，不能在已经烧录字幕的样片上再次叠字，也不会把第一条镜头当作整集底片。

此入口仅调整所选字幕位置。原素材字节不改写；派生预览会转码并截取固定区间。无 clean master 的多镜头重合成、其他剪辑或任意文本改写仍须沿专业工具处理。草稿计划和预览不自动成为获批计划、正式渲染或交付结果；接受内容和正式采用沿原批准、冻结与审片流程。

专业执行器为已有无字幕底片生成带字幕样片时，使用原后期入口，自动登记固定底片、字体与真实烧录回执，无需手写证明 JSON：

```bash
python3 -B scripts/post/subtitle_burn.py caption-render PROJECT_ID \
  --timeline-id TIMELINE_ID --artifact-id ARTIFACT_ID \
  --clean-master-media-id MEDIA_ID --font-media-id FONT_ID \
  --expected-revision N --key OPERATION_KEY --by ACTOR
```

该命令消费已批准的计划和时间线，只生成本地字幕烧录及原正式冻结记录；不是新的批准入口。失败预览可在原意见下重试同一任务；已经返回的草稿不会挡住基于原样片的另一轮独立字幕意见，人工新增计划仍触发版本核对。

## 素材登记、审查与选择

1. 通过上传或 CLI `stage FILE` 暂存字节；系统计算摘要、解码并归档到受控内容寻址位置。登记使用 `staged_upload` 凭据，不能从网页传任意服务器路径。
2. 登记素材的项目语境、来源证据与权利范围。同一 blob 可有不同的素材登记、权利和用途；去重不合并这些语义。
3. 建立用途槽位与候选。槽位由目标对象、用途与非空 `slot_key` 唯一确定；变体、台词覆盖和声轨有显式关系。
4. 技术检查与具名人工审查分别记录。正式选择要求可用字节、适用权利、通过的技术检查和该候选的人工审查，且在同一事务更新当前用途。
5. 拒绝候选、退役用途、停用素材分别操作。记录可反查来源、合成图层、任务、时间线、渲染和历史选择；面板不删除二进制文件。

写入须先按安装与启动部分建立实际操作人的会话；选择与停用需要确认。服务仅绑定本机地址，并验证 Host、Origin、CSRF；文本采用自然中文换行并按纯文本安全展示。

## 重复内容与可恢复回收

在回收站打开“整理重复内容”，查看同字节的重复登记，手动勾选后预览影响，再执行回收。正在采用、被制作任务固定引用、用于剪辑或渲染等素材会显示保护原因并保留。批量处理逐项返回结果；不会凭外观相似自动合并素材、来源或权利。

回收仅改变当前项目的登记状态，保留原始 blob、来源、历史意见与决定；其他项目共用同一字节仍可读取。在回收站恢复不会自动重新采用。当前没有永久删除或物理清理功能，释放磁盘空间为 **0 字节**。

## 制作与预览任务

模型注册通过 `registry provider|model|route --payload FILE --by 人员`。业务请求使用统一图像／视频／音频契约，不包含 SDK 参数或临时 URL。模型版本、能力、默认参数、批准的运行计划、固定媒体和版本关系都会进入任务快照。

视频的音频参考使用独立 `reference_audio` 用途绑定与 `reference_audio_media_ids` 请求字段，模型须声明 `reference_audio` 能力。图像参考字段不能夹带音频；参考模式可组合图像和音频，硬首尾帧模式保持独立。视频是否生成原声由固定模型默认参数决定，不能在后期同时播放独立对白与重复的生成对白。

正式 Profile 还要求先通过 `apply PROJECT_UUID configure_budget` 配置项目原生单位额度，输入为 `{"limits":{"remote_jobs":100,"images":30,"video_seconds":120,"speech_chars":2000,"audio_jobs":30,"vision_jobs":0},"reason":"经负责人确认的试点上限"}`。`budget PROJECT_UUID` 查询占用；实际提交在项目锁内预留，未知结果继续占用。实际用量和货币成本没有证据时保留未知，不把上限当实测值。

可写面板的后台生成执行器持续领取 PostgreSQL `production-v2` 项目中已有批准和预算的任务，自动轮询、下载、解码及登记；普通使用无需逐任务运行命令。执行前再次核对固定输入、批准、供应商／模型及既有预算，沿原账号路线调用。旧 Profile 不由常驻生成执行器自动启动，仍保留原显式执行方式。

在工作台“制作进度 → 后台执行状态”查看执行器是否启动。暂停后续制作只影响**本次服务的全部项目**：停止启动新生成提交及新的字幕预览，已提交远端生成继续追踪；它不是远端取消，也不是跨重启的项目暂停决定。继续制作恢复本次调度；重启按启动配置恢复。停止服务时未结束的远端任务保留真实状态与可能费用，不能因为关页或停服务就记作取消。

后台使用可续租的执行归属与轮次校验，旧实例失去租约后不能完成新轮次任务。项目与供应商采用保守的各一个在途执行步骤上限，轮询和单任务失败有持久退避。未知提交不自动重投；已有持久成功响应而转存中断的任务只恢复存储。其他未知结果由已验证人工会话依据真实回执对账。

维护或明确单次执行时仍可使用：

```bash
# 明确执行一个已批准运行计划中的任务；此命令可能产生在线调用
.venv/bin/python -B scripts/assets/resources.py worker --project-id PROJECT_UUID
# 轮询已有外部任务，不重新 POST
.venv/bin/python -B scripts/assets/resources.py worker --project-id PROJECT_UUID --poll
# 已有成功响应但转存中断时，只恢复下载／归档
.venv/bin/python -B scripts/assets/resources.py worker --project-id PROJECT_UUID --resume JOB_UUID
# 本地预览转换队列
.venv/bin/python -B scripts/assets/resources.py preview-worker --maximum 20
```

提交前持久记录意图，结果未知不自动重提。Provider 成功响应先入库，再下载临时 URL 或解码内联数据；输出完成转存和摘要检查后任务才成功。生成输出保持未知权利／未选用，人工确认后才能下游引用。

预览队列支持缩略图、视频海报、波形、H.264 代理视频和 PDF 首页。配方、工具版本、来源摘要绑定到 `media_renditions`，不污染源 blob 的事实；预览不会成为获批生产素材。崩溃后的租约恢复有 attempt 围栏，失败任务明确重试。

首个人物参考图／场景母版从已批准身份规格编译 `asset-context`，无需已有自身参考；图像资产任务显式给 `asset_id`，镜头任务给 `shot_id`，数据库约束二选一。资产准备守剧本 Gate，镜头生产守预演 Gate，两者都需要正式 run 和预算。声音复刻能力没有实现时仍保持不可用。

已冻结时间线通过 `render-export PROJECT_UUID TIMELINE_UUID --out DIRECTORY` 导出可迁移的渲染输入包，媒体按固定选择决定与 SHA 复制，原批准计划中的字幕、转场和样式保留。可加 `--remotion-out EDITOR_DIRECTORY` 一并准备含固定媒体的 Remotion 工程，或用 `scripts/post/remotion_plan.py scaffold PLAN OUTPUT` 接续已有编辑器。导出是只读投影，成功不代表浏览器渲染或人工审片已经通过。

## 显式委托 AI 选择素材

默认正式选择仍要求同一用途的人工审查通过。用户可另行批准 `vsc.review_delegation` 产物，契约为 `vsc.review-delegation/v1`，明确 `project_id`、`grantor_actor`、`delegate_actor`、`allowed_roles`、带时区的 `expires_at`、`action: "select_candidate"` 与 `final_release_authorized: false`。登记必须给出 `object_ids`，不得使用项目级隐含范围；层级对象覆盖其后代，资产身份须显式列出。只有固定委托人能够批准或撤销政策，受托 AI 不能自批。

受托人调用 `record_review` 时保留 `reviewer_type: "ai"`，并固定与候选一致的 `context_sha256`；调用 `select_candidate` 时显式传入 `candidate_id`、`delegation_artifact_id`、`review_id` 和 `reason`。服务核验受控存储实际字节、权利、技术检查、政策批准、有效期、对象和用途范围，以及本人最新 AI 审查。人工拒绝或要求修改会阻断委托选择。缺少委托时，AI 审查不能替代人工审查。

`binding_selection_delegations` 的一行表示一次选择决定使用的固定委托政策、批准决定与 AI 审查，主键是项目和选择决定，所有对象关联采用项目内复合外键且记录不可变。`get_media_usage` 的 `selection_delegations` 可逆查这些证据。操作授权、AI 审查和实际人工观看分别记录；该政策不授予最终发布权，也不形成成片人审通过事实。已有数据库需显式升级到 `0002_review_delegation`，旧批准与选择历史保持原样。

## 旧项目迁移与权威切换

已有项目默认只读浏览，不自动迁移。`scripts/assets/resources.py migrate PROJECT ACTION` 支持 `preview`、`backup`、`freeze`、`import`、`compare`、`cutover`、`status`；详见命令 `--help` 与 [迁移指南](resource-migration.md)。

迁移使用逐项证据与 typed-row 映射。缺少部／层级、来源、权利、历史决定或任务输入时报告缺口，不能用目录推断或 AI 批准补齐。导入核对前不切换；冻结阻止旧写，切换后旧入口拒绝写入，数据库不可用时不回退 JSON/SQLite。

## 验证边界

测试通过 `VSC_TEST_DATABASE_URL` 连接专用测试库，使用随机 schema 并在结束后删除。数据库与连接配置统一见[工作区接入](workspace-setup.md#本机数据库一个实例两个数据库)。受影响测试按领域运行：

```bash
.venv/bin/python -B tests/run.py --test assets.integration.test_resource_store project.integration.test_resource_panel_postgres production.integration.test_resource_worker
```

本版新增路径通过真实隔离 PostgreSQL、离线 Provider、真实媒体工具和合成输入验证关系、后台执行与恢复。没有为本版新增线上供应商用量验证；工具验证不代表普通用户可用性、作品音色／风格／叙事连续性或成片人审已通过，相关结论须有各自的实际证据。

文本建议宿主保留 Grok Build 订阅登录路线，使用无工具、禁子代理和禁搜索的单轮结构输出；子进程只接收最小环境，并设时间和输出上限，不继承数据库、人工会话或无关供应商密钥。该路线不授予模型数据库写入、素材采用或人工批准权限。

## 资源配置与画布

顶栏“资源配置”管理全局模型与默认用途；从“素材库 → 专业工具 → 关系画布”进入原无限画布。操作与能力边界见 [资源配置与官方更新](resource-settings.md)。

## 固定字幕交接

`render-export`正式导出从批准剧本、Cue和真实采用决定编译`subtitles.json`；测量必须指向所选音频SHA、源区间、具体方法和逐行时码。同句多次按行身份覆盖，换音频或转码后旧依据失效。三个后期消费者共享并校验此包；`--draft-subtitles`仅显示缺口，不满足正式交付。工程检查不替代真人语音同步及完整声画审片。
