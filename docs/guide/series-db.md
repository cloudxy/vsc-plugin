# 数据库连续短剧工作流（v0.18.0）

适用范围：新建的 60 集以上系列项目，每集约 3 分钟。作品题材、画幅、预算、声源权利、责任人和具体供应商模型仍由项目负责人决定。本版本提供本地关系库、素材索引、按镜上下文、统一任务执行入口、关系查询，以及生成结果到后期的离线接缝；没有验证方舟在线生成，也没有自动保证“一次生成即成片”。

## 建立项目与固定创作版本

```bash
python3 -B scripts/kernel/catalog.py doctor
python3 -B scripts/project/state.py init projects/作品名 --title '作品名' --profile vsc.series-db --owner '负责人'
python3 -B scripts/project/state.py object add projects/作品名 --kind episode --id EP001
```

按现有 [production-v2 指南](production-v2.md)登记集、场、sequence、镜头和资产对象；剧本、系列视觉圣经、资产圣经、场景状态、镜头计划及声音计划仍通过 `artifact add`、`artifact decide` 和 Gate 人工批准。每次登记形成新版本，不改已批准快照。数据库保存这些固定文档及关系索引；`vsc.json` 只用于兼容读取。镜像损坏时运行 `python3 -B scripts/production/series.py repair-mirror PROJECT`，不要手写 JSON 或 SQLite。

## 场景、人物、声音素材

一个反复出现的地点先登记稳定 `asset` 身份和空间规格：布局、门窗、固定地标、摄影轴线、光向及允许的日夜状态。选择场景母版后，按机位派生 `location_view`；复杂合成的背景、前景、道具、人像、遮罩和调色各保留父素材与变换参数，最终合成图登记为新媒体版本。多次生成完整背景只用于探索或局部修复；不同透视的背景不要直接拼成一个空间。需要明显视差时，用分层深度或简单 3D 布景，并在预演与相邻镜头检查空间关系。

人物、服装与声音分别使用稳定资产身份和当前变体；台词行 ID 在已批准剧本中固定，voice／speaker 绑定在已批准资产库中固定。资产库 `voice.pronunciations` 可按 `[{"term":"专有词","spoken":"读法"}]` 登记人物发音提示；契约检查非空和重复词条，音频任务连同资产库版本固定并写入生成记录，供审听核对。当前预置 TTS 接口没有已验证的自定义发音词典映射，因此发音提示**不会自动改变合成文本或保证读法**。场景混响等声学处理仍由声音计划与后期人工审核。导入本地素材会计算 SHA、完整解码并检查声明模态。批准媒体用途后，AI 才能把它当参考。示意：

```bash
python3 -B scripts/production/series.py import-media PROJECT --id LOC-Cafe-Master-v1 --file /path/to/master.png --modality image --rights owned --origin '人工选定母版'
python3 -B scripts/production/series.py import-media PROJECT --id LOC-Cafe-View-v1 --file /path/to/view.png --modality image --rights owned --origin '母版派生' --parent LOC-Cafe-Master-v1 --relation local_edit --parameters '{"camera":"reverse"}'
python3 -B scripts/production/series.py bind-media PROJECT --id B-LOC-1 --target LOC-Cafe --media LOC-Cafe-Master-v1 --role location_master
python3 -B scripts/production/series.py decide-binding PROJECT B-LOC-1 --status approved --by '负责人' --reason '空间与相邻镜头相容'
```

绑定分两类：身份脸、服装、地点母版／视图、道具、首尾帧和构图是**生成输入**，批准后进入对应镜头的上下文；`video_take` 与 `dialogue_dry` 是**后期选片**，只供剪辑与混音，不改变生成上下文。`rights=analysis_only/unknown` 可登记但不能批准制作用途。`--by` 是本机审计标签，不是账号认证。`--job` 可在成功任务后把生成媒体和任务关联；媒体字节统一落在项目 `.vsc-media/`。不要把带签名参数的临时 URL 当持久素材引用。制作用途一次只能有一个当前批准绑定；改选时保留旧记录并登记新的可审计版本。

## AI 按镜读取

```bash
python3 -B scripts/production/series.py context PROJECT --shot SH001 --out /tmp/SH001-context.json
python3 -B scripts/production/series.py validate-context PROJECT /tmp/SH001-context.json
```

