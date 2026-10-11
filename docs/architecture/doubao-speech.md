# 豆包语音合成适配器

`scripts/doubao_speech.py` 是 VSC 自有的标准库 HTTP 客户端，接入豆包语音合成 2.0 的单向流接口。产物是 `kind=audio`、`purpose=asset` 的候选声音资产；音色相同不代表表演、情绪或声线听感已通过人工确认。脚本不做 ASR、实时对话、上传训练音频或创建复刻音色。普通服务与方舟 Agent Plan 专属服务必须显式选择，不从密钥外形猜测，不因鉴权失败自动换端点。

## 已验证与尚未验证

2026-10-11：18 项离线测试通过，覆盖正常音频分块和完成码、错误与断流、幂等续接、请求与文本文件漂移、伪造声线记录、并发提交锁、预算、路径逃逸、凭证隔离、人物绑定以及真实本地 WAV/MP3 检查。测试使用替代 HTTP 响应，不访问付费接口。媒体检查确实执行本机 `ffprobe` 和 `ffmpeg`，并验证截断 WAV 被拒绝。

2026-10-11：已有方舟凭证的 `get_voice` 探测返回 HTTP 401、`Invalid X-Api-Key`。随后将用户提供的凭证配置到本机默认语音变量，以官方预置音色发起一次 12 字符的实际合成，普通地址仍返回 HTTP 401；再显式选择 Agent Plan 官方专属地址，返回业务码 `45000010`，底层 `AuthenticationError`／401。两种地址都未取得音频，均未自动重试。配置存在不能证明语音服务认证、权限或供应商可用。这个结果不能推断所有方舟 key 都不可跨服务；真实可用性、复刻效果和作品配音仍待有效凭证与实际审听，线上请求失败时也不臆断费用为零。

## 官方协议依据

