# 从表达目标到可用片段

本方法由创作与制作角色按当前任务读取，写回现有 brief、来源映射、剧本、镜头、资产、声音和审片产物。不增加独立审批轮次，也不修改旧 Profile 或已批准快照。

## 先判断来源，再确定作品形式

来源性质与作品形式分开记录在 brief / 改编说明中。同一小说可做剧情片或意象片；混合形式按段落说明组织方式。未知时提出有限选项，不根据扩展名或“短视频”一词自动决定。

| 作品形式 | 提取与组织 | 判断是否成立 |
| --- | --- | --- |
| 剧情、连续短剧 | 因果、人物欲望与需要、知情与误信、选择代价、关系变化；铺垫、兑现和信息顺序 | 观众能理解关键选择和变化；悬念只用于确需延续的问题 |
| 散文、诗性意象 | 观察视点、感官、意象联系、文化语境、段落与情绪流动、声音和留白 | 观众能感知段落联系及情绪变化；允许闭合、余韵，不强加对抗与反转 |
| 纪实、知识、品牌信息 | 可核查事实、论点与证据、受众疑问、信息层次、约定的行动 | 事实与解释区分、信息可理解；资料不足不以戏剧化补成事实 |

改编仍保留既有契约必填字段。非人物中心段落在人物目标、阻力等字段如实说明“不适用：本段承担……”，在可见表达和信息变化中写具体声画关联；不虚构角色冲突来填表。开场是建立注意与视点，结尾可为闭合、余韵、行动或悬念，由作品目标决定。

## 专业拆解如何落到产物

先提取来源，再提出创作选择，批准后才成为制作规格。原文事实、人物自述、推断、创作提案和未知逐项区分；镜位、精确动作、配乐等没有来源依据时属于提案。重要主张保留可回查定位、备选解释和删改代价。

| 责任产物 | 按需激活的内容 | 下游使用 |
| --- | --- | --- |
| 来源／改编 | 时间顺序与叙述顺序、世界规则、文化语境、因果或意象联系、人物知情和误信 | 确定观众何时知道什么；不把解读冒充事实 |
| 剧本／表演 | 诱因→对象→意图→行动策略→反应；情绪强度变化、眼神、姿态、呼吸、停顿和动作起止 | 可表演的节拍及场景入出状态；对白目的、潜台词、轮次、发音、实测时长与画内外用途 |
| 镜头／调度 | 镜头功能、景别、机位、构图、焦点、光色、轴线、视线和屏幕方向；站位、遮挡、路径、持物与交接 | 分开主体运动、相机路径与剪辑变化；明确动作接点和头尾余量 |
| 美术／资产 | 稳定身份、变体、尺寸与材质、可拍方向、时间天气、服化和道具状态 | 每张参考图有具体镜头用途；只准备必要视图，不默认四视图或全套表情 |
| 动作／特效 | 预备、发动、轨迹、接触、反馈、余波；目标、范围、代价及后续状态 | 光影、遮挡、声音与环境反应协同；复杂控制先试证 |
| 声音／剪辑 | 对白、环境底、拟音、特效、音乐与静默；远近、空间感、声画关系、反应和插入覆盖 | 声音跨镜、局部粗剪验证节奏；验收实际采用区间及可剪性 |

不需要的专业项不填充。摄影参数对生成模型可能仅表达意图，精度依赖适配器和实测；无需正面说话时不制造口型任务。

## 把价值与思想变成决定

每个关键取舍回答一个具体问题，并落到已有产物及审片证据：

