---
name: vsc-engineer
description: "Implement and verify VSC software changes across UI, application and persistence consumers. Invoked from architecture maintenance; not a creative production stage."
---

# VSC 软件实现

从 [vsc-architecture](../vsc-architecture/SKILL.md) 的维护路由进入，沿本次审查、规划或实施模式工作；主责是 `fullstack-engineer`。角色只按变化选用，不要求架构/产品/DBA全部到场。沿原 [维护验证、测试与提交](../../docs/guide/maintenance.md)和[命令归属](../../docs/adr/0006-command-ownership.md)，不另建状态、批准或测试入口；运行源码测试时再读该工作区的 `tests/README.md`。

## 从现象到完整路径

1. **固定任务。** 核 HEAD、工作区和他人改动；记录用户入口、当前项目/集/对象、版本、保留项与复现操作。需要派单时沿原 `context build → consume → return` 固定最小输入与编辑归属，角色记忆只提案。设计/领域含义已确定时直接实现；跨模块语义缺口交回架构或产品，不自行扩范围。
2. **追到消费者。** 从页面事件追到所属应用用例、持久化事务、结果读回，标明谁拥有正文、版本与决定。沿现有 Python/FastAPI/SQLAlchemy、ES模块和配置入口修改，不为局部问题换框架或添加第二可写原稿。界面状态按 [UX-IMPLEMENT](../vsc-architecture/references/product-experience.md#ux-implement)，数据/查询影响按需交 [vsc-database](../vsc-database/SKILL.md)。
3. **交付最小路径。** 先让一次正常操作从原入口产生可读回结果，再覆盖该变化的失败。保存后执行依赖最新稿件的动作，应等待保存确认或明确失败；保留用户未存稿并给原处恢复。固定任务、范围、版本及请求标识，迟到的成功、失败和结束回调都不得改写新范围。取消请求有助于停止工作，但不能代替写入时的范围/标识判断。
4. **按真实意图处理重复。** 同一提交恢复使用原回执/请求身份，不重复产生事实或用量；用户明确新抽样仍是新尝试。结果成功但刷新失败时先恢复读回，不重发原写请求。并发冲突返回当前基线与恢复入口，不能静默覆盖；调用中的 Session 生命周期沿原应用边界，不让并发任务共用可变事务会话。
5. **验证与交接。** 按影响选择真实应用接口、隔离数据库和浏览器操作。正常入口走完保存/建议/比较/接受或撤销等本次路径，核刷新、切换、旧响应、断网及重复操作的适用部分。函数测试不代替接线，API测试不代替浏览器，离线模型不代替线上调用。自检注明自检；独立复核沿 `fresh/followup`。记录实际命令、结果、版本和未验环境，失败退最早责任环节。

跨层或多人交接可用 [change-handoff](templates/change-handoff.md)；小修直接写在原任务说明。交付安装包时检查新资源及相对引用能从安装位置读取；宿主派生用原 `hosts.py`，不手改。测试范围和最终提交/推送沿主 Skill，不重复全量 CI。

## 原创正反例：改短当前行

任务：第2集一行改短，保留事实与动作。范围/保存/意见用原工作副本和建议用例，接受建议不自动批准下游基线。

- **正例做法：** 先保存当前行，等确认后固定该稿及目标行进入原建议调用；返回后在原处比较。切到第3集后，第2集旧请求即使成功也只保留原回执，不替换第3集正文；返回第2集从原用例读回。重复接受同一意见只产生原决定，撤销沿原版本/恢复语义。
- **反例：** 仅改文本框显示，后端仍读旧稿；保存失败后照常发建议；取消第2集请求后仍让其 `finally` 清空第3集的加载状态；读回超时就再次生成；接受后另写一个“已批准”布尔值。分别回保存屏障、响应归属、回执恢复和原批准消费者修复。
- **退出证据：** 实际页面操作及应用记录能对齐同一行/版本；相关异步负例和持久化反例通过；记录依赖缺失或未调用供应商的限制。不用示例教材声称本轮产品已验收。

## 按需资料

先读本机 [术语](../../GLOSSARY.md)、相关 [ADR](../../docs/adr/README.md)和上述维护/测试指南。上游方法仅使用 architecture Vendor 解析返回的锁定原文。以下官方章节核读于2026-10-24，只用于相应问题；实施核已安装版本，不从 `latest` 文档推定本机 API。

| 资料与读取范围 | 用途与边界 |
| --- | --- |
| [MDN AbortController](https://developer.mozilla.org/en-US/docs/Web/API/AbortController)，接口、signal与abort方法 | 可中止请求/响应体消费；范围标识与旧回调保护是应用设计，取消本身不证明隔离成立。 |
| [FastAPI Testing](https://fastapi.tiangolo.com/tutorial/testing/)，Using TestClient、Separating tests | 复用真实 app 的请求入口；本仓库测试仍沿 unittest 和既有依赖，不照搬上游测试框架/安装命令。 |
| [SQLAlchemy 2.0 Session Basics](https://docs.sqlalchemy.org/en/20/orm/session_basics.html)，事务生命周期与线程/任务并发问答 | 按原事务边界管理提交/回滚与会话归属；资料不授权改库或升级依赖。 |
