# 数据库连续短剧工作流（v0.14.0）

适用范围：新建的 60 集以上系列项目，每集约 3 分钟。作品题材、画幅、预算、声源权利、责任人和具体供应商模型仍由项目负责人决定。本版本提供本地关系库、素材索引、按镜上下文及统一任务执行入口；没有验证方舟在线生成，也没有自动保证“一次生成即成片”。

## 建立项目与固定创作版本

```bash
python3 -B scripts/vsc_kernel.py doctor
python3 -B scripts/vsc_state.py init projects/作品名 --title '作品名' --profile vsc.series-db --owner '负责人'
python3 -B scripts/vsc_state.py object add projects/作品名 --kind episode --id EP001
```

按现有 [production-v2 指南](production-v2.md)登记集、场、sequence、镜头和资产对象；剧本、系列视觉圣经、资产圣经、场景状态、镜头计划及声音计划仍通过 `artifact add`、`artifact decide` 和 Gate 人工批准。每次登记形成新版本，不改已批准快照。数据库保存这些固定文档及关系索引；`vsc.json` 只用于兼容读取。镜像损坏时运行 `python3 -B scripts/vsc_series.py repair-mirror PROJECT`，不要手写 JSON 或 SQLite。

## 场景、人物、声音素材

一个反复出现的地点先登记稳定 `asset` 身份和空间规格：布局、门窗、固定地标、摄影轴线、光向及允许的日夜状态。选择场景母版后，按机位派生 `location_view`；复杂合成的背景、前景、道具、人像、遮罩和调色各保留父素材与变换参数，最终合成图登记为新媒体版本。多次生成完整背景只用于探索或局部修复；不同透视的背景不要直接拼成一个空间。需要明显视差时，用分层深度或简单 3D 布景，并在预演与相邻镜头检查空间关系。

人物、服装与声音分别使用稳定资产身份和当前变体；台词行 ID、voice／speaker 版本、发音表和场景声学处理在已批准文档中固定。导入本地素材会计算 SHA、完整解码并检查声明模态。批准媒体用途后，AI 才能把它当参考。示意：

```bash
python3 -B scripts/vsc_series.py import-media PROJECT --id LOC-Cafe-Master-v1 --file /path/to/master.png --modality image --rights owned --origin '人工选定母版'
python3 -B scripts/vsc_series.py import-media PROJECT --id LOC-Cafe-View-v1 --file /path/to/view.png --modality image --rights owned --origin '母版派生' --parent LOC-Cafe-Master-v1 --relation local_edit --parameters '{"camera":"reverse"}'
python3 -B scripts/vsc_series.py bind-media PROJECT --id B-LOC-1 --target LOC-Cafe --media LOC-Cafe-Master-v1 --role location_master
python3 -B scripts/vsc_series.py decide-binding PROJECT B-LOC-1 --status approved --by '负责人' --reason '空间与相邻镜头相容'
```

`rights=analysis_only/unknown` 可登记但不能批准制作用途。`--by` 是本机审计标签，不是账号认证。`--job` 可在成功任务后把生成媒体和任务关联；媒体字节统一落在项目 `.vsc-media/`。不要把带签名参数的临时 URL 当持久素材引用。制作用途一次只能有一个当前批准绑定；改选时保留旧记录并登记新的可审计版本。

## AI 按镜读取

```bash
python3 -B scripts/vsc_series.py context PROJECT --shot SH001 --out /tmp/SH001-context.json
python3 -B scripts/vsc_series.py validate-context PROJECT /tmp/SH001-context.json
```

`ShotContext` 收录剧本场次、系列风格、镜头规格、入点和出点状态、人物／地点身份、声音锚点、当前变体适用的媒体引用，以及每个批准产物的 ID 与 SHA。`unresolved_reference_asset_ids` 列出镜头计划声明却没有批准媒体绑定的素材；在补齐前不能计划生成任务。修改上游版本后重新编译并比对 SHA，旧上下文不会冒充新批准版本。跨集状态须在剧本、场景状态与镜头计划中明确承接，不能靠相似图检索猜测。

相邻集末镜与次集首镜还要登记边界决定。`continuous` 要求地点、人物和环境状态一致；确有时间／空间跳切时用 `intentional_jump` 并写理由。未登记或状态版本漂移时，次集首镜的生成计划被拦住。集顺序使用 episode 对象登记顺序，镜头顺序使用 shot 对象登记顺序。
重审旧边界时加 `--replace`，旧决定保留为历史记录。

```bash
python3 -B scripts/vsc_series.py link-boundary PROJECT --from-shot EP001-LAST --to-shot EP002-FIRST --strategy continuous --by '负责人' --reason '同一动作接续'
```

## 统一生成任务入口