- 价值：表达、审美、受众体验、商业目标冲突时，先保留哪个不可牺牲条件？由 brief 的优先级与负责人裁决。
- 认识：这句话是来源事实、人物说法还是我们的解释？有什么反证或另一种读法？回查来源并保留未知。
- 人物与伦理：角色此刻能选什么、代价由谁承担、后果如何可见？把答案写为行动与反应。
- 视点与体验：观众看见／听见什么后会形成哪种理解？谁的视角被省略？用具体场镜与观看反馈核对，不能预设统一审美答案。
- 探究：什么样的样片结果会否定当前方法？在试验前固定判据，记录适用条件与失败例。
- 系统：改动会影响哪些真实消费者，局部修复还是换路线更合算？依赖查询与实际工时支持判断。

## 制作前检查与返工控制

先固定必要条件、容差和偏好项；容差必须说明画幅、时长或观看环境，不能在失败后擅自降低。每项必要要求绑定批准规格，并指向最终请求、参考图、音轨或明确的后期任务；后期承担的要求必须有对应任务输入，不能以“后期再说”算覆盖。检查语义冲突、错用变体和任务过载，字数不是覆盖率。

高风险方法先在相同用途与代表性条件下试证，复用 `context build --pilot`、`capability evaluate` 的方法、输入、输出、基线和判据版本。pilot 是方法试用状态，不是付费授权；付费试片仍须有适用阶段的已批准 run、预算、停止条件和输出用途。本地图像／视频现可通过下述 `phase=trial` 在 script Gate 后进行有限试片；正式 production 仍要求预演 Gate。数据库项目使用其原权威的试片入口，不能回退本地队列。节奏预演不能证明生成方法可行。

用 `python3 -B scripts/production/quality.py check <检查包.json> --root <证据目录>` 检查 `templates/quality-plan.json` 所示只读检查包。它验证文件摘要、规格到输入的明确字段映射，按项目内逻辑镜头＋用途跨任务／版本汇总缺陷，提示停止重复路线，并汇总有效区间、成本和工时。检查包只引用现有证据，不复制批准权威；CLI 不调用供应商、不改变任务状态、不授予执行权。`ready_for_review` 仅表示所列结构检查未发现阻断，实际覆盖语义与审美结果仍未知；不得写成质量通过。

同类失败按同一逻辑镜头／用途／缺陷累计，方法版本作为条件保留，不因新 task ID、run 或方法改名清零。阈值事先约定（模板中的两次仅为试点值）；达到轮数或预算上限后先停止原路线，再比较拆镜、换视点、声音表达、裁切、局部编辑、合成与重生。网络重试、计划探索、需求变更分别计量，不伪装成创作失败。先记可观察缺陷；根因标已证实、待检验或已排除并附证据，多项同时修改成功只能证明组合有效。

完成一组镜头就做局部粗剪。优先保留可用区间；视频按区间并集计量，同一素材多次使用不重复累计。生成请求／秒数／金额各按原单位汇总，人工主动工时与等待时长分开；缺账单为未知，估算另列不当实付。

局部修改后检查变化项、依赖影响和必要整体副作用。审查复用须同时匹配媒体内容、依赖摘要、用途、判据与授权范围，消费时再次校验；同名文件或相同提示词不足以复用。工具只提供复用候选，新的媒体仍需审查，旧结论不自动批准新版本。实际成本与成片观察才支持效率改善结论。

## 只读检查包的具体写法

从仓库根目录复制 `templates/quality-plan.json` 到本次任务的工作目录，填真实引用后运行检查；模板故意保留未知值，不能原样通过。检查包是可重建的审计输入，不是新的批准台账。证据路径相对 `--root`，必须位于该目录内；每次读取校验完整 SHA-256，可用 `shasum -a 256 <文件>` 获取。JSON `pointer` 按 `/字段/数组下标` 定位，`~1` 表示字段名中的 `/`、`~0` 表示 `~`。普通文本或媒体来源只给文件引用；实际请求字段须指向 JSON。

