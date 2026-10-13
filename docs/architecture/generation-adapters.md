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
| [`scripts/procedural_audio.py`](../../scripts/procedural_audio.py) | 离线合成原创环境底、拟音与简约配乐，固定 seed 可复现，输出声音资产候选 |
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

[`scripts/volc_ark.py`](../../scripts/volc_ark.py) 用标准库调用火山方舟。命令、模型默认值和参数以 `--help` 与代码为准；密钥只读 `ARK_AGENT_PLAN_API_KEY`（方舟 Agent Plan 专属 key），图像／视频只走套餐专属地址 `https://ark.cn-beijing.volces.com/api/plan/v3`。个人版视频新提交要求本机声明实际档位 `ARK_AGENT_PLAN_TIER=large` 或 `max`；套餐规则禁止用该 key 直接调用文本生成与向量化模型，因此视觉检查只能预检和读取已有报告。执行前应有本项目已批准输入、预算和授权。套餐边界与尚未接入能力见 [Agent Plan 个人版对照](ark-agent-plan-personal.md)。

```bash
# 一次生成规范资产图；模型需已在账号开通。
python3 -B scripts/volc_ark.py image --project projects/示例作品 \
  --out 06-素材/资产 --name character-01 --purpose asset --prompt-file ./人物提示.txt

# 提交前检查请求。去掉 --dry-run 才调用付费视频生成。
python3 -B scripts/volc_ark.py video --project projects/示例作品 \
  --out 06-素材/视频 --name SH-001-T1 --shot SH-001 \
  --bible projects/示例作品/04-视听设计/资产库.json \
  --state projects/示例作品/05-预演/状态时间线.json \
  --prompt-file ./动作提示.txt --ref-image projects/示例作品/06-素材/资产/character-01.png \
  --resolution 480p --draft --dry-run

python3 -B scripts/volc_ark.py inspect --project projects/示例作品 \
  --media projects/示例作品/06-素材/视频/SH-001-T1.mp4 \
  --bible projects/示例作品/04-视听设计/资产库.json \
  --state projects/示例作品/05-预演/状态时间线.json --shot SH-001
```

`image --purpose candidate` 生成关键帧前须给出镜头、时刻、资产库及时间线。`video --first-frame` 是首帧约束模式，不能混用参考素材；`--first-frame-ref` 是全模态模式中把图片1作为起始画面的文字要求，属于参考，不能声称平台硬约束首帧。视频返回尾帧登记为 `outputs[].role=last_frame`，可原样传给下一镜；一致性检查优先采用实际返回帧，画面接点仍须审阅。

