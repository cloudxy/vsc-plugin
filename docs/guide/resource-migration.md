# 旧项目迁移至 PostgreSQL

现有 JSON 和 SQLite 项目可以直接在资源面板中只读浏览。迁移是显式维护操作。迁移前旧存储保持唯一权威；切换后 `.vsc-postgres.json` 只记录 PostgreSQL 项目 UUID、连接变量名和存储策略，旧文件成为历史材料，不继续写入。

迁移工具不会调用生成平台，也不会替代人工批准。请先对照 [资源模型](resource-schema.md) 完成关系映射，安装 `postgres` 可选依赖，并显式执行数据库 schema 迁移。

```bash
uv sync --locked --extra postgres
python3 -B scripts/project/schema.py migrate
```

数据库连接由 `VSC_DATABASE_URL` 传入。配置写在工作区根目录 `.env` 并由工具启动时自动读取；真实 `.env` 不提交，连接字符串不写入作品、迁移清单或权威指针。

## 阶段和命令

以下命令从工作流根目录执行。`--by` 必须填写本次实际操作人。

```bash
python3 -B scripts/assets/resources.py migrate "projects/作品名" preview --out "projects/作品名/.vsc-migration/manifest.json"
```

预览读取旧权威、已登记产物及所有项目文件，生成固定摘要、事实清单、UUID 映射和缺口列表。不会修改旧 JSON/SQLite。清单放在项目的 `.vsc-migration/` 中或项目目录外，避免清单自身成为待迁移素材。

迁移预览会报告尚未完成的类型映射。

受支持的旧 JSON 项目可使用 `prepare` 准备类型化清单。必须显式指定单部工程容器及受控媒体根；它复制并核验素材，不改写原文件，也不执行冻结或切换：

```bash
.venv/bin/python -B scripts/assets/resources.py migrate "projects/作品名" prepare --by "实际操作人" --work-code W001 --source-timezone Asia/Shanghai --media-root "$VSC_MEDIA_ROOT" --archive-media --out "projects/作品名/.vsc-migration/manifest.json"
```

准备器从登记对象、固定版本正文、来源、生成输入输出及审核证据建立关系；原结构缺失的素材保持未绑定。无法建立执行关系的未批准草稿标记 `legacy_unindexed`，只保留历史原文，不能成为已冻结时间线。历史审核候选不会自动成为正式选片。准备结果有缺口时先处理缺口，不能直接切换；未知权利保留未知。

`--source-timezone` 明确旧版无时区时间的解释约定；应与来源工作区一致。清单保留原字符串和解释约定，类型化时间使用明确偏移，原文件与正文摘要不变。

完整清单准备并核对后，依次执行：

```bash
python3 -B scripts/assets/resources.py migrate "projects/作品名" backup --manifest "projects/作品名/.vsc-migration/manifest.json" --by "实际操作人"
python3 -B scripts/assets/resources.py migrate "projects/作品名" freeze --manifest "projects/作品名/.vsc-migration/manifest.json" --by "实际操作人"
python3 -B scripts/assets/resources.py migrate "projects/作品名" import --manifest "projects/作品名/.vsc-migration/manifest.json" --by "实际操作人"
python3 -B scripts/assets/resources.py migrate "projects/作品名" compare --manifest "projects/作品名/.vsc-migration/manifest.json" --by "实际操作人"
python3 -B scripts/assets/resources.py migrate "projects/作品名" cutover --manifest "projects/作品名/.vsc-migration/manifest.json" --by "实际操作人"
```

| 阶段 | 证据和行为 |
| --- | --- |
| preview | 原 revision、状态摘要、SQLite 表和行摘要、文件 SHA、全部待映射事实和缺口 |
| backup | 使用 SQLite 备份 API 和原文件字节创建独立备份；逐份校验摘要，不覆盖已有备份 |
| freeze | 再核对源、备份和完整映射；记录清单摘要，旧 CLI 写入被冻结 |
| import | 在一个 PostgreSQL 事务中插入全部类型行；外键或约束失败则整体回滚 |
| compare | 按主键逐项核对原文档字节、SHA、决定和关系；多出项目行也不通过 |
| cutover | 只发布已经对账的目标；原子写本地权威指针，再激活 PostgreSQL 写入 |

