---
name: vsc-assets
description: "Design VSC character, location, prop, action and voice assets before generation."
---

# VSC 资产

把“建模”分成语义设计、参考资产和可选技术实现。人物卡写不可变身份特征与可变服装/状态；场景卡写空间关系、光源、可见道具和时间天气；动作规格写目的、起止姿态、节拍、力量、交互；声音规格写声线、说话习惯、表演变化与授权范围。不要把一张参考图误称为 3D 模型，也不要把声音设计误称为已获声音克隆授权。

资产库保存为 `vsc.asset-bible/v1`（从 `templates/asset-bible.json` 复制起步，字段与命令见 `scripts/consistency.py --help`）：人物、道具、物体、地点各有稳定 ID、不可变特征和命名变体，参考素材绑定 SHA-256；会说话的人物绑定音色，有标志声音的物体或地点绑定声音；全片字幕样式写在同一份资产库里。新增服装、伤妆或道具状态时增加变体，不改写既有变体的含义。

按[上游 Skill 用法](../vsc-vendor/SKILL.md#下载后直接使用-skill)解析 `assets` 阶段，结论写入 VSC AssetBible、动作规格和连续性约束；不因使用上游方法扩大人物、声音或素材的授权范围。
