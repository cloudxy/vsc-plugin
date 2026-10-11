# 豆包原生批量生产

`scripts/vsc_production.py` 将已有 `volc_ark.py image/video` 串行为有依赖、预算上界和中断恢复的本地队列。只支持火山方舟 Seedream、Seedance；不会接入阿里或其他供应商，不运行 JSON 中的 shell，不修改创作批准、素材选择或项目状态。批量生产只产生候选；依赖前一候选的尾帧也不等于批准该候选。

## 创建与执行

从工作区根目录运行，将 [模板](../../templates/production-batch.json) 复制到作品内，填写真实 `project_id`、锚点文件、提示词和镜头编号。模板中的路径是占位示例，不是已存在的作品资产。

```sh
python3 -B scripts/vsc_production.py validate projects/作品/production-batch.json --project projects/作品
python3 -B scripts/vsc_production.py plan projects/作品/production-batch.json --project projects/作品
```

两个命令均全量预检且只读；不创建任务、不付费、不批准任何产物。核对计划中的拓扑顺序、`usage_bound`、输入文件 SHA-256、模型和具体参数。`estimated_currency` 为 `null`：本工具没有可核实单价，不虚报金额。

运行前须安装 `ffprobe` 和 `ffmpeg`；计划入口即检查工具可用。所有已有媒体输入按内容探测实际类别并完整解码，确认存在可读帧；JSON 规格、损坏文件、图片冒充视频或视频冒充图片均拒绝。扩展名与 SHA-256 不能代替媒体验证。全部任务的输出祖先也在首次调用前检查，既有普通文件及前序计划产物都不能作为后序输出目录。

```sh
python3 -B scripts/vsc_production.py run projects/作品/production-batch.json --project projects/作品 --execute --plan-hash <plan输出的plan_sha256>
python3 -B scripts/vsc_production.py status projects/作品/production-batch.json --project projects/作品
```

`run` 不带 `--execute` 时仅输出计划。显式执行同时要求当前计划的 hash；hash 是请求绑定凭证，不是人工创作批准。平台密钥仍由原方舟适配器从环境读取，队列不保存密钥。执行前确保生成供应商已配置并具备调用授权。

## 输入与参数

每个 job 必须写 `id`、`kind`（`image` 或 `video`）、`depends_on`、`args`。ID 不重复；依赖必须存在且无环。输出的 `out` 为项目内相对目录，`name` 为安全文件名，不能重复输出位置或覆盖输入。

| 输入结构 | 意义 |
| --- | --- |
| `{"path":"05-连续性/资产库.json"}` | 项目内已有本地文件；`bible`、`state`、`prompt_file` 仅接受这种结构 |
| `{"library":"LIB-001","path":"06-素材/素材库/LIB-001/人物.png"}` | 已通过 `vsc_library.py use` 绑定的库素材；校验当前作品来源清单和文件哈希 |
| `{"job":"video-001","output":"last_frame"}` | 显式 `depends_on` 上游生成记录中的原始尾帧 |

输出名限定为图像的 `image`、视频的 `video` 和 `last_frame`。帧输入只能引用图片，`ref_video` 只能引用视频，不能猜测文件名。绝对路径、`..`、通过符号链接离开项目、任意 URL、未知字段和命令字符串一律拒绝。所有 job 先通过预检后才开始第一个远程调用；镜头视频、候选关键帧必须绑定 `bible/state/shot`，候选图还须 `moment`。

`args` 对应原方舟 CLI 的下划线字段，白名单如下：

- 通用：`out/name/prompt/prompt_file/bible/state/shot/model`；`prompt` 与 `prompt_file` 二选一。
- 图像：`ref`（结构数组）、`base_frame`、`base_use`、`purpose`、`moment`、`size`。
- 视频：`first_frame/last_frame/first_frame_ref`、`ref_image/ref_video/ref_audio`（结构数组）、`resolution/ratio/duration/no_audio/draft`。

`first_frame + last_frame` 是首尾帧模式，不能同时使用其他多模态参考；`first_frame_ref` 将输入作为图片 1，并在文本中请求视频从这一画面开始，允许与多模态参考并用。这是参考和文本请求，不能保证模型输出严格匹配首帧，仍须审片。上游未返回或未登记原始尾帧时，下游停止，队列不会自行截图代替。

库素材须由用户先运行既有的 `vsc_library.py use` 流程；队列只消费已绑定结果，不自动复制、授权、批准或修改资产库。

## 预算与恢复

`max_remote_jobs` 是批次的总生成任务上限（不是并发数）。`budget.max_images` 限总张数，`budget.max_video_seconds` 限请求视频秒数；视频 `duration` 必须为正整数，禁止不可预估的自适应时长。图像每个 job 调用原适配器生成一张。执行顺序为串行，不需要后台服务或分布式队列。

`max_attempts` 是每个 job 的总调用次数上限，包含首次调用、轮询/下载续接和失败调用；它不是允许重复创建远程任务的次数。静态任务预算为最坏情况下的全批次预留，已执行任务不会腾出额度供新增任务。实际用量、是否计费与输出仍读取方舟生成记录；队列预算只是请求规模上界，不是人民币费用或平台最终账单保证。

独立 journal 写入作品 `.vsc-production/<batch-id>.json`，方舟 `<name>-任务.json` 和 `<name>-生成记录.json` 保持原位置、原格式并作为远程恢复权威。队列在调用前记录 plan hash、具体参数与文件哈希，并加非阻塞批次锁。失败即停止，不执行其下游。

再次运行同一执行命令时，已核实成功的任务跳过；有远程任务凭证的失败任务通过原适配器续接轮询或下载，不重新生成。已成功的字节、输入文件、锚点、提示词、参数或上游产物漂移会拒绝续接。变更创作请求时须审阅新计划并使用新的 batch ID 与 job name，不能把新输入记到旧任务。

成功复核会从生成记录重建请求绑定，对照原方舟任务的 binding 与完整 `task.record`，再核对计划中的提示词、模型、镜头和参数。每个产物必须符合声明的路径、ID、角色与实际媒体类别，并通过完整解码；真实 PNG 可以保存为尾帧的 `.jpeg` 路径，因为二者都是图片，JPEG 字节写成 `.mp4` 则会拒绝。原请求绑定和产物哈希同时保存在 journal 中，之后漂移不能靠修改状态跳过。

若提交时网络断开或进程终止，平台可能已经接单而本地还没有任务凭证。这种情况无法证明失败，队列拒绝自动重提；须先人工核对平台任务和账单。原凭证损坏、旧手工命令留下同名文件或已达调用上限时也停止；不要删除凭证后直接重跑。此限制保留了防重复计费边界。

## 离线验证

```sh
python3 -B tests/test_vsc_production.py
```

19 项离线测试使用真实方舟参数解析、记录流程以及 `ffmpeg` 生成的 PNG、JPEG、MP4、WAV，替换网络与下载，不产生付费调用。覆盖首尾帧依赖、多模态参考的图片 1 文本请求、下载恢复、结果已落盘而 journal 回写失败、未知提交状态、参数/输入/输出漂移、预算与调用次数、循环与路径逃逸、库素材来源清单、批次锁、记录与任务篡改、错误媒体和全部输出目录祖先预检。
