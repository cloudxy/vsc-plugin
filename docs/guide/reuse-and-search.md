# 素材复用、创作方法与章节衔接

制作前先查已有内容。数据库工作台的“素材库”提供工作区共享库，传统素材仍可保存在本机 `library/`。原创制作规格存在 [`knowledge/asset-recipes.json`](../../knowledge/asset-recipes.json)，公开创作方法存在 [`knowledge/craft.json`](../../knowledge/craft.json)。作品身份与状态由各项目权威管理。传统统一检索直接读取四类来源：`library`、`recipes`、`craft`、`projects`；数据库共享库使用下述固定版本入口，不把旧 JSON 当作运行镜像。

## 素材库

数据库共享库可在未选择项目时浏览或导入，选中固定版本后再选择目标项目、对象和用途。加入候选、明确采用和正式生成分别沿原流程；新版本不替换旧项目已固定的媒体。共享使用不复制原字节，也不调用生成供应商。许可不足、缺规格或模态不符时显示具体缺项；纯规格没有图片、声音或视频预览。

维护与自动化继续使用原资源 CLI：

```bash
.venv/bin/python -B scripts/assets/resources.py library search "雨夜" --limit 24
.venv/bin/python -B scripts/assets/resources.py library show VERSION_UUID
.venv/bin/python -B scripts/assets/resources.py library import --payload import.json --by 实际负责人 --confirmed
.venv/bin/python -B scripts/assets/resources.py library preview-use PROJECT_UUID --payload use.json
.venv/bin/python -B scripts/assets/resources.py apply PROJECT_UUID use_library --payload use.json --expected-revision 1 --key 本次用途意图 --by 实际负责人
```

导入清单包含脱敏描述、明确共享许可、用途范围与原 `stage` 返回的受控暂存成员；项目发布使用原 `apply … publish_library`。停用与撤权用 `library retire ENTRY_UUID --payload decision.json --by 实际负责人 --confirmed`，其中决定包含 reason、outcome 和 idempotency_key。现有引用和审计字节保留。

旧库迁移是独立的显式维护操作：`scripts/assets/library.py migrate preview` 只读核清单；有完整许可后再固定摘要导入、比较和切换。未知用途保留原库待核，不自动变成共享媒体。下面的 `add/promote/use` 是传统库路径，完成切换后原写入口会拒绝继续写入。

分类及权属状态唯一声明在 [`workflow/library.json`](../../workflow/library.json)，涵盖人物、服装、动物、道具、交通工具、场景、风格、特效、动作、打斗、表演、运镜、转场、人声、环境声、拟音、音乐、字体、字幕样式和图形。

```bash
python3 -B scripts/assets/library.py kinds
python3 -B scripts/assets/library.py search "雨夜" --kind location
python3 -B scripts/assets/library.py search "纸张" --kind sfx

# 从成功的本项目生成记录收入原始输出；多个输出必须指定 --output。
python3 -B scripts/assets/library.py promote --project projects/雨夜来信 \
  --record projects/雨夜来信/06-素材/人物-生成记录.json --output 人物 \
  --kind character --id character-01 --name "人物形象" --summary "本地填写形象概要" \
  --attr 'identity=["本地填写不可变特征"]' --role portrait

# 精确复制进项目，同时绑定该项目实体；工作文件变化需要重新登记和批准。
python3 -B scripts/assets/library.py use character-01 --project projects/雨夜来信 \
  --bible projects/雨夜来信/04-视听设计/资产库.json --entity CH-001
python3 -B scripts/assets/library.py check
```

