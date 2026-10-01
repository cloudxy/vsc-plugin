# VSC Vendor：本地开源 Skill 与工具治理

VSC 核心保持小而可审计；第三方 Skill、工具、示例和辅助模型工具可以从公开来源下载到本地 `vendor/`，但 vendor 内容不进入 Git。仓库只跟踪来源锁定文件、安装说明、审批和 NOTICE 指引。

## 为什么这样做

- 避免把供应链和生成工具的源码复制进 VSC 的发布物；更新也不污染核心历史。
- 每个本地依赖有确定来源、完整 commit、许可证证据、用途、责任人与审核结论。
- 不同工作室可以选择不同 Skill 组合，不改变 VSC 的通用产物、Profile 和状态协议。

## 不能误解为“规避商业纠纷”

是否提交 Git 与是否拥有使用权是两件事。GitHub 指出，未带许可证的代码默认受版权法保护；公开可见不等于可自由复制、分发或衍生。[GitHub Docs](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository) SPDX 提供标准化许可证标识和许可证文本参考，适合记录与交换许可证信息，但它不是对业务用途的法律判断。[SPDX](https://spdx.dev/learn/handling-license-info/)

因此 VSC 的默认原则是：**来源不明不下载；许可证/用途未审不自动同步；需要保留声明的依赖不删除 NOTICE；模型权重、声音、图像、商标和数据集另行核验。**

## 实现

- [.gitignore](../.gitignore) 忽略 `/vendor/*`，只放行 `vendor/README.md` 与 `vendor/sources.lock.json`。
- [sources.lock.json](../vendor/sources.lock.json) 是空白、可提交的审核台账。
- [vendor_sync.py](../scripts/vendor_sync.py) 默认没有动作；`--check` 和 `--plan` 不联网，`--sync` 只接受批准、带 SPDX 与证据、固定到 40 位 commit 的 git 来源。
- [vendor README](../vendor/README.md) 给出人工安装、更新和可选本机每日同步指引；插件不自行创建 cron，也不保管凭据。

在引入第一个真实来源前，应由项目负责人填完锁定记录，并按使用场景确认许可义务。商业发布、再分发、云端服务、训练/微调、声音/人物/素材权利或 copyleft 影响不确定时，应寻求适当的专业意见。
