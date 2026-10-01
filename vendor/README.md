# 本地 Vendor 缓存：不提交到 Git

此目录可存放经审核后下载的开源 Skill、工具和其依赖。除本说明和 `sources.lock.json` 外，所有内容均被 `.gitignore` 排除，不能 `git add -f`。

这能避免把第三方源码再次分发到 VSC 仓库，但**不等于自动获得商业使用、修改、分发、模型权重或素材使用的权利**。每个来源必须在下载前完成许可与用途审核；许可证不明、仅研究用途、非商业、限制竞争、限制模型训练或要求额外署名/NOTICE 的项目，均不得自动同步。

## 安装流程

1. 在 `sources.lock.json` 新增候选来源：仓库 URL、40 位 commit、许可证 SPDX 标识、许可证证据、使用用途、责任人和审批结论。
2. 由项目责任人和需要时的法务/版权负责人确认该用途可行；将 `review.status` 设为 `approved`。
3. 先运行 `python3 scripts/vendor_sync.py --check` 与 `--plan`；它们不下载内容。
4. 人工运行 `python3 scripts/vendor_sync.py --sync`，或在已批准的本机计划任务中运行同一命令。
5. 每次更新 revision、许可证或用途时重新审核；使用需要保留 NOTICE 的依赖时，按其许可证生成交付物 NOTICE。

## 本机每日同步（可选）

不要把密钥、Cookie 或付费供应商凭据放入此任务。管理员确认后，可在本机 crontab 中加入：

```cron
15 3 * * * cd /absolute/path/to/vsc-workflow && /usr/bin/python3 scripts/vendor_sync.py --sync >> vendor/sync.log 2>&1
```

同步前脚本只接受固定 commit，拒绝分支、tag 和无许可证/无审批来源；网络或校验失败不会改写已有已固定版本。`vendor/sync.log` 同样不应提交。

## 说明

SPDX 标识用于机器可读地记录已核验的许可证，不是法律意见。GitHub 也明确指出，未声明许可证的代码默认受版权法保护；如有商业化、再分发、SaaS、模型权重、声音或素材权利问题，应由具资格的专业人士判断。[GitHub 许可证说明](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository) · [SPDX 许可证信息](https://spdx.dev/learn/handling-license-info/)
