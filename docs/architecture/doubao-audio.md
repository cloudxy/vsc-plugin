# Seed-Audio 1.0 音频生成适配器

`scripts/providers/volcengine/audio.py` 是 VSC 自有的可选 MediaKit 客户端，使用标准库提交与查询豆包 `seed-audio-1.0`。它生成 `kind=audio`、`purpose=asset` 的声音候选，可按用途收入 music、ambience 或 sfx 素材库；用途分类是制作意图，不能据此保证返回结果只有音乐、环境声或音效。

它不自动批准候选、不做实时对话或 ASR，也不提供自动分轨、人声分离或音频延长。提示词中“约十秒”“无对白”属于生成指令，需要实际检查与审听，不能作为硬时长约束或已验证结果。

## 接口与前置条件

核验日期：2026-10-11。官方[通过 AI MediaKit 调用音频生成大模型](https://docs.volcengine.com/docs/Intelligentprocessing/audio-generation?lang=zh)要求：豆包语音开通相应模型、MediaKit 获得跨服务授权、取得有效 MediaKit API Key。

适配器按该指南示例提交 `POST https://mediakit.cn-beijing.volces.com/api/v1/tools/call-maas-proxy`，Bearer 鉴权；请求包含 `api=doubao.audio_generation` 和 `maas_params`。当前固定模型 `seed-audio-1.0`，输出 MP3、48000Hz，`pitch_rate`、`speech_rate`、`loudness_rate` 均为 0。提交成功后保存 `task_id`，用 `GET /api/v1/tasks/{task_id}` 查询，直到 `status=completed`，读取 `result.maas_result.audio` 的 Base64 原音频。

本版仅支持官方示例的 Base64 结果，不猜测其他 URL 字段、不下载未核实的音频地址。金额不在本地推算：响应有 usage 则原样保存，没有则明确记为可能计费、用量和金额未知。精确账单以供应商为准。

## 用法

默认读取统一的方舟 Agent Plan 专属 key `ARK_AGENT_PLAN_API_KEY`；套餐是否覆盖 MediaKit Seed-Audio 尚未验证。找不到时提示配置火山方舟 Agent 版本的 API Key。如另有具备该接口权限的 key，可用 `--key-env SOME_ENV_NAME` 显式选择其他变量；不接受密钥字面值。

默认 dry run，无需凭证和媒体工具，不写生成产物：

```bash
python3 -B scripts/providers/volcengine/audio.py generate \
  --project projects/示例作品 --out 06-素材/声音 --name BGM-01 \
  --asset-kind music --prompt '雨夜，克制的钢琴，约十秒，无对白。' \
  --max-chars 100 --dry-run
```

项目输入、授权与预算就绪后，将 `--dry-run` 换成 `--execute` 才提交一次可能计费的任务。`--max-chars` 必填，限制发送提示词的字符数，含空白和标点；它不等于生成音频时长或费用上限。

`--prompt-file 04-视听设计/音乐提示.txt` 可替代 `--prompt`；文本相对作品目录，完整原文绑定。`--asset-kind music|ambience|sfx` 记录预期用途。`--output` 为 `--out` 的别名，输出路径不得越出作品目录；名称使用安全 ID。

`--max-polls 30 --poll-interval 5` 控制本轮查询次数和间隔。轮询上限或网络错误会结束本轮，重跑同名命令可继续查询已有任务；允许调整查询次数和间隔，不改变原始生成请求。

## 恢复与输出证据

脚本复用 `scripts/providers/volcengine/speech.py` 中的安全路径、同名锁、原子记录和真实音频检查。实际提交前检查凭证、`ffprobe`/`ffmpeg`、生成记录合同与文件冲突，先持久化提交意图和完整请求绑定，再发 POST。POST 不重试，HTTP 重定向不跟随。

| 文件 | 用途 |
|---|---|
| `<name>-任务.json` | 原请求、规范化请求 SHA、预算、远程任务 ID、轮询序号和恢复状态 |
| `<name>-响应-submit.json` | 提交响应快照；可在任务 ID 写入前发生崩溃时恢复 |
| `<name>-响应-poll-000001.json` 等 | 查询响应快照与原请求 SHA；完成响应保留 Base64，以便本地重验 |
| `<name>-生成记录.json` | `vsc.generation-record/v1`：输入、provider/model、参数、任务 ID、响应路径与 SHA、用量、错误、输出 SHA 与真实时长 |
| `<name>.mp3` | 解码出非空音频，经真实容器/采样率/音轨/时长检查及完整解码后发布 |

生成记录 `engine.provider=doubao_audio`，`engine.model=seed-audio-1.0`。`outputs[].asset_kind` 保存预期用途；实际音频字节不做转码或改写。平台如提供 `result.duration`，只保存为平台报告时长，输出时长仍以实际探测为准。

提交结果不确定且没有可验证任务 ID 时，脚本拒绝重提；人工核验平台任务与账单后再决定下一步。收到有效任务 ID 后，GET 失败或达到轮询上限可续查。远程任务失败不重新生成。完成响应已缓存但本地媒体验证失败时，可从原响应再次验证，不发新 POST、不再次查询、不需要 key。

同名成功请求只有绑定、记录、响应快照及音频 SHA 均一致且媒体复验通过，才幂等返回。输入、用途、预算或显式凭证变量选择改变会拒绝沿用原任务；需要新候选时使用新名称。输出损坏不算成功，不会通过重新生成掩盖原错误。

## 素材库复用

先人工审听并按项目流程登记选择与授权，再收入对应种类。例如：

```bash
python3 -B scripts/assets/library.py promote \
  --project projects/示例作品 \
  --record projects/示例作品/06-素材/声音/BGM-01-生成记录.json \
  --kind music --id MUSIC-01 --name '雨夜音乐候选' --summary '待审听的场景音乐'

python3 -B scripts/assets/library.py use MUSIC-01 --project projects/目标作品
```

环境声或音效分别改用 `--kind ambience`、`--kind sfx`。成功生成与素材库 `generated` 状态都不等于可商用确认，不代替人审、版权清理或最终混音。

## 验证状态

2026-10-11：16 项离线测试通过，覆盖请求协议、凭证隔离、提交意图先落盘、提交响应恢复、GET 查询续接、未知提交不重提、缓存完成响应恢复、错误与用量、输入/记录/响应漂移、路径逃逸、并发锁与真实 48000Hz MP3 媒体检查。

测试替代网络，不调用付费 API。本次未配置有效 MediaKit key，没有线上成功证据；模型开通、跨服务权限、真实输出内容、质量与收费均未实测。已知方舟 key 的其他服务验证结果不能作为 MediaKit 可用证据，也不会触发本适配器自动尝试。

```bash
python3 -B tests/run.py --test production.integration.test_doubao_audio -v
```

真实媒体测试在缺少 `ffprobe`/`ffmpeg` 时明确跳过；实际 `--execute` 则在工具缺失时拒绝提交。
