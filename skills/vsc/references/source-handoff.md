# VSC 外部来源与交接协议

VSC 是独立插件。它不关心小说、剧本或素材来自哪个工具，只读取用户明确提供的文件或符合本协议的交接包；导入不执行来源工具的命令，也不反写来源项目。

## `creative-handoff/v1`

交接清单是一个 JSON 文件，最小结构如下：

```json
{
  "format": "creative-handoff/v1",
  "package_id": "source-20261001-r0001",
  "source": {"title": "作品名", "owner": "责任人", "scope": "本次允许使用的文本与资料", "rights": "licensed"},
  "artifacts": [
    {"id": "src-ch-001", "type": "source.chapter", "path": "chapters/ch-0001.md", "sha256_16": "…"}
  ],
  "decisions": [
    {"id": "d-001", "kind": "adaptation_boundary", "outcome": "accepted", "by": "作者", "reason": "…"}
  ]
}
```

`source` 说明来源身份、责任人与本轮允许使用的范围；可选 `rights` 只能是 `owned`、`licensed`、`analysis_only` 或 `unknown`。`artifacts` 是只读来源材料，带版本或摘要；`decisions` 保留已作出的边界和理由。不同来源可以增加自己的命名空间字段，但不要更改这五个核心字段的含义。

## 导入规则

1. 用 `python3 scripts/vsc_state.py handoff validate <manifest>` 校验结构，再 `source import` 登记其路径与 SHA。
2. 导入只登记来源，不自动把外部内容变成 VSC 的已批准剧本、镜头或资产。VSC 的故事分析和改编角色必须先审阅并产出本项目 artifact。
3. 原文事实、人物说法、解释、改编、新增和待定应保持可区分。人物说法不自动成为世界事实。
4. 旧交接包不可覆盖。来源变化、范围变化或改编边界变化时，由来源方产生新 revision；VSC 重新导入并评估受影响的下游版本。
5. 清单只表达本地项目声明的使用范围；它不替代版权、肖像、声音、商标或第三方素材授权核验。即使清单填写了 `source.rights`，VSC 导入时仍默认标为 `unknown`；负责人必须在 `source import --rights ...` 中显式确认，才可能用于 production learning。
