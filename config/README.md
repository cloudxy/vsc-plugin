# 项目配置

项目配置值与配置示例统一归此目录；加载代码由 `src/vsc/configuration.py` 负责。

| 路径 | 用途 | 是否提交／打包 |
| --- | --- | --- |
| `default/settings.toml` | 公共默认值 | 是 |
| `.env.example` | 本机配置模板 | 是 |
| `.env` | 本机数据库连接等初始化配置 | 否 |
| `mcp/connections/` | 本机 MCP 已启用的数据库连接和工具定义 | 否 |
| `mcp/examples/` | 尚未启用的本机数据库示例 | 否 |

首次使用，将 `config/.env.example` 复制为 `config/.env`，填写已确定的应用读写连接。Dynaconf 自动读取，无需设置 shell 变量。根目录不再读取或保留另一份 `.env`；修改后重启对应工具。

MCP 正式库使用独立只读账号，应用账号保留增删改查与显式结构迁移权限。MCP 启动器和运行数据继续放在 `.vsc-local/database-mcp/`，不与配置混放。安装与连接操作见[工作区接入](../docs/guide/workspace-setup.md)。

面板默认只读。需要日常编辑时，在同一`config/.env`填写实际操作人的`VSC_PANEL_HUMAN_IDENTITY`并设置`VSC_PANEL_WRITABLE=true`，使用`vsc-panel --open`打开：启动器提供120秒内有效、仅可兑换一次的本机引导，页面换取HttpOnly会话后立即清除引导信息。已有会话直接恢复，无需每次复制终端凭据。显式`--human`仍可指定本次操作人；项目本身只读时登录也不会解除。后台消费者随可写应用启动，只消费原有授权与固定输入，不修改数据库连接或MCP权限。
