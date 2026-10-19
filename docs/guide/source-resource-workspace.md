# 来源、分镜与资源工作区

适用于 PostgreSQL 项目。先运行显式迁移，再启动资源面板；旧 JSON 项目保持原有入口，按需显式迁移。

## 从材料到剧本

1. 在“创作来源”选择材料用途，粘贴文案或上传文件。文件复用受控存储，固定文件摘要；数据库保存来源清单和媒体关联。
2. 点击“提取原文与结构”，查看本次任务、固定输入、提取结果和失败原因。重试保留历史；改变参数、用途或来源时新建任务。
3. 对照原文校对场次、动作与对白。选择现有目录及人物，或确认界面展示的默认目录和新人物；同名人物是否复用由操作者明确选择。逐场输入预计时长。
4. 确认导入剧本工作副本。在剧本工作区补齐已批准改编来源与逐行叙事引用，校对后按原有流程提交和人工批准。解析、导入、保存均不产生创作批准。

文本、Markdown、DOCX、XLSX 使用本地提取器；文本 PDF 需要本机 `pdftotext`。XLSX 必须指定工作表和列映射。扫描 PDF、图片 OCR、音视频 ASR 未配置时明确报告能力缺口，不生成假结果。小说和大纲提取后进入既有改编链，不能直接导入成型剧本。

来源中的文字按材料处理。每个导入单元关联不可变的来源锚点，定位到行、段落、表格单元格或 PDF 页。新导入稿的连续正文由结构化场次派生；编辑和采纳建议同步更新正文和出处。旧剧本原始字节保持不变。

## 分镜与资源关系

对象目录保持部、集、场、序列、镜头的既有身份。分镜设计是固定产物中的逻辑单元，可有多张有序面板，并明确关联镜头、用途及主用／备选／参考角色；生成任务仍使用现有尝试、候选和选择流程。

“资产库”提供人物、背景环境、道具、生物、植物、声音、字幕文字、视觉特效、镜头风格、后期包装、制作文档十一类检索。分类、媒体类别、稳定身份和生产用途分别管理；可登记或可预览不代表已配置生成器。

固定产物可声明 `design_units`、`scene_locations`、`resource_requirements`；关系由登记事务从该版本正文生成。场级地点与逐镜地点分别表达，逐镜主地点覆盖同一版本的场级主地点。需求关联固定剧本行、身份、规格、实例和用途槽位，沿既有权利、检查及采用决定核验，不复制一套批准状态。

批准设计中的面板引用、地点和需求资产进入适用镜头上下文，沿现有版本／媒体输入表固定。历史任务不跟随最新资产或分类改变。字体、字幕、LUT、模型或其他只登记的资源不能因分类而自动进入供应商请求。

## 固定产物中的关系字段

下列字段添加到已有设计／连续性文档；占位符替换为同项目已登记身份，`line_ids`、`spec_version_id` 的所属版本必须列入该产物的固定依赖。关系由正文派生，不另行编辑数据库投影。

```json
{
  "design_units": [{
    "design_key": "门外等候", "scene_id": "SCENE_ID",
    "duration_ms": 6000, "action": "停步等候", "camera": {"movement": "推近"},
    "shots": [{"shot_id": "SHOT_ID", "purpose": "video_clip", "role": "primary"}],
    "panels": [{"panel_key": "起点", "media_id": "IMAGE_MEDIA_ID"}],
    "line_ids": ["FIXED_SCRIPT_LINE_ID"]
  }],
  "scene_locations": [{
    "scene_id": "SCENE_ID", "location_id": "LOCATION_ID",
    "spec_version_id": "FIXED_LOCATION_SPEC_ID", "role": "primary"
  }],
  "resource_requirements": [{
    "requirement_key": "主角参考", "category_code": "character.face_body",
    "purpose": "video_clip", "description": "本镜主角正脸参考",
    "scene_id": "SCENE_ID", "shot_id": "SHOT_ID", "asset_id": "CHARACTER_ID",
    "spec_version_id": "FIXED_CHARACTER_SPEC_ID", "line_ids": ["FIXED_SCRIPT_LINE_ID"],
    "slots": [{"slot_id": "EXISTING_BINDING_SLOT_ID", "role": "fulfills"}]
  }]
}
```

多张面板共用一个 `design_key`，按数组顺序排列；不要把同一镜头重复声明为多个主用设计。场主地点不填写 `shot_id`，逐镜覆盖时明确填写。需求未满足、规格未固定或权利失效时报告缺口，不能用“已分类”代替实际用料。

## 命令行

以下命令与面板使用同一服务；`PROJECT_ID` 替换为实际项目身份：

```sh
.venv/bin/python -B scripts/project/schema.py migrate --database-env VSC_DATABASE_URL
.venv/bin/python -B scripts/assets/resources.py source-workspace PROJECT_ID
.venv/bin/python -B scripts/assets/resources.py source-workspace PROJECT_ID --job-id JOB_ID --preview
.venv/bin/python -B scripts/assets/resources.py resource-model PROJECT_ID --section categories
.venv/bin/python -B scripts/assets/resources.py resource-model PROJECT_ID --section resources --category sound --limit 50
.venv/bin/python -B scripts/assets/resources.py resource-model PROJECT_ID --section designs --object-id SHOT_ID
```

写入沿用 `resources.py apply` 的固定 payload、期望 revision、幂等键和可信身份；支持 `create_source_intake`、`create_parse_job`、`run_parse_job`、`prepare_parse_import`、`import_parse_job`、`classify_resource`。文件先由 `stage` 生成上传凭据。正式库通过 MCP 仅只读查询；应用连接保留读写及显式迁移权限。
