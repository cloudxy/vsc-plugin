# Remotion：VSC 的可编程时间线与确定性渲染层

Remotion 不负责把小说改成剧本，也不生成稳定的人物、动作或场景。它在 VSC 中负责最后一段明确且可复现的生产链：把已批准的镜头、声音和字幕放入帧级时间线，供人工预演、修改和导出。

```text
VSC 改编/剧本/ShotPlan/连续性/声音
                ↓
       选中 video/image/audio take
                ↓
    vsc.remotion-render-plan/v1（可校验）
                ↓
     本地 Remotion Composition + Studio 预演
                ↓
       人工批准 → 确定性 MP4/静帧导出
```

## 本机安装与官方 Skill

`vendor/sources.lock.json` 将 `remotion-dev/remotion` 固定为本地可选组件，并稀疏检出 `.agents/skills` 与 `packages/skills/skills`。后者包含官方的 `remotion-best-practices`、`remotion-create`、`remotion-markup`、`remotion-captions`、`remotion-studio` 与 `remotion-render` Skill。

运行：

```bash
python3 scripts/maintenance/vendor_sync.py --install remotion
python3 scripts/maintenance/vendor_skills.py --resolve post
```

下载内容不进入 VSC Git 仓库；用户决定是否在本机为生成的 Composition 安装 Node/npm 依赖。VSC 不替任何人判断 Remotion 的许可或商业使用资格。

## 计划与项目脚手架

`vsc.remotion-render-plan/v1` 是 VSC 与 Remotion 的边界。它定义 Composition 的画幅、帧率、时长，以及视频、图片、音频、字幕和文字片段的开始帧、时长与来源。视觉片段必须回指 `source_shot_id`，以避免剪辑阶段脱离 VSC 连续性计划。

```bash
python3 scripts/kernel/catalog.py contract validate vsc.remotion-render-plan/v1 templates/remotion-render-plan.json
python3 scripts/post/remotion_plan.py scaffold templates/remotion-render-plan.json /tmp/vsc-remotion-example
```

脚手架生成 `src/`、`public/`、`package.json` 与计划副本，不会执行 `npm install`。将选定素材放入 `public/` 后，用户可在生成目录运行 `npm install`、`npm run studio` 预演；只有明确要求导出时才运行 `npm run render -- <composition-id> <output.mp4>`。

## 帧级字段

`vsc.remotion-render-plan/v1` 的可选帧级字段（旧字段保持兼容）：

| 字段 | 语义 |
| --- | --- |
| `composition.fps` | 正数，或 `{ "numerator": 30000, "denominator": 1001 }`；时间码都按 Composition 帧率解释 |
| `source_in_frame` | video/audio 源裁切入点，默认 0 |
| `handle_in_frames` / `handle_out_frames` | 入点前、出点后的预留素材；只检查，不自动插入转场 |
| `source_duration_in_frames` | 可选声明源时长；实际范围仍由 ffprobe 检查 |
| `fade_in_frames` / `fade_out_frames` | 视觉淡入/淡出；显式重叠片段可做叠化，不重叠则淡到黑 |
| `muted` / `volume` | 视频原声或独立音轨的静音与基础音量，volume 为 0..1 |
| `audio_fade_in_frames` / `audio_fade_out_frames` | 音频淡入/淡出，独立于画面淡变 |
| `volume_keyframes` | `[{"frame":0,"volume":1}, ...]`，按片段本地帧线性插值，可为对白设置 BGM 压低区间 |
| `still_motion` | 仅用于 image：`{"from":{"x":0.2,"y":0.5,"scale":1.1},"to":{"x":0.8,"y":0.5,"scale":1.3},"easing":"ease_in_out"}`；焦点 x/y 为 0..1，缩放为 1..1.5，画面在片段帧内插值并裁在画幅内 |

音量为基础音量 × 关键帧包络 × 音频淡变。未静音的视频保留原声；独立对白与原声并存时需明确混音，不能自动假定应丢弃原声。跨镜头 BGM 使用一条连续音轨；这里不自动分析对白、不自动决定 ducking。

静帧默认保持静止。`still_motion` 只给一个已获选图片提供受限推拉和焦点平移，使用帧驱动运算，不依赖浏览器 CSS 动画；构图、人物与文字可读性仍须在实际预览和审片中确认。没有图片素材、声音授权及真实渲染时，脚手架通过不代表静帧成片已验收。

脚手架包含同版 `@remotion/cli`、`@remotion/media`、`remotion` 及 `typecheck` 命令。它不安装依赖。`npm run typecheck`、Studio 回看和真正导出仍需在用户的生成目录中执行。