核验日期：2026-10-11。按最新[单向流式语音合成 HTTP 文档](https://docs.volcengine.com/docs/DoubaoVoice/unidirectional-streaming-text-to-speech-http?lang=zh)实现：

- 固定端点 `https://openspeech.bytedance.com/api/v3/tts/unidirectional`，新版 `X-Api-Key` 鉴权，UUID `X-Api-Request-Id`；使用 `X-Control-Require-Usage-Tokens-Return: *` 请求字符用量。
- 预置 2.0 音色资源为 `seed-tts-2.0`，已有复刻 2.0 音色资源为 `seed-icl-2.0`；`speaker` 取控制台音色 ID。官方示例预置音色为 `zh_female_vv_uranus_bigtts`。
- 情绪、语气等提示写入 `req_params.additions` 的 JSON 字符串，其内部字段为 `context_texts` 数组。复刻资源拒绝 `--context`，需显式提供模型版本。
- 接收逐行 JSON，按顺序拼接 `code=0` 的 Base64 音频；必须见到 `20000000` 完成码，EOF 不等于完成。官方[个人语音模型示例](https://docs.volcengine.com/docs/ark/agent-plan-personal-voice-model?lang=zh)也展示该完成码处理。其他业务码立即失败，不重试。

新版 HTTP 文档列出 WAV/MP3 支持，但建议流式场景使用 PCM。此脚本仅开放 WAV、MP3，默认 MP3；WAV 直接请求平台容器并检查实际返回结果，未经线上 WAV 验证。无法验证的流、错误容器或坏文件均不报成功，不自行猜测音频格式。

## 普通语音与 Agent Plan 路由

`--service speech` 是默认的普通语音接口。若使用[方舟 Agent Plan 专属 API Key](https://docs.volcengine.com/docs/ark/agent-plan-personal-voice-model?lang=zh)，须显式传 `--service agent-plan`，地址为 `https://openspeech.bytedance.com/api/v3/plan/tts/unidirectional`。鉴权头和 MP3 流协议相同，不能把专属 key 用普通地址的 401 当作专属服务不可用。专属路由仅开放官方已声明的 `seed-tts-2.0` 预置音色，不承诺声音复刻。

端点进入请求绑定；同名任务不能换服务续接。两种模式均无自动端点探测、回退或重提，不支持任意 URL。示例在默认 dry run 命令后加 `--service agent-plan`，确认后再 `--execute`。

## 凭证与提交

默认只读 `DOUBAO_SPEECH_API_KEY`，不自动回退到 `HUO_SHAN_API_KEY` 或 `ARK_API_KEY`。不接受密钥命令行字面值、不保存凭证。

官方 [IAM API Key 最佳实践](https://docs.volcengine.com/docs/ark/iam-api-key-best-practices?lang=zh)说明，方舟或 IAM 创建的 API Key 可通过所属 IAM 用户的权限策略扩展到豆包语音。因此具备语音权限的现有 key 可显式通过 `--key-env HUO_SHAN_API_KEY` 使用；这个参数只接受环境变量名，不检查、不授予云端权限。语音独立变量仍为默认值。

默认是 dry run，不需要 key、`ffprobe` 或 `ffmpeg`，不写作品产物：

```bash
python3 -B scripts/doubao_speech.py synthesize \
  --project projects/示例作品 --out 06-素材/声音 --name VOICE-01 \
  --text '你好，今天还好吗？' --speaker zh_female_vv_uranus_bigtts \
  --context '用温柔、克制的语气说话。' --max-chars 20 --dry-run
```

确认当前项目授权、文本、预算与音色后，用同样参数将 `--dry-run` 换为 `--execute` 才发起一次可能计费的请求。`--max-chars` 必填，按发送文本的 Python 字符数计算，含标点、空白；超限在网络请求前拒绝。它是单次文本预算，并非账户金额上限。供应商实际计费按返回 `usage.text_words` 记录，不将本地估算当作账单。

`--text-file 03-剧本/对白.txt` 可替代 `--text`；文件相对作品目录，原文包括换行完整绑定，不自动删改。`--format wav|mp3`、`--sample-rate`、`--speech-rate` 可调整；完整参数见 `--help`。`--output` 是 `--out` 的别名。名称使用安全 ID，路径必须在作品目录内，不允许父目录逃逸或符号链接跳出作品。

已有合法授权的复刻音色仅参与合成，例如：

```bash
python3 -B scripts/doubao_speech.py synthesize \
  --project projects/示例作品 --name VOICE-clone-01 --text '你好。' \
  --resource-id seed-icl-2.0 --speaker S_existing_licensed \
  --model seed-tts-2.0-standard --max-chars 10 --dry-run
```

这里的 `S_existing_licensed` 是占位符，必须换成账号内已有且授权明确的音色 ID；此命令不会创建真人克隆。

## 记录、失败与幂等

实际提交前同时检查凭证、媒体工具、记录合同与同名输出冲突，然后加同名进程锁、持久化 `<name>-任务.json`，再发一次 POST。HTTP 重定向被拒绝，不将带凭证的请求转发至其他地址。

输出目录包括：

| 文件 | 内容 |
|---|---|
| `<name>-任务.json` | 不含凭证的完整 request binding、请求 UUID、提交状态 |
| `<name>-生成记录.json` | `vsc.generation-record/v1`；输入原文、上下文、音色/资源、参数、请求与 payload 的规范化 SHA、字符预算、实际用量或“未知”说明、媒体元数据与输出 SHA |
| `<name>-响应.jsonl` | 每个已解析响应块的序号、业务码、消息、句级信息、用量、原始行 SHA、音频块字节数与 SHA；不重复保存 Base64 音频 |
| `<name>.mp3` 或 `<name>.wav` | 仅在收到完成码、非空音频、真实容器/采样率/时长/音轨检查及完整解码通过后原子发布 |

`engine.provider` 固定为 `doubao_speech`。输出保留 `voice`、`speaker`、`resource_id`，`engine.params` 也保留 `speaker` 和 `resource_id`。服务端日志 ID 与响应台账 SHA 记录在 `engine` 中。

同名请求只有输入、预算、音色、参数、目标目录和显式凭证变量选择都相同，且已有成功记录、输出及响应台账未变时，才可直接返回已有结果；返回前再次验证真实媒体，不需要读取 key。失败、HTTP 错误、断流、无完成码、无音频、坏输出或进程中断都不会自动重新提交。失败仍保留收到的用量；没有用量时明确记作可能计费且金额未知。人工处理账单与错误后，确需新请求须另用新名称。

## 人物绑定与素材库复用

可选 `--entity CHAR-01 --bible 04-视听设计/资产库.json` 会核对项目、人物及已有 `engine`/`voice`/`resource_id` 绑定，并记录资产库 SHA。脚本不自动修改人物或批准素材；输出 `entity` 可供连续性检查使用。

生成后使用现有素材库入口：

```bash
python3 -B scripts/vsc_library.py promote \
  --project projects/示例作品 \
  --record projects/示例作品/06-素材/声音/VOICE-01-生成记录.json \
  --kind voice --id VOICE-library-01 --name '角色声音候选' --summary '待人工审听的声音参考'

python3 -B scripts/vsc_library.py use VOICE-library-01 \
  --project projects/目标作品 --bible projects/目标作品/04-视听设计/资产库.json --entity CHAR-01
```

`promote` 从音频生成记录保留原始 `engine`、`voice`、`resource_id`、`model` 属性，`use` 将其复制到来源清单并可绑定人物。音色权属默认 `unknown`；平台生成成功、素材库 `generated` 状态都不等于人物声音授权或可商用确认。人工选择与授权按项目既有流程登记。

## 离线复验

```bash
python3 -B -m unittest discover -s tests -p test_doubao_speech.py -v
```

测试不会调用供应商。真实媒体用例在缺少 `ffprobe`/`ffmpeg` 时明确跳过；实际 `--execute` 则在工具缺失时拒绝提交。
