"""Typed authoring, analysis, local quality checks and localization work units."""
from copy import deepcopy
import base64
import json
import math
import re
import uuid

from vsc.assets.resource_service import ResourceError, Conflict
from vsc.production.quotes import fingerprint

TOOLS = {
 "novel":{"label":"小说转剧本","actions":{"synopsis":"梗概建议","characters":"人物小传建议","outline":"分集大纲建议","scenes":"场景建议","body":"重新创作正文建议","qa_notes":"正文检查建议"},"formats":["txt","docx","json"]},
 "translation":{"label":"剧本翻译","actions":{"terms":"提取术语与角色建议","translate":"生成当前集译文建议"},"formats":["txt","docx","json"]},
 "scoring":{"label":"剧本评分","actions":{"analyze":"分析类型、频道与首卡建议","score":"按固定标准新评分"},"formats":["json","csv","html"]},
 "breakdown":{"label":"视频拉片","actions":{"observe":"分析固定视频输入"},"formats":["txt","timestamp-txt","json"]},
 "qc":{"label":"视频与字幕质检","actions":{"check":"运行所选质检"},"formats":["xlsx","json","zip"]},
 "overseas":{"label":"出海本地化","actions":{"understand":"理解固定源视频","localize":"按理解稿提出本地化建议"},"formats":["json","txt","docx"]},
}
COMMON = {"source_text":"", "source_refs":[], "notes":""}
DEFAULTS = {
 "novel":{"synopsis":"","core_setting":"","novel_baseline_version_id":"","characters":[],"outline":"","scenes":"","body":"","qa_notes":"","chapter_start":1,"chapter_end":1,"target_episodes":1},
 "translation":{"body":"","target_language":"","translation_mode":"initial","translation_stage":"draft","episode_number":1,"style":"","style_version_id":"","style_request":False,"terms":[],"translation_characters":[],"reference_version_ids":[],"proofread":False},
 "scoring":{"analysis":"","channel":"未知","category":"未分类","card_start":1,"card_end":1,"card_start_line":1,"card_end_line":1,"card_source_sha256":"","criteria":[],"scores":[],"risk_score":0,"quality_score":0,"confidence":0,"review_decision":"pending","review_reason":""},
 "breakdown":{"media_id":"","understanding_mode":"light","observation_basis":"","observations":[],"body":""},
 "qc":{"videos":[],"subtitles":[],"matches":[],"checks":["metadata","subtitles"],"content_rules":[],"rule_version":"vsc.media-review/v1","check_ranges":[],"base_report_version_id":"","issues":[]},
 "overseas":{"source_media_id":"","target_language":"","understanding":"","understanding_mode":"light","observation_basis":"human-observation","understanding_version_id":"","entities":[],"body":"","groups":[],"segments":[]},
}
ROWS = {
 "characters":{"name":"text","description":"text"},
 "terms":{"source":"text","target":"text","aliases":"text"},
 "translation_characters":{"source":"text","target":"text","aliases":"text","kind":"text","description":"text"},
 "criteria":{"key":"key","label":"text","max_score":"positive","weight":"positive"},
 "scores":{"key":"key","score":"number","evidence":"text","reason":"text"},
 "observations":{"start_ms":"nonnegative","end_ms":"positive","kind":"text","text":"text"},
 "videos":{"media_id":"id","name":"text","sha256":"text"},
 "subtitles":{"filename":"text","text":"text"},
 "matches":{"video_id":"id","subtitle_name":"text"},
 "check_ranges":{"media_id":"id","start_ms":"nonnegative","end_ms":"positive"},
 "issues":{"rule":"text","media_id":"text","start_ms":"nonnegative","end_ms":"nonnegative","code":"text","severity":"text","message":"text","evidence":"text","original_subtitle":"text","suggested_subtitle":"text","rule_version":"text"},
 "content_rules":{"key":"key","description":"text"},
 "entities":{"key":"key","kind":"text","name":"text","localized":"text","asset_id":"text","media_id":"text"},
 "groups":{"key":"key","source_start_ms":"nonnegative","source_end_ms":"positive","target_duration_ms":"nonnegative","shot_id":"text","prompt":"text","first_frame_media_id":"text","candidate_media_id":"text","candidate_in_ms":"nonnegative"},
 "segments":{"key":"key","group":"key","source_start_ms":"nonnegative","source_end_ms":"positive","source_text":"text","inference":"text","entity_keys":"text","scene_key":"text","target_start_ms":"nonnegative","target_end_ms":"nonnegative","localized_text":"text"},
}
ROW_DEFAULTS={"number":0,"positive":1,"nonnegative":0,"id":"","text":"","key":""}


def fail(message, code="invalid_text_tool"):
    raise ResourceError(message, code)


def text(value, maximum=200000, empty=True):
    if not isinstance(value,str) or len(value)>maximum or re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]",value) or (not empty and not value.strip()):
        fail("文本字段为空、格式错误或超过长度限制")
    return value


def number(value, kind):
    if type(value) not in (int,float) or not math.isfinite(value) or abs(value)>10**9:
        fail("数值须为有限值")
    if kind in {"nonnegative","positive"} and (type(value) is not int or value<(1 if kind=="positive" else 0)):
        fail("时码、序号须为有效整数")
    return value


