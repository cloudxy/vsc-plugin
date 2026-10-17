# 工程维护工具

本目录负责官方更新、Vendor、本地 CI 和 Git 提交检查的实现。对应命令统一从 `scripts/maintenance/` 调用；维护工具互相导入本包，业务规则、Provider 请求和资源审查功能放在 `src/vsc/` 对应领域及适配器中。

维护工具不作为创作阶段，也不写入作品内容。最终推送的全量门禁由 `.githooks/pre-push` 调用 `scripts/maintenance/local_ci.py`。
