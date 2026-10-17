# 创作工作台与固定关系登记

工作台是只读查询入口，复用项目的 PostgreSQL 或旧 JSON/SQLite 权威。浏览、检索、分页和画布布局不修改 revision，也不产生素材选择或批准。旧项目缺少索引时返回明确缺口，不自动迁移或猜测文件名。

## 查询

后台默认进入创作工作台。项目概览先显示结构分组和资料数量，进入场或镜头后集中显示剧本、资产、使用状态、声音、动作与特效、用途候选及固定版本。镜头覆盖、声音覆盖、参与者和制作参考可按关联继续查阅；候选可以加入已有并排比较入口。

检索可以限定当前范围，也可以选择全项目；状态、类型、用途和关联情况分别筛选。“当前文案”与“已批准”含义不同，历史批准保留。场镜状态和人物声线有独立入口。未登记关系和旧项目未索引资料会显示缺口，不能据此判断没有依赖。

无限画布提供创作关联、制作来源、采用用料和版本影响视图。全部项目先展示分组，点选范围再展开；“全范围检索”可定位尚未加载的素材。影响报告列出直接和间接消费者，标记原版本后可以比较替换影响，查阅操作不改变正式选择。预览使用已登记的缩略图、海报和波形，原始媒体按明确打开动作加载。

HTTP：`GET /api/v1/projects/{project_id}/workbench`（沿面板既有鉴权与项目路由）。参数：`object_id`、`section`、`query`、`kind`、`status`、`purpose`、`version`、`association`、`entity_id`、`limit`（1–100）、`offset`、`revision`。全项目无筛选概览只取聚合与子级，集合用 `load_on_demand` 标记；场镜 `overview` 每类最多六项，单独集合可继续分页。

CLI 使用同一应用接口：

```sh
python3 -B scripts/vsc_workbench.py PROJECT_ID --object-id SHOT_ID --section overview
python3 -B scripts/vsc_workbench.py PROJECT_ID --section materials --query 杯子 --limit 24
python3 -B scripts/vsc_workbench.py PROJECT_ID --section cue_shots --entity-id CUE_ID
```

`VSC_DATABASE_URL` 未加载时仍可读旧项目；声明 PG 权威的项目拒绝回退。命令不显示连接信息。返回 `scope`、`ancestors`、`summary`、`sections`、`gaps`、`warnings`。每个集合区分 `scope_total`、`filtered_total`、`loaded_count`，并给出 `next_offset`、`truncated`。PG 查询使用一次只读 repeatable-read 快照；传入过期 revision 返回冲突，调用方应重新刷新。

集合包括 `children/shots/lines/assets/instances/cues/performances/bindings/candidates/materials/versions`，以及有界关系明细 `coverage/states/voices/interactions/dispositions/cue_shots/cue_slots/cue_timeline_items/timeline_media/execution_shots/execution_participants/execution_materials/execution_slots`。`jobs/quality_observations/method_evaluations`提供任务、待审输出计数与固定质量证据。`entity_id`可定位行、资产、槽位、执行或 Cue，`version`可指定固定产物 ID；`current`/`version_status`区分当前、历史批准与草稿。实例的 `use_count`指已登记使用，不推断遗漏资料。

画布节点 ID 使用 `line:UUID/state:UUID/voice:UUID/instance:UUID/cue:UUID/performance:UUID`。`mode=creative/production/usage/impact`切换关系视图。impact 只沿固定任务输入、加工、实际采用与成片用料传播，返回直接/间接距离与理由；`affected_pending_review`表示需要复核，不等于必须重生。截断、未登记依赖、未比较替换内容的部分均无法判定，不自动标成“不受影响”。

## 登记和权威

新增关系文档固定格式 `vsc.creative-relations/v1`，通过现有 `create_artifact` 登记，`artifact_type`固定为 `creative-relations`。服务在同一项目 revision 事务内保存正文 SHA 和 typed 投影，投影不可直接更新/删除。外部剧本行、规格、状态、方法和时间线引用必须在 `dependency_ids` 中固定其所属产物版本；项目内复合外键阻止串项目。方法批准仍不等于能力已获验证。