def normalize_document(tool, value):
    if tool not in TOOLS or not isinstance(value,dict):
        fail("未知工具或文档格式")
    defaults={**deepcopy(COMMON),**deepcopy(DEFAULTS[tool])}
    if set(value)-set(defaults)-{"format"}:
        fail("当前工具文档含未声明字段")
    result={**defaults,**deepcopy(value),"format":"vsc.text-tool/"+tool+"/v1"}
    for key,default in defaults.items():
        val=result[key]
        if isinstance(default,str): text(val)
        elif type(default) is bool:
            if type(val) is not bool: fail("确认标记须为布尔值")
        elif type(default) is int: number(val,"nonnegative" if key in {"risk_score","quality_score","confidence"} else "positive")
        elif not isinstance(val,list) or len(val)>500: fail("列表字段过长或格式错误")
        elif key in ROWS:
            fields=ROWS[key]
            for row in val:
                if not isinstance(row,dict) or set(row)-set(fields): fail("表格列与工具类型不匹配")
                for field,kind in fields.items():
                    row.setdefault(field,ROW_DEFAULTS[kind])
                    if kind in {"number","positive","nonnegative"}: number(row[field],kind)
                    else:
                        text(row[field],200000 if field=="text" else 10000)
                        if kind=="key" and not re.fullmatch(r"[A-Za-z0-9_-]{1,80}",row[field]):fail("行标识需为字母、数字、短横线或下划线")
                        if kind=="id" and not row[field]:fail("需要已登记对象 ID")
        elif key=="source_refs":
            for ref in val:
                if not isinstance(ref,dict) or set(ref)-{"kind","id","sha256"} or ref.get("kind") not in {"source","artifact","media"}:fail("来源须固定类型、版本 ID 与摘要")
                text(ref.get("id"),100,False)
        elif key=="reference_version_ids":
            if any(not isinstance(item,str) for item in val) or len(set(val))!=len(val):fail("参考集须为不重复的固定版本")
        elif key=="checks" and (not val or set(val)-{"metadata","subtitles","decode","subtitle_semantics","visual_quality","audiovisual","content"}):fail("检查项不受支持")
    if len(json.dumps(result,ensure_ascii=False))>2_000_000:fail("单元文档超过 2M 字符")
    if tool=="qc":
        prior={}
        for row in result["check_ranges"]:
            if row["start_ms"]<prior.get(row["media_id"],0) or row["end_ms"]<=row["start_ms"]:fail("局部复检区间须按媒体有序且不重叠")
            prior[row["media_id"]]=row["end_ms"]
    if tool=='novel':
        if result['chapter_end']<result['chapter_start'] or result['target_episodes']>200:fail('章范围倒置或目标集数超过200')
        if result['source_text'].strip() and not result['novel_baseline_version_id']:
            from vsc.production.text_tools import chapter_text
            chapter_text(result['source_text'],result['chapter_start'],result['chapter_end'])
    if tool=="scoring":
        from vsc.production.text_tools import scoring_boundary
        boundary=scoring_boundary(result)
        if result['card_source_sha256'] and result['card_source_sha256']!=boundary['source_sha256']:
            fail('原文变化使旧首卡失效，请重新选择行范围','scoring_card_stale')
        result['card_source_sha256']=boundary['source_sha256']
        if any(result[k]>100 for k in ('risk_score','quality_score','confidence')):fail('风险、质量与置信度须在0–100之间')
        if result["card_end"]<result["card_start"]:fail("首卡边界倒置")
        if result["review_decision"] not in {"pending","keep","exclude"}:fail("复核结论无效")
        if result["review_decision"]!="pending" and not result["review_reason"].strip():fail("人工复核需要理由")
        criteria={row["key"]:row for row in result["criteria"]}
        if len(criteria)!=len(result["criteria"]) or len({r["key"] for r in result["scores"]})!=len(result["scores"]):fail("评分标准或结果标识重复")
        for score in result["scores"]:
            c=criteria.get(score["key"])
            if not c or not 0<=score["score"]<=c["max_score"] or not score["evidence"].strip():fail("分数必须对应标准范围与具体依据")
    if tool in {'breakdown','overseas'}:
        if result['understanding_mode'] not in {'light','deep','manual'}:fail('视频理解模式无效')
    if tool=="breakdown":
        for row in result["observations"]:
            if row["end_ms"]<=row["start_ms"] or not row["text"].strip():fail("观察需要有效时码与正文")
    if tool=="overseas":
        groups={g["key"]:g for g in result["groups"]}
        if len(groups)!=len(result["groups"]):fail("出海组标识重复")
        prior=-1
        for g in result["groups"]:
            if g["source_start_ms"]<prior or g["source_end_ms"]<=g["source_start_ms"]:fail("出海组须按源片顺序且不重叠")
            prior=g["source_end_ms"]
        for seg in result["segments"]:
            g=groups.get(seg["group"])
            if not g or not g["source_start_ms"]<=seg["source_start_ms"]<seg["source_end_ms"]<=g["source_end_ms"]:fail("镜头源区间必须位于明确分组内")
        from vsc.production.overseas_production import normalize
        normalize(result)
    return result


def subtitle_matches(videos, subtitles):
    def stem(name):return re.sub(r"\.[^.]+$","",name.replace("\\","/").rsplit("/",1)[-1]).lower()
    edges={s["filename"]:[v["media_id"] for v in videos if stem(s["filename"])==stem(v["name"]) or any(stem(s["filename"]).startswith(stem(v["name"])+sep) for sep in (".","-","_"))] for s in subtitles}
    counts={v["media_id"]:sum(v["media_id"] in ids for ids in edges.values()) for v in videos}
    return [{"subtitle_name":name,"video_ids":ids,"status":"matched" if len(ids)==1 and counts[ids[0]]==1 else "conflict" if ids else "unmatched"} for name,ids in edges.items()]


def group_mapping(document):
    groups={g["key"]:g for g in document["groups"]}
    return [{**seg,"group_start_ms":seg["source_start_ms"]-groups[seg["group"]]["source_start_ms"],
             "group_end_ms":seg["source_end_ms"]-groups[seg["group"]]["source_start_ms"]} for seg in document["segments"]]


def validated_result(tool,action,result,document):
    if not isinstance(result,dict):fail("工具结果必须为结构化对象","invalid_tool_result")
    expected={"synopsis":{"synopsis"},"characters":{"characters"},"outline":{"outline"},"scenes":{"scenes"},"body":{"body"},"qa_notes":{"qa_notes"},"translate":{"body"},"terms":{"terms","translation_characters"},"analyze":{"analysis","category","channel","card_start_line","card_end_line"},"score":{"analysis","scores"},"observe":{"observations"},"localize":{"body"},"check":{"issues"},"understand":{"understanding","entities","segments","groups","observation_basis","understanding_version_id"}}[action]
    if action=='score' and set(result)==expected|{'risk_score','quality_score','confidence'}:expected=expected|{'risk_score','quality_score','confidence'}
    if action=='observe' and set(result)==expected|{'observation_basis'}:expected=expected|{'observation_basis'}
    if action=="translate" and document.get("style_request"):expected={"style","style_version_id"}
    if set(result)!=expected:fail("工具结果字段与固定动作不同","invalid_tool_result")
    normalized=normalize_document(tool,{**document,**result})
    if action=="score" and set(r["key"] for r in normalized["scores"])!=set(r["key"] for r in document["criteria"]):fail("评分结果没有覆盖完整标准","invalid_tool_result")
    return {k:normalized[k] for k in expected}


