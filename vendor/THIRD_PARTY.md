# VSC 第三方开源项目声明

此文件由 `vendor/sources.lock.json` 生成；不要手工维护项目列表。VSC 源码与文档采用 MIT。本项目也可在用户本机的 `vendor/` 目录直接使用下列开源项目；它们的源码、模型、依赖与资产**不随 VSC Git 仓库提交或再分发**，并继续受各自许可证约束。

| 项目 | 用途 | 上游许可证 | 安装 id |
| --- | --- | --- | --- |
| [inkos](https://github.com/Narcooo/inkos) | 本地调用其 Agent harness、工作区与记忆/Skill 组织能力，辅助 VSC 角色协作设计。 | AGPL-3.0-only | `inkos` |
| [openwrite](https://github.com/LiPu-jpg/Openwrite) | 本地调用小说创作、审阅与修订能力，为 VSC 改编与剧本化阶段提供可选组件。 | Apache-2.0 | `openwrite` |
| [jev-ultrafast](https://github.com/browser-use/jev-ultrafast) | 本地调用受约束浏览/研究代理能力，辅助公开创作资料与工具调研。 | MIT | `jev-ultrafast` |
| [learn-claude-code](https://github.com/shareAI-lab/learn-claude-code) | 本地使用 Agent harness、任务图、记忆与观察方法的实现和参考材料。 | MIT | `learn-claude-code` |
| [openmontage](https://github.com/calesthio/OpenMontage) | 本地调用镜头编排、制作管线、供应商选择与渲染质量检查能力。 | AGPL-3.0-only | `openmontage` |
| [remotion](https://github.com/remotion-dev/remotion) | 本地使用 Composition、Player、字幕、时间线和 Renderer，为 VSC 的剪辑预演与确定性成片渲染提供可选实现。 | LicenseRef-Remotion | `remotion` |
| [mattpocock-skills](https://github.com/mattpocock/skills) | 本地直接使用架构改进、代码库设计、澄清与领域建模 Skill，维护 VSC 及其业务扩展。 | MIT | `mattpocock-skills` |

来源 URL、固定 commit、许可证证据与本地调用模式见 [sources.lock.json](sources.lock.json)。用户可自行执行：

```bash
python3 scripts/vendor_sync.py --install inkos openwrite
```

这份清单是 VSC 对“借用了哪些开源项目”的公开声明，不改变上游许可证，也不构成对商业使用、再分发、模型权重、声音、图像或数据权利的额外授权。