`ShotContext` 收录剧本场次、系列风格、镜头规格、入点和出点状态、人物／地点身份、声音锚点、当前变体适用的媒体引用，以及每个批准产物的 ID 与 SHA。`unresolved_reference_asset_ids` 列出镜头计划声明却没有批准媒体绑定的素材；在补齐前不能计划生成任务。修改上游版本后重新编译并比对 SHA，旧上下文不会冒充新批准版本。跨集状态须在剧本、场景状态与镜头计划中明确承接，不能靠相似图检索猜测。

相邻集末镜与次集首镜还要登记边界决定。`continuous` 要求地点、人物和环境状态一致；确有时间／空间跳切时用 `intentional_jump` 并写理由。未登记或状态版本漂移时，次集首镜的生成计划被拦住。集顺序使用 episode 对象登记顺序，镜头顺序使用 shot 对象登记顺序。
重审旧边界时加 `--replace`，旧决定保留为历史记录。

```bash
python3 -B scripts/production/series.py link-boundary PROJECT --from-shot EP001-LAST --to-shot EP002-FIRST --strategy continuous --by '负责人' --reason '同一动作接续'
```

## 统一生成任务入口

`src/vsc/production/providers.py` 定义 Image/Video/Audio 三种逻辑请求和 `submit/poll/parse_result` 接口。`src/vsc/adapters/providers/volc_ark/provider.py` 已按此接口实现火山方舟图像、视频和 Agent Plan Seed TTS 2.0 的本地适配；图像／视频使用专属 key `ARK_AGENT_PLAN_API_KEY` 和 `https://ark.cn-beijing.volces.com/api/plan/v3`，语音使用同一 key 的专属 `/api/v3/plan/tts/unidirectional` 路由。图／视频／语音均未完成真实线上调用验证。模型能力、默认参数、版本与路由由 `scripts/production/jobs.py` 管理。准备 `vsc.generation-request/v1` JSON，引用现行 `ShotContext.sha256` 与已批准媒体 ID；`plan` 要求已批准 `production_run` 钉住该镜头的全部输入版本。套餐能力和 AFP 预算边界见 [Agent Plan 个人版对照](../architecture/ark-agent-plan-personal.md)。

```bash
python3 -B scripts/production/jobs.py provider-add PROJECT --name volc_ark --modality image --modality video --modality audio --auth-ref env:ARK_AGENT_PLAN_API_KEY
python3 -B scripts/production/jobs.py model-add PROJECT --provider volc_ark --id image-main --key MODEL_KEY --modality image --version MODEL_VERSION --capabilities '{"purposes":["shot_keyframe"],"reference_media":true}' --defaults '{"size_map":{"1080x1920":"MODEL_SIZE"}}'
python3 -B scripts/production/jobs.py route-set PROJECT --modality image --purpose shot_keyframe --model-id image-main
python3 -B scripts/production/jobs.py plan PROJECT --run A-RUN --request /path/to/request.json --candidate 1
```

这里的模型标识、版本和尺寸映射必须按真实账号能力填写；示例命令只注册本地配置，不访问供应商。相同 run、镜头、用途、候选和输入再次计划会返回原 job；变更输入须新建候选。任务状态事件保留 `created → submission_unknown → submitted/running → succeeded/failed`，外部 task ID 只进任务表。`adapter_for_job()` 只从固定任务快照构造适配器，不提交请求。

对白干声先在已批准资产库为人物设置 `voice: {"engine":"doubao_speech","voice":"控制台音色ID","resource_id":"seed-tts-2.0","rights":"owned"}`，并在已批准 coverage plan 中把台词行 ID 分配给镜头。音频逻辑请求示例：`{"format":"vsc.generation-request/v1","modality":"audio","shot_id":"SH001","purpose":"dialogue_dry","context_sha256":"当前上下文SHA","prompt":"与剧本逐字相同的台词","script_line_ids":["L001"]}`。注册音频模型的 `model_key` 为 `seed-tts-2.0`，用途为 `dialogue_dry`，默认参数可设 `format`、`sample_rate`、`speech_rate`；当前只接预置音色，不接声音复刻。一个台词行一个音频任务，同镜多句用不同候选编号列入已批准 run。调度前会核对台词、覆盖计划、人物音色和资产库版本。语音结果先写入 `.vsc-staging/`，经 FFmpeg 完整解码和 SHA 校验后转存 `.vsc-media/`；数据库不保存大段 base64。

