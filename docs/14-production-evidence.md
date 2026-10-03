# 用真实媒体形成专业制作证据

VSC 的第一条可运行专业验证切片是：计划校验 → 源媒体范围检查 → 导出成片检查 → 具名人工审片 → 登记证据。它不生成模型素材，不凭 JSON 推断人物或情绪一致，也不把脚手架生成当作渲染成功。

## 帧级编排

`vsc.remotion-render-plan/v1` 保持旧字段兼容，新增可选字段：

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

音量为基础音量 × 关键帧包络 × 音频淡变。未静音的视频保留原声；独立对白与原声并存时需明确混音，不能自动假定应丢弃原声。跨镜头 BGM 使用一条连续音轨；这里不自动分析对白、不自动决定 ducking。

脚手架包含同版 `@remotion/cli`、`@remotion/media`、`remotion` 及 `typecheck` 命令。它不安装依赖。`npm run typecheck`、Studio 回看和真正导出仍需在用户的生成目录中执行。

## 真实本地适配器与故障适配器

```bash
python3 scripts/remotion_plan.py validate ./remotion-render-plan.json
python3 scripts/media_qa.py check ./remotion-render-plan.json ./remotion/public --render ./final.mp4 --output ./media-qa-001.json
```

`local-ffprobe/v1` 有界执行本机 ffprobe，保存媒体 SHA256、字节数、时长、声画 stream、画幅、帧率、音频采样率与声道。它检查源裁切及尾手柄可用范围；指定成片时检查时长（允许一帧差异）、画幅、平均帧率和计划要求的独立音轨。符号链接不能越出 `media_root`。缺少 ffprobe、媒体缺失、时长未知、超范围和进程失败都会失败退出，不能被替换成模拟通过。

```bash
python3 scripts/media_qa.py check ./remotion-render-plan.json ./remotion/public --adapter fault --fault timeout --output ./fault-qa-001.json
```

`fault-ffprobe/v1` 注入 timeout、missing_tool、invalid_metadata 或 probe_error，经过真实适配器同一个错误处理路径。报告显式 `simulated: true`，不能用于样片批准。这是失败路径测试适配器，不是生成供应商。

报告不覆盖已有文件。报告中的来源和成片都绑定内容 hash；审片时会重新执行 ffprobe，比对真实源映射、计划、规格、元数据与 hash，变更后须生成新报告。只检查源素材、没有成片的报告可用于排查，但不能作为批准的技术证据或完成样片审查。

```bash
python3 scripts/media_qa.py validate-report ./media-qa-001.json
```

## 45–90 秒样片的人工审片

建议选一个有人物互动、情绪变化和场景衔接的 45–90 秒样片。长度是试验建议，不是所有项目的硬限制。按 `templates/sample-review.json` 填写负责人、技术报告及其 SHA256，并填写五类判断的具体时间码/镜头证据：

| 类别 | 回看问题 |
| --- | --- |
| 剧情与动机 | 没读过原著的人是否理解目标、阻碍与变化？改编有无新造事实或失去因果？ |
| 物理连续性 | 脸、服装、道具、空间、轴线、视线、动作接触与切点是否一致？ |
| 情绪连续性 | 情绪变化是否有原因与表演支撑？相邻片段的反应与强度是否衔接？ |
| 剪辑覆盖 | 主镜、反打、反应、空镜是否足够表达剧情？是否靠不必要的转场遮掩缺镜头？ |
| 对白与音乐 | 对白是否听得懂？BGM 是否压住对白、重复重启或情绪错配？环境底与声音桥是否自然？ |

记录实际耗时、成本及失败案例（包含失败原因、方法/模型版本、重试与处理）。没有失败明确填写 `[]`；未检查项保留 `not_checked`，不能当作通过。

```bash
python3 scripts/media_qa.py review ./sample-review.json
```

校验要求真实通过的成片技术报告、未变化的内容 hash、具名审查人、全部 pass 及具体证据，并记录耗时/成本/失败。它证明记录完整且绑定了版本，不证明人的审美判断必然正确，也不自动改变 VSC 项目批准状态。

所有 Profile 的 delivery Gate 要求批准的 `vsc.sample_review`；novel-serial 按 episode scope 逐集检查。技术报告以 `vsc.media_qa` 登记，审片记录以 `vsc.sample_review` 登记，负责人才可批准。批准会调用实际契约复检，源-only/fault/空 sources/空 render 不能批准。

审片记录与报告可以放在同一目录，`technical_report` 使用不含 `../` 的相对路径，注册快照会保留其资源；也可使用绝对路径并保留可访问的报告。技术报告中源计划、media_root 和成片路径为本机绝对路径，不能在批准后随意移动/删除；迁移资产时应生成新的技术报告及审片版本。

## 验证边界

测试包含真实 ffmpeg 合成的短视频/音频及本机 ffprobe 检查，也包含缺媒体、越界、损坏媒体、缺成片音轨、报告过期和故障注入。它们验证技术闭环，不是 AI 生成样片、Remotion 渲染验收或专业审美评测。没有 ffprobe/ffmpeg 的机器会明确跳过真实媒体集成测试，故障/结构测试仍运行。

实现参照：[Remotion Video](https://www.remotion.dev/docs/media/video)、[Remotion Audio](https://www.remotion.dev/docs/media/audio)、[Remotion CLI](https://www.remotion.dev/docs/cli)。
