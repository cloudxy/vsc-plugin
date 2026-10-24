# VSC Vendor：本地开源 Skill 与工具治理

VSC 核心保持 MIT、小而可审计；第三方 Skill、工具、示例和辅助模型工具可以从公开来源下载到本地 `vendor/`，但 vendor 内容不进入 Git。仓库只跟踪来源锁定文件、安装说明和第三方声明。**MIT 不是来源的准入条件：MIT、Apache-2.0、AGPL-3.0 及其他已声明许可证的项目都可以被 VSC 实际使用。**

## 为什么这样做

- 避免把供应链和生成工具的源码复制进 VSC 的发布物；更新也不污染核心历史。
- 每个本地依赖有确定来源、完整 commit、许可证证据、用途与责任人，供用户知道 VSC 借用了什么。
- 不同工作室可以直接使用不同许可证的独立工具或完整本地组件，不改变 VSC 的通用产物、Profile 和状态协议。

## MIT 是核心许可，不是工具禁令

VSC 自身保持 MIT；它不要求所有外部工具也必须是 MIT。每个来源必须登记一种使用模式：

| 模式 | VSC 与来源的关系 | 允许的边界 |
|---|---|---|
| `reference_only` | 只阅读方法、文档或公开接口 | 不复制代码/Skill 正文进 VSC |
| `ported` | 部分代码已移植进 VSC，本地目录只供对照 | 移植文件的文件头保留上游许可证声明；VSC 运行时不调用该来源 |
| `external_tool` | 用户本机独立运行的 CLI/桌面应用 | VSC 通过文件或命令交接，不内嵌代码 |
| `local_component` | 完整上游项目被固定版本下载至 `vendor/` 并由 VSC 直接调用 | 可以直接使用其原生 Skill、脚本、模型辅助代码和 CLI；源码仍留在本地，保留上游许可证 |
| `external_service` | 单独部署的服务 | 通过明确 HTTP/文件协议接入，并审查网络、数据和 copyleft 义务 |
| `adapter_protocol` | VSC 的薄适配器调用公开 CLI/HTTP/文件接口 | 适配器不复制上游实现，不将上游代码纳入 VSC 发布物 |

