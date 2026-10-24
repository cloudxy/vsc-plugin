---
name: vsc-schema-review
description: "Review VSC relational schema or migrations for atomic facts, typed relationships, project isolation, immutable evidence and safe authority cutover. Invoked from architecture maintenance."
---

# VSC 关系模型审查

从 `vsc-architecture` 的维护路由进入；不增加创作阶段或人工批准，不承担网页展示。

1. 读 [权威与迁移决定](../../docs/adr/0005-postgres-resource-authority.md) 和本次受影响领域。规范表定义是 `src/vsc/adapters/persistence/postgres/schema.py`，已发布迁移是 `migrations/postgres/versions/`；不在本 Skill 复制 SQL。
2. 说明每张新表的一行表示什么、候选键是什么。固定 1:N 用外键，M:N 或有生命周期的关系用中间表；引用对象必须有类型与外键。项目内引用检查复合外键，不能仅靠调用方过滤。
3. 检查同一事实是否出现多个可写来源。正文、参数、工具输出可用 JSON；对象引用、用途绑定、来源、选择和任务输入必须可用关系查询。标明不可变快照和可重建投影的来源、版本及摘要。
4. 检查 nullable unique、并发选择、图无环、审批历史、删除策略。跨行规则要有事务锁或数据库触发器，不能用读后写的应用检查冒充约束。
   固定版本还需封存成员集合：只禁止已有行UPDATE/DELETE，不能阻止INSERT改变快照；实际验证提交后追加成员与不完整集合。来源素材可再次共享时，核上游撤权能否沿加工/生成血缘传到最终消费者；没有完整权利闭包的路线应明确拒绝，不能只检查最后一跳的新权利记录。
5. 执行 `python3 -B scripts/project/schema.py check`；有隔离数据库时执行 `--database-env VSC_TEST_DATABASE_URL` 比对实际迁移。仅对本次修改运行 `tests/assets/integration/test_resource_store.py` 及对应受影响测试。跳过或无数据库不算通过。
6. 用 `python3 -B scripts/project/schema.py describe` 输出表粒度、键、外键和 Mermaid ERD，记录必要查询与索引证据。迁移检查预览、备份、冻结、导入、核对、切换；禁止读取失败时回退旧权威。

技术检查不替代用户的素材选择、创作批准或权利判定。领域基数有新歧义时记录问题和建议，已有会话决定直接执行。
