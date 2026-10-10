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
| [moneyprinterturbo](https://github.com/harry0703/MoneyPrinterTurbo) | 本地调用其 CLI：为已批准剧本生成预演临时配音与逐词字幕、烧录字幕；其一键成片 Skill 仅在用户显式选择时使用。附带的字体与 BGM 不在此来源中，见需显式安装的 moneyprinterturbo-assets；VSC 适配器默认使用 noto-sans-sc 字体。 | MIT | `moneyprinterturbo` |
| [moneyprinterturbo-assets](https://github.com/harry0703/MoneyPrinterTurbo) | MoneyPrinterTurbo 附带的字幕字体与背景音乐，供用户在本机评估效果；由 scripts/mpt_adapter.py 链接进 MoneyPrinterTurbo 的 resource 目录。 | NOASSERTION | `moneyprinterturbo-assets`（需显式安装） |
| [narratoai](https://github.com/linyqh/NarratoAI) | 本地调用其剪映草稿构件，由 VSC 适配器把已批准时间线写成可在剪映中继续精剪的草稿；不使用其云端版、赞助链接或自动解说流程。 | MIT | `narratoai` |
| [noto-sans-sc](https://github.com/notofonts/noto-cjk) | OFL 授权的简体中文字体，替代 MoneyPrinterTurbo 默认的华文黑体，用于字幕烧录与交付物。 | OFL-1.1 | `noto-sans-sc` |

## 需显式安装的来源

以下来源不随 `--install` 默认下载，必须写明来源 id 才会安装。是否下载、是否使用，由用户自行决定：

- `moneyprinterturbo-assets`：含微软雅黑（Microsoft）、华文黑体（华文/Apple）等商业字体，以及 29 首没有任何授权说明的背景音乐。MoneyPrinterTurbo 的 MIT 许可只覆盖其代码，不覆盖这些字体和音乐，VSC 的 MIT 也不授予它们的任何权利。用于商业作品或对外发布前，必须向各版权方取得商用授权；是否下载、是否使用，由用户自行决定。

来源 URL、固定 commit、许可证证据与本地调用模式见 [sources.lock.json](sources.lock.json)。用户可自行执行：

```bash
python3 scripts/vendor_sync.py --install inkos openwrite
```

这份清单是 VSC 对“借用了哪些开源项目”的公开声明，不改变上游许可证，也不构成对商业使用、再分发、模型权重、声音、图像或数据权利的额外授权。
