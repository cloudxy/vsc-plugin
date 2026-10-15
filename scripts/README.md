# 兼容命令入口

本目录保留已发布的 CLI 路径，Python 文件转发到 `src/vsc/` 的领域模块；工程维护实现位于 `tools/maintenance/`。新增业务功能不在本目录堆积实现。

模块对应关系见 [module-map.json](../src/vsc/module-map.json)，职责、依赖安装与受影响测试方法见 [代码结构指南](../docs/guide/code-structure.md)。