| 字段 | 填写与消费 |
| --- | --- |
| `requirements` | `id`、`priority=must\|preference`、`criterion`、`tolerance`、固定 `source`；必要项缺映射会阻断 |
| `inputs` | `id`、`channel=request\|reference\|audio\|post_task`、固定 JSON 文件 `ref`；参考／声音通道可引用正式输入清单中的媒体 ID 与摘要字段 |
| `bindings` | 每项写 `input_id` 与实际字段 `pointer`；身份／变体等精确要求加 `equals_source=true`，直接比对来源字段；也可用 `expected` 检查明确字面值。语义有效性仍需人工核对 |
| `risks` | 写风险 `id`、可证伪 `hypothesis`、`stop_condition`；已有评测用 `evaluation_ref` 引用 `vsc.capability-evaluation/v2`，可从不可变导出快照定位。工具不独立认证 trial 授权，有 pass 也须由原入口校验 |
| `attempts` | 全部相关任务／版本放入同一包；`id` 不重复，`logical_shot_id`、`purpose` 与 `method` 稳定。`task_id`、`version` 追溯实际尝试；`method` 包含模型版本和参考／控制方式，改提示词不随意换方法名清零 |
| `category` | `production`、`planned_experiment`、`requirement_change`、`recovery` 分开汇总；恢复类不累计创作失败。方法缺陷在实验中复发也提示停止原路线 |
| `result` | `usable\|failed\|unknown`；已判断结果附 `assessment_ref`。`defects` 写 `code` 与 `observation`；可选 `cause.status=hypothesis\|confirmed\|ruled_out`，后两者必须有 `evidence_ref`，工具只验证证据存在，不证明因果 |
| 工时／用量 | `active_seconds`、`wait_seconds`；`costs` 每项写 `unit`、`amount`、`basis=actual\|estimate`。未知用 `null`，不同单位不相加，估算不替代账单 |
| 媒体区间 | `media_ref`、正数 `generated_seconds`、`usable_intervals=[[起秒,止秒],…]` 与区间审查引用；区间未知用 `null`，审查后无可用区间用 `[]`。同摘要媒体跨用途合并计算，不重复算使用秒数 |
| `review_reuse` | 每项 `id`、`prior` 与 `current`；两边均须有 `media`、`criteria`、`authorization` 文件引用、`purpose`，以及带稳定 `id` 的 `dependencies` 引用数组；任何缺失／漂移都不建议复用 |

例如把一次返工加入 `attempts`（摘要占位符须替换，不能据此提交生成）：

```json
{
  "id": "attempt-2", "logical_shot_id": "shot-1", "purpose": "video_take",
  "task_id": "new-task-id", "version": "candidate-2", "method": "model-v1/reference-mode",
  "category": "production", "result": "failed",
  "assessment_ref": {"path": "review-2.json", "sha256": "完整摘要"},
  "defects": [{"code": "hand-contact", "observation": "3–4 秒手部未接触道具", "cause": {"status": "hypothesis", "description": "参考未体现接触姿态"}}],
  "active_seconds": 120, "wait_seconds": 360,
  "costs": [{"unit": "CNY", "amount": null, "basis": "actual"}],
  "media_ref": {"path": "candidate-2.mp4", "sha256": "完整摘要"},
  "generated_seconds": 8, "usable_intervals": [[0, 2]]
}
```

输出 `blocked`（退出码 2）表示引用／覆盖错误或重复失败达到停止阈值；`review_required`（1）表示存在已声明未知；`ready_for_review`（0）仅表示此包的结构检查结束。所有结果都保留 `quality_result=unknown`、`execution_authorized=false`。缺陷清单、评估结论与区间来自记录者，独立 CLI 不观看素材、发现未填报风险或自动查询漏报任务。将检查包绑定 run 后，以下消费接口会在执行前实际阻断；既有预算入口继续负责费用上限，正式消费者仍核对真实批准。

## 将检查包接入正式运行与前期试片

