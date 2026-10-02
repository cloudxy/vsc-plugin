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
python3 scripts/remotion_plan.py validate templates/remotion-render-plan.json
python3 scripts/remotion_plan.py scaffold templates/remotion-render-plan.json /tmp/vsc-remotion-example
```

脚手架生成 `src/`、`public/`、`package.json` 与计划副本，不会执行 `npm install`。将选定素材放入 `public/` 后，用户可在生成目录运行 `npm install`、`npm run studio` 预演；只有明确要求导出时才运行 `npm run render -- <composition-id> <output.mp4>`。

## VSC 创作边界

- 片段是否相接仍由连续性计划决定；Remotion 不修复 AI 画面中人物、空间或动作的错位。
- BGM、环境底和字幕必须沿用 VSC Cue Sheet/字幕时间码；不得因进入 Composition 而丢失使用权与版本信息。
- Studio 的编辑是一个新的候选版本；负责人批准并回写 VSC 时间线后才进入交付。