`production_run` 的 `series_batch.jobs` 列出每个**完整逻辑请求**和正整数 `candidate_no`；`plan_sha256` 是该 `series_batch` 的规范 JSON SHA；`operations` 对每项使用 `series:<shot_id>:<purpose>:<candidate_no>`，上限使用原生单位（图片 `remote_jobs:1, images:1`；视频还用 `video_seconds`；音频用 `audio_jobs` 与 `speech_chars`）。`approved_inputs` 与 run 依赖必须一一对应，含本镜的全部上下文版本和已批准 animatic。run 审核检查当前上下文、参考媒体及跨集边界。随后先用 `scripts/production/budget.py configure` 配置项目共享预算，再 `plan`，最后由下列入口执行：

```bash
python3 -B scripts/production/dispatch.py submit PROJECT --job J-ID
python3 -B scripts/production/dispatch.py resume PROJECT --job J-ID
```

run 批准前完整复核每个任务的实时上下文、参考媒体和跨集边界；批准后保持对固定版本的批准，不因之后某一镜的选片、改绑或边界决定整体失效。`plan` 与 `submit` 仍逐任务比对当前上下文：上下文已变的任务会被拦下，须编入新 run 重新批准，同批其他镜头不受影响。`approved_inputs` 中的产物被替代时，run 照常失效。

`submit` 复核批准 run、当前上下文、animatic Gate 和预算，在付费 POST 前登记不可重提的提交意图。视频返回外部 ID 后，`resume` 按原 ID 查询；同步结果直接解析。成功结果立即转存到项目 `.vsc-media/` 并校验解码与 SHA；重复恢复先核对已入库字节，避免临时 URL 过期后再次下载。平台 URL 仅在任务原始响应中保留用于故障恢复，媒体表的原始 URI 去掉签名参数，业务镜头只引用稳定媒体 ID。提交响应未知时保守占用预算，须人工核对平台任务及账单，不能重发。预算金额与实际计费用量在无供应商账单时保持未知。

新生成素材初始权属为 `unknown`，经 `decide-media-rights` 人审确认后才可绑定制作用途；完整的选片顺序见下文“从获选素材到后期”。

异步任务较多时，用 `resume-pending` 批量续查（`--limit` 1..100，默认 20）：

```bash
python3 -B scripts/production/dispatch.py resume-pending PROJECT --limit 20
```

它只查询已有外部编号的任务，并补做此前因下载失败而中断的转存，不会提交新任务。转存完成写入 `transferred` 事件；成功续查后再次调用不会重复下载。单个任务出错（如临时 URL 过期、平台返回错误）记为 `poll_error` 事件并排到队尾，其余任务照常处理；只要有失败，命令退出码为 1，须人工查看原因。转存完成只把仍未知的预留记为 `usage_unknown`，不覆盖负责人已录入的实际用量。

当前 CLI 以 `resume`／`resume-pending` 提供异步视频轮询兜底；没有 webhook 服务端、常驻队列或自动重提。同步语音经统一任务入口执行，现有供应商专用 CLI 保持独立，不作为系列任务的第二个状态权威。本次只用注入的本地假响应验证批准 run → 预算 → 提交意图 → 音频解码与转存 → 权属审核 → 按台词选片的离线链，**没有访问火山方舟**。首次真实调用、实际 URL 时效、平台用量与成片效果须待用户提供脚本及项目素材后验证。

## 从获选素材到后期

数据库记录媒体字节、权属决定和已批准选片；`vsc.selected_takes` 仍是进入剪辑的正式交接，须人工批准。视频候选按以下顺序接入：