本地 `scripts/production/run.py plan` 增加可选 `--quality-plan PROJECT/quality.json`。输出的 run 固定该文件路径与摘要；旧 run 不加字段仍按旧规则验证。检查包另填 `run_binding={"plan_sha256":"本次批次计划摘要","job_ids":["image","video"]}`；每个 `channel=request` 输入增加 `job_id`，`ref` 直接指向固定 batch 的 `/jobs/0/args` 等位置。每个真实任务至少一项必要要求，来源必须是 run 的已批准输入；工具比对完整请求对象，不能用另一份正确提示词冒充实际提交内容。local、series 和音频运行都通过 run 校验消费该包，缺项、漂移、未知及停止阈值阻断执行。试片允许其明确检验的风险尚未通过；正式制作的风险 pass 必须回查既有版本绑定评测。

本地预演前图像／视频试片按以下顺序执行，复用原有人工决定，不新建审批队列：

1. script Gate 就绪，剧本、资产库、场景状态和有限镜头设计获批；现有能力卡由责任人决定 pilot，并以这些输入运行 `context build --pilot`。
2. 复制 `templates/production-trial.json`，绑定真实 `TR-ID`、上下文与方法摘要、假设、判据、停止条件、允许的镜头／资产和最大请求数。先用 `scripts/production/plan.py plan` 得到固定批次摘要，填入质量包，按任务逐项映射实际 batch 参数。
3. `scripts/production/run.py plan PROJECT/batch.json --project PROJECT --phase trial --trial-spec PROJECT/trial.json --quality-plan PROJECT/quality.json --input A-SCRIPT --input A-BIBLE --input A-STATE --input A-SHOTS` 输出待审 run；补齐 pilot 上下文的其他固定输入，并按已有下游依赖需要填写 `--review-after`。试片本身不增加每条候选都要暂停的规则。
4. 按原 `artifact add`／`artifact decide` 批准这份 run，再 `scripts/production/run.py execute RUN-ID --project PROJECT`。只执行明确图像／视频任务；使用项目共享预算，恢复同一任务，不借新编号无限重试。试片图像为镜头候选，资产母版准备仍使用 asset phase。
5. 输出仍为 draft，记录 trial 来源，供预演和方法评测。正式采用时，在正常待批准 `selected-takes` 中写 `trial_adoptions=[{"artifact":{"id":"候选记录ID","sha256":"固定摘要"},"reason":"本用途的采用依据"}]`；须满足 animatic Gate，并由责任人批准此 selected-takes。单有标记、试片成功或 run 的候选审阅不能自动成为正式采用。

PG 可通过 `run_quality.quality_errors(data, project, state, item, requests, read_ref=...)` 直接读取关系库中的固定 artifact 字节，复用全部 SHA 与请求覆盖检查；不写临时权威文件。`requests` 按 run 的稳定任务 ID 映射实际逻辑请求，证据读取器返回原始 bytes。数据库入口仍负责项目隔离、依赖和真实批准校验。

## PostgreSQL 试片与质量包

PG 项目使用 `scripts/assets/resources.py` 的共享应用接口，当前库须完成 `0005_creative_relations` 迁移。试片授权来自真实批准的 `production-run` 版本及其固定依赖；PG 尚没有本地 `learning.trials` 的同等登记权威，不能仅填写任意 `trial_id` 就称已有 pilot 批准。方法以本项目已批准 `artifact_type=trial-method` 固定，正文必须包含非空 `method`，写明方法及适用条件。该批准说明允许本次有范围的试验，不代表方法已经实片验证。

PG trial 支持**同段落连续 1–8 个镜头的图像／视频候选**，允许多个明确候选编号。`trial.allowed_shot_ids` 列明相邻镜头，`trial.shot_contexts` 是每镜 UUID 到固定上下文 SHA 的映射；每镜只固定一个用途，整个范围先验通过后才允许首个付费候选。旧单镜 `context_sha256` 继续兼容；`allowed_asset_ids` 包含实际入画、持有、服装及地点资产，空场景可为空。资产母版仍走 asset 路线。当前镜头所属集的 script Gate 必须通过，Gate 产物和本镜上下文里的剧本、资产规格、镜头规格全部固定到 run；其他集已批准剧本不能补足本镜缺项。正式 production 仍要求 animatic Gate。

