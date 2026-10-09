# 本工作区的 AI 客户端接入

本仓库自带 AI 客户端接入层：根目录的 `AGENTS.md`、`CLAUDE.md`，以及 `.agents/`、`.claude/`、`.grok/` 下指向 `skills/` 与 `agents/` 的软链接。克隆后在客户端打开仓库根目录即可使用，无需另外安装。

## 开始使用

在客户端打开这个目录，并开始新会话。直接说：

> 用 VSC 把这份小说改编成竖屏短剧，先帮我确定创作委托。

已有作品可以说：

> 用 VSC 继续 projects/作品名，先读取当前进度，告诉我下一步。

无需每次粘贴整套规则。`AGENTS.md` 负责工作区路由、状态恢复和按需读取；具体创作方法仍在 `skills/`，角色规范仍在 `workflow/roles.json`。新作品通过 VSC CLI 创建在 `projects/`，所有客户端共用该作品的状态与产物。`projects/` 是本地创作数据，已被 Git 忽略，不随仓库提交。

## 客户端入口

| 客户端 | 工作区配置 | 使用方式 | 注意事项 |
|---|---|---|---|
| Codex | `AGENTS.md`、`.agents/skills/` 下的技能链接 | 自然语言或 `$vsc`、`$vsc-script` 等 | 无需额外配置 |
| Claude Code | `CLAUDE.md` 导入 `AGENTS.md`；`.claude/skills/`、`.claude/agents/` | 自然语言或 `/vsc`、`/vsc-script` 等 | 个人权限设置写在 `.claude/settings.local.json`，已被 Git 忽略 |
| Grok Build | `AGENTS.md`、`.grok/skills/` | 自然语言或 `/vsc`、`/vsc-script` 等 | 首次打开需在客户端接受工作区信任，之后再用 `grok inspect` 检查技能列表 |
| Kimi Code | `.agents/skills/`，工作区说明见 `AGENTS.md` | 自然语言或 `/skill:vsc` | 与 Codex 共用 `.agents/skills/` |
| ZCode | Workspace 根目录 `AGENTS.md`；`.zcode-plugin/plugin.json` | 直接说“用 VSC……”；Agent 按入口读取技能、内核与角色 | 工作区指令入口不等于插件菜单命令，见下文 |

ZCode 的工作区规则入口可以驱动完整本地工作流，但不等于在插件管理界面安装、启用了该目录。需要插件菜单形式时，在 ZCode 中将本目录作为本地插件导入并核验其内容。

软链接保留唯一规范来源，更新 `skills/` 或 `agents/` 后入口随之更新。加载技能时按 `AGENTS.md` 指引读取原始路径，避免从宿主发现目录误解析相对参考文件。新增或删除技能、角色时，需同步增删各入口目录中的链接并重新检查。

Windows 上克隆前需开启开发者模式，并设置 `git config --global core.symlinks true`；否则入口链接会被检出为内含目标路径的普通文本文件，客户端无法发现技能。

## 验证

```bash
python3 -B scripts/vsc_kernel.py doctor
python3 -B scripts/vsc_state.py profile list
find .agents .claude .grok -type l ! -exec test -e {} \; -print
grok inspect
```

`doctor` 应输出 `PASS`；`find` 无输出表示所有入口链接都指向存在的原始文件。

现有会话未必重新扫描技能和项目说明；克隆或更新入口后请在本目录开始新会话。客户端若要求工作区信任，请在其界面完成。网页聊天或无法访问本机文件的云端会话不会因这些本地文件而自动接入。

## 配置依据

- [Codex 本地技能发现](https://learn.chatgpt.com/docs/build-skills)
- [Claude Code 项目技能](https://code.claude.com/docs/en/skills)
- [Grok 技能](https://docs.x.ai/build/features/skills-plugins-marketplaces) 与 [项目指令](https://docs.x.ai/build/features/project-rules)
- [Kimi Code 技能目录](https://moonshotai.github.io/kimi-code/en/customization/skills)
- [ZCode Workspace 指令](https://zcode.z.ai/cn/docs/agents) 与 [插件管理](https://zcode.z.ai/cn/docs/plugin)
