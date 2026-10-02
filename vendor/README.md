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

## 本机每日同步（可选）

不要把密钥、Cookie 或付费供应商凭据放入此任务。用户若自己需要每日更新，可在本机 crontab 中加入：

```cron
15 3 * * * cd /absolute/path/to/vsc-workflow && /usr/bin/python3 scripts/vendor_sync.py --sync >> vendor/sync.log 2>&1
```

安装脚本只接受固定 commit，拒绝分支、tag 和无许可证声明来源；网络或校验失败不会改写已有已固定版本。它只在用户执行 `--install` 或 `--sync` 时联网；`vendor/sync.log` 同样不应提交。

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