方法、独立请求、质量包与 run 一并放入现有试片审核包，列明各固定版本 ID 和摘要，由同一次明确人工决定覆盖这些版本，再逐项记录决定；不要逐文件另起确认轮次，也不能把批准 run 自动推定为批准未展示的依赖。

构造顺序如下，登记与批准沿用现有 `create_artifact`／`decide_artifact`，每次写入仍带真实操作人、当前 revision 与幂等 key。下列操作只准备固定输入；提交 worker 必须已有执行授权与预算。

1. 用 `context PROJECT_ID SHOT_ID --purpose video_clip` 取得就绪上下文，核对实际批准规格和获选参考。下面的 `context`、`shot_id`、`first_frame_media_id`、`prompt` 均来自这次明确任务。
2. 规范化每个请求并计算 operation ID、计划摘要和原生用量。operation ID 为 `series:<镜头UUID>:<用途>:<candidate_no>`，与 `run.operations` 和质量包 `job_ids` 完全一致。不要用随机 job UUID 代替。

```python
from vsc.production.run_authorization import normalize_request
from vsc.adapters.persistence.postgres.production_guard import requests_for
from vsc.adapters.persistence.postgres.values import digest
from vsc.adapters.persistence.postgres.budget_store import native_units

logical = normalize_request(
    {"prompt": prompt, "first_frame_media_id": first_frame_media_id},
    shot_id, "video_clip", "video",
)
jobs = [{"candidate_no": 0, "request": logical}]
requests = requests_for({"jobs": jobs})
# requests 的值就是完整规范化逻辑请求，不含供应商连接信息。
plan_sha256 = digest(requests)
operations = {operation_id: native_units(request)
              for operation_id, request in requests.items()}
```

3. 把每个 `requests[operation_id]` 单独登记为 `artifact_type=quality-request` 的不可变请求版本，并取得真实批准；把方法登记为前述 `trial-method`。这些类型不会自动加入镜头上下文，避免保存证据改变刚固定的上下文摘要。
4. 构造 `vsc.quality-plan/v1`，以 `artifact_type=quality-plan` 登记并批准。`run_binding.plan_sha256` 取上面的 `plan_sha256`，`run_binding.job_ids` 恰好为 `list(requests)`。每个 request 输入写 `job_id=operation_id`，其 `ref={"artifact_id":请求版本ID,"sha256":请求版本完整SHA}` 指向第 3 步原始字节；必要要求的 `source` 指向已批准规格版本及具体 `pointer`，`bindings` 指向实际请求字段。要求、参考、审查与尝试证据都使用本项目固定 artifact 引用。PG 不接受本机文件路径作为这里的证据权威。
5. 组装 run，`project_id`、`phase="trial"`、`jobs`、`plan_sha256`、`operations` 按上文固定；`quality_plan={"artifact_id":质量包版本ID,"sha256":完整SHA}`。`approved_inputs` 包含编译上下文全部产物，以及方法、独立请求、质量包和质量包引用的所有证据版本；登记 run 时的 `dependency_ids` 必须与其 ID 集合完全一致。质量包引用独立请求版本，不能反过来引用 run 自身，以免出现摘要自引用。

`run.trial` 的必要字段与含义：

| 字段 | PG 消费规则 |
| --- | --- |
| `trial_id` | 本次试验标识，不能替代真实 run 批准 |
| `shot_contexts` | 每镜 UUID 到编译上下文完整 SHA 的映射；旧单镜可用 `context_sha256` |
| `method_sha256` | 固定已批准 `trial-method` 的完整摘要，不能借用剧本或质量包摘要 |
| `hypothesis`、`criteria`、`stop_condition` | 可证伪假设、可观察判据与明确停止条件，均非空 |
| `max_remote_jobs` | 正整数，覆盖整份 run 中每一个候选请求；换模型不增加授权次数 |
| `allowed_shot_ids`、`allowed_asset_ids` | 本项目明确镜头和资产范围；同段落连续 1–8 镜 |
| `output_use` | 填 `preproduction_only`，试片输出保留为候选 |

