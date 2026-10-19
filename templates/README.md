# 模板、草拟与示范

本目录JSON是机器交接的结构起点，格式、模板和校验入口由[契约目录](../workflow/contracts.json)维护。现有文件中的人物、疤痕、服装、声音、路径、项目ID和SHA用于演示；复制模板不代表取得这些身份、媒体、权利或批准，不把这些值带入新作品。

草拟框架及实际方法见[任务中使用方法](../skills/vsc/references/method-practice.md)；完整原创修改例在各Skill references中按方法读取。机器模板、草拟稿和教材例子有不同用途，不需要给普通用户展示机器JSON。

1. 从本次真实目标和固定输入确定内容。草稿先表达行动/信息或意象关系、声画与保留项；未知值明确待补，不沿用示例voice或人物特征。
2. 将真实正文映射到结构，逐单元核动作、台词、静默及来源引用。screenplay的body与单元必须指同一表达；存在差异保留草稿并返回具体段落，不在登记时静默删句或编造来源。
3. 设计用`continuity-plan.json`承接shot_plan；`coverage-plan.json`固定覆盖的screenplay单元。资产用`asset-bible.json`区分身份/变体/必要参考，声音用`sound-cue-sheet.json`，剪辑用`timeline.json`及其实际render-plan。不创造另一个shot-plan模板或新产物状态。
4. 固定真实项目、范围、依赖版本和实际媒体SHA，运行`python3 -B scripts/kernel/catalog.py contract validate <format> <本次文件>`。项目登记时再按原Profile核依赖/范围/批准。独立Schema成功不等于通过项目批准或听审。
5. 正式交接前检查第二遍正文/结构及下游映射。换题材时特别检查示例姓名、年龄、口音、声线、伤妆和情节泄漏；无必要项不增造人物或声音。缺必要字段/来源/可用媒体则返回所属模块，保留旧批准快照。

例：观察段落只有风、树影和旁白，不因为资产模板含主角就补人物；证据片里的必要旁白也不能为了套“视觉叙事”而删除。模板契约继续完整，形式不适用处按现有规则如实说明。
