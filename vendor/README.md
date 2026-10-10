# 本地 Vendor：不提交到 Git

此目录存放用户按需下载的第三方 Skill、工具和依赖。除本说明、`sources.lock.json` 和由它生成的 `THIRD_PARTY.md` 外，所有内容都被 `.gitignore` 排除，不能 `git add -f`。为什么这样做、各 `usage.mode` 的含义与许可证边界，见 [Vendor 治理](../docs/governance/vendor-governance.md)；各来源的用途、许可证与须知见 [THIRD_PARTY.md](THIRD_PARTY.md)。

## 声明与安装

1. 在 `sources.lock.json` 声明来源（字段见下）。改完运行 `python3 scripts/vendor_sync.py --write-declaration` 重新生成 `THIRD_PARTY.md`；不联网。
2. `python3 scripts/vendor_sync.py --check` 与 `--plan`：校验并预览；不联网、不下载。
3. `python3 scripts/vendor_sync.py --install <来源 id …>`：按固定 commit 安装；不写 id 时安装全部默认来源（`--sync` 为兼容别名）。
4. `python3 scripts/vendor_skills.py --scan`：为已下载的上游 `SKILL.md` 建本机目录；各阶段如何使用见 [vsc-vendor](../skills/vsc-vendor/SKILL.md#下载后直接使用-skill)。

上游有新版本时不会自动采用，候选分析与采用流程见 [Vendor 候选更新](../docs/governance/vendor-updates.md)。

## 锁定记录字段

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

- `revision` 必须是 40 位 commit；`redistribution` 固定为 `local_only`。
- `sparse_paths`：只检出列出的路径，适合大型仓库。
- `install: "explicit"`：附带字体、音乐等不在开源许可之内的资源时使用，并在 `notice` 写明权利状况；默认的 `--install` 不下载它，本地 CI 不要求安装，装了仍核对固定版本。
- `usage.mode` 为 `reference_only` 或 `ported` 时，VSC 运行时不调用该来源，本地 CI 不要求安装。
- `update`：候选更新策略，见 Vendor 候选更新。
