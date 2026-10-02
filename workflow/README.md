# VSC 工作流内核

`workflow/` 是 VSC 的**单一事实来源**：它描述而不执行短剧／短视频流程。宿主入口、角色提示和 Python 脚本都必须从这里取得共享事实，而不能各自维护一份阶段、角色或 JSON 契约列表。

| 文件 | 负责的事实 | 不负责什么 |
| --- | --- | --- |
| `kernel.json` | 入口阶段、命令、Skill、角色、Profile 覆盖和可选 Vendor 路由 | 具体生成供应商、项目运行状态 |
| `roles.json` | 角色身份、人格、权限、记忆范围与交付物 | 每个项目中的人员任命或批准决定 |
| `contracts.json` | 跨模块 JSON 格式、模板和校验器接口 | 校验器的字段实现细节 |

## 稳定接口

```bash
# 核对所有入口、角色、Profile、模板和校验器是否真的存在且相互对应
python3 scripts/vsc_kernel.py doctor

# 让总编排器或工具按名称获取一个阶段的真实路由
python3 scripts/vsc_kernel.py route adapt

# 通过统一接口校验跨阶段产物；底层实现可替换
python3 scripts/vsc_kernel.py contract validate vsc.continuity-plan/v1 ./连续性计划.json
```

## 如何扩展

先新增一个角色卡或契约，再在 `kernel.json` 中建立阶段引用；随后创建命令、Skill、Agent 文件和测试。最后运行 `doctor`。不要只在 README、Skill 或某个 Python 字典中添加能力名称——那会制造无法验证的“说了但没有”。

业务团队可以复制 `profiles/` 来改变阶段顺序和 Gate；Profile 中的阶段必须由内核中至少一个入口覆盖，才能获得明确的责任与路由。
