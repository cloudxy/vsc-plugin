# 制作交接 v2 操作

规则见 [内核制作协议](../../workflow/production-v2.md)。先使用 `status`、`next`、`gate`；连续剧可加 `--scope EP-ID` 独立推进。新作品默认使用 v2 固定 Profile，单条轻量任务可选 `vsc.light-short`。

```bash
python3 -B scripts/project/state.py init PROJECT --title TITLE --profile vsc.light-short --owner OWNER
python3 -B scripts/project/state.py status PROJECT --scope EP-ID
python3 -B scripts/project/state.py next PROJECT --scope EP-ID
python3 -B scripts/project/state.py gate check PROJECT design --scope EP-ID
```

大写占位必须替换；这些命令示例不代表已经获得作品批准或付费授权。

来源先 `source add`；从输出的 S-ID 和作品状态读取快照 SHA，填写 [来源模板](../../templates/source-map.json)与[改编模板](../../templates/adaptation-map.json)。定位用 `{"kind":"lines","start":1,"end":3}` 或 `{"kind":"json_pointer","pointer":"/chapters/0"}`。改编、剧本、镜头与声音按对象树登记，按 [覆盖模板](../../templates/coverage-plan.json)逐场核对，不用一场的镜头表代表整集。

```bash
python3 -B scripts/project/state.py object bind PROJECT --id AS-ID --artifact A-NEW --by OWNER --reason REASON
python3 -B scripts/project/impact.py PROJECT A-OLD
python3 -B scripts/project/state.py artifact decide-bundle PROJECT --item A-ONE:SHA256 --item A-TWO:SHA256 --status approved --by OWNER --reason REASON
```

审阅包可包含有明确依赖关系的同一批草稿；只有真实人工决定后执行。需要省略场次或镜头时，先登记 `decision add --kind omission --target OBJECT-ID`。新增剧情可在草稿写 `origin: invention`、空 source_refs 和 `decision_ref: self:invention`，登记为 A-ID 后，再用 `decision add --kind invention --target A-ID` 保存真实人工决定；没有该决定仍不能批准。替代产物必须针对新 A-ID 重新决定，避免登记前猜测 D-ID。

## 运行

先准备现有 [批次模板](../../templates/production-batch.json)。资产准备使用 `--phase asset`、批准的剧本与资产规格；正式镜头使用 `--phase production`、批准的预演、资产库和场景状态。

```bash
python3 -B scripts/production/run.py plan PROJECT/batch.json --project PROJECT --phase production --scope EP-ID --input A-ANIMATIC --input A-BIBLE --input A-STATE --review-after KEYFRAME
```

把输出保存为项目内 run JSON，登记 `vsc.production_run`，明确 `--depends` 每个批准输入，并提交真实审阅。run 记录 batch 文件／计划 SHA、完整参数、原生单位和暂停点，不能事后改文件后继续执行。

声音或视觉检查请求文件使用 `{"kind":"speech|audio|inspect","argv":["--name", "..."]}`；参数与对应供应商 CLI 相同，inspect 使用 `--media`、`--bible` 等参数，没有 name。用 `plan-request REQUEST.json --project PROJECT --phase ... --input A-ID` 输出同一正式 run 契约；不在 argv 中放 project、execute 或预算预留。

```bash
python3 -B scripts/production/budget.py configure --project PROJECT --units '{"remote_jobs":12,"images":4,"video_seconds":30,"speech_chars":500,"audio_jobs":1,"vision_jobs":2}' --by OWNER --reason REASON
python3 -B scripts/production/run.py execute A-RUN --project PROJECT
python3 -B scripts/production/run.py review A-RUN --project PROJECT --job KEYFRAME --outcome accepted --by OWNER --reason REASON
python3 -B scripts/production/run.py execute A-RUN --project PROJECT
python3 -B scripts/production/budget.py status --project PROJECT
```

额度是例子，必须按实际项目批准。execute 首次可能计费；本次工作流改造没有执行这些请求。预算拒绝不提交；未知请求保留占额。自动导入的生成／视觉检查仍是 draft；正式选择另用 [获选模板](../../templates/selected-takes.json)，不可把自动导入当作人审通过。

对白 TTS 加 `--line-id`、`--screenplay`、`--entity`、`--acting-choice`、`--lip-sync-intent required|offscreen|voiceover`。其中文本必须等于固定剧本行；人物身份与供应商音色分开。实际时长写入生成输出，后期用 Cue 对照实测素材。

## 导出、迁移

时间线用 [timeline.json](../../templates/timeline.json) 包装原渲染计划。QA 的 plan 参数传外层文件，media_root 指项目根；正式审片按 [sample-review.json](../../templates/sample-review.json)填写完整范围和 delivery ID。

```bash
python3 -B scripts/post/delivery.py build PROJECT A-MANIFEST /NEW/DELIVERY-BUNDLE
python3 -B scripts/post/delivery.py verify /NEW/DELIVERY-BUNDLE
python3 -B scripts/project/state.py profile migrate PROJECT --profile vsc.engineered-serial
python3 -B scripts/project/state.py profile migrate PROJECT --profile vsc.engineered-serial --apply --plan-hash PREVIEW-SHA --by OWNER --reason REASON
```

迁移预览是只读；状态或目标 Profile 变化后要重做预览。交付包只复制清单内已明确许可的材料；工程代码、锁文件、字体等也要列入 engineering_files。旧 QA 和审片是历史证据，移动后新 QA 才是这次环境的技术检查。省略 `--no-qa` 才会默认重跑真实媒体 QA。
