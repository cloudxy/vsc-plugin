# 本地 Vendor：第三方 Skill/工具

可选开源 Skill 和辅助工具可放在本地 `vendor/`，但下载内容不提交到 Git。仓库只提交第三方来源声明、安装说明、许可证证据和用途说明。

VSC 核心自身保持 MIT；这不妨碍直接使用 AGPL、Apache、MIT 等其他许可证的开源内容。除了只读参考、独立本地工具、独立服务和协议适配器，VSC 还支持将完整上游项目固定版本下载到本地 `vendor/`，作为 `local_component` 直接调用其原生 Skill、脚本或 CLI。根目录 MIT 只覆盖 VSC 自研部分，不替代第三方的许可证、NOTICE、网络服务、模型和素材权利义务，也不会把第三方代码伪装成 MIT。

因此，**AGPL-3.0 和 Apache-2.0 都是可接受的来源**，不是被排除的来源。当前 Vendor 模式不分发其完整源码；若未来把第三方源码复制/融合进 VSC 的可发布模块，则需保留该模块的原许可证边界与相应源码、NOTICE 义务。尤其是 AGPL 融合模块不能整体宣称为“仅 MIT”。

```bash
python3 scripts/vendor_sync.py --check  # 不联网、不下载
python3 scripts/vendor_sync.py --plan   # 不联网、不下载
python3 scripts/vendor_sync.py --write-declaration  # 由来源锁定文件生成 vendor/THIRD_PARTY.md
python3 scripts/vendor_sync.py --install inkos openwrite  # 用户按需安装指定来源
python3 scripts/vendor_sync.py --install remotion  # 安装可选的本地时间线、预览与渲染 Skill
python3 scripts/vendor_sync.py --install mattpocock-skills  # 安装公开的架构改进及其依赖 Skill
python3 scripts/vendor_sync.py --install  # 用户安装全部已声明、固定到 40 位 commit 的来源
python3 scripts/vendor_skills.py --scan  # 扫描已下载的上游 SKILL.md，写入本机目录
python3 scripts/vendor_skills.py --resolve adapt  # 查看改编阶段可直接使用的 Skill
```

不提交第三方源码只能降低再次分发的风险，**不等于获得商业使用权**。`sources.lock.json` 是机器可读的来源真相，`vendor/THIRD_PARTY.md` 是从它生成的公开声明；用户自行运行安装脚本。许可证、NOTICE、模型权重、声音、图像、数据集、商标和平台条款仍须逐项确认。详见 [第三方声明](../../vendor/THIRD_PARTY.md)、[Vendor 治理](../governance/vendor-governance.md) 与 [Vendor 安装说明](../../vendor/README.md)。

安装完成后，`vendor_skills.py` 会发现上游项目内的原始 `SKILL.md`；`/vsc-adapt`、`/vsc-script`、`/vsc-direct`、`/vsc-assets`、`/vsc-produce`、`/vsc-sound`、`/vsc-post` 分别按阶段路由并直接读取这些 Skill。方法型 Skill 可立即复用；需要 OpenWrite Bridge、ffmpeg、MCP、模型服务或 API 凭据的原生 Skill 会标记所需环境，只有环境实际就绪才执行。

## Vendor 最新性不是自动采用

VSC 候选维护改为用户按需运行脚本，`sources.lock.json` 的 `scheduler` 为 `manual`，不依赖 ZCode 定时任务、cron 或后台常驻服务：

```bash
bash scripts/vsc-vendor-maintenance.sh --plan  # 只预览，不联网、不写入
bash scripts/vsc-vendor-maintenance.sh         # 执行一次全部来源候选分析，不采用
bash scripts/vsc-vendor-maintenance.sh --source mattpocock-skills  # 只检查指定来源
```

每次执行分析 Skill、引用规则／脚本／参考文件，以及许可证和依赖声明；下载完成与分析完成分开记录，失败或报告损坏会重审。新增不自动路由；删除已引用 Skill 要明确保留、替换或退役。候选资源包在执行时按每来源 90 天、最多 3 份清理（含基线）；不运行脚本时不会后台清理，因此文件可能超过 90 天，下一次执行时才处理。它不是完整仓库、已安装运行环境或模型权重备份。

检查当次输出、报告和退出码；脚本只做结构分析，不自动调用模型。需要语义评估时手动调用 `/vsc-vendor` 阅读报告与 diff，由负责人决定是否采用，通过后才显式修改固定 revision 并安装。缓存路径、旧中央入口兼容和资源恢复说明见 [候选更新文档](../governance/vendor-updates.md)。