```bash
python3 -B scripts/post/export.py PROJECT --job J-ID --out PROJECT/drafts/J-ID.json
python3 -B scripts/project/state.py artifact add PROJECT --type vsc.generation_record --stage production --scope EP001 --file PROJECT/drafts/J-ID.json --depends A-RUN
python3 -B scripts/project/state.py object add PROJECT --kind take --id TK-SH001-1 --parent SH001 --artifact A-REC
python3 -B scripts/production/series.py decide-media-rights PROJECT J-ID-output-1 --rights owned --by '负责人' --reason '核对生成来源与使用权'
python3 -B scripts/production/series.py bind-media PROJECT --id B-SH001-TAKE --target SH001 --media J-ID-output-1 --role video_take
python3 -B scripts/production/series.py decide-binding PROJECT B-SH001-TAKE --status approved --by '负责人' --reason '画面与前后镜头连贯'
python3 -B scripts/post/selection.py compile PROJECT --episode EP001 --out PROJECT/drafts/EP001-selected.json
```

第一步把已转存任务编译为现有 `vsc.generation-record/v1` 草稿，不重新调用 Provider。导出要求全部输出已落库且 SHA 仍正确。记录包含：由任务钉住的资产库与状态版本重算的 `anchors_sha256`（音频另含 `audio_anchors_sha256`）；按媒体库来源标注的首尾帧（本镜生成、前一镜视频尾帧或外部参考）；带路径和资产 ID 的参考素材；模型版本与默认参数；输出 ID 与媒体路径。用量写批准 run 的原生单位上限，金额未知时不虚构费用。目标文件已存在时拒绝覆盖。系列项目的参考素材以数据库用途绑定为准，资产库 `references` 可以为空，因此不要用旧的 `scripts/story/consistency.py check --record` 判断其参考归属。

`compile` 只读：从本集已批准的 `video_take` 和 `dialogue_dry` 生成 `vsc.selected-takes/v1` 草稿，选择人取自绑定决定，并打印含全部 `--depends`（animatic 与各生成记录）的登记命令。对白干声绑定时用 `--variant L001` 指明当前镜头覆盖的台词行；同镜多句可分别选，草稿条目用 `cue_id` 保留行 ID。登记后仍须 `artifact decide` 人工批准。某镜缺唯一生成记录、take 对象或权属确认时，命令报错并指出缺项；手工导入的素材和静帧按 [selected-takes 模板](../../templates/selected-takes.json)补写条目。

系列项目登记或批准选片清单时自动核对数据库：获选媒体须已导入素材库；`usage_rights` 必须等于人审权属决定（`owned`／`licensed`，不使用 `project_generated`）；该镜已有批准的 `video_take` 或 `dialogue_dry` 时，同模态条目必须选同一份字节。手写清单可先用 `scripts/post/selection.py check PROJECT FILE` 预检。之后再编制 timeline 和 Remotion 渲染计划；静帧片段可使用受限 `still_motion` 运镜，参数见[Remotion 设计](../design/remotion.md#帧级字段)。

## 关系查询

AI 和制作人员按关系读取，不扫全库。以下命令只读，返回稳定 ID、固定版本和本地媒体引用，不含外部任务 ID、临时 URL 或原始响应：

```bash
python3 -B scripts/production/query.py shot PROJECT SH001          # 一镜的 ShotContext
python3 -B scripts/production/query.py shot-jobs PROJECT SH001     # 该镜全部候选任务、输出与绑定
python3 -B scripts/production/query.py asset PROJECT LOC-Cafe      # 资产已批准媒体及派生来源
python3 -B scripts/production/query.py episode PROJECT EP001       # 按集列镜头、任务计数和已批准媒体
python3 -B scripts/production/query.py scene PROJECT SC001         # 一场内逐镜入出点状态与跨集边界
python3 -B scripts/production/query.py media PROJECT J-ID-output-1 # 素材的权属决定、来源、派生、绑定与引用任务
python3 -B scripts/production/query.py line PROJECT L001 --episode EP001  # 本集已批准剧本中的台词行
```

结构化 ID 与关系查询是权威；全文或语义检索只帮助发现候选，选定后仍须核对版本与用途。

## 扩到 60 集前的验收

先做一个重复地点、两名角色、两个以上镜头边界的场景；再做一集完整 3 分钟和相邻两集。分别检查角色与场景一致性、首尾状态、声线和音频桥、成片可解码、人工观看理解、每镜付费尝试数和返工根因。每一批只从已批准版本制作；未过关退回最早错误的剧本、资产或状态版本。静帧成片、模型方言和真实案例分别以实际素材与观看证据评测，不把离线数据库回归当作实际成片证明。
