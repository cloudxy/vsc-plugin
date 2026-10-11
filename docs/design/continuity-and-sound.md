# VSC v0.4：把短剧做成连续作品，而不是片段集合

## 问题定义

小说剧本化、BGM、跨片段衔接不是后期“润色项”，而是短剧能否被看懂的共同骨架。

短视频生成通常以几秒到几十秒的镜头为单位，具体时长和功能随供应商、模型、地区及版本变化，不能将“最多 30 秒”写死为 VSC 的普遍事实。真正稳定的做法是：把每一段看成一个有明确入点和出点的**镜头单元**，用上游改编、资产、声音与剪辑计划约束它，再由时间线把它组织为场景与剧集。

公开工具的功能也指向相同的分层：Runway 将人物/场景 reference 与逐步迭代视为一致性控制手段；Google Flow 提供参考输入、视频扩展和场景组织功能；但这些是供应商能力，不能替代项目的状态契约。[Runway Gen-4 References](https://help.runwayml.com/hc/en-us/articles/40042718905875-Creating-with-Gen-4-Image-References) [Google Flow](https://labs.google/fx/tools/flow)

VSC v0.4 新增三个可验证协议：

| 问题 | 产物协议 | 责任角色 | 结构校验 |
|---|---|---|---|
| 小说如何变成可拍、可演、可剪的剧本 | `vsc.adaptation-map/v1` | story-analyst、adaptation-editor、screenwriter | `adaptation validate` |
| 多个 AI 片段如何保持人物、空间、动作和镜头连续 | `vsc.continuity-plan/v1` | director、asset-director、continuity-supervisor | `continuity validate` |
| 场景、情绪和剪辑如何组织 BGM、环境声和声音桥 | `vsc.sound-cue-sheet/v1` | music-supervisor、editor、post-reviewer | `sound validate` |

结构校验只检查“计划有没有表达关键约束、约束有没有自相矛盾”，不冒充视觉、声音、版权或叙事质量判断。每个通过项仍需人工审阅成片。

## 一、小说剧本化：从“讲述”变成“可见的变化”

小说不是剧本的长版本。小说可依赖内心、解释、叙述者和时间跳跃；短剧场次必须让观众在有限时长中看见：谁要什么、受什么阻碍、做了什么、局势怎样转向、观众新知道了什么。

VSC 的改编链为：

```text
来源定位与事实/说法/解释
    → 改编契约（不可改、可调整、新增原则）
    → 集级钩子（opening / exit hook）
    → 场景单元（可见行动、目标、阻力、转折、观众信息）
    → 对白、动作、声音提示与预计时长
    → 镜头与连续性计划
```

`vsc.adaptation-map/v1` 强制每个 screen unit 回指一个 source unit，并写：

- `visible_action`：屏幕上真正能看见/听见的行动，不是“她很害怕”；
- `character_goal` 与 `obstacle`：场景内的即时对抗；
- `turn`：场景尾部发生的关系、信息或策略变化；
- `audience_information`：观众新增理解；
- `episode_id`：它属于哪一集，集首和集尾分别靠什么抓住观众。

这并不禁止新增，而是拒绝无来源、无代价的偷偷新增：新增信息须在改编契约中留下决定与理由。用以下命令阻止“有漂亮梗概、没有可拍场景”的假完成：

```bash
python3 scripts/vsc_kernel.py contract validate vsc.adaptation-map/v1 ./02-改编/改编映射.json
```

## 二、跨片段连续性：把片段边界当成契约

### 2.1 先锁定稳定资产，再逐镜生成

每个连续场景先有 AssetBible：人物身份不变量（脸部/发型/体态、服装状态、道具持有、声线限制）、场景不变量（空间结构、地标、光源、天气、色彩）、动作规格（起止姿态、方向、接触和节拍）。再为每个镜头绑定稳定的角色、场景和道具 reference。参考图不是授权证明，也不是 3D 模型；它只是为生成适配器提供较稳定的视觉锚点。

Runway 的公开说明同样建议保存并复用人物/环境 reference，并用单独迭代的人物与场景路径提高控制度；VSC 将这个产品做法抽象为供应商中立的资产版本和引用关系，而非绑定某一模型。[Runway References Guide](https://help.runwayml.com/hc/en-us/articles/40042718905875-Creating-with-Gen-4-Image-References)

### 2.2 每镜都有状态机

一段 6–8 秒 AI 视频不应负责“整场追逐”，而应负责一个动作或信息单元。每镜写：

```text
entry_state  →  [本镜行动 / 镜头目的]  →  exit_state
```

状态至少包含：

- `scene_id`、`location_id`、时间/天气、光线和环境声；
- 每个出现角色的服装、道具、姿势、视线/方向和情绪外显；
- 景别、机位、运镜和屏幕方向；
- 稳定 reference asset IDs；
- `head_ms` / `tail_ms` 剪辑手柄；
- 到下一镜的桥接策略与必须相等的 `match_fields`。

例如，“女主向右奔跑”出镜后，下一镜的入点若使用 `match_action`，应显式匹配地点、服装、道具、姿势和屏幕方向。VSC 的校验器不会看懂成片，但会发现计划已经自相矛盾：

```bash
python3 scripts/vsc_kernel.py contract validate vsc.continuity-plan/v1 ./05-预演/连续性计划.json
```

`match_fields` 只约束相邻两镜。同场不相邻的镜头、隔几集回到同一地点，靠的是状态时间线（`vsc.scene-state/v1`）：每场只写一份基线和逐镜变化，出入点状态由累积推导，不会各写各的；时间线里的实体与变体又必须存在于资产库（`vsc.asset-bible/v1`）。生成时再按镜头推导锚点包，生成记录用其哈希绑定；锚点之后被改动，对应 take 会被标为过期。交叉核对见 `scripts/consistency.py check`。

### 2.3 桥接不是只有溶解

| 策略 | 适用条件 | 需要检查 |
|---|---|---|
| `match_action` / `match_frame` | 动作、视线、物体或画面构图要连起来 | 出入点匹配字段完全一致 |
| `cutaway` | 需要跨越人脸、动作或背景漂移 | 插镜提供叙事信息，而非只是遮丑 |
| `reaction_hold` | 对话、惊讶或反转需要留给观众反应 | 前一信息和后一反应在情绪上有因果 |
| `occlusion` / `whip_pan` | 遮挡或快速运动天然掩盖边界 | 屏幕方向、声音和运动速度仍一致 |
| `hard_cut` / `scene_cut` | 信息、时间、空间确实要跳变 | 写清跳变目的，并由声音承接或刻意留白 |

当“无缝生成”失败时，优先把问题退回最早根因：人物不同 → 资产/reference；左右跑反 → 动作规格/ShotPlan；光色不同 → 场景状态；观众看不懂 → 剧本/预演。不要用更花哨的转场掩盖前面没定义的状态。

视频扩展只适合修补很小的时间余量，不能替代镜头设计。Adobe 的当前文档将 Generative Extend 定义为片头/片尾增加少量帧以平滑转场或延长环境声；它不扩展对白或含音乐音频，且当前 FAQ 标注视频扩展上限为 2 秒、音频为 10 秒。因此 VSC 将“扩展”设为最后的补洞策略，且仍要求保留原始与生成版本。[Adobe Generative Extend FAQ](https://helpx.adobe.com/ph_en/premiere/desktop/edit-projects/edit-with-generative-ai/generative-extend-faq.html)

## 三、BGM 与声音：按情绪弧线跨镜铺设，而非每段重启

### 3.1 声音提示表

BGM 应由场景目标和情绪变化驱动，而不是只由“悲伤/紧张”标签驱动。每个 Cue 写：

- 叙事功能：建立、预期、对抗、揭示、释放、余波或反讽；
- 情绪和强度 `0–5`，并标明升级/降级发生在哪个剧情节拍；
- 音色、节奏/速度范围、留白与对白避让；
- 进入与退出方式、可控 stem/层、版本和使用权；
- 持续环境底（雨、空调、车流、房间调性等）；
- 每个画面边界的声音策略。

把一首或一组音乐 stem 按**场景/段落**铺到时间线上，让短视频片段只是视觉容器。环境底也独立于每条视频，覆盖同一声场的镜头边界。这避免了每 6 秒“音乐重新开头”、雨声突然消失或人声空间跳变。

### 3.2 声画分切创造连续性

J cut 让下一场声音先于画面出现，适合预示地点、人物或危险；L cut 让上一场声音延续到下一画面，适合保持情绪和因果。Adobe 的编辑文档对二者的定义和用途也是如此。[Premiere J/L Cuts](https://helpx.adobe.com/uk/premiere/desktop/edit-projects/trim-clips/perform-j-cuts-and-l-cuts.html)

对于相近声场，使用正确时长和曲线的 crossfade；对于音乐状态变化，设计过门、stinger 或声音桥。Wwise 的公开音乐文档将 source、destination 与可选过门段作为 transition 的显式对象；VSC 借用这一思想来管理线性短剧的 Cue，而不依赖某个游戏音频引擎。[Wwise Interactive Music](https://www.audiokinetic.com/en/public-library/2024.1.8_8893/?id=creating_interactive_music&source=Help) 音频 crossfade 的持续时间、重叠和曲线应写入时间线，而不是由导出软件猜测。[FFmpeg acrossfade](https://ffmpeg.org/ffmpeg-filters.html)

校验命令：

```bash
python3 scripts/vsc_kernel.py contract validate vsc.sound-cue-sheet/v1 ./07-后期/声音提示表.json
```

它要求每个声音边界有目的；非刻意静音时有环境底覆盖；J/L/crossfade 写了必要时长；音乐和环境素材声明 `owned`、`licensed` 或 `project_generated`。它不能替代音乐著作权、录音制品权、表演者权或供应商条款审查。

## 四、时间线是权威，不是文件夹排序

最终时间线必须写清 clip、时码、音视频轨、转场、marker、take 版本、声音 Cue 和选择理由。OpenTimelineIO（OTIO）提供了外部媒体引用的剪辑、轨道、转场、标记及编辑交换模型，适合作为未来 NLE/存储适配器的中立边界；VSC 当前只规定这个边界，不内置 OTIO 或绑定某个剪辑软件。[OpenTimelineIO](https://opentimelineio.readthedocs.io/en/latest/index.html)

每次审片至少分开报告：

1. **故事**：人物目标、转折和集尾钩子是否被看懂；
2. **画面连续**：人物、道具、动作、方向、空间、光色、画幅、帧率；
3. **声音连续**：对白空间、环境底、BGM 情绪弧、Cue 进出、音量和静音；
4. **技术**：时长、字幕、编码、媒体缺失、生成版本和交付规格；
5. **权利**：小说改编、图片/视频/音乐/音效、肖像与声音、模型与平台范围。

## 五、与公开 Skill/工具的关系

公开仓库和产品功能可以启发 VSC，但不应直接变成依赖：版本、活跃度、许可证、权重、数据集、素材和商用范围各不相同。比如 Storyboarder 可用于把剧本快速可视化并导出分镜/animatic，但它只是候选外部工具，必须先按 VSC Vendor 流程核验许可、维护状态与用途；VSC 不会下载或提交它的源码。[Storyboarder](https://github.com/wonderunit/storyboarder)

当前项目的 VSC 核心保持 MIT，但允许将其他许可证项目作为独立工具、完整本地组件或通过文件/CLI/HTTP 协议直接使用；第三方下载物仍留在本地 `vendor/` 而不进入 Git。任何声画生成、时间线、自动一致性检测或分镜工具，应在第三方声明中写明固定 commit、许可证证据、使用模式、用途边界和责任人；用户按需执行安装脚本后即可成为可选适配器。

## 验收路径

先用一个 45–90 秒样片验证，而不是直接做整部短剧：

1. 选小说的一次误读、一次对抗和一次反转，完成 `adaptation-map`；
2. 为同一场景做角色/场景/道具不变量和 6–8 个镜头状态；
3. 先做带临时对白、环境底和 Cue 的 animatic；
4. 逐镜生成候选，每镜保存 reference、出入点、参数摘要与 take；
5. 用 `continuity validate` 和人工逐镜审片找出错位；
6. 以连续环境底、BGM stem、J/L cut 完成声音桥，用 `sound validate` 检查；
7. 在时间线里完成真正的成片，再决定哪些方法可以进入能力卡。

通过这个样片后，才把有效做法以权属、观察、pilot、评测和人工批准的方式沉淀为 VSC 能力；不要把一次偶然成功的提示词自动升级为团队规则。
