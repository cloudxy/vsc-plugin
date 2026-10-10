---
name: vsc-adapt
description: "Adapt source material into an auditable VSC story basis, adaptation contract and episode beats."
---

# VSC 改编

只处理来源理解与影视改编：先建立 SourceMap、StoryBible、改编契约、AdaptationPlan、EpisodeBeats 和 `vsc.adaptation-map/v1`。明确区分原文事实、人物说法、解释、改编、新增和待定；每个重要删改写出来源、原功能、屏幕表达、代价与采用理由。没有来源依据时标待定，不编造。

按[上游 Skill 用法](../vsc-vendor/SKILL.md#下载后直接使用-skill)解析 `adapt` 阶段；无论借用何种 Skill，改编结果仍必须满足以下 VSC 追溯与批准契约。

每个剧本化场景必须写回 `source_refs`，并把小说叙述外化为：可见行动、角色即时目标、阻力、转折和观众新增信息；每集还要有开场钩子与结束钩子。新增内容必须在改编契约中登记，不可用空引用掩盖。交付进入 `01-来源/` 与 `02-改编/`，登记为 artifact，并运行：

```bash
python3 scripts/vsc_kernel.py contract validate vsc.adaptation-map/v1 <改编映射.json>
```

随后等待创作负责人批准。
