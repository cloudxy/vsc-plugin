# ADR-0001：以工作流内核收敛路由、角色、契约和第三方声明

- 状态：已采纳
- 日期：2026-10-02

## 背景

早期 VSC 把阶段与角色的事实分别写进 README、`skills/vsc/SKILL.md`、`agents/`、`scripts/vsc_state.py` 和零散模板。结果出现了正式路由提到 `storyboard-artist`、`performance-sound-director`、`continuity-reviewer`，但没有对应 Agent 的问题；角色卡又被 Agent Markdown 和 Python 字典各维护一份。跨阶段 JSON 契约也要求使用者知道不同的底层脚本和子命令。

这些都是浅模块：接口小到只是一段说明，但调用者需要理解许多分散实现，局部性和杠杆都很低。

## 决定

1. `workflow/kernel.json` 是阶段 → 命令 → Skill → 角色 → Profile 覆盖 → 契约的唯一机器可读路由。
2. `workflow/roles.json` 是角色身份、人格、权限、记忆范围及交付物的唯一机器可读来源。Agent 文件保留为宿主入口，并引用角色卡；项目状态机从角色卡读取数据。
3. `workflow/contracts.json` 是跨模块格式、模板与校验器接口的唯一目录。调用者使用 `vsc_kernel.py contract validate <format> <file>`，不需要知道底层由状态机还是 Remotion 实现。
4. `scripts/vsc_kernel.py doctor` 在本地验证上述接缝：所有 command、Skill、Agent、Profile 阶段、模板和校验器必须可达且一致。
5. `vendor/sources.lock.json` 是第三方来源的机器可读真相；`vendor/THIRD_PARTY.md` 由它生成，避免根目录与锁定文件各自维护项目清单。

## 后果

- 新能力需先在内核登记，再添加物理入口；未登记或缺失的入口会被 doctor 阻止。
- 角色会从 11 个实际 Agent 加上此前只存在于状态机中的总编排器，形成 12 个可发现、可校验的角色；不再保留三个没有实现文件的虚构角色名。
- 底层契约校验器仍可独立演进，调用接口保持稳定。
- Profile 仍是团队的业务扩展点；它只能使用内核至少覆盖过的阶段，避免“业务流程无责任路由”。
- 这是模块化单体，不是服务拆分。真实生成适配器、队列、成本账本和媒体存储仍是未来可替换实现，不因本 ADR 被假定为已完成。
