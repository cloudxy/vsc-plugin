# 本地 Vendor 缓存：不提交到 Git

此目录可存放用户按需下载的开源 Skill、工具和其依赖。除本说明、`sources.lock.json` 和由其生成的 `THIRD_PARTY.md` 外，所有内容均被 `.gitignore` 排除，不能 `git add -f`。

VSC 核心采用 MIT，**但这不禁止直接使用其他许可证的开源项目**。MIT、Apache-2.0、AGPL-3.0 等项目都可进入本目录并由 VSC 使用。关键在于把使用方式登记清楚：`reference_only`（只学习方法）、`external_tool`（本机独立 CLI/应用）、`local_component`（完整项目下载到本目录后直接调用其原生能力）、`external_service`（独立部署的服务）或 `adapter_protocol`（仅通过文件/CLI/HTTP 交接）。

完整上游项目仍保留自己的 `LICENSE`、NOTICE 和修改记录；根目录的 MIT 只覆盖 VSC 自研部分。`vendor/` 默认不随 VSC Git 仓库发布，因此可以直接使用这些组件而不把它们伪装成 MIT。若将来要把第三方源码复制、融合或随发行包再分发，必须为该组件保留相应许可证边界和履约材料；AGPL 融合模块不能被标为“仅 MIT”。

这能避免把第三方源码再次分发到 VSC 仓库，但**不等于自动获得商业使用、修改、分发、模型权重或素材使用的权利**。`sources.lock.json` 是机器可读的来源真相；`THIRD_PARTY.md` 从它生成，供人阅读。安装脚本不代替许可证本身，也不替用户作法律判断。

## 安装流程

1. 查看 `sources.lock.json` 中项目声明：仓库 URL、40 位 commit、许可证 SPDX 标识、许可证证据、用途、责任人与 `usage.mode`。
2. 修改已审核锁定记录后，运行 `python3 scripts/vendor_sync.py --write-declaration` 更新提交到 Git 的 `THIRD_PARTY.md`；这不联网、不下载。
3. 运行 `python3 scripts/vendor_sync.py --check` 与 `--plan`；它们不下载内容。
4. 按自己需要安装一个或多个来源：`python3 scripts/vendor_sync.py --install inkos openwrite`。
5. 不指定来源即安装声明中的全部：`python3 scripts/vendor_sync.py --install`；`--sync` 是兼容别名。
6. 运行 `python3 scripts/vendor_skills.py --scan`，将已经下载的原始 `SKILL.md` 建成本机目录；用 `--resolve adapt|script|direct|assets|produce|sound|post` 查看 VSC 在某阶段会直接使用哪些 Skill。
7. 用户决定是否更新或修改本地组件；需要保留 NOTICE 的交付物应按上游许可证处理。

## 本机候选维护（可选）

`vendor_sync.py --sync` 只同步已经固定的 commit，不负责发现最新 Skill。发现新能力请显式执行项目自己的候选入口，或由用户在 ZCode 中配置每日任务：

```bash
bash scripts/vsc-vendor-maintenance.sh --source mattpocock-skills
# 已使用 ZCode 更新中心时，可以继续把缓存与快照放在更新中心：
bash scripts/vsc-vendor-maintenance.sh --updater-root /absolute/path/to/plugin-updater
```

不要把密钥、Cookie 或付费供应商凭据放入此任务。项目不自动创建定时任务。候选入口只在显式执行时联网，下载上游 HEAD 和固定基线到独立缓存，绝不执行候选脚本、修改活跃 Vendor、锁定 revision 或路由。无 `--updater-root` 时，维护数据放在被忽略的 `vendor/.maintenance/`。

安装脚本仍只接受固定 commit；网络或校验失败不会改写已有固定版本。只有用户执行 `--install` 或 `--sync` 才安装活跃版本。

`vendor_skills.py` 不联网、不复制上游文件。它直接指向下载目录里的原始 `SKILL.md`：标为 `guide` 的 Skill 可立即按其方法使用；标为 `runtime: ...` 的 Skill 则需要先满足所列 CLI、MCP、依赖或凭据。

大型仓库可以在来源声明中写 `sparse_paths`。安装器会固定同一 commit、只检出这些路径，适合先直接复用上游 Skill 而不下载不相关的源码和构建产物；需要完整源码时，用户可自行完整克隆到另一目录。

## 使用方式示例

```json
{
  "id": "external-video-runner",
  "type": "git",
  "url": "https://host.example/org/runner.git",
  "revision": "40位完整commit",
  "license_spdx": "AGPL-3.0-only",
  "license_evidence": "https://host.example/org/runner/blob/<commit>/LICENSE",
  "purpose": "完整本地视频生产组件；VSC 直接调用其原生 CLI，并读取交接文件",
  "owner": "制作负责人",
  "redistribution": "local_only",
  "usage": {
    "mode": "local_component",
    "interface": "cli",
    "modified": false
  }
}
```

如果把同一项目修改后作为对外网络服务，`mode` 改为 `external_service`，并按上游许可证处理相应的源码、NOTICE 或其他义务；Vendor 清单本身不会给出豁免。

## 说明

SPDX 标识用于机器可读地记录已核验的许可证，不是法律意见。GitHub 也明确指出，未声明许可证的代码默认受版权法保护；如有商业化、再分发、SaaS、模型权重、声音或素材权利问题，应由具资格的专业人士判断。[GitHub 许可证说明](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository) · [SPDX 许可证信息](https://spdx.dev/learn/handling-license-info/)

## 每日候选更新

ZCode 更新中心可薄调用项目维护入口，按 `sources.lock.json` 的 schema 4 策略每天下载上游 HEAD 的候选资源包，保留每来源最多 3 份、最长 90 天（比较基线也计入数量）。资源包包含 Skill 目录、递归显式本地引用、根许可证与依赖声明，并保存逐文件散列和执行权限以供完整性验证和恢复；它不是整个仓库、安装好的运行环境或模型权重备份。

它只把 JSON 和 Markdown 分析写到被忽略的 `vendor/.reviews/`。下载完成与分析完成分别保存状态；分析失败或报告丢失后，再次运行会重试，不能因为“已有候选”而跳过分析。旧的仅 `SKILL.md` 快照会重建为 v2，不能冒充完整备份。

Markdown 代码围栏中的示例和站点根相对 URL（如 `/docs/...`、`/v1/...`）不当作本机资源依赖。运行时配置、输出目录只记录外部前置条件，不读取、不打包、不声称已就绪。正文相对资源缺失、本机绝对输入、符号链接或单文件超限会逐 Skill 标记不可用；被拒绝的资源仅保留元信息，候选不能冒充该 Skill 的完整备份。其他可用 Skill 仍可形成分析；整体文件数／字节数超限则任务失败。

当 Skill 的正文、规则、脚本、参考、资产、许可证或依赖声明新增、修改或删除时，先阅读报告并作出明确决定；新增 Skill 默认不路由，已路由 Skill 被删除时保留当前活跃版本，显式决定保留/替换/退役。通过后再更新锁定 revision 并运行 `vendor_sync.py --install <source>`。详细流程及旧中央入口迁移见 [Vendor 候选更新](../docs/12-vendor-candidate-updates.md)。
