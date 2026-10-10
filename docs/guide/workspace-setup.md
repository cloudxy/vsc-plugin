# 本工作区的 AI 客户端接入

本仓库自带 AI 客户端接入层：根目录的 `AGENTS.md`、`CLAUDE.md`，以及由 `workflow/hosts.json` 声明、`scripts/vsc_hosts.py` 生成的宿主入口（见下表）。克隆后在客户端打开仓库根目录即可使用，无需另外安装。

## 开始使用

在客户端打开这个目录，并开始新会话。直接说：

> 用 VSC 把这份小说改编成竖屏短剧，先帮我确定创作委托。

已有作品可以说：

> 用 VSC 继续 projects/作品名，先读取当前进度，告诉我下一步。

无需每次粘贴整套规则。`AGENTS.md` 负责工作区路由、状态恢复和按需读取；具体创作方法仍在 `skills/`，角色规范仍在 `workflow/roles.json`。新作品通过 VSC CLI 创建在 `projects/`，所有客户端共用该作品的状态与产物。`projects/` 是本地创作数据，已被 Git 忽略，不随仓库提交。

## 客户端入口

下表由 `workflow/hosts.json` 生成：

<!-- vsc:view hosts -->
| 客户端 | 工作区说明 | 发现入口 | 调用 | 注意 |
|---|---|---|---|---|
| Codex | `AGENTS.md` | 技能 `.agents/skills/`（13 个，软链接）；角色 `.codex/agents/`（12 个，Codex TOML） | $vsc、$vsc-script |  |
| Claude Code | `CLAUDE.md` | 技能 `.claude/skills/`（13 个，软链接）；角色 `.claude/agents/`（12 个，软链接） | /vsc、/vsc-script | 个人权限设置写在 .claude/settings.local.json，已被 Git 忽略 |
| Grok Build | `AGENTS.md` | 技能 `.grok/skills/`（13 个，软链接）；角色 `.claude/agents/`（12 个，软链接） | /vsc、/vsc-script | 首次使用须在客户端信任工作区；角色经 Claude 兼容读取 .claude/agents |
| Kimi Code | `AGENTS.md` | 技能 `.agents/skills/`（13 个，软链接）；角色 `.agents/agents/`（12 个，软链接） | /skill:vsc |  |
| ZCode | `AGENTS.md` | 命令 `commands/`（13 个，插件命令） | 用 VSC…… | 工作区指令可直接驱动工作流；要出现在插件面板，须先添加本地市场 marketplace.json 并安装，见下文 |
<!-- /vsc:view -->

ZCode 的工作区规则入口可以驱动完整本地工作流，但不等于插件管理界面已经安装、启用了该目录。要让 `vsc-workflow` 出现在插件面板：在 ZCode 中进入“设置 → 插件 → 创建 → 添加插件市场”，选择本目录（其中的 `marketplace.json` 会声明本插件），然后在“个人”市场中安装并启用 `vsc-workflow`。修改插件后回到市场源面板刷新，再检查版本和组件。

宿主入口只是发现层，规范正文只在 `skills/`、`agents/` 与 `workflow/` 维护：软链接随原文件更新，Codex 角色 TOML 与 ZCode 命令由来源生成。加载技能时按 `AGENTS.md` 指引读取原始路径，避免从宿主发现目录误解析相对参考文件。新增、删除或改名技能、角色，修改角色卡的 name/description，或修改 `kernel.json` 的阶段入口后，运行 `python3 -B scripts/vsc_hosts.py sync`；未同步的入口会使 doctor 失败。新增宿主时，在 `workflow/hosts.json` 声明它读取的入口，再运行 sync。

Windows 上克隆前需开启开发者模式，并设置 `git config --global core.symlinks true`；否则入口链接会被检出为内含目标路径的普通文本文件，客户端无法发现技能。

## 验证

```bash
python3 -B scripts/vsc_kernel.py doctor
python3 -B scripts/vsc_state.py profile list
python3 -B scripts/vsc_hosts.py list
python3 -m json.tool marketplace.json >/dev/null
grok inspect
```

`doctor` 应输出 `PASS`，它同时核对每个宿主入口与来源一致；`list` 显示每个客户端能发现的说明文件、技能、角色与命令。ZCode 插件面板还需要单独完成本地市场的添加与插件安装，仓库内的 `plugin.json` 不会自动修改 ZCode 的市场或已安装插件索引。

现有会话未必重新扫描技能和项目说明；克隆或更新入口后请在本目录开始新会话。客户端若要求工作区信任，请在其界面完成。网页聊天或无法访问本机文件的云端会话不会因这些本地文件而自动接入。

## 配置依据

- [Codex 本地技能发现](https://learn.chatgpt.com/docs/build-skills) 与 [自定义子智能体](https://learn.chatgpt.com/docs/agent-configuration/subagents)
- [Claude Code 项目技能](https://code.claude.com/docs/en/skills)
- [Grok 技能](https://docs.x.ai/build/features/skills-plugins-marketplaces)、[子智能体](https://docs.x.ai/build/features/subagents) 与 [项目指令](https://docs.x.ai/build/features/project-rules)
- [Kimi Code 技能目录](https://moonshotai.github.io/kimi-code/en/customization/skills) 与 [子智能体](https://www.kimi.com/code/docs/en/kimi-code-cli/customization/agents.html)
- [ZCode Workspace 指令](https://zcode.z.ai/cn/docs/agents) 与 [插件管理](https://zcode.z.ai/cn/docs/plugin)
