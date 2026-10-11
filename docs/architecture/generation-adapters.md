# 生成适配器边界

VSC 核心不依赖模型供应商 SDK。需要上游项目的能力时，把它移植成 VSC 自己的代码（见下文），运行时不调用上游项目。已有可选豆包适配器；团队按账号、成本、地区、授权与数据政策选择或补充实现。更换适配器不应改变项目的剧本、资产或镜头语义。适配器位于 `workflow/` 声明的稳定 VSC 语义与外部实现之间；它不拥有阶段、角色或项目批准规则。

每次生成任务保存一份 `vsc.generation-record/v1` 生成记录（字段见 `scripts/consistency.py` 与 `templates/generation-record.json`）。生成输出只登记为候选 take，必须经项目责任人选择后才能进入时间线。

## 已实现的本地媒体验证适配器

`scripts/media_qa.py` 提供 `LocalProbeAdapter`（`local-ffprobe/v1`）与 `FaultProbeAdapter`（`fault-ffprobe/v1`）。前者有界、只读执行 ffprobe，返回真实媒体元数据与 SHA256；成片有音轨时，还用 ffmpeg 的 loudnorm 分析测量综合响度、真峰值与响度范围，给出 `--loudness-target` 时据此判定；后者注入工具缺失、超时、坏 JSON 和进程失败，走同一个错误处理接口。故障报告显式标记 `simulated`，不能作为真实样片批准证据。

这两个实现是媒体检查适配器，不是图生视频或语音生成供应商。没有付费模型 SDK、生成调用或自动审美评分。运行方式、真实样片审查与测试边界见 [专业制作证据链](../governance/production-evidence.md)。

## 已实现的本机制作工具

用法、输出与边界见各脚本的 `--help`；移植代码的来源与许可证写在被移植文件的文件头。

| 工具 | 做什么 |
|---|---|
| [`scripts/temp_voice.py`](../../scripts/temp_voice.py) | 为已批准台词生成预演临时配音与整句／逐词字幕，并写生成记录 |
| [`scripts/subtitle_burn.py`](../../scripts/subtitle_burn.py) | 把已批准的 SRT 烧进视频 |
| [`scripts/jianying_export.py`](../../scripts/jianying_export.py) | 把 `vsc.remotion-render-plan/v1` 写成剪映多轨草稿 |

剪映草稿是非官方公开格式。2026-10-10 的核验：同一输入下，VSC 移植的构件与 NarratoAI 上游输出逐文件一致（忽略随机 ID、时间与路径）；该草稿在 macOS 剪映专业版 10.3.0 中可打开、字幕可见。

`vsc.remotion-render-plan/v1` 因此有两个导出：Remotion 与剪映。`temp_voice.py` 的生成记录即采用 `vsc.generation-record/v1`。

## 供应商实测

以下是在真实作品上低分辨率测试得到的平台行为，用来选择“资产图 → 关键帧 → 视频”（见 [vsc-produce](../../skills/vsc-produce/SKILL.md)）各段的供应商。平台策略会变，用前请复测并更新日期。

| 日期 | 供应商与模型 | 用途 | 结果 |
|---|---|---|---|
| 2026-10-11 | 火山方舟 Seedream 4.5（`doubao-seedream-4-5-251128`） | 资产图、关键帧 | 可用。单次最多 14 张参考图，也可以把上一张关键帧当底图做局部编辑。但道具数量和位置仍会出错，需要逐张检查。 |
| 2026-10-11 | 火山方舟 Seedream 5.0 flash（`doubao-seedream-5-0-flash-260915`） | 纯文生人物资产图 | 已生成并登记人物规范图，原始产物被同账号 Seedance 接受。当前账号其他模型是否开通须单独核对。 |
| 2026-10-11 | 火山方舟 Seedance 2.5（`doubao-seedance-2-5-260628`） | 参考人物图生成视频，返回尾帧接下一镜 | 可信 Seedream 原始产物获接受；三镜 480p、24fps，均含音轨，后两镜绑定前镜返回尾帧。普通 Seedream 4.5 写实人脸图曾被拒绝，不能概括为所有 AI 人脸都不可用。输入 SHA 和镜头交界检查通过；表演、动作、口型和声音仍需审片。 |

## 豆包适配器

[`scripts/volc_ark.py`](../../scripts/volc_ark.py) 用标准库调用火山方舟。命令、模型默认值和参数以 `--help` 与代码为准；密钥只读环境变量 `HUO_SHAN_API_KEY` 或 `ARK_API_KEY`。执行前应有本项目已批准输入、预算和授权。

```bash
# 一次生成规范资产图；模型需已在账号开通。
python3 -B scripts/volc_ark.py image --project projects/雨夜来信 \
  --out 06-素材/资产 --name character-01 --purpose asset --prompt-file ./人物提示.txt

# 提交前检查请求。去掉 --dry-run 才调用付费视频生成。
python3 -B scripts/volc_ark.py video --project projects/雨夜来信 \
  --out 06-素材/视频 --name SH-001-T1 --shot SH-001 \
  --bible projects/雨夜来信/04-视听设计/资产库.json \
  --state projects/雨夜来信/05-预演/状态时间线.json \
  --prompt-file ./动作提示.txt --ref-image projects/雨夜来信/06-素材/资产/character-01.png \
  --resolution 480p --draft --dry-run

python3 -B scripts/volc_ark.py inspect --project projects/雨夜来信 \
  --media projects/雨夜来信/06-素材/视频/SH-001-T1.mp4 \
  --bible projects/雨夜来信/04-视听设计/资产库.json \
  --state projects/雨夜来信/05-预演/状态时间线.json --shot SH-001
```

`image --purpose candidate` 生成关键帧前须给出镜头、时刻、资产库及时间线。`video --first-frame` 是首帧约束模式，不能混用参考素材；`--first-frame-ref` 是全模态模式中把图片1作为起始画面的文字要求，属于参考，不能声称平台硬约束首帧。视频返回尾帧登记为 `outputs[].role=last_frame`，可原样传给下一镜；一致性检查优先采用实际返回帧，画面接点仍须审阅。

方舟官方[肖像素材指南](https://docs.volcengine.com/docs/ark/seedance-portrait-asset-guide?lang=zh)说明：平台信任同账号近 30 天内指定 Seedance 视频及对应尾帧、Seedream 5.0 lite/pro 纯文生图的含人脸原始产物；改动、转码、跨账号或过期不能据此获得信任。参考生图产物不能自动沿用纯文生图的信任。具体型号范围由脚本 `TRUSTED` 声明，平台最终判定优先。原始下载链接的有效期和人脸信任期限是两回事；记录期限不能保证原始 URL 始终可访问。可信素材库的 `asset://` 引用须在账号内另行建立，不会因本地复制自动创建。

每次生成保留输入快照、请求摘要、远程任务／响应、原始链接、用量和输出 SHA。同名命令只有请求完全一致才可续接，下载失败保留已计费用量；不同输入须用新 take 名称。无法核实的旧任务，以及引用链接过期后请求编码变化的任务，会停止并说明原因，不把旧结果绑定到新输入。音轨存在只证明有声音，联合生成不等于可复用的稳定角色声线；专用 TTS／音乐生成尚未接入。

视觉检查按锚点逐项给出 `pass/fail/unsure` 和可见依据，保存 `vsc.visual-check/v1`。视频默认抽首、中、尾三帧，因此不是逐帧动作或口型验证；报告必须 `advisory=true`，完整清单通过也不能代替人审。
