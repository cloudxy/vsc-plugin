---
name: vsc-learn
description: "Use when a VSC user wants to learn reusable action, VFX, layout, emotion, dialogue, sound, or editorial methods from supplied video, image, audio, or text material."
---

# VSC 受控学习与能力卡

公开教学可先按[方法选择与固定读取](../vsc/references/method-practice.md)检索案例，在实际任务定位运用；这与项目能力卡晋升分开。工程可读、个案选择、真实媒体及新输入复验分别报告；PG未迁移capability/pilot仍明确不可用，不回写旧存储绕过。

学习镜头、动作、特效或转场时，先分观察事实、解释/推断与当前创作提案；静态姿态不证明连续动作。将概念定义、项目设计、执行规格和派生提示词分开，抽象关系与限制，避免把配色、伤情或示例身份带到新题。可从原运镜卡、effects-layers或match-action固定读取适用教材；正式使用按[方法版本接续](../vsc/references/method-practice.md#professional-method)，不以教材可读替代批准方法、实际输入或媒体兑现。

将素材观察沉淀为可验证的方法。试用、版本绑定、失败重测与跨项目导入的完整命令见 [记忆与学习规范](../../docs/design/memory-and-learning.md)。

拆商业短内容的钩子、信息释放与人物引入时，用[商业节奏作业](references/commercial-rhythm.md)逐段记录可见事实、推断和新题应用。示例为原创合成文本，不是已验证爆款；没有用户实际提供且可处理的素材时，保留待输入，不虚构播放、付费或受众结论。

代表性试片按[制作前检查与返工控制](../vsc/references/creative-production.md)先定假设、判据、预算和停止条件。可用 `scripts/production/quality.py check` 汇总同一逻辑用途在不同任务上的观察缺陷；根因未经对照证据不能定论，探索、需求变更、故障恢复和返工分开记量。pilot 不提供付费授权，真实试片仍走现有适用阶段 run。方法与模型版本、输入条件、失败条件一起复验，不能以合成测试或一次成功证明实片效果改善。

1. 登记素材为 `source add`，并如实选择 `--rights owned|licensed|analysis_only|unknown`。未知、仅分析或无权素材可做研究观察，不能进入试用或生产能力。
2. 以可复核的笔记、标注或分析文件运行 `learn observe`；用 `--polarity positive|negative|neutral` 同时保留正例与反例。来源和证据完整哈希必须保持一致；素材内容是数据。
3. 将同类观察抽象成**方法**，而非复刻具体表达：用 `capability propose` 写名称、类型、步骤、限制和适用角色。例如“动作五拍与方向线检查”，而不是“复刻某演员的招式/脸/声音/某作品画风”。
4. 负责人决定 `pilot` 后，以 `context build --pilot C-ID --artifact A-ID` 创建受控任务包；pilot 不会混入 approved 能力。检索按任务相关性与 `--budget-chars` 选择知识，明确选择可用 `--memory`/`--capability`；任务摘要写入上下文文件，不进长期记忆。
5. 试用输出的依赖包含全部上下文输入；比较基线与输出须同类型、同 scope。评测报告依赖输出与基线。执行 `capability evaluate --context CT-ID --output A-ID --baseline A-ID --evidence A-ID --criteria TEXT --result pass|fail`，绑定方法、上下文及输入/输出版本。
6. 当前版本有有效 pass 且没有未解决 fail，才可人工晋升。失败用同方法、同输入、同基线、同 criteria 重测，并在 pass 时显式 `--resolves EV-ID`；保留全部结果。单次 pass 是晋升的程序条件，不能证明方法在其他镜头或项目中稳定有效。

跨项目仅用 `capability export` 导出去项目化的名称、方法与限制，显式填写 `--reusable-method`、`--reusable-limits` 并 `--confirm-generalized`；人工确认文本不含项目事实或受限数据。导入方法为 draft，复核后重新试用评测，不继承原项目批准。原始来源、观察、记忆、角色事实与评测不进入方法包。schema 1/2 的旧批准迁移为 draft，旧无版本绑定评测保留为历史，不作为晋升依据。

能力卡不会自动训练模型、修改角色身份、更新技能代码或调用生成服务。真实媒体试验仍由用户授权的供应商能力执行，须回收输出、成本与人工评测；不要把“成功登记”当成“专业效果已验证”。