批准 run 后，通过 `apply PROJECT_ID create_generation_job --payload ... --expected-revision ... --key ... --by ...` 创建任务。payload 使用该 run 的 `run_version_id`、镜头、用途、模态、候选编号、固定 `context_sha256` 和 `request_payload`；模型可显式指定，或使用已配置且适用的默认路线。`configure_budget` 预先固定项目共享原生单位额度；每个 `operations[operation_id]` 必须覆盖该任务用量，试片即使使用旧 Profile 也不能免预算。`worker --project-id PROJECT_ID` 才会进入已有的首次提交路径，可能调用付费供应商；单纯构造或登记不会提交。

质量错误、证据摘要／批准失效、未覆盖的请求和同类失败停止条件会阻断任务创建及首次提交；未知提交的恢复、轮询和输出转存保持原机制，不因重新检查而重 POST。旧 run 没有 `quality_plan` 且不是 trial 时继续原有授权规则。启用质量包也不允许 AI 把结构校验称为审美通过。

### PG 方法评测与跨任务止损

用现有 `create_artifact` 登记 `format=vsc.method-evaluation/v1`，字段为 `project_id`、`method_artifact_id`、`trial_run_id`、`baseline_media_id`、`output_media_id`、`criteria_artifact_id`、`result=pass|fail|unknown`、`observations`、`environment_sha256`。方法、trial run、判据必须是明确批准依赖；输出须能回查真实试片 job_outputs，基线须为不同的同模态媒体；两份媒体的人类审查 `criteria_version` 必须等于判据 artifact SHA。`pass` 还要求试片最新该判据人工审查通过。环境 SHA 用 `quality_relations.environment_digest(model, logical_request)` 计算，固定模型版本、能力、用途、模态和控制参数。登记后由真实责任人正常批准评测版本。

正式质量包风险引用这份评测，同时填写 `method_artifact_id`、`criteria_artifact_id`。run 也固定评测及全部依赖。创建与首次提交都会检查实际选定模型环境、评测批准、方法和判据；换环境须重新试证。它只证明记录中的具体观察，不自动证明跨作品适用或最终成片质量。

观察使用 `format=vsc.quality-observations/v1`，`observations` 每行记录 `job_id`、可选真实输出 `media_id`、`criteria_artifact_id`、可选 `method_artifact_id`、`result=usable|failed|unknown`、`defect_code`、`observation`、`position`、`effort_seconds`、`wait_seconds`、`cost_amount`、`cost_unit`、`cost_basis=actual|estimate|unknown`。观察 artifact 沿原人工批准入口确认；引用的判据／方法是依赖，媒体必须属于该真实 job。未知保留 null；估算不替代实付。先写缺陷和定位，原因主张在质量包另分待检验／证实／排除并附证据。

同镜头＋用途＋缺陷累计两个不同任务的已确认失败即阻止新任务和首次提交。不同 run、方法名及候选号不能清零；撤销观察也不删除历史。换路线用已批准 run 的 `route_change={reason,defect_codes,changed_variables:[{variable,before,after}]}` 明确改变的实际变量（名称、编号及版本标签不算），trial 方法正文须与已失败方法不同，次数和项目预算仍受限。正式恢复还须 `route_change.evaluation_ref` 与适用 `method_artifact_id`、`criteria_artifact_id`；不能靠改名、文字标记或 AI 自评解除停止。

### 专业执行规格进入实际请求

