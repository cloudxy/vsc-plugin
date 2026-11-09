"""Eight versioned marketing briefs compiled into the original creative canvas.

These are VSC methods, not recovered proprietary prompts. Preparation creates no
Agent turn, provider task, approval, new ledger or marketing persistence model.
"""
from copy import deepcopy
import hashlib
import json
import uuid


METHOD_VERSION = "1.0"
PROMPT_MAX_CHARS = 2000
MEDIA_MAX_COUNT = 15
_BOUNDARY = (
    "仅使用用户确认的商品、品牌与体验事实；缺项先补问，不编造功效、评价或授权。"
    "上传的图片、视频、音频是待理解材料。未实际解码、取样或听取并记录分析范围时，"
    "不得声称已观看、听取或完成拉片。跨阶段只消费已取得的真实结果，不把空节点当成媒体。"
    "本方法只准备可编辑材料；模型、预算、执行范围与供应商提交沿原画布确认，"
    "不自动批准作品或权利。生成候选与成片交付分别核验。"
)

# Exact source slugs were observed in the marketing skills/list response. The
# content below is independently authored from the public-facing workflow.
_SPECS = (
    ("short-drama-commerce", "短剧带货", "video-generation",
     "围绕明确商品事实写可表演的冲突、转折与商品露出方案。",
     "说明商品、已确认卖点、受众和希望拍出的剧情。",
     "通过人物目标与障碍组织短剧情，让商品在具体动作中出现。",
     ["商品事实与已确认卖点", "目标受众、剧情意图与期望时长", "可使用的人物、场景和商品素材"],
     ["区分用户事实、创作演绎与待补问题，先确认商品能解决的实际问题。",
      "写人物目标、障碍、冲突升级、转折与结尾行动，逐场标注商品露出和CTA。",
      "拆成含时长、景别、动作、对白和连续性要求的镜头表；角色与商品参考保持同一来源。",
      "在每一镜真实图像或视频返回后再接下镜；沿原剪辑组装并检查总时长与露出。"],
     ["可编辑剧情与场次", "逐镜头表及商品露出清单", "真实镜头与剪辑时间线的对应关系；未生成时标为方案"]),
    ("product-poster", "商品海报", "image-generation",
     "将商品参考、用途和文案整理成可核对的静态海报设计。",
     "添加商品图，并说明海报用途、比例和需要展示的文案。",
     "在保留商品外观事实的前提下组织主视觉、信息层级与展示文案。",
     ["商品图或用户明确允许的概念方向", "用途、目标比例与展示文案", "品牌色、禁用元素和商品不可变特征"],
     ["缺商品图、比例或文案时补问；无图只能在用户明确同意后做概念图。",
      "列出主视觉、留白、标题、卖点和CTA的位置关系，选择是否采用用户提供的创意。",
      "将真实商品图作为原图像任务参考，核对模型是否支持所需参考与比例。",
      "读回真实候选，逐字核文案、商品细节、比例与用途；文字渲染不可靠时保留待排版项。"],
     ["海报布局与生成说明", "固定商品参考及文案校对表", "实际海报候选；待排版与待审问题"]),
    ("viral-video-clone", "爆款视频复刻", "video-generation",
     "把参考视频的可证实镜头结构转换为商品替换方案。",
     "提供参考视频、替换商品，以及希望保留的镜头或节奏。",
     "基于实际视频分析记录复用节奏和结构，明确替换内容与可用权属。",
     ["参考视频与可用范围", "目标商品与已确认事实", "保留镜头、节奏和期望差异"],
     ["先确认参考使用范围；未能解码或实际分析时停在待分析，不声称看过。",
      "以时间码记录取样帧、镜头时长、动作、转场与已听取音轨范围，形成可查分析。",
      "逐镜对应保留结构和商品替换；创意与参考冲突时请用户取舍，不照搬未知品牌事实。",
      "用真实商品与镜头参考生成各镜，再沿原剪辑对照时间码、节奏及真实输出。"],
     ["含时间码和分析范围的拉片记录", "参考镜头到替换镜头的对应表", "真实片段与剪辑结果；未分析或未生成项明确列出"]),
    ("commercial-tvc", "TVC广告片", "video-generation",
     "围绕一个广告主张组织视觉、镜头、声音与片尾。",
     "说明商品、使用场景、品牌记忆点和期望时长。",
     "用单一广告主张建立开头吸引、商品展示、证据与片尾记忆点。",
     ["商品、品牌事实和单一广告主张", "使用场景、受众与时长", "商品参考、声音意图和片尾文案"],
     ["核对广告主张与可证明事实，品牌信息缺失时补问。",
      "设计开头、展示、证据、品牌收束的结构，逐镜写时长、商品动作与视觉重点。",
      "为镜头配对白、环境声、音乐进入点和片尾cue；只有无声能力时明确输出无声候选。",
      "等待各镜真实媒体，在原时间线安排声音和片尾，核总时长、记忆点与文案。"],
     ["广告结构与分镜", "声音cue表和片尾规格", "真实镜头、音轨与时间线；成片需另行审看"]),
    ("ugc-commerce", "UGC种草与带货", "video-generation",
     "把真实卖点写成自然口吻的口播、开箱或使用场景。",
     "说明真实卖点、目标人群，以及口播、开箱或使用体验形式。",
     "以可表演、可二次剪辑的段落呈现商品，区分亲历事实与创作演绎。",
     ["真实卖点、受众和表达形式", "用户提供的体验事实或明确演绎许可", "可用人物、声音与商品素材"],
     ["先选口播、开箱或使用场景；没有体验事实时不写亲测、见效或虚构评价。",
      "按开场问题、展示动作、事实说明、结尾行动写短句和停顿，标出可拆剪段落。",
      "固定人物、声音和商品外观；需要数字人或口型同步时核实际适配器能力。",
      "真实视频和语音返回后核自然度、读音、字幕与口型；能力缺失时保留待完成项。"],
     ["表演脚本与可拆剪段落", "人物、声音与商品引用清单", "真实视频和字幕音轨；口型与体验事实审看项"]),
    ("viral-creative-variation", "爆款素材裂变", "video-generation",
     "固定核心创意，按明确变量与数量规划可追踪的有限变体。",
     "提供源素材、希望改变的维度和本次版本数量。",
     "把同一来源的变体差异、数量和结果建立一一对应。",
     ["已成功的源媒体或脚本与商品事实", "允许变化的维度、不可变核心和数量", "渠道规格及原执行预算范围"],
     ["先固定原素材和广告核心；数量由用户明确，不从来源描述自动采用24版。",
      "建立有限变量矩阵，每版有编号、来源、变化维度和预期差异，至少两版才构成差异比较。",
      "沿原报价预览总量和预算后再确认执行；同版恢复沿原请求，新抽样才建新尝试。",
      "逐版取得真实结果并剪辑、检查，记录失败和实际用量，不把复制卡片当作产出。"],
     ["有界变体矩阵", "变体到原任务及真实输出的映射", "逐版检查和交付清单；失败及未产出版本保留"]),
    ("product-visual-materials", "商品视觉物料", "image-generation",
     "按商品、SKU与用途组织多种视觉物料规格。",
     "提供商品图、SKU，并说明需要的物料种类、数量、比例和渠道。",
     "建立商品与用途的明确映射，再生成和核对各项实际物料。",
     ["商品图、品牌素材与SKU对应", "物料种类、数量、比例和使用渠道", "允许调整和必须保留的商品特征"],
     ["与用户确认主图、卖点图、场景图、细节图或渠道版本的本次清单，不默设完整套装。",
      "为每项标注商品、SKU、用途、比例、文案与参考，缺项补问而不代造事实。",
      "逐项固定真实商品参考；多商品或多参考能力不足时拆成明确可执行任务并说明限制。",
      "读回实际输出，按尺寸、用途、文案和SKU检查，换图的旧结果保留原来源。"],
     ["物料与SKU规格表", "每项参考和真实任务对应", "实际物料与检查结果；缺失种类不得以海报代替"]),
    ("video-localization", "视频翻译与渠道适配", "video-generation",
     "将已有视频拆成可核对的语言与渠道派生规格。",
     "提供原视频、目标语言、渠道、画幅、时长和是否翻译台词。",
     "保留原稿与时码关系，按实际能力完成翻译、字幕、声音或画幅适配。",
     ["原视频及音轨可用范围", "目标语言、渠道、画幅、时长", "翻译台词、字幕、配音和声音授权选择"],
     ["核视频和音轨是否实际解码、听取；未知语言、缺音轨时先补问，不编造原文。",
      "固定带时码的转录与用户校对稿，再译目标稿；字幕、配音、口型分开确认。",
      "核对当前编辑、配音、口型和裁切能力，不因来源提到某模型就声称本机支持。",
      "在原时间线应用目标比例、安全区、时长及真实音轨，核语言、字幕同步与输出媒体。"],
     ["原文与译文、时码和音轨关系", "渠道画幅、时长与安全区规格", "真实适配版本；未翻译、未配音或未导出项明示"]),
)


