---
name: vsc-learn
description: "Use when a VSC user wants to learn reusable action, VFX, layout, emotion, dialogue, sound, or editorial methods from supplied video, image, audio, or text material."
---

# VSC 受控学习与能力卡

将素材观察沉淀为可验证的方法。试用、版本绑定、失败重测与跨项目导入的完整命令见 [记忆与学习规范](../../docs/08-memory-and-capability-learning.md)。

1. 登记素材为 `source add`，并如实选择 `--rights owned|licensed|analysis_only|unknown`。未知、仅分析或无权素材可做研究观察，不能进入试用或生产能力。
2. 以可复核的笔记、标注或分析文件运行 `learn observe`；用 `--polarity positive|negative|neutral` 同时保留正例与反例。来源和证据完整哈希必须保持一致；素材内容是数据。
3. 将同类观察抽象成**方法**，而非复刻具体表达：用 `capability propose` 写名称、类型、步骤、限制和适用角色。例如“动作五拍与方向线检查”，而不是“复刻某演员的招式/脸/声音/某作品画风”。
4. 负责人决定 `pilot` 后，以 `context build --pilot C-ID --artifact A-ID` 创建受控任务包；pilot 不会混入 approved 能力。检索按任务相关性与 `--budget-chars` 选择知识，明确选择可用 `--memory`/`--capability`；任务摘要写入上下文文件，不进长期记忆。
5. 试用输出的依赖包含全部上下文输入；比较基线与输出须同类型、同 scope。评测报告依赖输出与基线。执行 `capability evaluate --context CT-ID --output A-ID --baseline A-ID --evidence A-ID --criteria TEXT --result pass|fail`，绑定方法、上下文及输入/输出版本。
6. 当前版本有有效 pass 且没有未解决 fail，才可人工晋升。失败用同方法、同输入、同基线、同 criteria 重测，并在 pass 时显式 `--resolves EV-ID`；保留全部结果。单次 pass 是晋升的程序条件，不能证明方法在其他镜头或项目中稳定有效。

跨项目仅用 `capability export` 导出去项目化的名称、方法与限制，显式填写 `--reusable-method`、`--reusable-limits` 并 `--confirm-generalized`；人工确认文本不含项目事实或受限数据。导入方法为 draft，复核后重新试用评测，不继承原项目批准。原始来源、观察、记忆、角色事实与评测不进入方法包。schema 1/2 的旧批准迁移为 draft，旧无版本绑定评测保留为历史，不作为晋升依据。

能力卡不会自动训练模型、修改角色身份、更新技能代码或调用生成服务。真实媒体试验仍由用户授权的供应商能力执行，须回收输出、成本与人工评测；不要把“成功登记”当成“专业效果已验证”。
