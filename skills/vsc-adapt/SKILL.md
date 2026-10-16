---
name: vsc-adapt
description: "Adapt source material into an auditable VSC story basis, adaptation contract and episode beats."
---

# VSC 改编

只处理来源理解与影视改编：先建立 SourceMap、StoryBible、改编契约、AdaptationPlan、EpisodeBeats 和 `vsc.adaptation-map/v1`。明确区分原文事实、人物说法、解释、改编、新增和待定；每个重要删改写出来源、原功能、屏幕表达、代价与采用理由。没有来源依据时标待定，不编造。

按[上游 Skill 用法](../vsc-vendor/SKILL.md#下载后直接使用-skill)解析 `adapt` 阶段；无论借用何种 Skill，改编结果仍必须满足以下 VSC 追溯与批准契约。

先按[来源与作品形式](../vsc/references/creative-production.md)选择因果剧情、散文意象或纪实信息的组织方式。每个屏幕单元必须写回 `source_refs`：剧情外化为可见行动、角色目标、阻力、选择与观众新增信息；散文组织观察视点、感官意象与情绪关联；纪实组织可核查事实、证据与理解顺序。开场建立视点与关注，结尾按目标选择闭合、余韵、行动或悬念，不强制对抗、反转或双钩子。新增内容必须在改编契约中登记，不可用空引用掩盖。交付进入 `01-来源/` 与 `02-改编/`，登记为 artifact，并运行：

```bash
python3 scripts/vsc_kernel.py contract validate vsc.adaptation-map/v1 <改编映射.json>
```

随后等待创作负责人批准。

## 制作交接 v2

新规则使用来源快照与可解析定位；source-map、episode-beats、adaptation-map 固定版本。区分事实、人物说法、解释与新增；invention 必须绑定真实决定。单条结尾可闭合、余韵、行动或悬念。

规则见 [制作协议](../../workflow/production-v2.md)，操作见 [v2 指南](../../docs/guide/production-v2.md)。