class TextToolsServiceMixin:
    def open_text_tool_workspace(self, *, actor):
        self._actor(actor)
        identity=self.store.text_tool_workspace_identity(actor)
        return self.create_project({'name':'独立剧本与分析工具','profile_snapshot':{
            'profile_id':'vsc.text-tools','version':'1.0','stages':[],
            'storage_policy':'postgres-series-v1','workspace_kind':'text-tools'}},
            actor=actor,idempotency_key='text-tools-workspace:'+identity)

    def preview_text_tool_copy(self, project_id, payload):
        return self.store.preview_text_tool_copy(project_id,payload)

    def copy_text_tool_to_project(self, project_id, payload, **kw):
        self._validate_write(payload,**kw)
        return self.store.copy_text_tool_to_project(project_id,payload,**kw)

    def text_tool_capabilities(self):
        from vsc.production.text_tool_host import GrokBuildTextTools
        backend=getattr(self,"text_tool_host",None) or GrokBuildTextTools()
        import shutil
        from vsc.production.media_understanding import default_media_host
        media=getattr(self,'media_understanding_host',None) or default_media_host()
        return {"tools":deepcopy(TOOLS),"defaults":deepcopy(DEFAULTS),"rows":deepcopy(ROWS),"common":deepcopy(COMMON),
                'media_host':{'name':media.name,'available':media.available(),'capabilities':sorted(media.capabilities),'basis':media.basis,'online_verified':False},
                "host":{"name":backend.name,"available":backend.available(),"online_verified":False},
                "local_probe":bool(shutil.which("ffprobe")),"local_decode":bool(shutil.which("ffmpeg")),
                "limitations":["默认Grok媒体宿主使用实际抽样图像，无音频，不能推断对白。完整音画理解须配置支持源媒体的适配器。","供应商效果未经本轮线上验证。"]}

    def text_tool_options(self,project_id):
        tree=self.get_project_tree(project_id)
        return {"episodes":[r for r in tree["nodes"] if r["kind"]=="episode"],"assets":[r for r in tree["nodes"] if r["kind"]=="asset"],
                "media":self.list_resources(project_id,modality="video",limit=200)["items"],"images":self.list_resources(project_id,modality="image",limit=200)["items"],"works":[r for r in tree["nodes"] if r["kind"]=="work"],"scenes":[r for r in tree["nodes"] if r["kind"]=="scene"],"shots":[r for r in tree["nodes"] if r["kind"]=="shot"],"styles":self.store.list_translation_styles(project_id)["items"],"revision":tree["revision"]}

    def list_text_tools(self,project_id,tool,group_key=None):
        if tool not in TOOLS:fail("未知工具")
        return self.store.list_text_tools(project_id,tool,group_key)

    def get_text_tool(self,project_id,unit_id):
        value=self.store.get_text_tool(project_id,unit_id)
        if value['tool']=='novel':value['novel_plan']=self.store.get_novel_plan(project_id,unit_id)
        if value['tool']=='translation':
            from vsc.production.text_tools import translation_residuals
            value['residuals']=translation_residuals(value['document'])
        if value["tool"]=="qc":
            value["matching"]=subtitle_matches(value["document"]["videos"],value["document"]["subtitles"])
            value['issue_reviews']=self.store.text_issue_reviews(project_id,value['current_version_id'])
        if value["tool"]=="overseas":
            value["document"]=normalize_document("overseas",value["document"])
            value["mapping"]=group_mapping(value["document"])
            value["overseas"]=self.store.overseas_status(project_id,unit_id)
        return value

    def get_text_tool_attempt(self,project_id,attempt_id):
        return self.store.get_text_tool_attempt(project_id,attempt_id)

    def recover_text_tool_attempt(self,project_id,payload,**kw):
        self._validate_write(payload,**kw)
        if set(payload)!={"attempt_id"}:fail("恢复需要固定尝试ID")
        return self.store.recover_text_tool_attempt(project_id,payload,**kw)

    def _text_tool_document(self,project_id,tool,value):
        doc=normalize_document(tool,value)
        for ref in doc["source_refs"]:
            original=(self.store.get_media if ref["kind"]=="media" else self.get_source_version if ref["kind"]=="source" else self.store.get_artifact_version)(project_id,ref["id"])
            if ref.get("sha256",original["sha256"])!=original["sha256"]:raise Conflict("固定来源摘要已变化","tool_reference_changed")
            ref["sha256"]=original["sha256"]
        if tool=="translation":
            if doc['translation_stage'] not in {'draft','terms_reviewed','translated','complete'}:fail('翻译阶段无效')
            if doc['translation_mode'] not in {'initial','incremental'}:fail('翻译方式须为初译或增量')
            if doc['translation_mode']=='incremental' and not doc['reference_version_ids']:fail('增量翻译须选择从第1集开始的连续精校参考','translation_reference_required')
            if doc['translation_mode']=='initial' and doc['reference_version_ids']:doc['translation_mode']='incremental'
            if doc["style_version_id"]:
                fixed=self.store.get_artifact_version(project_id,doc["style_version_id"])
                if fixed["artifact_type"]!="translation-style":fail("所选风格不是本项目风格版本")
                style=json.loads(fixed["document"])
                if doc["style"] and doc["style"]!=style["content"]:fail("固定风格版本不可同时手改；请另存风格或取消固定选择")
                doc["style"]=style["content"]
            for identifier in doc["reference_version_ids"]:
                ref=self.store.get_artifact_version(project_id,identifier)
                prior=json.loads(ref["document"])
                if ref["artifact_type"]!="text-tool-draft" or prior.get("format")!="vsc.text-tool/translation/v1" or not prior.get("proofread"):fail("增量参考须为明确精校后的固定翻译版本")
        if tool=='novel' and doc['novel_baseline_version_id']:
            fixed=self.store.get_artifact_version(project_id,doc['novel_baseline_version_id'])
            if fixed['artifact_type']!='novel-adaptation-plan':fail('小说分集须引用固定全剧计划')
        if tool=="qc":
            for scope in doc["check_ranges"]:
                if scope["media_id"] not in {r["media_id"] for r in doc["videos"]}:fail("复检区间只能引用本次检查视频")
                media=self.store.get_media(project_id,scope["media_id"])
                if scope["end_ms"]>(media.get("duration_ms") or 0):fail("局部复检区间越界")
            if doc["check_ranges"] and not doc["base_report_version_id"]:fail("局部复检须固定此前已接受的质检版本")
            if doc["base_report_version_id"]:
                old=self.store.get_artifact_version(project_id,doc["base_report_version_id"]);prior=json.loads(old["document"])
                if old["artifact_type"]!="text-tool-draft" or prior.get("format")!="vsc.text-tool/qc/v1":fail("复检基线必须是本项目质检版本")
                old_media={r["media_id"]:r["sha256"] for r in prior["videos"]}
                if any(old_media.get(r["media_id"])!=self.store.get_media(project_id,r["media_id"])["sha256"] for r in doc["videos"]):fail("局部复检不能更换基线媒体")
            for row in doc["videos"]:
                media=self.store.get_media(project_id,row["media_id"])
                if media["modality"]!="video":fail("质检仅接受已登记视频")
                if row.get("sha256") and row["sha256"]!=media["sha256"]:raise Conflict("质检素材摘要不匹配")
                row.update(sha256=media["sha256"],name=media["name"])
            if len({r["media_id"] for r in doc["videos"]})!=len(doc["videos"]) or len({r["filename"] for r in doc["subtitles"]})!=len(doc["subtitles"]):fail("视频或字幕不能重复")
            if len({r["video_id"] for r in doc["matches"]})!=len(doc["matches"]) or len({r["subtitle_name"] for r in doc["matches"]})!=len(doc["matches"]):fail("显式字幕匹配须为一对一")
            for row in doc["matches"]:
                if row["video_id"] not in {r["media_id"] for r in doc["videos"]} or row["subtitle_name"] not in {r["filename"] for r in doc["subtitles"]}:fail("字幕匹配指向当前列表之外")
        if tool in {"overseas","breakdown"}:
            mid=doc.get("source_media_id") or doc.get("media_id")
            if mid:
                media=self.store.get_media(project_id,mid)
                if media["modality"]!="video":fail("需要已登记视频")
                duration=media.get("duration_ms")
                ranges=doc.get("groups",doc.get("observations",[]))
                if ranges and (not duration or any(r.get("source_end_ms",r.get("end_ms",0))>duration for r in ranges)):fail("时码超出源媒体已登记时长")
                if not any(ref["kind"]=="media" and ref["id"]==mid for ref in doc["source_refs"]):doc["source_refs"].append({"kind":"media","id":mid,"sha256":media["sha256"]})
            for entity in doc.get("entities",[]):
                if entity["asset_id"]:
                    tree=self.get_project_tree(project_id)
                    if not any(row["id"]==entity["asset_id"] and row["kind"]=="asset" for row in tree["nodes"]):fail("实体资产不属于本项目")
                if entity["media_id"]:self.store.get_media(project_id,entity["media_id"])
            for group in doc.get("groups",[]):
                from vsc.production.overseas_production import duration
                if group["candidate_media_id"]:
                    media=self.store.get_media(project_id,group["candidate_media_id"])
                    if media["modality"]!="video" or not media.get("duration_ms") or group["candidate_in_ms"]+duration(group)>media["duration_ms"]:fail("组候选视频不足以覆盖所选片段")
                    if not any(ref["kind"]=="media" and ref["id"]==media["id"] for ref in doc["source_refs"]):doc["source_refs"].append({"kind":"media","id":media["id"],"sha256":media["sha256"]})
        return doc

    def preview_overseas_merge(self,project_id,payload):
        return self.store.preview_overseas_merge(project_id,payload)

    def merge_overseas_entities(self,project_id,payload,**kw):
        self._validate_write(payload,**kw)
        return self.store.merge_overseas_entities(project_id,payload,**kw)

    def stage_overseas_baseline(self,project_id,payload,**kw):
        self._validate_write(payload,**kw)
        return self.store.stage_overseas_baseline(project_id,payload,**kw)

    def prepare_overseas_group(self,project_id,payload,**kw):
        self._validate_write(payload,**kw)
        return self.store.prepare_overseas_group(project_id,payload,build_document=self._classic_document,**kw)

    def prepare_overseas_asset_image(self,project_id,payload,**kw):
        self._validate_write(payload,**kw)
        return self.store.prepare_overseas_asset_image(project_id,payload,build_document=self._classic_document,**kw)

    def select_overseas_asset_image(self,project_id,payload,**kw):
        self._validate_write(payload,**kw)
        return self.store.select_overseas_asset_image(project_id,payload,**kw)

    def preview_overseas_group_run(self,project_id,payload):
        from vsc.production.quotes import fingerprint
        if not isinstance(payload,dict) or not payload.get("group_draft_id"):fail("预览需要固定分组制作稿")
        fixed=self.store.overseas_group_input(project_id,payload.get("group_draft_id"))
        if set(payload)-{"group_draft_id","execution_policy","commerce_account_actor"}:fail("分组预览字段无效")
        result=self.preview_classic_run(project_id,{"draft_version_id":fixed["classic_draft_id"],"execution_policy":payload.get("execution_policy"),
            **({"commerce_account_actor":payload["commerce_account_actor"]} if "commerce_account_actor" in payload else {})})
        if result["ready"]:
            artifact=result["artifact"];run=artifact["document"]
            artifact["artifact_key"]="overseas-run:"+payload["group_draft_id"]
            artifact["dependency_ids"].append(fixed["localization_version_id"])
            baseline=self.get_artifact_version(project_id,fixed["localization_version_id"])
            run["approved_inputs"].append({"id":baseline["id"],"sha256":baseline["sha256"]})
            run["overseas_group"]={**fixed,"group_draft_id":payload["group_draft_id"]}
            result["preview_sha256"]=fingerprint(artifact)
        return result

    def propose_overseas_group_run(self,project_id,payload,**kw):
        self._validate_write(payload,**kw)
        return self.store.propose_overseas_group_run(project_id,payload,build_preview=self.preview_overseas_group_run,**kw)

    def select_overseas_candidate(self,project_id,payload,**kw):
        self._validate_write(payload,**kw)
        return self.store.select_overseas_candidate(project_id,payload,normalize=self._text_tool_document,**kw)

    def save_text_tool(self,project_id,payload,**kw):
        self._validate_write(payload,**kw)
        return self.store.save_text_tool(project_id,payload,normalize=self._text_tool_document,**kw)

    def set_text_tool_lock(self,project_id,payload,**kw):
        self._validate_write(payload,**kw)
        if set(payload)!={"unit_id","locked"} or type(payload["locked"]) is not bool:fail("锁定需要单元与布尔值")
        return self.store.set_text_tool_lock(project_id,payload,**kw)

    def accept_text_tool_result(self,project_id,payload,**kw):
        self._validate_write(payload,**kw)
        if set(payload)!={"attempt_id","base_version_id"}:fail("接受结果需要任务与所见人工稿版本")
        return self.store.accept_text_tool_result(project_id,payload,normalize=self._text_tool_document,**kw)

    def merge_text_tools(self,project_id,payload,**kw):
        self._validate_write(payload,**kw)
        if set(payload)!={"tool","version_ids","title"} or payload["tool"] not in TOOLS or not isinstance(payload["version_ids"],list) or not 1<=len(payload["version_ids"])<=200:fail("合并需要明确工具、固定版本列表和标题")
        text(payload["title"],200,False)
        return self.store.merge_text_tools(project_id,payload,**kw)

    def extract_text_tool_source(self,project_id,payload):
        from vsc.assets.source_intake import extract_source
        self.get_project(project_id)
        if not isinstance(payload,dict) or set(payload)-{"content_base64","media_id","format","parameters","split"}:fail("文件提取参数无效")
        if payload.get('media_id'):
            if 'content_base64' in payload:fail('请选择唯一固定文件输入')
            path,media=self._text_tool_path(project_id,payload['media_id'])
            if media['modality'] not in {'document','text'} or not 0<path.stat().st_size<=10*1024*1024:fail('文本来源须为不超过10MiB的已登记文档')
            raw=path.read_bytes()
        else:
            try:raw=base64.b64decode(payload["content_base64"],validate=True)
            except (ValueError,KeyError,TypeError):fail("文件内容不是有效编码")
        if not 0<len(raw)<=10*1024*1024:fail("文件须为非空且不超过10MiB")
        value=extract_source(raw,payload.get("format"),payload.get("parameters"))
        expression=r"(?m)^(第[零一二三四五六七八九十百千0-9]+章[^\n]*)" if payload.get("split")=="chapters" else r"(?m)^((?:第[零一二三四五六七八九十百千0-9]+集|EP\s*\d+)[^\n]*)"
        matches=list(re.finditer(expression,value["text"]))
        units=[]
        if matches:
            if value["text"][:matches[0].start()].strip():units.append({"title":"前言","source_text":value["text"][:matches[0].start()]})
            for i,match in enumerate(matches):units.append({"title":match.group(1),"source_text":value["text"][match.start():matches[i+1].start() if i+1<len(matches) else None]})
        else:units=[{"title":"未分章文本","source_text":value["text"]}]
        return {**value,"units":units,"requires_range_review":True}

    def _text_tool_path(self,project_id,media_id):
        if self.storage is None:fail("未配置媒体存储","media_unavailable")
        media=self.store.get_media(project_id,media_id)
        location=next((r for r in media["locations"] if r["storage"]=="local"),None)
        if not location:fail("本机质检需要可核验的本地媒体副本","media_unavailable")
        return self.storage.verify(location["object_key"],media["sha256"]),media

    def check_text_tool_quality(self,project_id,document,request_id='local'):
        from vsc.adapters.media.qa import LocalProbeAdapter,ProbeFailure
        from vsc.post.subtitles import parse_srt,SubtitleError
        from vsc.post.local_media_tools import command
        videos=document["videos"]
        if not videos:fail("质检至少需要一个视频")
        matching=subtitle_matches(videos,document["subtitles"])
        chosen={r["video_id"]:r["subtitle_name"] for r in document["matches"]}
        for row in matching:
            if row["status"]=="matched" and row["video_ids"][0] not in chosen:chosen[row["video_ids"][0]]=row["subtitle_name"]
        if set(document['checks'])&{'subtitles','subtitle_semantics'} and (len(set(chosen.values()))!=len(chosen) or set(chosen)!={v["media_id"] for v in videos}):fail("字幕缺失或匹配有歧义，请显式逐项选择","subtitle_match_conflict")
        subtitles={r["filename"]:r["text"] for r in document["subtitles"]}
        ranges=document.get("check_ranges",[])
        issues=[]
        if document.get("base_report_version_id") and ranges:
            old=self.store.get_artifact_version(project_id,document["base_report_version_id"])
            if old["artifact_type"]!="text-tool-draft":fail("复检基线须为已接受的质检稿")
            prior=json.loads(old["document"])
            if prior.get("format")!="vsc.text-tool/qc/v1":fail("复检基线须为质检稿")
            for old_issue in prior["issues"]:
                affected=[r for r in ranges if r["media_id"]==old_issue["media_id"]]
                if not affected or old_issue.get("rule") not in document["checks"]:
                    issues.append(old_issue);continue
                spans=[(old_issue["start_ms"],old_issue["end_ms"])]
                for r in affected:
                    next_spans=[]
                    for a,b in spans:
                        if b<=r["start_ms"] or a>=r["end_ms"]:next_spans.append((a,b))
                        else:
                            if a<r["start_ms"]:next_spans.append((a,r["start_ms"]))
                            if b>r["end_ms"]:next_spans.append((r["end_ms"],b))
                    spans=next_spans
                issues.extend(dict(old_issue,start_ms=a,end_ms=b) for a,b in spans)
        for video in videos:
            mid=video["media_id"]
            selected=[r for r in ranges if r["media_id"]==mid]
            if ranges and not selected:continue
            path,media=self._text_tool_path(project_id,mid)
            duration=media.get("duration_ms") or 0
            if not duration:fail("检查视频需要有效时长")
            selected=selected or [dict(media_id=mid,start_ms=0,end_ms=duration)]
            for window in selected:
                a,b=window["start_ms"],window["end_ms"]
                if not 0<=a<b<=duration:fail("局部复检区间越界")
                for rule in document["checks"]:
                    if rule not in {'metadata','subtitles','decode'}:
                        from vsc.post.subtitle_formats import normalize_subtitle
                        sub=normalize_subtitle(chosen[mid],subtitles[chosen[mid]],duration=duration/1000) if mid in chosen else None
                        if rule=='content' and not document.get('content_rules'):fail('内容检查需要明确规则，不使用隐藏标准')
                        result=self._understand_media(project_id,document,action='check',request_id=request_id+':'+mid+':'+rule+':'+str(a),media_id=mid,start_ms=a,end_ms=b,checks=[rule],subtitle=sub)
                        issues.extend(result['issues']);continue
                    try:
                        if rule=="metadata":LocalProbeAdapter().probe(path)
                        elif rule=="decode":command(['ffmpeg','-v','error','-xerror','-nostdin','-protocol_whitelist','file,pipe','-ss',str(a/1000),'-i',str(path),'-t',str((b-a)/1000),'-f','null','-'],60)
                        else:
                            from vsc.post.subtitle_formats import normalize_subtitle
                            original=normalize_subtitle(chosen[mid],subtitles[chosen[mid]],duration=duration/1000,require_timing=True)['srt']
                            selected_blocks=[]
                            for block in re.split(r"\n\s*\n",original.strip().replace("\r\n","\n")):
                                timed=parse_srt(block,strict=False)
                                if not timed or any(start*1000<b and end*1000>a for start,end,_ in timed):selected_blocks.append(block)
                            if selected_blocks:parse_srt("\n\n".join(selected_blocks),strict=True,duration=duration/1000)
                        issues.append(dict(rule=rule,media_id=mid,start_ms=a,end_ms=b,code="local_checks_passed",severity="info",message=rule+"：所选本地技术检查通过（固定范围）；不代表内容质量",evidence=media["sha256"]))
                    except (ResourceError,ProbeFailure,SubtitleError,ValueError,KeyError) as error:
                        issues.append(dict(rule=rule,media_id=mid,start_ms=a,end_ms=b,code=getattr(error,"code","local_check_failed"),severity="error",message=str(error)[:2000],evidence=video["sha256"]))
        return {"issues":issues}

    def run_text_tool(self,project_id,payload,*,_materials_artifact_id=None,**kw):
        from vsc.production.text_tool_host import GrokBuildTextTools
        self._validate_write(payload,**kw)
        if set(payload)-{"unit_id","input_version_id","action","new_attempt"} or type(payload.get("new_attempt",False)) is not bool:fail("运行需要固定单元、版本和动作")
        backend=getattr(self,"text_tool_host",None) or GrokBuildTextTools()
        if payload.get('action') in {'observe','check','understand'}:
            from vsc.production.media_understanding import default_media_host
            media_backend=getattr(self,'media_understanding_host',None) or default_media_host()
        caller=str(uuid.uuid4())
        start=self.store.start_text_tool_attempt(project_id,payload,backend=media_backend.name if payload.get('action') in {'observe','check','understand'} else backend.name,caller=caller,materials_artifact_id=_materials_artifact_id,**kw)
        run=self.store.get_text_tool_attempt(project_id,start["id"])
        if start.get("caller")!=caller or run["status"]!="running":return run
        unit=self.store.get_text_tool(project_id,run["unit_id"])
        doc=json.loads(self.store.get_artifact_version(project_id,run["input_version_id"])["document"])
        result,error=None,None
        try:
            if run['action']=='understand':result=self._understand_overseas(project_id,doc,run['id'])
            elif run["action"]=="check":result=self.check_text_tool_quality(project_id,doc,run['id'])
            elif run['action']=='observe' and doc.get('understanding_mode','manual')!='manual':
                result=self._understand_media(project_id,doc,action='observe',request_id=run['id'],media_id=doc['media_id'])
            else:
                if not backend.available():fail("当前没有可用文本宿主；人工稿与本地导出仍可使用","text_host_unavailable")
                if run["action"]=="observe" and not doc["observations"] and not doc["source_text"].strip():fail("文本宿主不能读取视频，需要先记录带时码观察或提供转录","video_understanding_unavailable")
                if run["action"]=="score" and not doc["criteria"]:fail("评分需要显式标准与分数上限")
                references=run.get('references',[])
                if unit["tool"]=="translation" and doc.get("style_request"):
                    proposed=backend.generate("translation-style","body",{**doc,"requested_output":"仅创作可复用翻译风格说明，包含语气、节奏、称谓和术语原则；不要翻译正文"},references)
                    result={"style":proposed["body"],"style_version_id":""}
                else:
                    from vsc.production.text_tools import host_input
                    extra={}
                    if unit['tool']=='novel' and run.get('role_materials_manifest'):
                        from vsc.production.text_tools import novel_execution_materials
                        extra['materials']=novel_execution_materials(run['action'],run['role_materials_manifest'])
                    result=backend.generate(unit["tool"],run["action"],host_input(unit['tool'],doc,run['action']),references,**extra)
            result=validated_result(unit["tool"],run["action"],result,doc)
        except ResourceError as exc:error=exc.code
        except Exception:error="text_submission_unknown"
        # Receiving an already accepted call is not a new user action. Keep
        # its response even if access was revoked while the host was running.
        self.store.persist_text_tool_receipt(project_id,run["id"],result if error is None else None,error)
        return self.store.finish_text_tool_attempt(project_id,run["id"],result,error,actor=kw["actor"])

    def text_tool_export(self,project_id,version_id,format,view='translation'):
        from vsc.post.text_tool_exports import export_document
        value=self.store.get_artifact_version(project_id,version_id)
        if value["artifact_type"] not in {"text-tool-draft","text-tool-bundle","text-tool-result","text-tool-review-report"}:fail("此版本不是文本工具输出")
        document=json.loads(value["document"])
        if document.get('format')=='vsc.text-tool/scoring/v1':document=self.store.scoring_export_document(project_id,version_id)
        if value["artifact_type"]=="text-tool-result":fail("请先比较并接受结果，再导出人工工作稿")
        return export_document(document,format,lambda mid:self._text_tool_path(project_id,mid),view=view)

    def create_novel_plan(self,project_id,payload,**kw):
        self._validate_write(payload,**kw)
        return self.store.create_novel_plan(project_id,payload,**kw)

    def preview_novel_batch_import(self,project_id,payload):return self.store.preview_novel_batch_import(project_id,payload)

    def import_novel_batch(self,project_id,payload,**kw):
        self._validate_write(payload,**kw)
        return self.store.import_novel_batch(project_id,payload,**kw)

    def preview_text_tool_import(self,project_id,payload):
        return self.store.preview_text_tool_import(project_id,payload)

    def import_text_tool(self,project_id,payload,**kw):
        self._validate_write(payload,**kw)
        return self.store.import_text_tool(project_id,payload,**kw)


    def save_translation_style(self,project_id,payload,**kw):
        self._validate_write(payload,**kw)
        return self.store.save_translation_style(project_id,payload,**kw)

    def list_translation_styles(self,project_id):return self.store.list_translation_styles(project_id)
    def preview_novel_tool_import(self,project_id,payload):return self.store.preview_novel_tool_import(project_id,payload)
    def import_text_tool_novel(self,project_id,payload,**kw):
        self._validate_write(payload,**kw)
        return self.store.import_text_tool_novel(project_id,payload,**kw)

    def capture_text_tool_evidence(self,project_id,payload,**kw):
        self._validate_write(payload,**kw)
        if set(payload)!={"version_id","issue_index"} or type(payload["issue_index"])is not int:fail("证据帧须固定质检版本和问题序号")
        def build(media,at):
            import tempfile
            from pathlib import Path
            from vsc.post.local_media_tools import frame
            path,_=self._text_tool_path(project_id,media["id"])
            with tempfile.TemporaryDirectory(prefix="vsc-qc-evidence-") as directory:
                target=Path(directory)/"qc-evidence.png";receipt=frame(path,target,'current',at)
                with target.open('rb') as stream:staged=self.storage.stage_upload(stream,target.name)
                return self.storage.commit_upload(staged['staged_upload']),receipt
        return self.store.capture_text_tool_evidence(project_id,payload,build=build,**kw)

    def preview_text_tool_subtitles(self,project_id,payload):return self.store.preview_text_tool_subtitles(project_id,payload)
    def apply_text_tool_subtitles(self,project_id,payload,**kw):
        self._validate_write(payload,**kw)
        return self.store.apply_text_tool_subtitles(project_id,payload,**kw)

    def create_text_batch(self,project_id,payload,**kw):
        self._validate_write(payload,**kw)
        return self.store.create_text_batch(project_id,payload,**kw)

    def get_text_batch(self,project_id,batch_id):return self.store.get_text_batch(project_id,batch_id)
    def list_text_batches(self,project_id,tool):return self.store.list_text_batches(project_id,tool)

    def process_text_batch(self,project_id,payload,**kw):
        self._validate_write(payload,**kw)
        if set(payload)!={'batch_id'}:fail('批次接续需要原批次身份')
        def authority(key):return dict(actor=kw['actor'],expected_revision=self.get_project(project_id)['revision'],idempotency_key=key)
        claim=self.store.claim_text_batch(project_id,payload,**authority('batch-claim:'+str(uuid.uuid4())))
        item=claim.get('item')
        if not item:return self.get_text_batch(project_id,payload['batch_id'])
        run=None;output=None;status='blocked';error=None
        try:
            run=self.run_text_tool(project_id,{'unit_id':item['unit_id'],'input_version_id':item['input_version_id'],'action':item['action'],'new_attempt':False},_materials_artifact_id=claim.get('materials_artifact_id'),**authority('batch-run:'+item['id']))
            run=self.get_text_tool_attempt(project_id,run['id'])
            if run['status']=='completed':
                if claim['auto_accept']:
                    output=self.accept_text_tool_result(project_id,{'attempt_id':run['id'],'base_version_id':item['input_version_id']},**authority('batch-adopt:'+item['id']))['id']
                status='completed'
            elif run['status']=='failed':status='failed';error=run.get('error_code')
            else:status='running';error=run.get('error_code')
        except ResourceError as exc:error=exc.code
        self.store.finish_text_batch_item(project_id,{'item_id':item['id'],'status':status,'attempt_id':run['id'] if run else None,'output_version_id':output,'error_code':error},**authority('batch-finish:'+item['id']+':'+status))
        if status=='completed':self.store.claim_text_batch(project_id,payload,**authority('batch-settle:'+str(uuid.uuid4())))
        return self.get_text_batch(project_id,payload['batch_id'])

    def stop_text_batch(self,project_id,payload,**kw):
        self._validate_write(payload,**kw)
        if set(payload)!={'batch_id'}:fail('停止需要固定批次')
        return self.store.stop_text_batch(project_id,payload,**kw)

    def decide_text_issue(self,project_id,payload,**kw):
        self._validate_write(payload,**kw)
        return self.store.decide_text_issue(project_id,payload,**kw)

    def freeze_text_review_report(self,project_id,payload,**kw):
        self._validate_write(payload,**kw)
        if set(payload)!={'version_id'}:fail('报告需要固定工作稿')
        return self.store.freeze_text_review_report(project_id,payload,**kw)

    def set_translation_stage(self,project_id,payload,**kw):
        self._validate_write(payload,**kw)
        return self.store.set_translation_stage(project_id,payload,**kw)

    def _understand_media(self,project_id,document,*,action,request_id,media_id,start_ms=0,end_ms=None,checks=None,subtitle=None):
        from vsc.production.media_understanding import default_media_host
        backend=getattr(self,'media_understanding_host',None) or default_media_host()
        if not backend.available():fail('当前没有可用媒体理解宿主','media_understanding_unavailable')
        required=set(checks or ['observe'])
        if required-set(backend.capabilities):fail('当前宿主不支持所选媒体理解能力；抽帧宿主不能听音轨','media_capability_unavailable')
        path,media=self._text_tool_path(project_id,media_id);duration=media.get('duration_ms') or 0;end_ms=end_ms or duration
        if not 0<=start_ms<end_ms<=duration:fail('媒体理解区间越界')
        if path.stat().st_size>256*1024*1024:fail('单次媒体理解源文件超过256MiB，请先裁剪')
        request={'request_id':request_id,'action':action,'media':{'id':media['id'],'sha256':media['sha256'],'duration_ms':duration,'mime_type':media.get('mime_type')},
            'mode':document.get('understanding_mode','light'),'start_ms':start_ms,'end_ms':end_ms,'checks':list(required),
            'rule_version':document.get('rule_version','vsc.media-understanding/v1'),'content_rules':document.get('content_rules',[]),'subtitles':subtitle}
        result=backend.analyze(request,path)
        if not isinstance(result,dict) or set(result)!={'observations' if action=='observe' else 'issues'}:fail('媒体理解结果结构无效','invalid_media_understanding_result')
        rows=result['observations' if action=='observe' else 'issues']
        if not isinstance(rows,list) or len(rows)>500:fail('媒体理解行数无效','invalid_media_understanding_result')
        for row in rows:
            if type(row.get('start_ms'))is not int or type(row.get('end_ms'))is not int or not start_ms<=row['start_ms']<row['end_ms']<=end_ms:fail('媒体结果区间越界','invalid_media_understanding_result')
            if action!='observe':
                if row.get('rule') not in required or row.get('severity') not in {'info','warning','error'}:fail('媒体质检返回了未请求规则或无效级别','invalid_media_understanding_result')
                row.update(media_id=media_id,rule_version=request['rule_version'])
        if action=='observe':result['observation_basis']=backend.basis
        return result

    def _understand_overseas(self,project_id,document,request_id):
        from vsc.production.media_understanding import default_media_host
        from vsc.production.overseas_production import understanding_patch
        if document['understanding_mode']=='manual':fail('当前选择人工观察，请直接编辑理解稿；自动读取需先选择轻量或深度视觉抽样','media_capability_unavailable')
        host=getattr(self,'media_understanding_host',None) or default_media_host()
        if not host.available() or 'understand' not in host.capabilities:fail('当前媒体宿主没有结构化视频理解能力','media_capability_unavailable')
        path,media=self._text_tool_path(project_id,document['source_media_id'])
        if not media.get('duration_ms') or path.stat().st_size>256*1024*1024:fail('源视频时长无效或超过256MiB，请先裁剪')
        request={'request_id':request_id,'action':'understand','mode':document['understanding_mode'],'media':{'id':media['id'],'sha256':media['sha256'],'duration_ms':media['duration_ms'],'mime_type':media['mime_type']},'start_ms':0,'end_ms':media['duration_ms']}
        return understanding_patch(host.analyze(request,path),media['duration_ms'],host.basis)

    def overseas_registry_options(self,project_id,unit_id):
        from vsc.adapters.providers.asset_registry import CommandAssetRegistry
        from vsc.adapters.persistence.postgres.provider_assets import ProviderAssetRepository
        host=getattr(self,'asset_registry',None) or CommandAssetRegistry()
        return {**ProviderAssetRepository(self.store).list(project_id,unit_id),'available':host.available(),'provider':host.provider,'account_scope':host.account_scope,'message':'注册需供应商专门回执；已登记图片不等于远端资产。' if host.available() else '未配置供应商资产注册能力；可继续用参考图片工作生成，不能声称已注册。'}

    def register_overseas_asset(self,project_id,payload,**kw):
        self._validate_write(payload,**kw)
        if set(payload)-{'unit_id','version_id','entity_key','new_attempt'} or not {'unit_id','version_id','entity_key'}<=set(payload) or type(payload.get('new_attempt',False))is not bool:fail('资产注册需固定原实体及所见版本')
        from vsc.adapters.providers.asset_registry import CommandAssetRegistry,validated_receipt
        from vsc.adapters.persistence.postgres.provider_assets import ProviderAssetRepository
        host=getattr(self,'asset_registry',None) or CommandAssetRegistry()
        if not host.available():fail('未配置供应商资产注册能力，原参考图保留','asset_registry_unavailable')
        caller=str(uuid.uuid4());repo=ProviderAssetRepository(self.store)
        started=repo.start(project_id,payload,host.provider,host.account_scope,caller,**kw)
        if started.get('caller')!=caller:return started
        request={k:started[k] for k in ('provider','account_scope','entity_key','media_id','media_sha256')};request['request_id']=started['id']
        status='submission_unknown';receipt=None;error=None
        try:
            path,media=self._text_tool_path(project_id,started['media_id'])
            self._verify_media(project_id,media['id'],media['sha256'])
            receipt=validated_receipt(host.register(request,path),request);status='completed'
        except ResourceError as exc:status='failed' if exc.code in {'asset_registry_failed','asset_reference_required','media_unavailable','media_changed','rights_restricted'} else 'submission_unknown';error=exc.code
        return repo.finish(project_id,{'id':started['id'],'status':status,'receipt':receipt,'error_code':error},actor=kw['actor'],expected_revision=self.get_project(project_id)['revision'],idempotency_key='provider-asset-receipt:'+started['id'])

    def apply_text_issue_subtitle(self,project_id,payload,**kw):
        self._validate_write(payload,**kw)
        if set(payload)!={'unit_id','version_id','issue_index','subtitle_filename'} or type(payload['issue_index'])is not int:fail('字幕建议采用需固定问题与字幕文件')
        unit=self.get_text_tool(project_id,payload['unit_id'])
        if unit['tool']!='qc' or unit['current_version_id']!=payload['version_id']:raise Conflict('质检工作稿已变化')
        doc=deepcopy(unit['document'])
        if not 0<=payload['issue_index']<len(doc['issues']):fail('问题序号越界')
        issue=doc['issues'][payload['issue_index']]
        if not issue.get('suggested_subtitle') or not issue.get('original_subtitle'):fail('此问题没有可精确采用的字幕建议')
        subtitle=next((s for s in doc['subtitles'] if s['filename']==payload['subtitle_filename']),None)
        if not subtitle:fail('字幕不属于当前报告')
        from vsc.post.subtitle_formats import normalize_subtitle
        from vsc.post.subtitles import to_srt
        cues=normalize_subtitle(subtitle['filename'],subtitle['text'],require_timing=True)['cues']
        matched=[c for c in cues if c['text']==issue['original_subtitle'] and c['start_ms']<issue['end_ms'] and c['end_ms']>issue['start_ms']]
        if len(matched)!=1:fail('字幕原文及时码匹配有歧义，请手工校正','subtitle_suggestion_conflict')
        matched[0]['text']=issue['suggested_subtitle'];name=subtitle['filename'].rsplit('.',1)[0]+'.corrected.srt'
        existing=next((s for s in doc['subtitles'] if s['filename']==name),None)
        value={'filename':name,'text':to_srt([(c['start_ms']/1000,c['end_ms']/1000,c['text']) for c in cues])}
        if existing:existing.update(value)
        else:doc['subtitles'].append(value)
        doc['matches']=[m for m in doc['matches'] if m['video_id']!=issue['media_id']]+[{'video_id':issue['media_id'],'subtitle_name':name}]
        doc.update(base_report_version_id=payload['version_id'],check_ranges=[{'media_id':issue['media_id'],'start_ms':issue['start_ms'],'end_ms':issue['end_ms']}],checks=[issue['rule']])
        request={k:unit[k] for k in ('tool','group_key','unit_key','title','ordinal','episode_id')}
        return self.save_text_tool(project_id,dict(request,unit_id=unit['id'],base_version_id=unit['current_version_id'],document=doc),**kw)

    def preview_breakdown_canvas(self,project_id,payload):return self.store.preview_breakdown_canvas(project_id,payload)
    def apply_breakdown_canvas(self,project_id,payload,**kw):
        self._validate_write(payload,**kw)
        return self.store.apply_breakdown_canvas(project_id,payload,**kw)
