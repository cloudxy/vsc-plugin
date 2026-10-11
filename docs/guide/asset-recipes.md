# 原生制作规格包

`knowledge/asset-recipes.json` 是可跨作品复用的原创制作规格目录，格式为 `vsc.asset-recipes/v1`。目前覆盖 `workflow/library.json` 的全部 20 种分类，每类至少一条；不包含作品人物、情节、现成媒体、供应商账号或音色 ID。它让制作从可执行的参数与验收要求起步。

| 范围 | 已提供规格 |
| --- | --- |
| 人物、服装、动物 | 成年人物定妆、素色外套、小型短毛犬行为 |
| 道具、交通、场景、风格、特效 | 折叠纸条、城市自行车、单窗小房间、柔和中性色、窗外细雨 |
| 动作、打斗、表演、运镜、转场 | 桌面递物、错位闪避、聆听后松弛、动机慢推、前景遮挡 |
| 人声、环境声、拟音、音乐 | 沉稳清晰人声绑定、室内空气底、纸张轻折、留白式配乐 |
| 字体、字幕、图形 | 中文字体选择、双行底部字幕、留白标题卡 |

## 查找与安装

所有命令从工作区根目录运行，完全离线，不安装 vendor，不调用生成 API。

```sh
python3 -B scripts/vsc_recipes.py list
python3 -B scripts/vsc_recipes.py search 打斗 --kind fight
python3 -B scripts/vsc_recipes.py search 沉稳 --kind voice
python3 -B scripts/vsc_search.py 递物 --in recipes
python3 -B scripts/vsc_search.py 声音桥 --in all
python3 -B scripts/vsc_recipes.py show AR-motion-pass-object
python3 -B scripts/vsc_recipes.py validate
python3 -B scripts/vsc_recipes.py install AR-motion-pass-object
python3 -B scripts/vsc_recipes.py install --all
```

搜索名称、标签、说明及完整规格，支持中文词组；多个查询词共同匹配。`list/search` 可加 `--json`、`--kind`、`--limit`。统一检索的 `--in recipes` 直接读取原生规格，`--in all` 同时查方法卡、本机素材与作品，不要求先安装规格；结果会标注非媒体。另一个规格包使用 `vsc_recipes.py` 的全局参数 `--catalog <JSON>`；`validate <JSON>` 可直接校验输入文件。

安装默认写入本机 `library/`，也可用 `install ... --library <目录>` 或 `VSC_LIBRARY` 指定目标。安装调用现有 `vsc_library.add` 与素材库锁，复用条目校验和创建逻辑。全量安装先检查现有 ID 冲突，再创建新条目；相同版本、内容及完整条目属性重复安装返回 `UNCHANGED`，不重复创建或改写。相同 ID 的版本变化、内容变化、手工编辑或已有占位目录都报错并保留已有内容；升级请使用新 ID。目标目录不得通过符号链接越出素材库。

安装的每条素材明确包含：

```json
{
  "asset_type": "specification",
  "is_media": false,
  "requires_human_selection": true,
  "rights_scope": "specification_only",
  "recipe": {"id": "AR-motion-pass-object", "version": "1.0.0", "sha256": "<规格内容哈希>"},
  "spec": {"fixed": ["..."], "variable": ["..."], "inputs": ["..."], "procedure": ["..."], "acceptance": ["..."], "deliverables": ["..."]}
}
```

条目没有媒体文件或 provider refs。素材库里的 `owned`、商用许可只覆盖原创规格文字；未来录制、生成、下载的人脸、音色、字体、音乐或媒体应分别记录来源与许可，不能沿用文字规格的权利结论。`requires_human_selection` 不是批准记录，安装也不批准任何项目产物。

`vsc_library.py use` 不带 `--bible` 时可将规格清单复制进项目供设计参考；加 `--bible` 会拒绝把规格直接登记为实体参考、真实音色或全片字幕样式。字体选择规格不附字体文件，标题卡规格也不附已生成贴片；必须另选合法字体、制作图形并验证交付许可。

## 制作时如何使用

先检索并人工选规格，再将其中固定项、变量与验收点纳入项目资产设计。填入作品实体 ID、尺寸、画幅、时间码及实际授权来源；完成参考或媒体制作后，按原 VSC 流程登记候选、选择、依赖与批准。`deliverables` 表示待制作输出，不能据此报告已生成媒体或有可用供应商。

动作与打斗规格含安全拍点、起止状态、镜头、时长与逐拍顺序。真实拍摄由现场动作指导确认错位与间距；打斗示例只采用无接触空挥和自主后撤，后期添加打击声。人声规格使用 `<PROJECT_SPEAKER_ID>`，`provider` 与 `voice_id` 为 `null`；选定合法声源后固定角色映射，不能将描述伪装成供应商音色 ID。声音规格明确循环、对白避让、进出点、格式和权利确认要求。

`craft_refs` 仅引用 `knowledge/craft.json` 的方法卡 ID，提供创作方法线索，不复制方法卡全文，也不获得任何素材的权利或项目批准。当前方法库有 34 条卡、14 个来源，可用 `vsc_craft.py show <ID>` 查看概括与来源依据。

实际声音制作后，按用途把已选文件收入 `voice/ambience/sfx/music`，保留 provider、model、prompt、原记录与文件 SHA；人声固定实际声源及 speaker 映射，环境底复核循环接缝，拟音复核接触点，音乐复核对白避让与进出点。规格里的分轨、loop 或时长目标必须经真实输出验证，不能沿用为已完成结论。操作与来源继承范围见[声音来源与跨项目复用](reuse-and-search.md#声音来源与跨项目复用)。

## 维护与验证

目录和每条规格均使用三段数字版本。每条必须含安全且唯一的 ID、taxonomy 分类、名称、说明、标签、原创规格权利声明，以及 `fixed/variable/inputs/procedure/acceptance/deliverables` 六个非空数组。校验要求完整覆盖全部分类，并检查动作、声音等专类字段；这只是结构与制作合同检查，实际效果和权利仍需依据媒体证据审阅。

```sh
python3 -B scripts/vsc_recipes.py validate
python3 -B tests/test_vsc_recipes.py
```

离线测试覆盖 taxonomy、schema、搜索、素材库 API 安装、重复安装、版本与内容冲突、全量预检、中文与空格路径、非法路径和符号链接越界。测试只写临时素材库。