这使已有的 AGPL、Apache、MIT 等开源成品可以被**直接使用**，而不是只能阅读或绕开；每项仍按其自身许可证、NOTICE、修改情况和部署方式执行。尤其是修改后的 AGPL 程序若作为网络服务提供给用户，可能涉及向网络用户提供相应源码的义务。[GNU AGPL FAQ](https://www.gnu.org/licenses/gpl-faq.en.html) Apache-2.0 允许再分发和衍生，但要求保留许可证、修改声明及适用 NOTICE；这些义务不会因 VSC 使用 MIT 而消失。[Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0)

根目录的 `LICENSE` 中的 MIT 仅授予 VSC 自研代码和文档的许可，**绝不把 `vendor/<source>` 中的第三方代码改写成 MIT**。当前本地 Vendor 模式不再分发这些完整上游项目，因而可以同时保有 MIT 核心和 AGPL/Apache 本地组件。若未来将上游源码复制到可发布的 VSC 模块、合并成衍生模块或随发行包分发，应为该模块保留原许可证、NOTICE 与源码义务；涉及 AGPL 的融合模块不能整体声称为“仅 MIT”。这是发布结构的调整，不是对本地使用的限制。

## 不能误解为“规避商业纠纷”

是否提交 Git 与是否拥有使用权是两件事。GitHub 指出，未带许可证的代码默认受版权法保护；公开可见不等于可自由复制、分发或衍生。[GitHub Docs](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository) SPDX 提供标准化许可证标识和许可证文本参考，适合记录与交换许可证信息，但它不是对业务用途的法律判断。[SPDX](https://spdx.dev/learn/handling-license-info/)

因此 VSC 的默认原则是：**来源不明不下载；许可证/用途未审不自动同步；需要保留声明的依赖不删除 NOTICE；模型权重、声音、图像、商标和数据集另行核验。**

## 实现

| 文件 | 作用 |
|---|---|
| [sources.lock.json](../../vendor/sources.lock.json) | 机器可读的来源声明（不是许可证批准书） |
| [THIRD_PARTY.md](../../vendor/THIRD_PARTY.md) | 由锁定文件生成的公开声明 |
| [vendor/README.md](../../vendor/README.md) | 声明、安装与锁定字段的操作说明 |
| [scripts/maintenance/vendor_sync.py](../../scripts/maintenance/vendor_sync.py) / [scripts/maintenance/vendor_skills.py](../../scripts/maintenance/vendor_skills.py) | 固定版本安装 / 按阶段路由上游 Skill |
| [Vendor 候选更新](vendor-updates.md) | 下载候选 → 分析 → 显式采用的流程 |

安装是用户的本机动作，不由 VSC 自动触发。锁定记录是“本项目借用了什么”的公开声明，不替用户作商业发布、再分发、云端服务、训练/微调、声音/人物/素材权利或 copyleft 的法律判断；这些情形有疑问时应寻求适当的专业意见。

<a id="candidate-assessments"></a>
## 候选来源的固定评估（2026-10-24）

以下记录只读获取的实际候选，不是已安装、已路由或可用执行器清单。原推荐只留下名称，无法据此证明同名仓库就是当时输入；本次明确选择并评估下列版本，歧义与拒绝理由保留。未修改来源锁、安装这些候选或执行其代码；本VSC原创教材不会倒写成此前已读这些来源。

| 候选与完整固定提交 | 实际读取／许可证据 | 本轮结论与不采用部分 |
| --- | --- | --- |
| caption-studio候选：[FrameCoreWorks工作流套件](https://github.com/FrameCoreWorks/framecore-works-codex-chatgpt-workflow-kit/tree/55c8bf19962c7bf7fb43648637ee433d990eb2a9/.agents/skills/caption-studio)，`55c8bf19962c7bf7fb43648637ee433d990eb2a9` | 该Skill、caption-task-pack模板及根[LICENSE](https://github.com/FrameCoreWorks/framecore-works-codex-chatgpt-workflow-kit/blob/55c8bf19962c7bf7fb43648637ee433d990eb2a9/LICENSE)／[NOTICE](https://github.com/FrameCoreWorks/framecore-works-codex-chatgpt-workflow-kit/blob/55c8bf19962c7bf7fb43648637ee433d990eb2a9/NOTICE)全文；Apache-2.0 | 只作字幕事实归属对照，不安装整套编排、复制正文或引入其Copy Gate。与同名应用、分发站条目不混为来源；未恢复原推荐材料的身份 |
| [linyqh/speclip-skills](https://github.com/linyqh/speclip-skills/tree/cb51e23c69254930858e489c4bcaae5bb10f54b3)，`cb51e23c69254930858e489c4bcaae5bb10f54b3` | 横／竖屏字幕Skill全文，README边界段及索引前段；该未截断树未发现LICENSE／COPYING／NOTICE，已读段也未给出明确许可 | 许可未定，拒绝安装／移植／复制；“开源”与README示意树中的LICENSE.txt不能替代实际文件。其固定ASS数值不成为VSC通用默认；完整Speclip产品亦不由该仓库自动提供 |
| [audio-score-design](https://github.com/2799662352/ai-image-master/tree/139c21ae0aa65a00c36900486381702100fb3cd3/.cursor/skills/audio-score-design)，`139c21ae0aa65a00c36900486381702100fb3cd3` | SKILL全文、emotion-tension-map前70行、根[LICENSE](https://github.com/2799662352/ai-image-master/blob/139c21ae0aa65a00c36900486381702100fb3cd3/LICENSE)全文；MIT。范围由声音责任人移交并复核固定文件摘要 | 可参考声层分列与可删阶段的思路，VSC实现和练习独立表述。拒绝张力机械换算音量／呼吸、名家／名曲模仿和绕审核词；未全读作曲家库，也未验证其影视事实或声音效果 |
| [storyboard-character-acting候选](https://github.com/2799662352/ai-image-master/blob/139c21ae0aa65a00c36900486381702100fb3cd3/resources/codex-skills/storyboard-character-acting/SKILL.md)，`139c21ae0aa65a00c36900486381702100fb3cd3` | 该文件全文及同仓根MIT许可；它自述来自外部教程，该教程访问转至登录页，本轮未取得全文／许可 | 仅对照“标签转可观察动作”的问题，不复制例文或声称科学情绪映射。同作者另一个[catimation-plugins](https://github.com/2799662352/catimation-plugins/tree/499c7f55ab1965a1ea876288bace178b58bfc26c)，`499c7f55ab1965a1ea876288bace178b58bfc26c`，树未发现许可，不替其推定MIT、不安装其自动注入钩子 |
| [Emily2040/seedance-2.0主源](https://github.com/Emily2040/seedance-2.0/tree/4668457e560eee06e95d7fcfdf441c8c0bba802e)，`4668457e560eee06e95d7fcfdf441c8c0bba802e` | 根MIT LICENSE全文；根Skill入口／约束优先级片段，README证据状态，EVIDENCE_NOTES首30行，first-last-frame指南及一个golden示例全文 | 可作有限只读方法／评测设计对照，不安装完整OS或继承其门。该版README明确实片评分及独立语言审阅仍待完成；不能把教学例、静态lint或上游自评写成VSC模型效果。不是同名fork，也未全读多语言／全部样例 |

这里只审了上述文件和树元数据，未审各仓库全部依赖、安装器、模型权重、附带素材或所有第三方出处。[video-shotcraft](https://github.com/Vincentwei1021/video-shotcraft/tree/43bd349a136651865ecfa6ea1cf012f6e957d304)固定`43bd349a136651865ecfa6ea1cf012f6e957d304`：实际读取根Apache-2.0 LICENSE、README、card-flip-reveal、spotlight-sweep-moves、blur-slide及final-review正文；只对照“意图、运动参数、已知失败与逐帧证据”的方法组织。未读取demo源码／参考样片或执行／安装，不复制其代码、风格或素材，也不将其产品宣传片时值当漫剧硬门。VSC叠层插值沿本地原合成器自主实现。许可可核与完整组件可直接采用是两项结论；需要实际安装时按原显式安装、scan、resolve和用途声明处理，保留对应许可／NOTICE，不由本表授权额外运行。字幕对象复用决定与供应商能力评估见[生成适配器边界](../architecture/generation-adapters.md#subtitle-authority)。

<a id="distribution-boundary"></a>
## 分发入口的边界

`vendor_sync`只接固定40位提交的Git来源。Git传输支持HTTPS、SSH、scp-style和可识别的本地测试仓库；协议形状与type声明分别核对，ClawHub／未知URI、ext或其他remote helper、控制字符和选项注入不能靠改成type=git通过。验证先于任何Git调用和目标目录写入；接受声明只证明形状，不证明远端存在、许可或运行安全。

`provider_sync`另有明确登记的官方npm包校验路线，不能据此泛称任意npm／Skill站点均支持。当前未登记的分发格式保持不可用，不把其页面或包地址伪装成Git URL。新增格式仍走原维护任务，不新增审批服务或绕过用户已授权的采用流程。
