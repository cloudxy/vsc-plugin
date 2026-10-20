---
name: vsc-assets
description: "Design VSC character, location, prop, action and voice assets before generation."
---

# VSC 资产

主体识别、色彩或光源有问题时，按[固定读取](../vsc/references/method-practice.md)选[注意力与光线练习](references/visual-attention-light.md)，只准备当前机位所需参考；教学示例身份/服装/声线不进入新作品默认值。

本轮交规格还是实际参考先说清，按[规格与实际参考的交接例](references/visual-attention-light.md#reference-delivery)检查固定身份、变体、可见侧与用途。接收生成角色实际打开媒体并绑定原任务输入后才有该用途消费；提示词、占位图或可读但不适用的图片不能补足参考任务，未采用候选仍保留真实比较价值。

按[资产最小用途与专业拆解](../vsc/references/creative-production.md)为每个参考视图、状态和声源写具体下游用途；先检索再补缺，不默认四视图、表情全集或无用道具。稳定身份、变体、表演与声线分开；验收按实际画幅与用途所需信息，辅助图不能承担其看不见的身份细节证明。

先用 `scripts/knowledge/search.py <词> --in all` 检索本机素材、原生制作规格、方法卡与作品。原生规格覆盖人物、服装、动物、道具、交通、场景、风格、特效、动作、打斗、表演、运镜、转场、人声、环境声、拟音、音乐、字体、字幕和图形全部 20 类；`--in recipes` 可单查，无需安装。方法库现有 34 条卡、14 个来源，供方法参考，不自动成为项目已批准能力。

先选择适合本片且权属可用的真实参考图、声源或媒体，再用 `scripts/assets/library.py use` 复制并按支持的种类绑定本项目，决定哪些素材需要新建。制作规格标记 `asset_type=specification`、`is_media=false`、`requires_human_selection=true`，只能指导设计，不能称为已生成媒体；`use --bible` 会拒绝直接绑定规格。规格的 `owned` 仅覆盖原创文字，不覆盖未来人物、音色、字体或音乐。清单与安装见[原生制作规格包](../../docs/guide/asset-recipes.md)，分类和操作见[素材复用与检索](../../docs/guide/reuse-and-search.md)。复用不继承另一个项目的创作批准。

把“建模”分成语义设计、参考资产和可选技术实现。人物卡写不可变身份特征与可变服装/状态；场景卡写空间关系、光源、可见道具和时间天气；动作规格写目的、起止姿态、节拍、力量、交互；声音规格写声线、说话习惯、表演变化与授权范围。不要把一张参考图误称为 3D 模型，也不要把声音设计误称为已获声音克隆授权。

动作与打斗设计写安全拍点、入出点状态、镜头与时长；真实接触风险由现场动作指导确认。人声规格用固定 speaker 占位，实际 provider/voice ID 未选定时留空，不能编造。选定合法声源后冻结角色映射，情绪变化写表演变体；声音文件保留来源记录、provider、model、prompt、SHA 和许可范围。环境底、拟音、音乐分别写循环条件、对白避让、进出点与输出格式；只有经实测的文件才能称为可循环、等长分轨或满足目标时长。

资产库保存为 `vsc.asset-bible/v1`（从 `templates/asset-bible.json` 复制起步，字段与命令见 `scripts/story/consistency.py --help`）：人物、道具、物体、地点各有稳定 ID、不可变特征和命名变体，参考素材绑定 SHA-256；会说话的人物绑定音色，有标志声音的物体或地点绑定声音；全片字幕样式写在同一份资产库里。新增服装、伤妆或道具状态时增加变体，不改写既有变体的含义。

按[上游 Skill 用法](../vsc-vendor/SKILL.md#下载后直接使用-skill)解析 `assets` 阶段，结论写入 VSC AssetBible、动作规格和连续性约束；不因使用上游方法扩大人物、声音或素材的授权范围。

## 制作交接 v2

稳定资产身份更新用 object bind 保留版本历史；参考按变体、媒体类别和用途过滤。资产准备正式 run 在 script Gate 与批准资产规格后进行，不以未来预演造成依赖环。

规则见 [制作协议](../../workflow/production-v2.md)，操作见 [v2 指南](../../docs/guide/production-v2.md)。

## 资源分类与横向引用

[资源工作区](../../docs/guide/source-resource-workspace.md)的十一类用于检索，身份种类、媒体类别和生产用途继续分别管理。人物／地点／道具／物体／生物／交通工具／植物可进入 Bible；声音、风格、服装沿各自规格。资源通过场地点、需求、实例和用途槽位横向关联。只登记、可预览、可作为输入和已具备执行器分别核对；模型、字体或 LUT 入库不等于供应商已支持执行。
