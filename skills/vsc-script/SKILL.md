---
name: vsc-script
description: "Write or revise VSC screenplays from an approved adaptation plan."
---

# VSC 剧本

只把已批准的改编设计外化为可表演、可拍摄、可听的场次。每场写人物目标、阻力、行动、变化、观众新增信息、对白/旁白、声音提示和预计时长；不要把小说心理描写原样改成台词。若剧情动机、信息顺序或新增内容需要改变，退回改编角色并登记决定，不在剧本里悄悄修改。

先运行 `python3 scripts/vendor_skills.py --resolve script`。对已安装且标为 `guide` 的 InkOS 剧本 Skill 与 OpenWrite 对白质量 Skill，直接读取原始 `SKILL.md` 后运用其方法；OpenWrite 原生创作 Skill 只有在 bridge 已配置时才调用。输出必须仍符合 VSC 已批准改编方案和场次结构。
