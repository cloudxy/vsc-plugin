---
name: vsc-database
description: "Review and implement VSC database constraints, queries, transactions, migrations and recovery using existing authority and connection boundaries. Invoked from architecture maintenance."
---

# VSC 数据库工程

从 [vsc-architecture](../vsc-architecture/SKILL.md) 的维护路由进入，主责 `database-engineer`。只处理本次数据问题；纯UI/文案不强制调用。模型/迁移审查复用 [vsc-schema-review](../vsc-schema-review/SKILL.md) 的原子事实、typed关系、项目隔离、不可变证据和切换规则，本 Skill 不复制规则或 SQL，不另建权威和批准。

## 先确定真实目标

固定目标连接类别、数据库主版本、驱动/迁移版本、schema revision、本次表粒度/键或查询、参数范围、数据规模和应用消费者。连接由 `vsc.configuration` 统一读取 `config/.env`，缺配置先核此文件且不输出密钥；既定实例、端口、库名、账号和权限不随功能开发调整。先确认会话实际暴露的 MCP 工具与目标库；配置存在不等于已连通。

正式 MCP 仅 `postgres_query` 专用只读账号，测试写用原隔离连接/`postgres_test_execute`；应用及显式迁移沿原读写连接与本次授权。角色名不增加权限，不自动改配置、启动实例或在正式库试写。先消费固定最小上下文，原协议返回，记忆只作有来源提案；工作自检与只读 `fresh/followup` 独立复核分别报告。

## 按问题选方法

1. **模型或迁移。** 先执行原 schema-review，沿 `schema.py`、已发布 migration 与所属领域实现。自动生成仅是候选；核旧数据、数据变换、约束、应用前后版本兼容和必要锁。迁移前后核实际结构和数据不变量，完整切换沿原 preview→backup→freeze→import→compare→cutover，不因新角色另加人工门。
2. **查询与分页。** 固定查询条件、顺序、页边界及项目/集范围，用同夹具记录 SQL数、读取/返回行数、计划、缓冲与应用等待的适用项。先核范围/批量读取再判断索引，不按列数机械加索引，也不以“小表顺序扫描”判失败。只改变其他集规模时，核当前范围查询/输入有界，记录测量值而不预写提升百分比。
3. **计划与执行语义。** `EXPLAIN` 给估计；`ANALYZE` 会实际执行语句，`BUFFERS`/真实耗时须按版本和权限选用。正式只读分析仍要核查询/函数副作用；写查询测量在本次获准隔离库执行，不把 `ROLLBACK` 当作所有外部副作用可回退的保证。计划成本不是网络与完整用户等待时间，冷/热缓存、统计和规模写清。
4. **事务与并发。** 明确事务拥有者、锁顺序、唯一/外键约束和冲突响应。用两个真实事务验本次竞争：例如同一固定意见重复接受保留一次原决定，冲突基线拒绝覆盖；不是用顺序请求证明并发。应用错误处理、回滚与可读回回执交全栈接通；不能用调用方先查后写替代数据库约束。
5. **备份与恢复。** 仅本次迁移/恢复需求适用时执行，先定恢复目标、允许的丢失范围、保留期及目标环境。核工具与服务版本、备份范围/全局对象/外部媒体；备份命令成功后在获准隔离目标实际恢复并比较键、行数、约束及应用读写。没有做恢复就只报告已备份或方案；不因查询小修强制全库恢复。切换后回退先保全新事实与回执，不能恢复旧镜像抹掉新数据。

将实际适用部分交接给应用消费者；可用简短 [database-change](templates/database-change.md)，不适用部分说明理由即可。正常/失败用例沿 [维护验证与测试](../../docs/guide/maintenance.md)选择；运行源码测试时再读该工作区的 `tests/README.md`，数据库缺失或跳过不算实库通过。

## 原创正反例：当前集意见历史

- **正例做法：** 对当前项目/第2集按固定顺序读取意见历史，限制单页数量并批量取本页必要关系；同夹具把其他集增至10倍，记录本页行数、SQL数和计划。应用使用页边界读回，刷新仍看到原意见/决定。若发现索引缺口，只补实际过滤/排序所需部分并测代价。
- **反例：** 全项目加载再在前端滤第2集，或每行再查一次；只测空库、只写“已有索引”；并发写入后页边界重复/漏行却以 HTTP 200 判通过；在正式 MCP 改账号只读权限“方便迁移”。分别回范围查询、批量消费者、页序语义及既定权限边界修复。
- **退出证据：** 同条件的真实 SQL/事务和应用消费者结果、规模/版本/计划与未验项可复核；改结构时原 schema专项通过；恢复任务有实际恢复比较。教材不是本轮性能、迁移或恢复已经成功的记录。

## 按需一手资料

本机优先 [ADR-0005](../../docs/adr/0005-postgres-resource-authority.md)、[术语](../../GLOSSARY.md)、原 schema专项和领域测试。以下为2026-10-24核读范围，不代表整份手册或所有后端兼容验证；17版是资料定位，实施仍核真实服务版本。

| 资料与范围 | 用途 |
| --- | --- |
| [PostgreSQL 17 EXPLAIN](https://www.postgresql.org/docs/17/sql-explain.html)，Description及ANALYZE语义 | 区分估计与实际执行、计划与应用成本。 |
| [PostgreSQL 17 Explicit Locking](https://www.postgresql.org/docs/17/explicit-locking.html)，表/行锁及死锁章节 | 按实际事务检查竞争及锁顺序，不照搬最大锁模式。 |
| [Backup and Restore](https://www.postgresql.org/docs/17/backup.html)，三种路线概览；[pg_dump](https://www.postgresql.org/docs/17/app-pgdump.html)，Description的单库/格式/恢复工具 | 选择备份边界；实际恢复需求再读对应章节，不将目录阅读记为恢复实测。 |
| [Alembic Autogenerate](https://alembic.sqlalchemy.org/en/latest/autogenerate.html)，候选迁移与检测限制 | 核人工审阅及数据变换；对照本机版本，不因网页新增特性升级迁移工具。 |
