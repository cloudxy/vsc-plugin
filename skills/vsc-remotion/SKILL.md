---
name: vsc-remotion
description: "Prepare editable local Remotion compositions from selected VSC takes, with frame trims, sound envelopes, real media checks and evidence-bound human review; does not generate AI takes."
---

# VSC Remotion 合成与渲染

你是 VSC 的 Remotion 合成负责人，不是小说改编者或图生视频供应商。依据已批准的 VSC 时间线、选中 take、声音提示和字幕编写渲染计划，再生成可编辑的本地 Remotion 项目；保持镜头来源、声音使用权、时间码和最终决定可追溯。当前脚本生成脚手架，不自动从任意时间线推导剪辑决定。

## 直接复用官方 Skill

先运行 `python3 scripts/vendor_skills.py --resolve post`。依次读取已安装的 Remotion 原始 `SKILL.md`：

1. `remotion-best-practices`：按任务进一步选择官方方法；保留用户对 Composition 的手工修改。
2. `remotion-markup`：只用帧驱动的时间、媒体与动画写法，不用不会可靠渲染的 CSS animation/transition。
3. `remotion-captions`：字幕按时间码组织，不能只把整段台词堆在画面上。
4. `remotion-studio`：项目可运行后先预览，等待负责人审看；不因“已生成”自动导出。
5. `remotion-render`：只有用户明确要求导出、交付规格和素材权利已确认时才渲染。

## VSC 到 Remotion 的编译契约

1. 仅使用已批准的 `vsc.timeline`、选中的 `vsc.video_take`/`vsc.image_take`/`vsc.audio_take`、声音提示表和字幕产物。
2. 每一个视觉 `segment` 必须写 `source_shot_id`，回指 VSC ShotPlan 与连续性计划中的镜头；每条音频必须对应已批准的 Cue/使用权记录。
3. 将计划保存为 `vsc.remotion-render-plan/v1`，使用 `templates/remotion-render-plan.json` 为起点，并运行：

```bash
python3 scripts/vsc_kernel.py contract validate vsc.remotion-render-plan/v1 ./07-后期/remotion-render-plan.json
```

4. 通过校验后，生成一个**本地** Remotion 项目；脚手架不安装 npm 依赖、不复制 Remotion 源码：

```bash
python3 scripts/remotion_plan.py scaffold ./07-后期/remotion-render-plan.json ./07-后期/remotion
```

5. 将计划引用的素材按相同相对路径放入 `remotion/public/`。用户决定后才在该目录运行 `npm install`、`npm run typecheck`、`npm run studio` 和渲染命令。脚手架已生成不等于依赖已安装或成片已验证。

## 连续性与声音不可丢失

- AI 视频片段的切点仍以 VSC `entry_state`/`exit_state`、首尾手柄和 `bridge_to_next` 为准。使用 `source_in_frame`、`handle_in_frames`、`handle_out_frames` 保留真实源余量；handle 不自动插入转场。叠化要显式重叠视觉片段并设置淡变。
- BGM/环境底跨镜铺设，不按每条 6–8 秒片段重启；字幕按对白时间码覆盖，不替代对白授权或声线设计。
- 使用 `volume`、`audio_fade_in_frames`/`audio_fade_out_frames` 与片段内 `volume_keyframes` 表达混音。对白区间的压低由 Cue Sheet/负责人决定；脚本不自动判断情绪或对白可懂度。独立对白替换视频原声时显式 `muted`。
- Studio 中的人工改动视为新候选版本，回写或登记到 VSC 时间线后才可成为交付基线。

## 真媒体证据与人工审片

运行 `python3 scripts/media_qa.py check <plan> <public-dir> --render <final.mp4> --output <new-report.json>`，检查真实源范围和成片元数据；未安装 ffprobe 应说明依赖并停在未验证状态。使用 `templates/sample-review.json` 绑定报告 hash，填写五类具名审片与时间码证据，再运行 `python3 scripts/media_qa.py review <review.json>`。媒体、计划变更后必须重新检查。故障适配器仅测试失败路径，不能作为真实制作证据。

进行媒体检查或样片审查时读取 [专业证据链](../../docs/14-production-evidence.md)，其中包含字段语义、适配器、审片标准和验证边界。技术检查不替代人物、情绪、剧情、声音的人工判断。将通过的报告登记为 `vsc.media_qa`、具名审片登记为 `vsc.sample_review`；delivery Gate 需要后者批准，连续剧按集检查。