```bash
python3 -B scripts/assets/resources.py migrate "projects/作品名" status
```

冻结后修改清单或旧状态会阻止后续阶段。映射应在备份前完成；确需重新设计映射时，保留现有备份及冻结证据，制定明确的迁移恢复步骤，不能直接删除标记继续旧写。

## 清单的约束

`tables` 以真实 PostgreSQL 表名组织行，每行只能使用实际 schema 的列。`mappings` 为每条旧事实列出目标表及完整主键，`id_mapping` 保存原编号与新 UUID 的对应关系。使用 `objects:原编号`、`artifacts:原编号`、`media:原编号`、`jobs:原编号`、`bindings:原编号` 区分不同类型的编号空间；没有歧义时也支持原编号键。

必须完成以下映射：

- 项目、部、集、场、段、镜进入类型表，保留显示编号和原父级关系；结构缺失需要显式选择，不能从目录名猜测。
- 产物、来源保留原字节和原 SHA；依赖进入中间表。镜头与资产的固定版本绑定、历史资产版本也必须保留。
- 剧本台词、资产规格、状态、选片和时间线建立对应关系索引；只保存原始 JSON 文档不能代替这些关系。
- 素材区分 Blob、项目登记和存储副本；文件事实映射必须能核对相同 SHA。当前迁移器只接受可核验的本地副本，远程素材应先转存和核验。
- 合成、派生、用途绑定及人工选择进入操作输入/输出、候选与决定表。临时 URL 不成为最终资产位置。
- 任务保留模型版本、完整请求、状态、attempt、external_task_id 和幂等键；固定输入版本、媒体和输出用中间表关联，禁止把已提交任务恢复成未提交。

`document` 二进制列可使用 `{"legacy_file":"项目内相对路径"}`、`{"base64":"…"}` 或 `{"utf8":"原文本"}`。媒体二进制放受控存储，数据库文档导入大小有限制。`media_root` 指明本地对象键的受控根目录；面板和消费者需配置相同的存储根。

批准和选择行必须通过 `decision_evidence` 指向原事实：真实操作人、原结论和所选固定版本必须一致。文档批准不能充当素材选择，某一用途退役不能充当全局弃用，AI 建议不能变成人工批准。缺失批准证据时需要先补充真实人工决定，不能由迁移器生成。原备注必须原样保留；没有历史备注时，理由只能明确写为“迁移保留原人工决定；原记录无备注”。

如果旧任务的逻辑媒体编号需要转换，可在新 `request_payload` 中明确保留完整 `legacy_request`，再填写转换后的 `logical_request` 并计算新快照摘要。原请求 SHA、原编号和全部映射仍保留于不可变迁移审计文档；任务外部 ID、状态和幂等键保持原值。新逻辑编号必须落入任务的固定输入中。

未知字段、未知 SQLite 表和未登记文件都会成为缺口。需要明确分类的文档可作为独立不可变 `artifact_versions` 保存，并标注 `classification=document`，完整保留该事实的规范 JSON 内容；不能只指向项目行或迁移总快照就宣称已经迁移。工具自动保留两个只读审计文档：原状态快照及最终迁移清单，供追溯使用。

## 权威切换与恢复

导入完成后，PostgreSQL 目标处于 `migration_pending` 只读状态；调度消费者也不会取走它的任务。原项目仍冻结。只有完整对账通过才能切换。

切换事务失败时，本地可能已经指向 PostgreSQL，但目标仍保持只读。重新执行相同 `cutover` 可完成激活；此时不能删除指针或退回旧数据库写入。成功激活后重复执行同一切换不会重复导入或重置 revision。

切换后新增的决定和任务只存在于 PostgreSQL。需要回退时必须先导出、对账这些新增事实并制定恢复步骤，不能用旧 JSON 或旧 SQLite 覆盖新权威。

专项验证使用合成项目和随机 PostgreSQL 测试 schema。工具没有对工作区里的真实作品执行迁移。