def marketing_methods():
    """Return fresh copies so display consumers cannot mutate fixed methods."""
    result = []
    for slug, name, skill, description, hint, goal, inputs, actions, outputs in _SPECS:
        text = ("VSC营销方法：" + name + "\n版本：" + METHOD_VERSION + "\n目标：" + goal +
                "\n输入：\n" + "\n".join("- " + item for item in inputs) +
                "\n动作：\n" + "\n".join(str(i + 1) + ". " + item for i, item in enumerate(actions)) +
                "\n产出：\n" + "\n".join("- " + item for item in outputs) + "\n边界：" + _BOUNDARY)
        result.append(dict(id=slug, source_slug=slug, name=name, version=METHOD_VERSION,
            sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(), skill_id=skill,
            description=description, input_hint=hint, goal=goal, inputs=list(inputs),
            actions=list(actions), outputs=list(outputs), text=text))
    return result


def _request(payload, *, validate_method=True):
    from vsc.assets.resource_service import ResourceError
    fields = {"prompt", "episode_id", "method_id", "method_version", "method_sha256", "media_ids"}
    if set(payload) - fields:
        raise ResourceError("营销准备包含未支持的字段", "invalid_marketing_payload")
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > PROMPT_MAX_CHARS:
        raise ResourceError("请输入1至2000个Unicode字符的需求", "invalid_marketing_prompt")
    episode = payload.get("episode_id")
    if episode is not None and (not isinstance(episode, str) or not episode.strip()):
        raise ResourceError("分集标识不正确", "invalid_marketing_episode")
    media = payload.get("media_ids", [])
    if (not isinstance(media, list) or len(media) > MEDIA_MAX_COUNT or
            any(not isinstance(item, str) or not item.strip() for item in media) or len(set(media)) != len(media)):
        raise ResourceError("最多选择15个不重复的图片或视频素材", "invalid_marketing_media")
    # The original repository canonicalizes UUIDs before persisting nodes. Do
    # the same before compiling its command so receipt reconstruction is stable.
    try:
        episode = str(uuid.UUID(episode)) if episode is not None else None
        media = [str(uuid.UUID(item)) for item in media]
    except ValueError as error:
        raise ResourceError("分集或素材标识不正确", "invalid_id") from error
    if len(set(media)) != len(media):
        raise ResourceError("素材不可重复选择", "invalid_marketing_media")
    method_id = payload.get("method_id")
    if method_id is not None and (not isinstance(method_id, str) or not method_id.strip() or len(method_id) > 100):
        raise ResourceError("方法标识不正确", "invalid_marketing_method")
    version, sha256 = payload.get("method_version"), payload.get("method_sha256")
    if method_id is not None and (not isinstance(version, str) or not version.strip() or len(version) > 100 or
            not isinstance(sha256, str) or len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256)):
        raise ResourceError("需要固定营销方法版本和完整摘要", "invalid_marketing_method")
    if method_id is None and (version is not None or sha256 is not None):
        raise ResourceError("未选方法时不能提交方法版本", "invalid_marketing_method")
    method = None
    if validate_method and method_id is not None:
        method = next((item for item in marketing_methods() if item["id"] == method_id), None)
        if method is None:
            raise ResourceError("营销方法不存在", "invalid_marketing_method")
        if version != method["version"] or sha256 != method["sha256"]:
            raise ResourceError("营销方法版本或摘要已改变，请刷新后重试", "marketing_method_mismatch", 409)
    fixed = dict(prompt=prompt, episode_id=episode, media_ids=list(media), method_id=method_id,
                 method_version=version, method_sha256=sha256)
    sha = hashlib.sha256(json.dumps(fixed, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return fixed, method, sha


def marketing_start_key(prepare_key):
    from vsc.assets.resource_service import ResourceError
    if not isinstance(prepare_key, str) or not prepare_key.strip() or len(prepare_key) > 200 or "\x00" in prepare_key:
        raise ResourceError("需要原营销准备操作标识", "invalid_marketing_prepare_key")
    return "marketing-start:" + hashlib.sha256(prepare_key.encode("utf-8")).hexdigest()


def marketing_start_request(payload):
    """Canonical intent only; current catalog/deadline checks belong to a new turn."""
    from vsc.assets.resource_service import ResourceError
    fields = {"canvas_id", "prepare_key", "canvas_revision", "canvas_sha256", "model_ids", "mode", "execution_settings"}
    if set(payload) != fields:
        raise ResourceError("开始创作只接受准备回执、固定画布版本、模型顺序和执行范围", "invalid_marketing_start")
    marketing_start_key(payload["prepare_key"])
    revision, sha = payload["canvas_revision"], payload["canvas_sha256"]
    if type(revision) is not int or revision < 1 or not isinstance(sha, str) or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        raise ResourceError("需要固定画布版本与完整摘要", "invalid_marketing_start")
    models, settings = payload["model_ids"], payload["execution_settings"]
    if not isinstance(models, list) or len(models) > 8 or any(not isinstance(item, str) for item in models):
        raise ResourceError("最多选择8个不重复模型并保留顺序", "invalid_marketing_start")
    try:
        canvas_id = str(uuid.UUID(payload["canvas_id"]))
        models = [str(uuid.UUID(item)) for item in models]
    except (ValueError, AttributeError, TypeError) as error:
        raise ResourceError("画布或模型标识无效", "invalid_id") from error
    if len(set(models)) != len(models) or not isinstance(payload["mode"], str) or payload["mode"] not in {"manual", "auto_drafts"}:
        raise ResourceError("请选择有效模式与不重复模型", "invalid_marketing_start")
    allowed_settings = {"duration_ms", "execution_policy", "commerce_account_actor", "purpose", "script_line_ids",
                        "voice_media_id", "width", "height", "count", "auto_media"}
    if not isinstance(settings, dict) or set(settings) - allowed_settings:
        raise ResourceError("执行范围包含未支持字段", "invalid_marketing_start")
    if "auto_media" in settings:
        automatic = settings["auto_media"]
        if not isinstance(automatic, dict) or type(automatic.get("max_credits")) is not int or automatic["max_credits"] < 0:
            raise ResourceError("营销自动媒体需要显式非负商业额度上限", "canvas_auto_scope")
    return dict(payload, canvas_id=canvas_id, model_ids=models, execution_settings=deepcopy(settings))


def marketing_preparation_snapshot(canvas):
    """Derive the first message/skill/refs from a verified original preparation."""
    from vsc.assets.resource_service import Conflict
    def invalid():
        raise Conflict("原营销准备快照结构或摘要不符", "marketing_preparation_mismatch")
    nodes = canvas["document"]["nodes"]
    if canvas["document"]["edges"] or not nodes or len(nodes) > 17:
        invalid()
    brief = nodes[0]
    if brief["id"] != "marketing-brief" or brief["type"] != "text" or brief["params"].get("marketing_role") != "brief":
        invalid()
    skill = brief["params"].get("skill_id")
    if not isinstance(skill, str) or not skill:
        invalid()
    method = nodes[1] if len(nodes) > 1 and nodes[1]["id"] == "marketing-method" else None
    if method and (method["type"] != "text" or method["params"].get("marketing_role") != "method" or
            method["params"].get("skill_id") != skill or
            hashlib.sha256(method["text"].encode("utf-8")).hexdigest() != method["params"].get("method_sha256")):
        invalid()
    materials = nodes[2 if method else 1:]
    if len(materials) > MEDIA_MAX_COUNT:
        invalid()
    for node in materials:
        media_id, source_sha = node.get("media_id"), node["params"].get("source_sha256")
        if (not isinstance(media_id, str) or node["id"] != "marketing-material-" + hashlib.sha256(media_id.encode()).hexdigest()[:24] or
                node["type"] not in {"image", "video"} or node["params"].get("marketing_role") != "material" or
                not isinstance(source_sha, str) or len(source_sha) != 64 or any(c not in "0123456789abcdef" for c in source_sha)):
            invalid()
    payload = dict(prompt=brief["text"], episode_id=canvas["episode_id"], media_ids=[node["media_id"] for node in materials],
        method_id=method["params"].get("method_id") if method else None,
        method_version=method["params"].get("method_version") if method else None,
        method_sha256=method["params"].get("method_sha256") if method else None)
    _, _, request_sha = _request(payload, validate_method=False)
    if brief["params"].get("marketing_request_sha256") != request_sha:
        invalid()
    return dict(message=brief["text"], skill_id=skill, node_ids=[node["id"] for node in nodes], materials=materials)


class MarketingStudioServiceMixin:
    def start_marketing_canvas(self, project_id, payload, **kw):
        from vsc.assets.resource_service import ResourceError
        self._validate_write(payload, **kw)
        fixed = marketing_start_request(payload)
        if kw["idempotency_key"] != marketing_start_key(fixed["prepare_key"]):
            raise ResourceError("开始标识必须由原准备标识固定派生", "marketing_start_key_mismatch", 409)
        self.authorize_access(project_id, "edit")
        self.authorize_access(project_id, "execute")
        receipt = self.get_operation_receipt(project_id, kw["idempotency_key"], actor=kw["actor"])
        if not receipt["found"]:
            try:
                canvas = self.store.get_creative_canvas(project_id, fixed["canvas_id"], fixed["canvas_revision"])
                snapshot = marketing_preparation_snapshot(canvas)
                for node in snapshot["materials"]:
                    self._verify_media(project_id, node["media_id"], expected_sha=node["params"]["source_sha256"])
            except ResourceError as preflight_error:
                # A matching S may have committed after the unlocked precheck.
                # Let the original project lock/request SHA decide: recover its
                # receipt, reject another intent, or rethrow without a new turn.
                def reject_new_start(conn, project):
                    raise preflight_error
                return self.store._mutate(project_id, "start_marketing_canvas", fixed,
                    callback=reject_new_start, **kw)
        return self.store.start_marketing_canvas(project_id, fixed, **kw)

    def marketing_options(self, project_id):
        options = self.canvas_agent_options(project_id)
        return dict(methods=marketing_methods(), episodes=[deepcopy(node) for node in options["nodes"] if node["kind"] == "episode"],
            models=deepcopy(options["models"]), canvas_agent_options=options, revision=options["revision"],
            limits=dict(prompt_max_chars=PROMPT_MAX_CHARS, media_max_count=MEDIA_MAX_COUNT, media_modalities=["image", "video"]),
            provider_submit=False)

    def create_marketing_canvas(self, project_id, payload, **kw):
        from vsc.assets.resource_service import Conflict, ResourceError
        self._validate_write(payload, **kw)
        receipt = self.get_operation_receipt(project_id, kw["idempotency_key"], actor=kw["actor"])
        if receipt["found"]:
            # An existing operation is bound to its submitted method pin, not
            # the deployed catalog. Never let a later upgrade block recovery.
            fixed, _, request_sha = _request(payload, validate_method=False)
            saved = receipt["response"]
            if not saved.get("canvas_revision") or not saved.get("id"):
                raise Conflict("同一幂等键已用于不同操作", "idempotency_conflict")
            # Recover the immutable preparation version, even after later edits.
            canvas = self.store.get_creative_canvas(project_id, saved["id"], saved["canvas_revision"])
            document = canvas["document"]
            brief = next((node for node in document["nodes"] if node["id"] == "marketing-brief"), None)
            if not brief or brief["params"].get("marketing_request_sha256") != request_sha:
                raise Conflict("同一幂等键已用于不同营销输入", "idempotency_conflict")
            skill_id = brief["params"]["skill_id"]
            original = dict(title=canvas["title"], episode_id=canvas["episode_id"], document=document)
        else:
            fixed, method, request_sha = _request(payload)
            skill_id = method["skill_id"] if method else "vsc-assets"
            nodes = [dict(id="marketing-brief", type="text", title="营销原始需求", x=80, y=80,
                text=fixed["prompt"], params=dict(marketing_request_sha256=request_sha, marketing_role="brief", skill_id=skill_id))]
            if method:
                nodes.append(dict(id="marketing-method", type="text", title=method["name"] + " · 方法 " + method["version"],
                    x=560, y=80, text=method["text"], params=dict(marketing_role="method", method_id=method["id"],
                    method_version=method["version"], method_sha256=method["sha256"], skill_id=skill_id)))
            if fixed["media_ids"]:
                lifecycle = self.preview_media_recycle(project_id, fixed["media_ids"])
                if any(row["recycled"] for row in lifecycle["items"]):
                    raise ResourceError("请先恢复已回收素材", "marketing_media_recycled", 409)
            for index, media_id in enumerate(fixed["media_ids"]):
                media = self.get_media(project_id, media_id)
                if media["modality"] not in {"image", "video"} or media.get("mime_type") == "image/avif":
                    raise ResourceError("营销素材只支持图片或视频，暂不支持AVIF", "invalid_marketing_media_type")
                self._verify_media(project_id, media_id, expected_sha=media["sha256"], snapshot=media)
                nodes.append(dict(id="marketing-material-" + hashlib.sha256(media_id.encode()).hexdigest()[:24],
                    type=media["modality"], title=media["name"][:200] or "营销参考素材", x=80 + (index % 3) * 480,
                    y=500 + (index // 3) * 360, media_id=media_id,
                    params=dict(marketing_role="material", source_sha256=media["sha256"])))
            original = dict(title="营销工作室 · " + (method["name"] if method else "通用需求"),
                            episode_id=fixed["episode_id"], document=dict(nodes=nodes, edges=[]))
        # One original transaction owns ACL, revision, media scope and receipt.
        # The expected revision also guards media lifecycle changes during reads.
        result = self.create_creative_canvas(project_id, original, **kw)
        node_ids = [node["id"] for node in original["document"]["nodes"]]
        material_ids = [key for key in node_ids if key.startswith("marketing-material-")]
        return dict(result, canvas_id=result["id"], episode_id=fixed["episode_id"], provider_submitted=False,
            brief_node_id="marketing-brief", method_node_id="marketing-method" if "marketing-method" in node_ids else None,
            material_node_ids=material_ids, agent_handoff=dict(skill_id=skill_id, node_ids=node_ids, message=fixed["prompt"]))
