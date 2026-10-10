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
python3 scripts/vendor_sync.py --install remotion
python3 scripts/vendor_skills.py --resolve post
```

下载内容不进入 VSC Git 仓库；用户决定是否在本机为生成的 Composition 安装 Node/npm 依赖。VSC 不替任何人判断 Remotion 的许可或商业使用资格。

## 计划与项目脚手架

`vsc.remotion-render-plan/v1` 是 VSC 与 Remotion 的边界。它定义 Composition 的画幅、帧率、时长，以及视频、图片、音频、字幕和文字片段的开始帧、时长与来源。视觉片段必须回指 `source_shot_id`，以避免剪辑阶段脱离 VSC 连续性计划。

```bash
python3 scripts/vsc_kernel.py contract validate vsc.remotion-render-plan/v1 templates/remotion-render-plan.json
python3 scripts/remotion_plan.py scaffold templates/remotion-render-plan.json /tmp/vsc-remotion-example
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

音量为基础音量 × 关键帧包络 × 音频淡变。未静音的视频保留原声；独立对白与原声并存时需明确混音，不能自动假定应丢弃原声。跨镜头 BGM 使用一条连续音轨；这里不自动分析对白、不自动决定 ducking。

脚手架包含同版 `@remotion/cli`、`@remotion/media`、`remotion` 及 `typecheck` 命令。它不安装依赖。`npm run typecheck`、Studio 回看和真正导出仍需在用户的生成目录中执行。

## VSC 创作边界

- 片段是否相接仍由连续性计划决定；Remotion 不修复 AI 画面中人物、空间或动作的错位。
- BGM、环境底和字幕必须沿用 VSC Cue Sheet/字幕时间码；不得因进入 Composition 而丢失使用权与版本信息。
- Studio 的编辑是一个新的候选版本；负责人批准并回写 VSC 时间线后才进入交付。
