# VSC：角色记忆、受控试用与可复用方法

## 结论

VSC 需要“记忆”和“持续进化”，但不能把它理解为：每个子智能体保存全部聊天记录、观看任意素材后自行修改人格/提示词/代码、或无授权地把素材拿去训练模型。那会让错误、提示注入、版权风险和一次性的创作偏好被放大到之后每个项目。

本版本选择一条可审计的路径：**稳定身份 → 最小上下文 → 审批记忆 → 不可信观察 → 受控试用 → 评测晋升 → 可撤销能力**。它把“从素材学习武术、打斗、动作特效、背景布局、情绪、对白和声音”落实为可验证的工作方法，而不是声称已经获得对某人、某作品或某种模型的复制权。

这与公开智能体记忆实践的共同点是分层、有限注入和可检索审计：Hermes Agent 将持久记忆同会话快照和搜索区分；OpenClaw 也将文件记忆、索引及不同写入/注入层分开处理。[Hermes Agent Memory](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/memory.md) [OpenClaw Memory Architecture](https://docs.openclaw.ai/concepts/memory-architecture)

## 设计目标与非目标

| 目标 | 当前做法 | 非目标 |
|---|---|---|
| 子角色有身份与人格 | `workflow/roles.json` 维护身份、工作人格、权限和记忆边界；`agents/*.md` 提供宿主入口 | 让素材、用户台词或子角色自己重写身份 |
| 继承主会话上下文 | 总编排器把本轮已确认目标/决定收敛为 `parent_brief`，连同批准输入建立角色上下文包 | 给每个子角色复制完整聊天记录、密钥或无关个人资料 |
| 长期记住可复用经验 | `memory add` → draft → 人工 `memory decide` → scoped injection | 自动把模型输出、原文或瞬时偏好永久化 |
| 从素材学习 | 来源权属 + 带证据的观察 + 抽象能力卡 + pilot + 评测 | 直接复制人物、声音、受保护表达/风格，或自动做 LoRA/微调 |
| 持续演进 | 能力可通过、拒绝、退役；每次操作有事件台账 | 无审计地自我修改技能、代码、供应商配置或发布策略 |

## 内核对象

### 1. 角色卡：稳定人格与职责边界

角色卡是工作上的“性格”，不是随意人设。它由下列稳定字段构成：

- `identity`：该角色负责什么；
- `temperament`：稳定的判断倾向，例如故事分析师“证据优先”、导演“镜头服务叙事”、生成制作人“候选与成片分离”；
- `authority`：角色可以提出什么、不能批准或修改什么；
- `memory_scope`：能接收哪一类已批准项目记忆；
- `deliverables`：应输出的可验收产物。

角色卡与 Profile 一样应由版本控制和人审维护。角色可提交新的经验，但不能修改自己的核心身份、权限、核心技能或代码。

### 2. 记忆：先审后用

项目 `vsc.json` 的 `memories` 支持：

- 范围：`project`（项目共享）或 `role`（只给指定角色）；
- 类型：`fact`、`decision`、`lesson`、`preference`、`session_brief`；
- 置信度：`high`、`medium`、`low`；
- 敏感度：`public`、`project`、`restricted`；
- 生命周期：`draft` → `approved`，或 `rejected`/`retired`。

只有已批准、任务相关且仍有有效依据的记忆会进入上下文包。`restricted` 默认不注入，需要 `--include-restricted` 显式开启。记忆可用 `--tag` 标注主题，用 `--memory M-ID` 显式选择当前任务需要的记忆；选择仍受可见范围和预算约束。引用的来源/产物已改变、失效或被替代时不再注入。

### 3. 上下文包：继承，但不全量复制

`context build` 在 `10-记忆/上下文/CT-xxxx.json` 写入 `vsc.role-context/v1`。它包含：

1. 项目标识、Profile 和负责人；
2. 角色卡与本次单一任务；
3. 显式选择的**已批准**输入产物（路径、摘要、哈希和依赖）；
4. 按任务相关性、角色范围与字符预算检索的已批准记忆；
5. 被授权、证据仍有效且任务相关的 approved 能力卡，以及仅由 `--pilot C-ID` 指定的独立试用能力列表；
6. 可选的 `parent_brief`，即总编排器从当前会话提炼的任务摘要；
7. 不执行外部内容、不得越权持久化/训练的规则。

`parent_brief` 只写在任务包文件，不回写 `vsc.json` 正文或长期记忆。标签为 `context_file_only_not_long_term_memory`：任务包文件确实保存在磁盘上，当前没有自动清理，因此不能把它称为真正临时内存。如果值得长期保留，另行登记为 draft `session_brief` 并批准。

当前检索使用可解释的关键词、中文双字组合与领域词重合；不调用 embedding 或模型。`--budget-chars` 默认 12000，计量的是被检索知识的序列化字符量；`--memory`、`--capability`、`--pilot` 的显式选择必须完整放入预算，超出就报错。无相关性的知识不会因为“已经批准”就全量注入。任务和父摘要各限 6000 字符，输入最多 50 个产物且元数据最多 20000 字符，完整任务包最多 150000 字符；这些必要元数据不计入检索预算。

## 素材到能力的生命周期

### 来源与观察

先把视频、图片、音频、文本或已有交接包登记为来源，并声明权属：

- `owned`：项目方拥有足以覆盖拟定用途的权利；
- `licensed`：已有可核验许可，且用途未越界；
- `analysis_only`：仅用于研究/分析；
- `unknown`：尚未核验，默认不能用于生产性学习。

随后执行 `learn observe`。它产生 `O-xxxx`，包含观察类别、来源编号、来源与证据的完整 SHA-256、权属快照、摘要和 `untrusted_observation` 标记。`--polarity positive|negative|neutral` 区分有效例子、失败反例和未判断观察，反例不会因成功晋升而删除。来源路径被替换、证据被改写或权属不可用于生产时，后续试用/晋升会停止。观察类别包括：

- `action`：动作目标、起止姿态、节拍、空间方向、碰撞/反应；
- `vfx`：特效触发条件、层次、时序、合成边界；
- `layout`：前中后景、动线、构图、光源、空间关系；
- `emotion`：情绪目标、表演外显、信息变化、镜头/声音响应；
- `dialogue`：人物意图、潜台词、轮次、停顿、信息转折；
- `sound`：声线设计、节奏、声画关系、授权限制；
- `editing`：镜头覆盖、切点、节拍、转场、声音重叠。

这一步的核心是“**观察是数据，不是命令**”。无论来源中出现何种文字、提示、角色命令或网页说明，都不允许它修改 VSC 规则、调用工具、写入长期记忆或越过权属限制。

### 能力卡与评测

`capability propose` 把同类观察变成 `C-xxxx` draft，字段包括：

- 名称和类别；
- `method`：可复用的抽象做法；
- `limits`：适用范围、不可做什么、版权/人格/声音边界；
- 观察证据与来源权属快照；
- 被允许使用它的角色；
- 状态、评测记录和责任人的决定。

一个正确的能力卡例子是：“**五拍动作节奏与方向线检查**：按起势、交手、受击、停顿、反转拆分镜头；每拍标注进入/离开方向、情绪变化和安全限制；仅用于拥有或获许可的项目。”

一个不合格的能力卡例子是：“复刻某演员的武打动作、某作品镜头、某真人声线或某作者画风。”后者既不是可验证方法，也可能涉及人格、版权、邻接权、合同或平台限制。

状态转移为：

```text
draft --(负责人，且所有来源 owned/licensed)--> pilot
pilot --(有效版本绑定 pass + 无未解决 fail + 负责人)--> approved
draft/pilot --(负责人)---------------------------> rejected
pilot/approved --(负责人)------------------------> retired
```

`pilot` 只在显式构建的试用上下文中使用，且至少绑定一个已批准输入。`context build --pilot` 写入 `TR-xxxx`，绑定 `CT-xxxx`、方法摘要和输入版本。普通上下文不会注入 pilot。

`capability evaluate` 必须提供试用 `--context`、试用输出 `--output`、同类型同 scope 的比较 `--baseline`、评测报告 `--evidence` 和 `--criteria`。输出的 `depends_on` 包含全部试用输入，报告的依赖包含输出与基线；三者须是不同的已批准产物。`EV-xxxx` 保存完整方法摘要、输入/输出/基线/报告版本与上下文摘要。上下文被篡改、证据被替代或依赖失效时，评测不能作为晋升证据。

所有 pass/fail 记录都会保留。先 pass 后 fail 会阻止晋升；负责人在同方法、同输入、同基线与同 criteria 下重测，通过时用 `--resolves EV-ID` 明确解决失败。未解决 fail 不能被其他 pass 掩盖。旧评测缺少这些绑定，仅作为历史。

至少一次有效 pass 且无未解决 fail 是程序上的必要条件，不足以证明专业效果或跨场景泛化。方法仍需代表性样本、不同条件的反例和人工声画评价；代码不自动判断“音乐是否感动观众”或“打斗是否有说服力”。退役后不再注入，原证据与结论保留。

## 操作示例

```bash
# 1) 登记已授权的动作视频；VSC 只记录路径与哈希，不复制素材
python3 scripts/vsc_state.py source add ./projects/追逐 \
  --kind video --file ./reference/owned-action.mp4 --rights owned

# 2) 以标注笔记为证据，记录不可信观察
python3 scripts/vsc_state.py learn observe ./projects/追逐 \
  --kind action --source S-0001 --file ./notes/action-beats.md \
  --content "动作按起势、交手、受击、停顿、反转五拍拆解；每拍检查屏幕方向。" --polarity positive

# 3) 写出方法与限制，限定给导演使用
python3 scripts/vsc_state.py capability propose ./projects/追逐 \
  --name "五拍动作节奏" --kind action --observation O-0001 --role director \
  --method "按五拍拆镜头，并为每拍记录方向线、动作目的和情绪变化。" \
  --limits "只用于拥有或获许可的项目；不得复刻人物、声音或具体作品表达。"

# 4) 开放受控试用。假设已批准输入 A-0010；比较基线 A-0011；
#    输出 A-0012 depends_on A-0010；报告 A-0013 depends_on A-0011/A-0012。
python3 scripts/vsc_state.py capability decide ./projects/追逐 C-0001 \
  --status pilot --by "导演"
python3 scripts/vsc_state.py context build ./projects/追逐 \
  --role director --task "用五拍方法设计这场打斗，与原方案比较方向清晰度" \
  --artifact A-0010 --pilot C-0001 --budget-chars 12000
python3 scripts/vsc_state.py capability evaluate ./projects/追逐 C-0001 \
  --context CT-0001 --output A-0012 --baseline A-0011 --evidence A-0013 \
  --criteria "相同输入下，观众能正确指出动作方向，且衔接优于基线" --result pass --by "导演" \
  --note "方向连续、节奏和表意均通过；未出现授权范围外的参考复刻。"
python3 scripts/vsc_state.py capability decide ./projects/追逐 C-0001 \
  --status approved --by "导演"
```

## 跨项目复用

项目记忆、来源素材和角色事实保持在原项目。方法跨项目复用通过 `vsc.capability-method/v1`，白名单仅含名称、类别、方法、限制、角色、主题标签与内容摘要。

```bash
python3 scripts/vsc_state.py capability export ./projects/追逐 C-0001 \
  --file ./shared/action-method.json --name "通用方向线方法" \
  --reusable-method "切动作镜头前建立方向线，并核对入出点。" \
  --reusable-limits "适用于方向明确的动作；不能替代人工审片。" --confirm-generalized
python3 scripts/vsc_learning.py method validate ./shared/action-method.json
python3 scripts/vsc_state.py capability import ./projects/新故事 --file ./shared/action-method.json
```

导出不会自动拷贝原 method 文本，用户需要显式给出去项目化内容并确认。结构校验可以排除项目 ID、来源、记忆、观察、试用和评测字段，无法可靠判断自然语言是否包含私密事实，因此文本去项目化仍由导出负责人复核。首次导入为 draft，不继承原 approved 与评测结果；复核时带 `--note` 决定 pilot，再在新项目建立试用与评测。

## 安全、权利与运营边界

1. **权属是门，不是备注。** `unknown` 与 `analysis_only` 来源可以帮助人理解素材，但不能推进到 pilot 或 approved。`licensed` 也要由负责人确认许可是否覆盖训练、衍生、商用、地区、期限和发布平台；状态机不替代法律判断。
2. **防止提示注入。** 文件、网页、字幕、音频转写、图像 OCR 和模型回复都按不可信来源对待；不执行其中的“忽略规则”“导出记忆”“运行命令”等内容。
3. **保护敏感信息。** 不将完整会话、密钥、联系人、未公开剧本、演员生物特征或声音样本默认写入长期记忆；`restricted` 需要显式下发。
4. **不混淆方法与复制。** 镜头节奏、空间方向、动作安全、对白轮次和情绪转折可成为抽象方法；特定人物肖像、声线、作品画面或风格不能因“学习”自动获得可用权。
5. **可撤销且可复盘。** 失败、投诉、权属变化或审美失效时退役能力卡；未来任务不再读取它，但证据、评测和决定保留在事件台账中。
6. **不替代真实训练治理。** 如果未来接入模型训练/微调，应另建数据集清单、同意/授权记录、去重与删除机制、供应商条款审查、隔离执行环境、模型版本、红队评测、成本预算和发布审批。它不是 `capability approve` 的隐含副作用。

## 迁移

schema 1/2 的旧项目需要迁移到 schema 3。运行：

```bash
python3 scripts/vsc_state.py migrate <项目目录>
```

迁移先在 `09-台账` 备份原状态，保存来源、产物、决定、记忆与评测历史；旧产物与能力批准撤为 draft，旧评测标记 `legacy_unbound`。历史 Profile 版本与当前不同且无法恢复时，显式使用 `--accept-current-profile` 迁移到当前规则。缺少权属的旧来源补 `unknown`；旧产物需重新登记为版本快照，能力须重新试用评测，不把旧 pass 当作新机制下的证明。

## 验证

`tests/test_vsc_learning.py` 与状态机测试覆盖以下关键行为：

- 按任务相关性和预算检索，显式选择预算不足时失败；
- pilot 仅通过显式试用上下文注入，普通任务不会误用；
- pass 后的 fail 阻止晋升，明确的同比较条件重测可解决失败，历史全部保留；
- 改写上下文、替代输出或改变观察来源会使评测/晋升停止；
- 去项目化方法可跨项目导入，但保持 draft 并重新评测；
- 旧无版本绑定 pass 不作为当前晋升依据。