每条素材用稳定 ID、SHA-256、权属、标签、生成来源和复用记录定位。`promote` 不自动认定商用许可。`use` 校验后复制原始字节，同目录保存 `来源.json`；方舟原始链接及期限随文件保留，供适配器复用。平台的人脸信任规则见[生成适配器](../architecture/generation-adapters.md#豆包适配器)。复制过的作品文件若已修改，复用命令拒绝覆盖，需使用新 ID。并发写入使用素材库锁和项目锁，JSON 原子替换；发生跨文件写入异常后，应先运行 `check` 核对再重试。

已选媒体中的人物、地点等素材可登记为资产库实体；已选人声条目绑定既有人物音色，已定字幕样式可绑定全片样式。动作、音乐等其他素材可复制使用，不冒充人物实体。`asset_type=specification` 或 `is_media=false` 的制作规格不能用 `use --bible` 直接绑定；不带 `--bible` 时可将规格清单带入项目供设计参考，不会产生媒体文件。使用方法不继承另一个项目的创作批准；生成的语音也不自动成为稳定角色声线。

## 20 类原创制作规格

原生包有 23 条规格，覆盖上文全部 20 类，逐条给出固定项、可变项、输入、制作步骤、验收要求与待制作输出。动作和打斗明确安全拍点、起止姿态、镜头与时长；人声使用固定 speaker 占位，供应商与音色 ID 留空；环境声、拟音、配乐说明循环、对白避让、进出点与权利确认。完整清单、安装及版本规则见[原生制作规格包](asset-recipes.md)。

```bash
python3 -B scripts/knowledge/recipes.py list
python3 -B scripts/knowledge/recipes.py show AR-motion-pass-object
python3 -B scripts/knowledge/search.py "递物" --in recipes
python3 -B scripts/knowledge/recipes.py validate
# 可选：收入本机素材库；不会生成媒体或批准项目。
python3 -B scripts/knowledge/recipes.py install --all
```

规格安装保留 `asset_type=specification`、`is_media=false`、`requires_human_selection=true` 和 `rights_scope=specification_only`。`owned` 只覆盖原创规格文字，不是人物肖像、音色、音乐或字体文件的许可。检索找到规格后，先由人选择并填写本项目参数，再进入资产设计、生成候选与审阅；不能把规格中的 `deliverables` 当作已经存在的素材。

## 声音来源与跨项目复用

声音按实际用途收入 `voice`、`ambience`、`sfx` 或 `music`。`promote` 从成功或部分成功的本项目生成记录选择一个真实输出，核对项目编号、文件与 SHA，保存原项目、记录路径、provider、model、prompt 和生成时间；有原始 URL、有效期时随文件保留。部分成功记录只证明所选输出存在，不表示整次任务全部成功。自录或外部许可素材用 `add` 写清 `--rights`、`--license`、`--source` 与可核验的文件，商用范围须按实际凭证填写。

```bash
# 例中项目、文件、输出与人物 ID 均须换成实际值。
python3 -B scripts/assets/library.py promote --project projects/雨夜来信 \
  --record projects/雨夜来信/06-素材/声音/对白-生成记录.json --output 对白 \
  --kind voice --id voice-01 --name "已选角色声源" --summary "本地填写声音与表演范围" --role sample
python3 -B scripts/assets/library.py use voice-01 --project projects/雨夜来信 \
  --bible projects/雨夜来信/04-视听设计/资产库.json --entity CH-001
```

人声音频 promote 会从记录提取实际 `engine`、`voice`、`resource_id`、`model`；显式传入的属性若与来源冲突会拒绝。`use --bible --entity` 将这些绑定写入目标人物；项目应保持固定 speaker 映射，不能因换台词或情绪更换身份音色。来源中缺失的 ID 不得自行编造，音色描述也不能充当 provider ID。生成服务条款、声音使用范围及商用状态仍需核实；`promote` 默认不确认商用、不会把样本变成声音克隆许可。

环境底复用时保持空间、声像和循环接缝；拟音对齐接触拍点；配乐重核调性、节拍、对白避让及进出点。规格要求分轨不代表候选已分轨，生成的完整音频也不能自动称为 loop。程序合成、语音与 SeedAudio 的来源以各自记录为准，不能统称为同一豆包服务。可用 `python3 -B scripts/media/toolchain.py --project projects/雨夜来信 --json` 只读区分脚本实现、配置存在性和本项目有效候选；配置或 SHA 通过不等于权限验证、试听通过或人工批准。

## 公开创作方法与快速查找

```bash
python3 -B scripts/knowledge/craft.py search "眼神" --stage direct
python3 -B scripts/knowledge/craft.py show eyeline-match
python3 -B scripts/knowledge/craft.py show eyeline-match --with-teaching
# 专业角色接任务后，用上次返回的 teaching_sha256 固定读取：
python3 -B scripts/knowledge/craft.py show eyeline-match --expected-sha <固定摘要>
python3 -B scripts/knowledge/craft.py validate
python3 -B scripts/knowledge/search.py "声音桥" --in all
python3 -B scripts/knowledge/search.py "对白" --in craft
python3 -B scripts/knowledge/search.py "打斗" --in recipes --json
python3 -B scripts/knowledge/search.py "SH-001" --in projects --project projects/雨夜来信
python3 -B scripts/knowledge/search.py "递物" --in library --json
```

方法库现有 **36 条方法卡、16 个来源**，涉及镜头、场面调度、表演、剪接、声音、对白与短片写作。方法条目的 `source_basis` 是简要概念依据；`principle`、`steps` 和 `pitfalls` 是 VSC 的应用建议。来源标题、机构、链接和核查日期只保存在方法库的 `sources`，条目通过 ID 引用。资料包括耶鲁电影分析教材、哥伦比亚电影语言词汇表、BFI、BBC 及情绪感知研究；库中只保存自行概括与应用，不收录影片素材或文章全文。公开方法是可查阅的建议；项目内受控能力卡的试用、评测和批准仍按 [记忆与学习](../design/memory-and-learning.md) 执行，不自动装入已批准角色上下文。

其中15卡可按需读取六组原创教学，涵盖行动与信息、潜台词与表演、注意力与光线、调度与覆盖、声画节奏、选声与空间。`--with-teaching`返回完整自足章节、适用/不适用例和`teaching_sha256`；无教学卡明确返回null。摘要覆盖卡、所引来源与该章节，改变其中任何内容后旧摘要拒绝，不静默换最新版。每次只选择当前问题需要的方法；超过1600字符软目标仍完整返回，不截断反例。

编排者把方法ID、路径/锚点、发布版本及摘要放入原最小context；专业角色consume后实际固定读取，在原产物定位使用位置和取舍，再按原return回收。具体方法及有限比较见[任务中使用方法](../../skills/vsc/references/method-practice.md)，机器JSON、草拟框架和教材例子的分工见[模板使用](../../templates/README.md)。这些步骤由AI处理，普通用户直接读作品和差异。

统一检索按名称、ID、标签、摘要和正文加权，支持中文相邻双字匹配，多个查询词须同时命中；不是向量检索。结果标注来源域、路径与短摘录；`recipes` 摘要标明“制作规格（非媒体）”，尚未安装也可检索。`--catalog` 指定 craft 方法库文件；自定义规格包用 `scripts/knowledge/recipes.py --catalog` 检索。项目检索覆盖创作对象、登记产物的范围／依赖／状态及工作文本；默认排除原始来源、批准快照、上下文和构建缓存。它不验证产物批准是否仍有效，继续任务须运行 `scripts/project/state.py status`、`next` 并读取有效基线。

## 集、场衔接

同场镜头用状态时间线与连续性计划；跨集或跨场用 [`vsc.sequence-links/v1` 模板](../../templates/sequence-links.json)。有序 `units` 绑定真实状态文件的路径、SHA 和首尾镜头；`links` 为每对相邻单元记录叙事承接、声音桥、必须连续的字段与变化理由。

```bash
python3 -B scripts/kernel/catalog.py contract validate vsc.sequence-links/v1 ./衔接计划.json
python3 -B scripts/story/sequence.py check ./衔接计划.json --project projects/雨夜来信
```

`scene` 单元须覆盖一整场；`episode` 单元须覆盖绑定文件全体镜头，因此由作者把文件范围划定为一集。检查器从状态文件推导出入点，不另存副本；点路径如 `entities.CH-001.holding`、`environment.time`、`location_id`。两端都缺字段不能当作匹配；每个变化字段须有理由，新增或移除对象可以整体说明。时间省略或换场允许有意变化，不要求跨集画面相同。文本非空只能证明填写过，叙事因果和听觉效果仍需人审。

登记为 `vsc.sequence_links` 产物时，单元及首尾镜头须是已登记创作对象；每个状态文件须指向明确的 `vsc.scene_state` 版本并列为 `--depends`。批准和下游消费复验对象范围、依赖版本、状态 SHA 与边界。原有 Profile 不自动增加 Gate；新项目可在 Profile 中显式要求该产物，既有项目固定的 Profile 不静默改变。