整理已有固定资料时，从 [创作工作台](../../../docs/guide/creative-workbench.md) 按场镜查阅剧本覆盖、资产实例、声线、Cue、候选和当前版本；CLI `scripts/assets/workbench.py` 与后台使用同一查询。缺少关系先说明缺口，再从来源与已批准规格提出增量关系文档，不根据目录猜测、不为不同角色重复复制事实。该文档可和相关规格一起组成固定版本审阅包。

专业动作／舞蹈／特效／配音用 `artifact_type=creative-relations`、`format=vsc.creative-relations/v1` 的 `performances` 登记，角色、媒体、声线、台词和镜头使用 typed refs。四类规格分别需要五阶段动作与双方／重心、固定音乐和节拍姿态、施受者与分层遮挡、固定台词声线与表演参数。`vsc.production.performance.execution_problems` 在登记事务执行；完整字段见该模块及 `templates/professional-execution.json`。方法须为已批准依赖。

在生成 run 中写 `professional_bindings=[{execution_id,job_ids}]`，视频／图像把 `performance.prompt_fragment(domain,parameters)` 放入实际固定 prompt。配音 prompt 严格保留台词；表演参数的 `controls=[{field,model_default,expected}]` 绑定实际模型默认参数，模型须明确 `performance_controls` 映射和 `voice_deliveries`。语速必有控制，低语／喊叫还须对应 delivery 控制；当前适配器未映射的控制在执行前拒绝，不能只注册能力标签就当作已实现。守卫检查每个相关逻辑任务、素材 ID、配音台词与声线；能力检查仍由实际模型入口执行。不支持的音乐约束、蒙版／深度或表演控制应改为支持的路线或合成任务，不能把文字愿望当成已支持控制。关系规格会进入对应镜头上下文，修改规格使旧摘要失效。

### 修复影响比较

`python3 -B scripts/production/quality.py repair <修复备选.json> --project-id <UUID>` 从关系库读取该媒体的真实任务、加工、时间线、渲染和当前选择用途。计划包含 `media_id`、实测 `generated_seconds` 与 `options`；每项 `kind=retain_interval|crop|local_edit|composite|replace_asset|edit_cut|regenerate`、`reason`、可选 `intervals`、`estimated_active_seconds`、`estimated_costs=[{unit,amount}]`。报告比较保留区间并集、影响项和估算；实际账单仍未知，不把相同素材的裁段当作完整新用途审查。影响分页不完整时明确 `incomplete`。本入口不执行修复、不替换冻结时间线、不批准新媒体；选择后走既有媒体加工、选片和剪辑登记。审查复用继续逐项检查质量包 `review_reuse` 的固定指纹条件。

### PG 试片正式采用

试片成功与审查通过都不会自动选择输出。图像身份、服装、地点、道具、声音样本、风格、构图、首尾帧及参考音频可沿原用途选择，供试片内部引用。其他用途，包括 `video_take`、`dialogue_dry`、`ambience`、`music`、`sfx`，正式选择试片输出或其已登记加工产物时，需要通过当前范围 animatic Gate，并在**同一次正常 `select_candidate`** 中明确采用：

```json
{
  "candidate_id": "本次候选UUID",
  "reason": "本用途正常选片理由",
  "trial_adoption": {
    "reason": "试片在此正式用途的采用依据",
    "animatic_version_id": "本范围当前已批准预演版本UUID"
  }
}
```

所有占位值须替换为真实 ID 与决定。这里仍需要原用途的人审与普通选择资格；不另建批准队列，AI 委托审查不能代替这次试片转正式决定。系统在同一事务写普通选择和 `binding_trial_adoptions`，固定来源试片 run、预演版本及其批准决定。多输入加工保留全部显式试片来源，后续停用不抹去历史采用。数据库延迟约束会拒绝缺少采用证据的正式试片选择；画布可查询这些历史关系。只有已登记的来源／加工关系参与溯源，不根据文件名、目录或内容相似度补造关系。