方舟官方[肖像素材指南](https://docs.volcengine.com/docs/ark/seedance-portrait-asset-guide?lang=zh)说明：平台信任同账号近 30 天内指定 Seedance 视频及对应尾帧、Seedream 5.0 lite/pro 纯文生图的含人脸原始产物；改动、转码、跨账号或过期不能据此获得信任。参考生图产物不能自动沿用纯文生图的信任。具体型号范围由脚本 `TRUSTED` 声明，平台最终判定优先。原始下载链接的有效期和人脸信任期限是两回事；记录期限不能保证原始 URL 始终可访问。可信素材库的 `asset://` 引用须在账号内另行建立，不会因本地复制自动创建。

每次生成保留输入快照、请求摘要、远程任务／响应、原始链接、用量和输出 SHA。同名命令只有请求完全一致才可续接，下载失败保留已计费用量；不同输入须用新 take 名称。无法核实的旧任务，以及引用链接过期后请求编码变化的任务，会停止并说明原因，不把旧结果绑定到新输入。音轨存在只证明有声音，联合生成不等于可复用的稳定角色声线；专用声音适配器见下文，须分别验证权限与结果。

视觉检查按锚点逐项给出 `pass/fail/unsure` 和可见依据，保存 `vsc.visual-check/v1`。视频默认抽首、中、尾三帧，因此不是逐帧动作或口型验证；报告必须 `advisory=true`，完整清单通过也不能代替人审。

## 声音适配器与当前状态

以下工具已经实现；脚本存在、离线测试通过、凭证存在、线上成功和人工审听是不同证据。

| 工具 | 能力与凭证 | 2026-10-11 验证状态 |
|---|---|---|
| [`doubao_speech.py`](../../scripts/doubao_speech.py) | 豆包语音合成 2.0，固定 `speaker`、情绪 context、已有合法复刻音色合成；默认读取 `ARK_AGENT_PLAN_API_KEY` 并走 `agent-plan` 路由 | 离线协议及真实本地媒体检查通过。音色列表探测与普通合成返回 HTTP 401；专属 Agent Plan 合成返回 45000010／底层 AuthenticationError 401。均未取得成功 TTS 音频；不能报告当前账号语音可用。 |
| [`doubao_audio.py`](../../scripts/doubao_audio.py) | 经 MediaKit 调用 Seed-Audio 1.0，异步生成音乐／环境／音效候选；默认读取 `ARK_AGENT_PLAN_API_KEY`（套餐是否覆盖 MediaKit 尚未验证） | 离线协议、续接与真实本地媒体检查通过。当前有效 MediaKit key 未配置，尚无线上的成功音频与效果证据。 |
| [`procedural_audio.py`](../../scripts/procedural_audio.py) | 标准库离线原创合成，无凭证、无外部采样；wind/rain/cloth/footsteps/ceramic/bell/music_pad | 可离线生产声音候选。它是本地程序合成，不是豆包模型结果；仍须试听、按场景选择和混音。 |

语音默认 `--service agent-plan`，配合统一 key；普通语音服务须显式 `--service speech`，并用 `--key-env` 指定具备权限的其他变量。端点随请求绑定，不自动猜测或回退。两个远程声音工具默认 dry run，显式 `--execute` 才可能付费。`--max-chars` 限文本或提示词字符数，不能当作人民币费用或生成时长上限。Seed-Audio 的“约十秒”“无对白”只属于提示词要求；工具不保证精确时长，也不自动分轨或分离人声。TTS 的相同 `speaker` 只能绑定供应商音色 ID，不能代替跨镜声线、情绪、口型与表演审听。

官方 [IAM API Key 最佳实践](https://docs.volcengine.com/docs/ark/iam-api-key-best-practices?lang=zh)允许给方舟／IAM key 扩展其他云产品权限。语音或 MediaKit 适配器可用 `--key-env 变量名` 显式选择其他环境变量，但不会自动 fallback；具备方舟图像／视频权限不证明语音或 MediaKit 权限。当前语音 401 不应绕过，也不能外推为所有账号或接口都不支持。

```bash
# 只核对请求；不需要 key、不提交生成。
python3 -B scripts/doubao_speech.py synthesize --project projects/示例作品 \
  --name VOICE-01 --text '你好，今天还好吗？' --speaker zh_female_vv_uranus_bigtts \
  --context '温柔、克制地说话。' --max-chars 20 --dry-run
python3 -B scripts/doubao_audio.py generate --project projects/示例作品 \
  --name BGM-01 --asset-kind music --prompt '克制的钢琴，约十秒，无对白。' \
  --max-chars 100 --max-polls 30 --dry-run

# 本地生成声音候选；不联网。
python3 -B scripts/procedural_audio.py --project projects/示例作品 \
  --name ambience-wind-01 --preset wind --duration 10 --seed 0
```

声音均写 `kind=audio`、`purpose=asset` 的 `vsc.generation-record/v1`。TTS 保存请求、分块摘要、用量与原音频 SHA；Seed-Audio 保存任务 ID、提交／查询响应及用量，可续查原任务，已缓存完成响应可本地重验。未知提交不自动重新生成，坏媒体不报成功。详细用法与限制见[豆包语音](doubao-speech.md)、[Seed-Audio](doubao-audio.md)。人工确认后用 `vsc_library.py promote/use` 复用；voice 条目保留供应商、音色、资源与模型，声音权属须独立核验。

## 只读就绪诊断与批次入口

```bash
python3 -B scripts/vsc_toolchain.py --project projects/示例作品 --json
python3 -B scripts/vsc_production.py plan projects/示例作品/production-batch.json --project projects/示例作品
```

`vsc_toolchain.py` 分别报告实现、默认环境变量配置、当前作品中 schema 与媒体 SHA 有效的候选、素材库媒体／规格数量及待人工审阅状态。它只读、无网络探测，`permission_verification=not_probed`；`configured=true` 不验证账号权限、额度或供应商可用性，候选统计也不做解码或审美批准。显式 `--key-env` 的其他变量不被默认配置检测自动推定可用。

`vsc_production.py` 的有界串行队列当前只支持方舟 `image/video`，按依赖顺序绑定资产、关键帧与视频尾帧；声音工具仍使用各自独立入口。先 `validate/plan` 审阅输入 SHA、任务数和图像／视频秒数上界，再 `run --execute --plan-hash <hash>`；不带 `--execute` 只给出计划。plan hash 绑定请求，不是创作批准。预算不是精确金额，未知提交不重提，失败不继续下游。完整入口、模板与恢复规则见[批量生产](../guide/production-batch.md)。
