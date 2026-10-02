# VSC 第三方开源项目声明

VSC 源码与文档采用 MIT。本项目也可在用户本机的 `vendor/` 目录直接使用下列开源项目；它们的源码、模型、依赖与资产**不随 VSC Git 仓库提交或再分发**，并继续受各自许可证约束。

| 项目 | 用途 | 上游许可证 | 安装 id |
|---|---|---|---|
| [InkOS](https://github.com/Narcooo/inkos) | Agent harness、工作区、记忆与 Skill 组织 | AGPL-3.0 | `inkos` |
| [OpenWrite](https://github.com/LiPu-jpg/Openwrite) | 小说创作、审阅、修订与改编 | Apache-2.0 | `openwrite` |
| [JEV Ultrafast](https://github.com/browser-use/jev-ultrafast) | 受约束浏览与公开资料研究 | MIT | `jev-ultrafast` |
| [learn-claude-code](https://github.com/shareAI-lab/learn-claude-code) | Agent harness、任务图、记忆与观察方法 | MIT | `learn-claude-code` |
| [OpenMontage](https://github.com/calesthio/OpenMontage) | 镜头编排、制作管线与渲染检查 | AGPL-3.0 | `openmontage` |
| [Remotion](https://github.com/remotion-dev/remotion) | Composition、帧级时间线、字幕、Studio 预演与确定性渲染 | 见上游许可 | `remotion` |

来源 URL、固定 commit、许可证证据与本地调用模式见 [vendor/sources.lock.json](vendor/sources.lock.json)。用户可自行执行：

```bash
python3 scripts/vendor_sync.py --install inkos openwrite
```

这份清单是 VSC 对“借用了哪些开源项目”的公开声明，不改变上游许可证，也不构成对商业使用、再分发、模型权重、声音、图像或数据权利的额外授权。
