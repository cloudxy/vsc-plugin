# 生成适配器边界

VSC 核心不含任何图像、视频、音频或模型供应商 SDK。适配器只通过 CLI 或文件调用本机固定版本的上游工具（见下文），不把上游代码复制进 VSC。适配器由团队按其账号、成本、地区、授权与数据政策另行实现；更换适配器不应改变项目的剧本、资产或镜头语义。适配器位于 `workflow/` 声明的稳定 VSC 语义与外部实现之间；它不拥有阶段、角色或项目批准规则。

每次生成任务至少保存：输入 artifact ID 与 SHA、参考资产、适配器/模型版本、参数摘要、预算归属、提交与完成时间、输出路径、错误信息和人工选择结果。生成输出只登记为候选 take，必须经项目责任人选择后才能进入时间线。

## 已实现的本地媒体验证适配器

`scripts/media_qa.py` 提供 `LocalProbeAdapter`（`local-ffprobe/v1`）与 `FaultProbeAdapter`（`fault-ffprobe/v1`）。前者有界、只读执行 ffprobe，返回真实媒体元数据与 SHA256；成片有音轨时，还用 ffmpeg 的 loudnorm 分析测量综合响度、真峰值与响度范围，给出 `--loudness-target` 时据此判定；后者注入工具缺失、超时、坏 JSON 和进程失败，走同一个错误处理接口。故障报告显式标记 `simulated`，不能作为真实样片批准证据。

这两个实现是媒体检查适配器，不是图生视频或语音生成供应商。没有付费模型 SDK、生成调用或自动审美评分。运行方式、真实样片审查与测试边界见 [专业制作证据链](../governance/production-evidence.md)。

## 已实现的本机工具适配器

| 适配器 | 上游（vendor） | 做什么 | 边界 |
|---|---|---|---|
| `scripts/mpt_adapter.py voice` | moneyprinterturbo | 为已批准台词逐条生成预演临时配音与逐词字幕，并写生成记录 | Edge-TTS 声音的商业授权未经核验，只能用于预演；不调用大模型，不登记或批准产物 |
| `scripts/mpt_adapter.py prepare` | moneyprinterturbo、noto-sans-sc、moneyprinterturbo-assets（可选） | 链接字幕字体与 BGM，默认字体设为 OFL 的 Noto Sans SC | 附带资源以 `assets-` 前缀标出，权利说明见 [第三方声明](../../vendor/THIRD_PARTY.md) |
| `scripts/jianying_export.py export` | narratoai | 把 `vsc.remotion-render-plan/v1` 写成剪映多轨草稿 | 剪映草稿是非官方公开格式；已在 macOS 剪映专业版 10.3.0 实测可打开、字幕可见（2026-10-10）。淡入淡出、音量关键帧与图片片段不迁移并逐条记录 |

`vsc.remotion-render-plan/v1` 因此有两个导出适配器：Remotion 与剪映。生成记录目前是各适配器写在输出目录里的 JSON，还不是内核契约。
