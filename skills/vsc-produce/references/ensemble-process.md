# 多人动作、表情与过程输入

下列为VSC原创工程与方法示例。字段可追溯、请求可构建、观察可回收，与媒体正常速度下表演成立分开；未生成连续媒体时保留后者待验。它们沿原批准方法、Profile、Gate、run与选择，不增加新的批准权威。

<a id="ensemble-chain"></a>
## 多人多招：身份与职责分开

先列 A、B、C 三个固定参与实例。A向B作非接触佯动，B退让后C封住A的通道：`feint(A→B) → block(C→A)`。两人都可以承担 fighter 职责，节点必须用 `actor_instance/counterpart_instance` 指向已登记 participant.instance，不能靠角色名猜人。原五相位仍是每招的准备、发起、接触、反应、恢复；“接触”可以明确为空间接近而无真实接触。

combat.parameters 可选 `chain` 每节点写 `id`、`after`（首节点为`[]`）、两方实例和五相位 action；可选起止秒数同时填写，因果后继不得早于前驱结束。登记沿现 creative-relations；实例由原项目／依赖／场镜边界解析，重复身份、未参与或跨项目ID、缺前驱、环和乱序相位均应失败。旧无chain的二元五相位保持原语义，已有N参与关系不重建。

固定方法后从原 ShotContext 读取专业实例及 `request_constraints`；在批准run前用 `vsc.production.performance.prompt_fragment(domain, parameters)`加入完整规格，用`vsc.story.consistency.compile_state_request(request, context)`加入结构状态。原 resources context 入口会显示要求的片段；也可逐条将`request_constraints[].fragment`原样附入prompt，不能删改后仍声称固定覆盖。函数只准备请求，不执行或批准。创建任务与提交都会核对；缺失回请求准备，漂移回上游版本，不在已批准run后补写prompt。

这是普通文字意图，不是供应商的姿态／坐标硬控制。模型未兑现时，按可见失败区间返回动作分段、反应镜或已支持的实拍／合成路线。

<a id="expression-listening"></a>
## 表情基准与背景反应

`asset-bible.entities[].expression_baseline`写可观察description；如用图片，reference_sha256须指本实体已登记的真实图片。它是平静基线，不能把某一表情当不可变身份。状态的`expression`写本时刻可观察变化，进锚点、固定请求和连续性对账。

原创例：听到“已交接”，A先停笔、视线落向B手中空文件夹，嘴角放松；B仍扶着文件夹，不抢台词；C在后景停止收椅子，保持原位置。初稿若只写“三人惊讶”，改写把不同人物的任务、注意对象和先后反应写清。改变的是表演可执行性，没有断言观众能读出唯一情绪。

“怀疑”可尝试停笔后再核对物件；也可继续写字但缩短回答。眼睛或嘴角某一肌肉运动不能一一换算情绪；遮挡、远景、个体差异或剧情刻意掩饰时不宜强塞微表情。背景人只承担关系或信息任务，避免所有人同时同步点头。练习把C改为完全不知交接的人，重写其反应；若无法给出注意来源，删掉反应。回到原 listen／dialogue-subtext 方法和scene-state，不另存第二份表演正文。

<a id="spatial-and-people"></a>
## 世界坐标、机位、镜面与人数

场景可选`spatial={frame:"floor",unit:"m"}`；位置仍兼容旧文本，结构位置写`{frame:"floor",x:0,y:0}`。跨镜先统一世界参考系，不能把画左直接当世界西。不同参考系无变换依据时记未判，不猜转换。

用原`python3 -B scripts/story/consistency.py state map <状态文件> <镜头ID> --moment entry`输出世界坐标SVG示意图，可分别查看入／出点。它读取原state，不另存布局正文；没有结构坐标就报告依据不足。示意图不是摄影投影或画面兑现证据。

机位可选`camera.spatial={frame:"floor",x:1,y:-3,axis:["A","B"],mirrored:false}`。以同参考系A/B位置和机位叉积核世界机位侧，前镜出点对后镜入点。轴上、轴退化、缺坐标或不同轴时返回未判。同侧反打合法；换到另一侧须在后镜`crossing_reason`写可读的重建空间设计。显式镜面记录屏幕左右反射，不把人物世界位置交换；镜面不能掩盖没有说明的真实机位越轴。

人数检查显式启用`shot.people_check=true`并列`in_frame`。quality-plan原must requirement引用该固定数组，绑定真实请求片段，实际观察仍走原advisory visual-check。人物按实体ID辨认，prop不算人；遮挡看不清写unsure，不用“看到三个头”自动认证三个身份或无复制。错误人数先回输入帧与身份分离，不让视频阶段修错图。

<a id="grid-frames"></a>
## N格参考先还原为逐帧输入

网格只是构图／动作讨论图，不是多时刻视频控制。先保存原网格SHA和格子顺序，逐格裁出真实文件，登记每格源网格SHA、像素矩形、独立输出SHA、参与身份、entry/exit用途和所属镜头。若有字框或格线，在裁切后复核是否残留；重新生成或编辑的格子要有自己的来源记录，不能冒称原像素裁切。

只把裁出的单格文件绑定到原first_frame、last_frame或已支持的reference用途；首尾帧模式另核身份、光源、景深和空间兼容。每格只能代表所记录的时刻，顺序和身份未清时回网格标注。静帧相似、裁切成功都不证明中间动作成立。

<a id="process-mode"></a>
## 显式组装过程

原状态的changes能表达入／出状态，缺少过程的显式固定语义与阶段顺序。因此只增加shot.process可选块，不另造过程状态：`enabled:true`、`fixed_entities`、`direction:{frame,axis,sign}`和递增`beats:[{seconds,action}]`。允许变化仍只有本镜原changes；未列的字段固定。缺省／false不启用此约束。

原创例：桌面、夹具固定；木销由floor坐标x=0移到x=0.5并落座，direction为x正向。0秒对准，1秒推入，2秒停稳。changes只列木销位置和pose；夹具不得同时列fixed_entities与changes。不能把组装完成的尾帧当作中间顺序已成功，不能让构件在两阶段间凭空增加。

顺序：先用原资产身份、首尾状态及changes登记版本；开启process并校验固定物／方向／阶段；从context读取约束并在run批准前编译到请求；原advisory检查清单自动列固定物、仅允许变化、方向及阶段，看到倒序、跳变或固定物漂移须给区间，遮挡记unsure。需要连续媒体时再按已有授权制作候选并正常速度检查；本例的工程夹具不代替该证据。

有效：同一机位、少量构件、端点和方向可说明。暂不适用：复杂拓扑变化、看不到安装关系、模型无法保持固定物；拆阶段、补可检查单帧或改实际合成路线。练习只改插销推进方向，列出必须同时改的position、direction与参考；只改prompt中的“向左”而状态不变应返回规格，不允许修改已批准快照掩盖冲突。
