# VSC 工作流改造实施记录

- 日期：2026-10-12；版本：v0.12.0。
- 依据：[深度审查方案](2026-10-11-vsc-workflow-review.md)，按用户“根据方案，实施改造”执行。
- 范围：工作流代码、固定 Profile、契约、模板、技能与文档。既有作品未自动迁移，未替用户批准作品，也未发起新增云端付费生成。
- 规范：[制作交接与正式运行](../../workflow/production-v2.md)；操作：[v2 指南](../guide/production-v2.md)；结构决定：[ADR 0003](../adr/0003-production-handoffs-and-approved-runs.md)。

## 工作包与证据

| 工作包／问题 | 已实施 | 回归证据 |
|---|---|---|
| W1 · F04/F05/F13 | 完整解码、音频区间覆盖、固定响度目标复检；结构化完整审片；剪映24/25/30与尾黑场；严格SRT；三端共用样式和字体证据 | test_media_qa、test_jianying_export、test_subtitles、test_subtitle_burn、test_remotion_plan |
| W2 · F01/F02/F03/F05 | 来源快照／可解析定位／新增决定；最低故事与剧本结构；逐场覆盖；获选媒体→时间线→混音→QA→审片→交付版本链 | test_vsc_v2_state、test_vsc_handoffs、test_vsc_workflow_v2 |
| W3 · F06/F07/F08 | 明确选择和桥接策略；资产稳定身份重绑及历史；变体过滤；类型化多模态引用；表演状态 | test_consistency、test_volc_ark、test_vsc_v2_state |
| W4 · F09/F11 | 固定批准run与资产准备／镜头制作Gate；人审暂停；draft导入；共享原生单位原子预算与分集／镜头汇总；有界轮询和原任务恢复 | test_vsc_run、test_vsc_budget、test_vsc_production、test_volc_ark、预算复核回归 |
| W5 · F12 | 独立声音锚点；对白行ID／人物／表演／口型用途／实测时长与Cue、获选声音核对；实际J/L cut检查 | test_consistency、test_vsc_performance、test_vsc_handoffs、语音复核回归 |
| W6 · F10/F15 | scoped status/next/gate；显式Profile迁移预览、SHA、revision冲突、备份与历史；只读返工消费者报告 | test_vsc_v2_state、test_vsc_workflow_v2 |
| W7 · F14/F16 | 轻量单条Profile与结尾功能；固定ID:SHA包审阅；相对媒体、依赖产物、工程文件／锁文件归档；移动后重新QA；来源不自动复制 | test_vsc_v2_state、test_vsc_delivery、test_vsc_workflow_v2 |

真实默认 Profile 的隔离 CLI 场景包含两场剧本、逐场镜头／声音／覆盖、可播放预演、手工导入获选 take、时间线、混音、实际 FFmpeg QA、完整结构化审片和交付清单。另覆盖三集 scope 独立推进；交付包移走原目录后重新检查真实媒体。正式run的恢复测试使用合成媒体和供应商请求替身，保存真实任务／请求绑定，不访问平台；上游故事内容验证由独立完整链测试覆盖。

负例包括一场冒充整集、错误来源定位、未获批新增、错误／未选 take、SHA漂移、未知权属、损坏预演／成片、短音轨、越界审片／字幕、错误声音桥、多候选顺序、错误参考变体、额外未批准生成参数、预算并发超额、未知提交重发、旧候选审阅放行新输出、过期迁移预览和包内越界路径。修复过程中另外消除了重复递归校验的成倍开销：缓存仅限单次操作，不持久保存。

## 验收边界

工程回归验证协议和故障阻断，不证明叙事、表演或审美已经合格。以下仍是下一次真实制作的验收工作，不计入本次软件测试的通过项：

- 凭证权限有效后的真实云端TTS、声音生成与音色稳定；本次未复用密钥发付费请求。
- 演员表演、人物情绪、口型同步与观众对故事的理解；需要具名观看／审听决定。
- 真正的 Remotion 依赖安装、类型检查与浏览器渲染，以及剪映界面的样式／黑场回看。脚手架中未执行步骤明确标记 not_run。
- 未授权归档的私有原文无法在迁移包内重验；包明确标为 not_checked，授权后列入清单再重验。
- 历史方舟任务缺少语义请求凭据时仍严格匹配原请求，不猜测丢失的媒体角色；新任务才具备URL编码变化的语义恢复证据。

旧作品继续按原固定规则读取。采用新规则须人工查看迁移预览；迁移保留历史批准，但旧文本壳和失效依赖不会自动成为新规则下的合格交付。