`vsc_provider.py` 定义 Image/Video/Audio 三种逻辑请求和 `submit/poll/parse_result` 接口。`vsc_volc_provider.py` 已按此接口实现火山方舟图像和视频的提交、查询与结果解析；模型能力、默认参数、版本与路由由 `vsc_series_jobs.py` 管理。准备 `vsc.generation-request/v1` JSON，引用现行 `ShotContext.sha256` 与已批准媒体 ID；`plan` 要求已批准 `production_run` 钉住该镜头的全部输入版本。

```bash
python3 -B scripts/vsc_series_jobs.py provider-add PROJECT --name volc_ark --modality image --modality video --modality audio --auth-ref env:ARK_API_KEY
python3 -B scripts/vsc_series_jobs.py model-add PROJECT --provider volc_ark --id image-main --key MODEL_KEY --modality image --version MODEL_VERSION --capabilities '{"purposes":["shot_keyframe"],"reference_media":true}' --defaults '{"size_map":{"1080x1920":"MODEL_SIZE"}}'
python3 -B scripts/vsc_series_jobs.py route-set PROJECT --modality image --purpose shot_keyframe --model-id image-main
python3 -B scripts/vsc_series_jobs.py plan PROJECT --run A-RUN --request /path/to/request.json --candidate 1
```

这里的模型标识、版本和尺寸映射必须按真实账号能力填写；示例命令只注册本地配置，不访问供应商。相同 run、镜头、用途、候选和输入再次计划会返回原 job；变更输入须新建候选。任务状态事件保留 `created → submission_unknown → submitted/running → succeeded/failed`，外部 task ID 只进任务表。`adapter_for_job()` 只从固定任务快照构造火山图像或视频适配器，不提交请求。

`production_run` 的 `series_batch.jobs` 列出每个**完整逻辑请求**和正整数 `candidate_no`；`plan_sha256` 是该 `series_batch` 的规范 JSON SHA；`operations` 对每项使用 `series:<shot_id>:<purpose>:<candidate_no>`，上限使用原生单位（图片 `remote_jobs:1, images:1`；视频还用 `video_seconds`；音频用 `audio_jobs` 与 `speech_chars`）。`approved_inputs` 与 run 依赖必须一一对应，含本镜的全部上下文版本和已批准 animatic。run 审核检查当前上下文、参考媒体及跨集边界。随后先用 `vsc_budget.py configure` 配置项目共享预算，再 `plan`，最后由下列入口执行：

```bash
python3 -B scripts/vsc_series_dispatch.py submit PROJECT --job J-ID
python3 -B scripts/vsc_series_dispatch.py resume PROJECT --job J-ID
```

`submit` 复核批准 run、当前上下文、animatic Gate 和预算，在付费 POST 前登记不可重提的提交意图。视频返回外部 ID 后，`resume` 按原 ID 查询；同步结果直接解析。成功结果立即转存到项目 `.vsc-media/` 并校验解码与 SHA；重复恢复先核对已入库字节，避免临时 URL 过期后再次下载。平台 URL 仅在任务原始响应中保留用于故障恢复，媒体表的原始 URI 去掉签名参数，业务镜头只引用稳定媒体 ID。提交响应未知时保守占用预算，须人工核对平台任务及账单，不能重发。预算金额与实际计费用量在无供应商账单时保持未知。

新生成素材初始权属为 `unknown`，经人审确认后才可绑定制作用途：

```bash
python3 -B scripts/vsc_series.py decide-media-rights PROJECT J-ID-output-1 --rights owned --by '负责人' --reason '核对生成来源与使用权'
python3 -B scripts/vsc_series.py bind-media PROJECT --id B-SH001-TAKE --target SH001 --media J-ID-output-1 --role video_take
python3 -B scripts/vsc_series.py decide-binding PROJECT B-SH001-TAKE --status approved --by '负责人' --reason '画面与前后镜头连贯'
```

当前 CLI 以 `resume` 提供轮询兜底；没有 webhook 服务端、自动队列、账号级限流或自动重试。音频统一请求与任务表已就绪，火山语音服务映射尚未验证；现有供应商专用 CLI 未迁入此入口。本次只用注入的本地假 Provider 验证了批准 run → 预算 → 提交意图 → 状态恢复 → 转存 → 权属审核链，**没有访问火山方舟**。首次真实调用、实际 URL 时效、平台成本与成片效果须待用户提供脚本及项目素材后验证。

## 扩到 60 集前的验收

先做一个重复地点、两名角色、两个以上镜头边界的场景；再做一集完整 3 分钟和相邻两集。分别检查角色与场景一致性、首尾状态、声线和音频桥、成片可解码、人工观看理解、每镜付费尝试数和返工根因。每一批只从已批准版本制作；未过关退回最早错误的剧本、资产或状态版本。静帧成片、模型方言和真实案例评测按 [drama-skills 对标计划](../plans/2026-10-13-drama-skills-benchmark.md)执行，不把离线数据库回归当作实际成片证明。
