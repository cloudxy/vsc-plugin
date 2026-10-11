# 素材复用、创作方法与章节衔接

制作前先查已有内容。跨作品素材存在本机 `library/`，作品身份与状态仍由项目资产库、状态时间线和 `vsc.json` 管理；公开创作方法存在 [`knowledge/craft.json`](../../knowledge/craft.json)。检索直接读取这些来源，不维护第二份内容索引。

## 素材库

分类及权属状态唯一声明在 [`workflow/library.json`](../../workflow/library.json)，涵盖人物、服装、动物、道具、交通工具、场景、风格、特效、动作、打斗、表演、运镜、转场、人声、环境声、拟音、音乐、字体、字幕样式和图形。

```bash
python3 -B scripts/vsc_library.py kinds
python3 -B scripts/vsc_library.py search "雨夜" --kind location
python3 -B scripts/vsc_library.py show motion-handover-01

# 收入自己编写的动作规格；文件可省略，使用 attributes 保存规格。
python3 -B scripts/vsc_library.py add --kind motion --id handover-01 \
  --name "递物五拍" --summary "准备、伸手、接触、转移、收手" \
  --rights owned --attr 'beats=["准备","伸手","接触","转移","收手"]'

# 从成功的本项目生成记录收入原始输出；多个输出必须指定 --output。
python3 -B scripts/vsc_library.py promote --project projects/雨夜来信 \
  --record projects/雨夜来信/06-素材/人物-生成记录.json --output 人物 \
  --kind character --id character-01 --name "人物形象" --summary "本地填写形象概要" \
  --attr 'identity=["本地填写不可变特征"]' --role portrait

# 精确复制进项目，同时绑定该项目实体；工作文件变化需要重新登记和批准。
python3 -B scripts/vsc_library.py use character-01 --project projects/雨夜来信 \
  --bible projects/雨夜来信/04-视听设计/资产库.json --entity CH-001
python3 -B scripts/vsc_library.py check
```

每条素材用稳定 ID、SHA-256、权属、标签、生成来源和复用记录定位。`promote` 不自动认定商用许可。`use` 校验后复制原始字节，同目录保存 `来源.json`；方舟原始链接及期限随文件保留，供适配器复用。平台的人脸信任规则见[生成适配器](../architecture/generation-adapters.md#豆包适配器)。复制过的作品文件若已修改，复用命令拒绝覆盖，需使用新 ID。并发写入使用素材库锁和项目锁，JSON 原子替换；发生跨文件写入异常后，应先运行 `check` 核对再重试。

人物、地点等素材可登记为资产库实体；人声条目绑定既有人物音色，字幕样式条目绑定全片字幕样式。动作、音乐等其他素材可复制使用，不冒充人物实体。使用方法不继承另一个项目的创作批准；生成的语音也不自动成为稳定角色声线。

## 公开创作方法与快速查找

```bash
python3 -B scripts/vsc_craft.py search "眼神" --stage direct
python3 -B scripts/vsc_craft.py show eyeline-match
python3 -B scripts/vsc_craft.py validate
python3 -B scripts/vsc_search.py "声音桥" --in all
python3 -B scripts/vsc_search.py "SH-001" --in projects --project projects/雨夜来信
python3 -B scripts/vsc_search.py "递物" --in library --json
```

方法条目的 `source_basis` 是简要概念依据；`principle`、`steps` 和 `pitfalls` 是 VSC 的应用建议。来源标题、机构、链接和核查日期只保存在方法库的 `sources`，条目通过 ID 引用。初始资料来自耶鲁电影分析教材、哥伦比亚电影语言词汇表及 BFI 文章；库中只保存自行概括与应用，不收录影片素材或文章全文。公开方法是可查阅的建议；项目内受控能力卡的试用、评测和批准仍按 [记忆与学习](../design/memory-and-learning.md) 执行，不自动装入已批准角色上下文。

统一检索按名称、ID、标签、摘要和正文加权，支持中文相邻双字匹配，多个查询词须同时命中；不是向量检索。返回来源路径与短摘录。项目检索覆盖创作对象、登记产物的范围／依赖／状态及工作文本；默认排除原始来源、批准快照、上下文和构建缓存。它不验证产物批准是否仍有效，继续任务须运行 `vsc_state.py status`、`next` 并读取有效基线。

## 集、场衔接

同场镜头用状态时间线与连续性计划；跨集或跨场用 [`vsc.sequence-links/v1` 模板](../../templates/sequence-links.json)。有序 `units` 绑定真实状态文件的路径、SHA 和首尾镜头；`links` 为每对相邻单元记录叙事承接、声音桥、必须连续的字段与变化理由。

```bash
python3 -B scripts/vsc_kernel.py contract validate vsc.sequence-links/v1 ./衔接计划.json
python3 -B scripts/vsc_sequence.py check ./衔接计划.json --project projects/雨夜来信
```

`scene` 单元须覆盖一整场；`episode` 单元须覆盖绑定文件全体镜头，因此由作者把文件范围划定为一集。检查器从状态文件推导出入点，不另存副本；点路径如 `entities.CH-001.holding`、`environment.time`、`location_id`。两端都缺字段不能当作匹配；每个变化字段须有理由，新增或移除对象可以整体说明。时间省略或换场允许有意变化，不要求跨集画面相同。文本非空只能证明填写过，叙事因果和听觉效果仍需人审。

登记为 `vsc.sequence_links` 产物时，单元及首尾镜头须是已登记创作对象；每个状态文件须指向明确的 `vsc.scene_state` 版本并列为 `--depends`。批准和下游消费复验对象范围、依赖版本、状态 SHA 与边界。原有 Profile 不自动增加 Gate；新项目可在 Profile 中显式要求该产物，既有项目固定的 Profile 不静默改变。
