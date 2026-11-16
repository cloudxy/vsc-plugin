# 工程维护工具

本目录负责官方更新、Vendor、本地 CI 和 Git 提交检查的实现。对应命令统一从 `scripts/maintenance/` 调用；维护工具互相导入本包，业务规则、Provider 请求和资源审查功能放在 `src/vsc/` 对应领域及适配器中。

维护工具不作为创作阶段，也不写入作品内容。最终推送的全量门禁由 `.githooks/pre-push` 调用 `scripts/maintenance/local_ci.py`。

创作精选的画布媒体使用 `python -m tools.maintenance.featured_showcase --root <资源目录> --work <作品ID> --budget-gib <媒体上限>` 建立依赖清单。默认只盘点本地快照；显式加 `--sync` 才联网恢复，完整文件和可验证分块会复用，缺失、失败及容量受限分别记录。应用继续只读取本地媒体。