```json
{
  "artifact_key": "scene-uses",
  "artifact_type": "creative-relations",
  "object_ids": ["SCENE_UUID"],
  "dependency_ids": [],
  "document": {
    "format": "vsc.creative-relations/v1",
    "project_id": "PROJECT_UUID",
    "instances": [
      {"key": "cup-left", "asset_id": "CUP_ASSET_UUID", "scene_id": "SCENE_UUID", "shot_id": "SHOT_UUID", "label": "左侧杯子", "state": {"position": "桌左", "orientation": "杯口朝上", "damage": "完好", "consumption": "未消耗"}},
      {"key": "cup-right", "asset_id": "CUP_ASSET_UUID", "scene_id": "SCENE_UUID", "shot_id": "SHOT_UUID", "label": "右侧杯子", "state": {"position": "桌右"}}
    ],
    "interactions": [{"subject": "cup-left", "object": "cup-right", "relation": "touches"}],
    "cues": [{"key": "pause", "kind": "silence", "label": "有意停顿", "scope_object_id": "SCENE_UUID", "shots": [{"shot_id": "SHOT_UUID", "start_ms": 1000, "end_ms": 1800}], "parameters": {"purpose": "留出反应"}}]
  }
}
```

以上 UUID 是字段占位，须替换为该项目真实登记 ID；不是可直接导入的作品资料。实例 key 在该不可变文档内唯一；同一资产可有多个实例。状态 JSON 保存摆放、朝向、损坏等参数，参与对象引用放正式字段。`interactions` 的双方引用本文实例 key 或已登记实例 UUID，`holds` 另记 `hand`；`restores/consumes`记录恢复/消耗关系。`dispositions`引用固定 `line_id`、`disposition=omit|defer`和理由；只有其版本经既有批准路径批准后，才显示为当前明确决定。

保存为 payload.json 后沿既有写入口登记：

```sh
python3 -B scripts/vsc_resources.py apply PROJECT_ID create_artifact \
  --payload payload.json --expected-revision REVISION --key UNIQUE_COMMAND_KEY --by ACTOR
```

登记得到固定 artifact ID 和 SHA 后，按现有审阅决定调用 `decide_artifact`。不得替用户批准或把自评写成人审。版本修改登记新文档，不覆盖历史投影；用途素材仍由 propose/review/select 路径采用。

## 表粒度和专业执行

| 表 | 一行含义与候选键 |
| --- | --- |
| asset_use_instances | 固定文档内一次可区分的场镜使用；project + artifact + instance_key |
| instance_interactions | 两个使用实例的一次有类型交互；project + id |
| script_line_dispositions | 固定关系版本对一条固定剧本行的省略/延期提案；project + artifact + line |
| execution_instances | 一次专业或普通动作执行规格；project + artifact + execution_key |
| execution_shots | 执行到镜头的覆盖；project + execution + shot |
| execution_participants | 执行参与实例及角色；project + execution + instance + role |
| execution_materials / execution_slots | 执行的参考素材/用途槽位及角色；project + execution + media/slot + role |
| sound_cues | 一次声音意图，包含有意静默；project + artifact + cue_key |
| cue_shots | 一个 Cue 覆盖一镜及可选镜内毫秒范围；project + cue + shot |
| cue_slots / cue_timeline_items | Cue 对用途/实际时间线条目的 M:N 关系；project + cue + slot/item |
| quality_observations | 固定文档记录的一次任务/输出观察；project + id |
| method_evaluations | 固定方法、试片、基线/输出、判据和环境的评测；project + id |

一个跨三镜的环境声 Cue 只登记一次，`shots`列三镜，`timeline_item_ids`可指向一个跨镜用料。源区间、目标帧、混音包络继续由既有时间线保存；Cue 的镜内毫秒不能替代源区间或成片帧坐标。Cue 可用 `subtitle_version_id/lipsync_version_id` 固定字幕/口型同步规格，须列入文档版本依赖；这是同步依据，不冒充已完成同步检验。原生音画一体及声音抽取继续通过原媒体/加工输入输出追溯，不伪造独立录音。

`performances`每行含 `key/label/domain/method_artifact_id/shot_ids/participants/materials/slots/parameters`，可带固定 `line_id/voice_spec_id`。domain 支持 `combat/dance/vfx/voice/acting/action`。四专业领域经 `vsc.production.performance.execution_problems` 检查可观察参数，方法须已批准且固定为依赖；打斗参与双方、舞蹈音乐、特效施放/目标及所需层、声音台词/声线都必须是 typed 引用。参数不接受 `*_id/*_ids/*_ref/*_refs`对象引用。制作上下文消费当前批准执行规格；实际供应商能力仍由生产检查核对，登记本身不承诺生成成功。

关系未登记、旧格式未索引、权限不可用和数据截断分别显示，不能仅凭某页为空判定“没有依赖”。合成性能测试只证明工程规模；真实制作质量、真实项目负载和浏览器交互必须另行验收。