## 固定 plate 叠加 <a id="fixed-overlay"></a>

透明 plate 沿原 `selected_takes`、binding、媒体登记及 `timeline_item_media` 使用。`source_shot_id`只说明镜头归属；plate必须有独立 `vfx_overlay`用途的选用决定与真实素材SHA，不能把主镜视频或`post_mask`当成plate。当前只支持`kind=image`的静态RGBA plate，用帧驱动位置运动；蒙版、深度、跟踪与三维遮挡未因此获得能力。

image segment可选`overlay`，存在时还必须有完整`source_sha256`：

```json
{"x":20,"y":20,"width":64,"height":48,"alpha":0.5,"layer":1,"blend_mode":"normal","motion":{"to":{"x":220,"y":80},"easing":"ease_in"}}
```

坐标与尺寸使用Composition像素。完整图像缩放到指定矩形，RGBA透明区保持透明；起止矩形必须完整位于画幅内，不隐式裁切。`alpha`为0..1，`layer`为1..999（数值大者在上），仅作用于视觉叠加，字幕保留在上方。支持`normal/screen/multiply`，其他混合、蒙版或深度字段明确拒绝。当前仅normal合成在仓库工程夹具中有实际导出像素对照；其他模式仍需按具体材料核实际结果。

片段从`from_frame`出现，到`from_frame+duration_in_frames`之前结束。motion从本地第0帧的`x/y`移至最后一帧的`to.x/to.y`，帧率沿原Composition解释。`linear`匀速；`ease_in`从慢到快；`ease_out`逐渐停稳；`ease_in_out`首尾较缓。时长、位移与曲线应对应信息何时揭示、注意力如何转移，不能把产品视频配方固定时值套成叙事硬门。能量等级只作创作注记，没有伪装为生成模型控制。需要停留时，另排同一固定plate的静态片段，保留其原选择与来源。

脚手架在写文件前检查真实plate存在且SHA匹配，复制固定字节到`public/`并记录`overlay_sources`。原资源导出保留overlay与独立选用血缘，媒体QA复核SHA并且不会把透明plate算作补齐底片空隙。生成工程、类型检查、实际导出与画面对照分别留证；这些技术结果不代替视效、字幕遮挡或叙事效果的人审。

## 单 Cue 局部位置修改

后期角色先核对原意见引用的固定产物字节 SHA，再读取所见 render-plan 或含 `render_plan` 的 timeline。调用 `vsc.post.remotion_plan.edit_caption_position` 时另用 `document_sha256(document)` 固定完整 JSON 文档；这是规范 JSON 摘要，与数据库产物的原始字节 SHA 分别核验，不能互换。

```python
from vsc.post.remotion_plan import document_sha256, edit_caption_position

change = edit_caption_position(
    document,
    caption_id=selected_caption_id,
    expected_sha256=fixed_document_sha256,
    layout={"position": "top"},
    frame_range={"from_frame": selected_from_frame,
                 "duration_in_frames": selected_duration},
)
new_document, diff = change["document"], change["diff"]
```

`fixed_document_sha256` 必须在意见绑定时由 `document_sha256` 取得，执行前不要重新计算后覆盖旧值。`frame_range` 只允许精确等于已有整 Cue，不用于裁切、拆分或重定时。可用位置是 `top`、`bottom`、`center`，或 `{"position":"custom","custom_position":30}`（距顶部百分比0–100）。函数不改原文档，不保存或批准；登记返回的新文档、差异及原产物依赖，再将预览与适用的新 render 接回原意见。

Remotion 脚手架直接消费 caption 的 `subtitle_style`，资源导出只在台词／正文／时码唯一匹配时带入。字幕烧录使用 `scripts/post/subtitle_burn.py burn --help` 中的 `--render-plan` 读取同一布局并校验固定包、项目和画幅。剪映当前拒绝带局部位置覆盖的计划；需要该格式时先回到明确的编辑决定，不能静默去掉布局。

## VSC 创作边界

- 片段是否相接仍由连续性计划决定；Remotion 不修复 AI 画面中人物、空间或动作的错位。
- BGM、环境底和字幕必须沿用 VSC Cue Sheet/字幕时间码；不得因进入 Composition 而丢失使用权与版本信息。
- Studio 的编辑是一个新的候选版本；负责人批准并回写 VSC 时间线后才进入交付。

## v0.12.0 制作交接

新项目使用固定 production-v2 Profile，旧项目保留历史规则。正式运行、共享预算、交接契约与迁移操作以 [v2 指南](../guide/production-v2.md) 为准；旧低层命令不再作为新项目的直接付费执行入口。
