"""Typed creative documents and their original generation-task consumer.

The canvas owns editing history only. Media, approvals and task states remain
owned by their original repositories; preparing a node never submits a provider.
"""
from copy import deepcopy
import json
import math
import re

from vsc.assets.resource_service import ResourceError


NODE_TYPES = {
    "text": {"label": "文本", "inputs": {}, "output": "text"},
    "image": {"label": "图片", "inputs": {"prompt": "text", "reference": "image"}, "output": "image"},
    "video": {"label": "视频", "inputs": {"prompt": "text", "first_frame": "image", "last_frame": "image",
              "reference_image": "image", "reference_video": "video", "reference_audio": "audio"}, "output": "video"},
    "audio": {"label": "音频", "inputs": {"prompt": "text", "reference_audio": "audio"}, "output": "audio"},
    "spatial": {"label": "三维预演", "inputs": {"prompt": "text", "reference": "image"}, "output": "spatial"},
    "director": {"label": "导演台", "inputs": {"prompt": "text", "reference": "image"}, "output": "spatial"},
    "edit": {"label": "剪辑", "inputs": {"visual": ["image", "video"], "sound": "audio"}, "output": "video"},
    "music_mix": {"label": "视频配乐", "inputs": {"source_video": "video", "sound": "audio", "prompt": "text"}, "output": "video"},
    "processing": {"label": "视频加工", "inputs": {"source_video": "video", "prompt": "text"}, "output": "media"},
}
DOMAIN_TYPES = {"spatial", "director", "edit", "music_mix", "processing"}
CANVAS_IMAGE_TOOL = "vsc_image_tool"
CANVAS_IMAGE_TOOL_SETTINGS = "vsc_image_tool_settings"
CANVAS_IMAGE_TOOLS = (
    "angle", "lighting", "three_view", "headshot", "face_views",
    "texture", "expression", "panorama", "upscale", "watermark",
    "inpaint", "outpaint", "matting",
    "multi_camera_grid_2k", "multi_camera_grid_4k", "story_four_grid",
    "cinematic_lighting", "frame_predict_3s_after", "frame_predict_5s_before",
)
CANVAS_FIXED_IMAGE_TOOLS = {
    "three_view", "headshot", "face_views",
    "multi_camera_grid_2k", "multi_camera_grid_4k", "story_four_grid",
    "cinematic_lighting", "frame_predict_3s_after", "frame_predict_5s_before",
}


def canvas_image_tool_options():
    from vsc.production.image_tools import TOOLS
    options = {tool: deepcopy(TOOLS[tool][1]) for tool in CANVAS_IMAGE_TOOLS if tool in TOOLS}
    if "lighting" in options:
        options["lighting"]["intensity"] = 0.5
        options["lighting"]["view"] = "perspective"
    return options


def canvas_image_tool(kind, params):
    """Validate the canvas-owned tool descriptor without passing it to a provider."""
    keys = {CANVAS_IMAGE_TOOL, CANVAS_IMAGE_TOOL_SETTINGS}
    present = keys.intersection(params)
    if not present:
        return None
    opts = canvas_image_tool_options()
    if present != keys or kind != "image" or not isinstance(params.get(CANVAS_IMAGE_TOOL), str) or params[CANVAS_IMAGE_TOOL] not in opts:
        _fail("画布图像工具及其参数必须同时绑定到图片节点", "invalid_canvas_image_tool")
    raw = params[CANVAS_IMAGE_TOOL_SETTINGS]
    if not isinstance(raw, str):
        _fail("画布图像工具参数须为 JSON 字符串", "invalid_canvas_image_tool")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result
    def reject_constant(_):
        raise ValueError("nonfinite")
    try:
        settings = json.loads(raw, object_pairs_hook=pairs, parse_constant=reject_constant)
    except (ValueError, TypeError, RecursionError):
        _fail("画布图像工具参数 JSON 无效", "invalid_canvas_image_tool")
    from vsc.production.image_tools import normalize_tool
    if not isinstance(settings, dict):
        _fail("画布图像工具参数须为 JSON 对象", "invalid_canvas_image_tool")
    tool = params[CANVAS_IMAGE_TOOL]
    normalized = normalize_tool(tool, {**opts[tool], **settings})
    if tool in CANVAS_FIXED_IMAGE_TOOLS and normalized != opts[tool]:
        _fail("画布图片生成工具使用固定视图规格", "invalid_canvas_image_tool")
    if tool == "angle" and not normalized["include_instructions"]:
        _fail("画布多角度必须包含固定角度指令", "invalid_canvas_image_tool")
    return {"tool": tool, "settings": normalized}


def accepts_port(target_type, port, source_type):
    if port == "derived_from":
        return target_type in {"text", "image", "video", "audio"} and source_type in NODE_TYPES
    expected = NODE_TYPES[target_type]["inputs"].get(port)
    return source_type in expected if isinstance(expected, list) else source_type == expected


def _fail(message, code="invalid_canvas"):
    raise ResourceError(message, code)


def _key(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value):
        _fail("节点及连线标识须为 1–100 位字母、数字、下划线或短横线")
    return value


def _number(value, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high or not math.isfinite(value):
        _fail("画布坐标或缩放超出范围")
    return float(value)


def normalize_document(value):
    """Reject dangling/typed/cyclic edges before any relational mutation."""
    if not isinstance(value, dict) or set(value) - {"nodes", "edges", "viewport"}:
        _fail("画布文档仅接受节点、连线和视口")
    nodes, edges = value.get("nodes", []), value.get("edges", [])
    if not isinstance(nodes, list) or not isinstance(edges, list) or len(nodes) > 200 or len(edges) > 800:
        _fail("单个画布最多 200 个节点、800 条连线")
    result, by_id = [], {}
    for node in nodes:
        if not isinstance(node, dict) or set(node) - {"id", "type", "title", "x", "y", "text", "params", "media_id", "job_id", "group", "domain_object_id", "domain_version_id"}:
            _fail("节点包含未支持的字段；运行状态不能写入画布")
        key = _key(node.get("id"))
        kind = node.get("type")
        if key in by_id or not isinstance(kind, str) or kind not in NODE_TYPES:
            _fail("节点标识重复或类型未支持")
        title, content, group = node.get("title", NODE_TYPES[kind]["label"]), node.get("text", ""), node.get("group", "")
        if not isinstance(title, str) or not title.strip() or len(title) > 200 or not isinstance(content, str) or len(content) > 50000:
            _fail("节点标题或文本长度不正确")
        if not isinstance(group, str) or len(group) > 100:
            _fail("分组名称最长 100 字")
        params = node.get("params", {})
        if not isinstance(params, dict) or len(params) > 40 or any(not isinstance(k, str) or len(k) > 100 or
                not isinstance(v, (str, int, float, bool, type(None))) or isinstance(v, str) and len(v) > 2000 or
                isinstance(v, float) and not math.isfinite(v) for k, v in params.items()):
            _fail("节点参数必须是有界的简单键值")
        canvas_image_tool(kind, params)
        if kind == "text" and (node.get("media_id") or node.get("job_id")):
            _fail("文本节点不能伪装媒体或生成任务")
        row = {"id": key, "type": kind, "title": title.strip(), "x": _number(node.get("x", 0), -100000, 100000),
            "y": _number(node.get("y", 0), -100000, 100000), "text": content, "params": deepcopy(params), "group": group,
            "media_id": node.get("media_id") or None, "job_id": node.get("job_id") or None}
        if kind in DOMAIN_TYPES:
            if row["media_id"] or row["job_id"]:
                _fail("工具节点引用原领域对象；输出放入独立媒体节点")
            object_id, version_id = node.get("domain_object_id"), node.get("domain_version_id")
            if bool(object_id) != bool(version_id):
                _fail("工具节点必须同时固定原对象与版本")
            row.update(domain_object_id=object_id or None, domain_version_id=version_id or None)
        elif node.get("domain_object_id") or node.get("domain_version_id"):
            _fail("媒体节点不接受工具对象引用")
        result.append(row)
        by_id[key] = row
    links, ids, signatures, single_ports = [], set(), set(), set()
    successors = {key: [] for key in by_id}
    for edge in edges:
        if not isinstance(edge, dict) or set(edge) != {"id", "source", "target", "port"}:
            _fail("连线需要 id、source、target、port")
        key = _key(edge["id"])
        source, target, port = edge["source"], edge["target"], edge["port"]
        if not all(isinstance(v, str) for v in (source, target, port)) or source not in by_id or target not in by_id:
            _fail("连线端点不存在", "canvas_missing_node")
        if source == target or not accepts_port(by_id[target]["type"], port, by_id[source]["type"]):
            _fail("端口不接受该节点类型", "canvas_port_mismatch")
        signature = (source, target, port)
        if key in ids or signature in signatures:
            _fail("连线重复")
        if port in {"first_frame", "last_frame"}:
            if (target, port) in single_ports:
                _fail("首尾帧端口分别只能接一张图片", "canvas_port_cardinality")
            single_ports.add((target, port))
        ids.add(key)
        signatures.add(signature)
        successors[source].append(target)
        links.append(dict(edge))
    visiting, done = set(), set()
    def visit(key):
        if key in visiting:
            _fail("画布引用不能成环", "canvas_cycle")
        if key in done:
            return
        visiting.add(key)
        for child in successors[key]:
            visit(child)
        visiting.remove(key)
        done.add(key)
    for key in by_id:
        visit(key)
    viewport = value.get("viewport", {})
    if not isinstance(viewport, dict) or set(viewport) - {"x", "y", "zoom"}:
        _fail("视口需要 x、y、zoom")
    return {"nodes": result, "edges": links, "viewport": {"x": _number(viewport.get("x", 0), -100000, 100000),
        "y": _number(viewport.get("y", 0), -100000, 100000), "zoom": _number(viewport.get("zoom", 1), .1, 8)}}


class CreativeCanvasService:
    def _direct_canvas_copy_payload(self, project_id, payload):
        from vsc.assets.access_control import current_principal, denied
        from vsc.adapters.persistence.postgres.values import checked_id
        from vsc.assets.service_operations import fields
        fields(payload, 'source_project_id source_canvas_id source_version_id source_sha256 episode_id title')
        principal = current_principal()
        if principal and (principal.share_id or principal.api_key_id):
            denied('完整画布复制需要项目会话权限')
        result = dict(payload)
        for key in ('source_project_id', 'source_canvas_id', 'source_version_id', 'episode_id'):
            result[key] = checked_id(payload[key])
        if not isinstance(payload['source_sha256'], str) or not re.fullmatch(r'[0-9a-f]{64}', payload['source_sha256']):
            _fail('复制需要明确的源版本摘要', 'invalid_canvas_copy')
        title = payload['title']
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 100 or '\x00' in title:
            _fail('新画布名称须为 1–100 字', 'invalid_canvas_title')
        result['title'] = title.strip()
        return checked_id(project_id), result

    def preview_direct_canvas_copy(self, project_id, payload):
        from vsc.adapters.persistence.postgres.canvas_copy import DirectCanvasCopiesRepository
        project_id, payload = self._direct_canvas_copy_payload(project_id, payload)
        return DirectCanvasCopiesRepository(self.store).preview(project_id, payload)

    def copy_direct_canvas(self, project_id, payload, **kw):
        from vsc.adapters.persistence.postgres.canvas_copy import DirectCanvasCopiesRepository
        self._validate_write(payload, **kw)
        project_id, payload = self._direct_canvas_copy_payload(project_id, payload)
        return DirectCanvasCopiesRepository(self.store).copy(project_id, payload, verify_media=self._verify_media, **kw)

    def canvas_library_options(self, *, workspace_id=None, relation=None, owner_kind=None):
        from vsc.adapters.persistence.postgres.canvas_library import CanvasLibrary
        from vsc.adapters.persistence.postgres.project_presentation import catalog_scope
        return CanvasLibrary(self.store).options(catalog_scope(workspace_id, relation, owner_kind))

    def list_canvas_library(self, *, project_id=None, episode_id=None, creator_filter='mine',
                            creator_id=None, permission='all', collaboration_only=False, order='updated_desc', query='', offset=0, limit=30,
                            workspace_id=None, relation=None, owner_kind=None):
        from vsc.adapters.persistence.postgres.canvas_library import CanvasLibrary
        from vsc.adapters.persistence.postgres.project_presentation import catalog_scope
        from vsc.adapters.persistence.postgres.values import checked_id
        if (type(offset) is not int or not 0 <= offset <= 2147483647
                or type(limit) is not int or not 1 <= limit <= 100):
            raise ResourceError('分页要求 offset >= 0，1 <= limit <= 100', 'invalid_page')
        if (not isinstance(creator_filter, str) or creator_filter not in {'mine','all','member'}
                or not isinstance(permission, str) or permission not in {'all','edit','view'}
                or type(collaboration_only) is not bool
                or not isinstance(order, str) or order not in {'updated_desc','updated_asc'}):
            raise ResourceError('画布筛选或排序无效', 'invalid_canvas_filter')
        if not isinstance(query, str) or len(query) > 200 or '\x00' in query:
            raise ResourceError('画布搜索文字无效', 'invalid_canvas_filter')
        if creator_id is not None and (not isinstance(creator_id, str) or not creator_id.strip()
                or len(creator_id) > 200 or '\x00' in creator_id):
            raise ResourceError('画布创建者无效', 'invalid_canvas_filter')
        if (creator_filter == 'member') != bool(creator_id):
            raise ResourceError('成员筛选需要明确创建者，其他筛选不能同时指定创建者', 'invalid_canvas_filter')
        if episode_id and not project_id:
            raise ResourceError('剧集筛选需要先指定项目', 'invalid_canvas_filter')
        return CanvasLibrary(self.store).search(dict(project_id=checked_id(project_id) if project_id else None,
            **catalog_scope(workspace_id, relation, owner_kind),
            episode_id=checked_id(episode_id) if episode_id else None, creator_filter=creator_filter,
            creator_id=creator_id, permission=permission, collaboration_only=collaboration_only,
            order=order, query=query.strip(), offset=offset, limit=limit))

    def preview_canvas_work_generation(self, project_id, payload):
        from vsc.production.quotes import fingerprint
        preview = self.preview_workbench_generation(project_id, payload)
        routing = self.store.canvas_work_routing(project_id, payload.get('draft_version_id'))
        if routing:
            preview['routing'] = routing
            if preview['ready']:
                preview['artifact']['document']['canvas_model_routing'] = routing
                preview['preview_sha256'] = fingerprint(preview['artifact'])
        return preview

    def prepare_canvas_work_input(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        return self.store.prepare_canvas_work_input(project_id, payload, **kw)

    def generate_canvas_work(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        self.authorize_access(project_id, "execute")
        return self.store.generate_canvas_work(project_id, payload, build_preview=self.preview_canvas_work_generation, **kw)

    def adopt_canvas_work_outputs(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        return self.store.adopt_canvas_work_outputs(project_id, payload, **kw)

    def create_canvas_domain_node(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        return self.store.create_canvas_domain_node(project_id, payload, **kw)

    def canvas_node_to_edit(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        return self.store.canvas_node_to_edit(project_id, payload, **kw)

    def use_canvas_domain_output(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        return self.store.use_canvas_domain_output(project_id, payload, **kw)

    def canvas_node_candidates(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        return self.store.canvas_node_candidates(project_id, payload, **kw)

    def canvas_agent_options(self, project_id):
        from vsc.production.canvas_agent import SKILLS,GrokBuildCanvasAgent
        tree=self.get_project_tree(project_id)
        backend=getattr(self,"canvas_agent_backend",None) or GrokBuildCanvasAgent()
        return {"skills":[dict(value,id=key) for key,value in SKILLS.items()],"models":self.list_models(),
            "nodes":tree["nodes"],"revision":tree["revision"],"host_available":backend.available(),"provider_submit":False}

    def list_canvas_agent_sessions(self, project_id, canvas_id, *, include_archived=False):
        return self.store.list_canvas_agent_sessions(project_id, canvas_id, include_archived=include_archived)

    def update_canvas_agent_session_state(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        from vsc.adapters.persistence.postgres.values import checked_id
        if not isinstance(payload, dict) or set(payload) - {"canvas_id", "session_id", "title", "archived", "auto_approve"}:
            _fail("会话状态更新字段无效", "invalid_agent_session_state")
        checked_id(payload.get("canvas_id"))
        checked_id(payload.get("session_id"))
        if "title" in payload and payload["title"] is not None:
            if not isinstance(payload["title"], str) or not 1 <= len(payload["title"].strip()) <= 200 or "\x00" in payload["title"]:
                _fail("会话名称须为 1–200 字", "invalid_agent_session_state")
        for flag in ("archived", "auto_approve"):
            if flag in payload and payload[flag] is not None and type(payload[flag]) is not bool:
                _fail("会话布尔开关类型无效", "invalid_agent_session_state")
        return self.store.update_canvas_agent_session_state(project_id, payload, **kw)

    def mutate_canvas_agent_queue(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        from vsc.adapters.persistence.postgres.values import checked_id
        if not isinstance(payload, dict) or set(payload) - {"canvas_id", "session_id", "action", "queue_item_id", "message", "skill_id", "mode", "turn_id"}:
            _fail("会话消息队列字段无效", "invalid_agent_queue_item")
        checked_id(payload.get("canvas_id"))
        checked_id(payload.get("session_id"))
        if payload.get("action") not in {"enqueue", "steer", "take_for_edit", "cancel", "mark_dispatched"}:
            _fail("队列操作须为入队、优先、取回编辑或取消", "invalid_agent_queue_action")
        if payload["action"] != "enqueue":
            checked_id(payload.get("queue_item_id"))
        if payload["action"] == "mark_dispatched":
            checked_id(payload.get("turn_id"))
        return self.store.mutate_canvas_agent_queue(project_id, payload, **kw)

    def list_camera_motion_templates(self, project_id):
        return self.store.list_camera_motion_templates(project_id)

    def mutate_camera_motion_template(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        from vsc.adapters.persistence.postgres.values import checked_id
        if not isinstance(payload, dict) or set(payload) - {
            "action", "template_id", "name", "prompt_fragment",
            "horizontal_pan", "vertical_tilt", "zoom_delta", "roll_deg", "speed_preset", "favorite",
        }:
            _fail("运镜模板参数无效", "invalid_camera_motion")
        action = payload.get("action")
        if action not in {"create", "favorite", "delete"}:
            _fail("运镜模板操作无效", "invalid_camera_motion_action")
        if action == "create":
            name = payload.get("name")
            prompt_fragment = payload.get("prompt_fragment", "")
            if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100 or "\x00" in name:
                _fail("运镜模板名称须为 1–100 字", "invalid_camera_motion")
            if not isinstance(prompt_fragment, str) or len(prompt_fragment.strip()) > 1000 or "\x00" in prompt_fragment:
                _fail("运镜提示词片段长度无效", "invalid_camera_motion")
            for key, low, high in (("horizontal_pan", -100, 100), ("vertical_tilt", -100, 100), ("zoom_delta", -100, 100), ("roll_deg", -45, 45)):
                val = payload.get(key, 0)
                if type(val) is not int or not low <= val <= high:
                    _fail("运镜角度或推拉参数超出范围", "invalid_camera_motion")
            if payload.get("speed_preset", "normal") not in {"slow", "normal", "fast"}:
                _fail("运镜速度档位无效", "invalid_camera_motion")
        else:
            checked_id(payload.get("template_id"))
            if action == "favorite" and type(payload.get("favorite")) is not bool:
                _fail("收藏状态须为布尔值", "invalid_camera_motion")
        return self.store.mutate_camera_motion_template(project_id, payload, **kw)

    def get_canvas_agent_turn(self,project_id,turn_id):return self.store.get_canvas_agent_turn(project_id,turn_id)
    def preview_canvas_agent_run(self,project_id,turn_id):
        request=self.store.get_canvas_agent_run_request(project_id,turn_id)
        return self.preview_canvas_work_generation(project_id,request) if request.get('draft_version_id') else self.preview_creative_canvas_run(project_id,request)
    def create_canvas_agent_turn(self,project_id,payload,**kw):return self._write("create_canvas_agent_turn",project_id,payload,**kw)
    def execute_canvas_agent_turn(self,project_id,turn_id):
        self.authorize_access(project_id,"execute")
        from vsc.production.canvas_agent import execute_agent
        return execute_agent(self,project_id,turn_id)
    def decide_canvas_agent_turn(self,project_id,payload,**kw):
        self._validate_write(payload,**kw)
        if payload.get("outcome") not in {"confirm","reject","stop"}:_fail("请选择确认、拒绝或停止")
        if payload.get('outcome') == 'confirm':self.authorize_access(project_id, 'execute')
        return self.store.decide_canvas_agent_turn(project_id,payload,build_preview=self.preview_creative_canvas_run,build_work_preview=self.preview_canvas_work_generation,**kw)

    def _canvas_access(self,project_id,capability,version_id=None):
        if not hasattr(self,"authorize_access"):
            _fail("统一分享权限尚未接通","access_unavailable")
        return self.authorize_access(project_id,capability,target_type="canvas_version" if version_id else None,target_id=version_id)

    def get_creative_canvas_version(self,project_id,version_id):
        self._canvas_access(project_id,"read",version_id)
        result=self.store.get_creative_canvas_version(project_id,version_id)
        for node in result["document"]["nodes"]:
            node["job_id"]=None
            if node["media_id"]:node["preview_url"]="/api/v1/projects/%s/media/%s/content"%(project_id,node["media_id"])
        return result

    def creative_canvas_version_media(self,project_id,version_id):return self.store.creative_canvas_version_media(project_id,version_id)
    def list_canvas_templates(self,project_id,actor):
        self._canvas_access(project_id,"read")
        return self.store.list_canvas_templates(project_id,actor)
    def publish_canvas_template(self,project_id,payload,**kw):
        self._validate_write(payload,**kw);self._canvas_access(project_id,"publish")
        canvas=self.get_creative_canvas(project_id,payload.get("canvas_id"),payload.get("canvas_revision"))
        self._canvas_access(project_id,"read",canvas["version_id"])
        return self.store.publish_canvas_template(project_id,payload,**kw)
    def favorite_canvas_template(self,project_id,payload,**kw):
        self._validate_write(payload,**kw);self._canvas_access(project_id,"edit")
        return self.store.favorite_canvas_template(project_id,payload,**kw)
    def copy_canvas_template(self,project_id,payload,**kw):
        self._validate_write(payload,**kw);self._canvas_access(project_id,"edit")
        source=payload.get("source_project_id",project_id)
        template=self.store.get_canvas_template(source,payload.get("template_id"))
        self._canvas_access(source,"read",template["version_id"])
        return self.store.copy_canvas_template(project_id,payload,**kw)

    def preview_creative_canvas_run(self, project_id, payload):
        from vsc.production.canvas_execution import preview_canvas
        return preview_canvas(self,project_id,payload)

    def preview_canvas_execution_batch(self,p,payload):
        items=payload.get('nodes')
        if not isinstance(items,list) or not 1<=len(items)<=200:raise ResourceError('请选择本轮节点')
        shared={k:v for k,v in payload.items() if k!='nodes'}
        return {'items':[dict(node_id=item.get('node_id'),result=self.preview_creative_canvas_run(p,dict(shared,**item))) for item in items]}

    def advance_canvas_execution(self,p,payload,actor):
        from vsc.production.canvas_execution import advance_runs
        canvas=self.get_creative_canvas(p,payload.get('canvas_id'))
        if canvas['canvas_revision']!=payload.get('canvas_revision'):raise ResourceError('请刷新固定画布版本')
        steps=self.store.list_canvas_execution_steps(p,canvas['version_id'])
        ids=payload.get('step_ids')
        if not isinstance(ids,list) or len(ids)>200 or any(i not in {x['id'] for x in steps} for i in ids):raise ResourceError('请选择该固定版本的执行步骤')
        return advance_runs(self,p,[x['run_artifact_id'] for x in steps if x['id'] in ids],actor)

    def preview_canvas_fallback(self,p,step_id):
        return self.store.preview_canvas_fallback(p,step_id,service=self)

    def propose_canvas_fallback(self,p,payload,**kw):
        self._validate_write(payload,**kw)
        self.authorize_access(p, 'execute')
        return self.store.propose_canvas_fallback(p,payload,build_preview=self.preview_canvas_fallback,**kw)

    def propose_creative_canvas_run(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        if set(payload) != {"request", "preview_sha256"}:
            _fail("保存运行草稿需要所预览的请求与摘要")
        return self.store.propose_creative_canvas_run(project_id, payload, build_preview=self.preview_creative_canvas_run, **kw)

    def list_creative_canvases(self, project_id, episode_id=None, collaboration_only=False):
        if type(collaboration_only) is not bool:
            raise ResourceError('画布协作筛选须为布尔值', 'invalid_canvas_filter')
        return self.store.list_creative_canvases(project_id, episode_id, collaboration_only=collaboration_only)

    def get_creative_canvas(self, project_id, canvas_id, version=None):
        result = self.store.get_creative_canvas(project_id, canvas_id, version)
        result["node_types"] = deepcopy(NODE_TYPES)
        for node in result["document"]["nodes"]:
            if node.get("media_id"):
                node["preview_url"] = "/api/v1/projects/%s/media/%s/content" % (project_id, node["media_id"])
        result["execution_steps"] = self.store.list_canvas_execution_steps(project_id,result["version_id"])
        can_edit = bool(result.get("permission", {}).get("can_edit", True))
        result["capabilities"] = {"edit": can_edit, "prepare": can_edit, "provider_submit": False, "agent": can_edit}
        return result

    def create_creative_canvas(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        if "collaboration_enabled" in payload and payload["collaboration_enabled"] is not None and type(payload["collaboration_enabled"]) is not bool:
            raise ResourceError("多人协作开关须为布尔值", "invalid_collaboration_flag")
        payload = dict(payload, document=normalize_document(payload.get("document", {})))
        return self.store.create_creative_canvas(project_id, payload, **kw)

    def set_canvas_collaboration(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        return self.store.set_canvas_collaboration(project_id, payload, **kw)

    def issue_canvas_collab_ticket(self, project_id, canvas_id, payload, *, actor):
        if not isinstance(actor, str) or not actor.strip():
            raise ResourceError("需要真实操作身份", "access_denied", 403)
        self.authorize_access(project_id, "read", "canvas", canvas_id)
        return self.store.issue_canvas_collab_ticket(project_id, canvas_id, payload, actor=actor)

    def recover_canvas_batch(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        return self.store.recover_canvas_batch(project_id, payload, **kw)

    def save_creative_canvas(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        payload = dict(payload, document=normalize_document(payload.get("document")))
        return self.store.save_creative_canvas(project_id, payload, **kw)

    def copy_creative_canvas(self, project_id, payload, **kw):
        return self._write("copy_creative_canvas", project_id, payload, **kw)

    def add_canvas_library_node(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        if (not isinstance(payload, dict) or set(payload)-{"canvas_id", "canvas_revision", "library_version_id", "member_key", "role", "x", "y"}
                or type(payload.get("canvas_revision")) is not int or payload["canvas_revision"] < 1
                or not isinstance(payload.get("member_key"), str) or not 1 <= len(payload["member_key"]) <= 200
                or not isinstance(payload.get("role"), str) or not 1 <= len(payload["role"]) <= 80):
            raise ResourceError("需要固定画布、库版本、媒体成员与引用用途", "invalid_canvas_library_reference")
        from vsc.adapters.persistence.postgres.values import checked_id
        for key in ("canvas_id", "library_version_id"):checked_id(payload.get(key))
        for key in ("x", "y"):
            if key in payload and (type(payload[key]) not in (int, float) or not -100000 <= payload[key] <= 100000):
                raise ResourceError("节点位置无效", "invalid_canvas_position")
        return self.store.add_canvas_library_node(project_id, payload,
            materialize_reference=self._library().materialize_reference, **kw)

    def add_canvas_project_media_node(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        if (not isinstance(payload, dict) or set(payload)-{"canvas_id", "canvas_revision", "source_project_id", "source", "x", "y"}
                or type(payload.get("canvas_revision")) is not int or payload["canvas_revision"] < 1
                or not isinstance(payload.get("source"), dict)):
            raise ResourceError("需要固定画布版本和项目素材来源", "invalid_canvas_project_reference")
        from vsc.adapters.persistence.postgres.values import checked_id
        for key in ("canvas_id", "source_project_id"):checked_id(payload.get(key))
        if checked_id(project_id)==checked_id(payload["source_project_id"]):
            raise ResourceError("当前项目素材请直接加入画布", "invalid_canvas_project_reference")
        source=payload["source"]
        if source.get("kind")=="asset_form":
            if set(source)!={"kind", "asset_id", "form_version_id", "media_id"}:
                raise ResourceError("需要固定资产形态和素材", "invalid_canvas_project_reference")
            for key in ("asset_id", "form_version_id", "media_id"):checked_id(source[key])
        elif source.get("kind")=="blocking":
            fields={"kind", "workflow_id", "version_id", "episode_id", "unit_key", "media_id", "spatial_export_id"}
            if (set(source)!=fields or not isinstance(source.get("unit_key"),str)
                    or not 1<=len(source["unit_key"])<=200):
                raise ResourceError("需要固定站位版本和素材", "invalid_canvas_project_reference")
            for key in ("workflow_id", "version_id", "episode_id", "media_id"):checked_id(source[key])
            if source["spatial_export_id"] is not None:checked_id(source["spatial_export_id"])
        else:
            raise ResourceError("素材来源类型无效", "invalid_canvas_project_reference")
        for key in ("x", "y"):
            if key in payload and (type(payload[key]) not in (int,float) or not -100000<=payload[key]<=100000):
                raise ResourceError("节点位置无效", "invalid_canvas_position")
        return self.store.add_canvas_project_media_node(project_id, payload, storage=self.storage, **kw)

    def _read_verified_local_media_bytes(self, media):
        import hashlib
        if self.storage is None:
            _fail("操作需要受控素材存储", "storage_unavailable")
        locations = [item for item in media["locations"] if item["storage"] == "local" and item["available"]]
        if not locations:
            _fail("原图缺少可用本地字节", "media_unavailable")
        for location in locations:
            try:
                candidate = self.storage.read(location["object_key"], media["sha256"])
                if hashlib.sha256(candidate).hexdigest() == media["sha256"]:
                    return candidate
            except (OSError, ResourceError):
                continue
        _fail("固定原图字节不可读取或摘要不符", "media_sha_mismatch")

    def split_canvas_image(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        required_fields = {"canvas_id", "canvas_revision", "node_id", "rows", "columns", "cells"}
        if (not isinstance(payload, dict) or not required_fields.issubset(payload)
                or set(payload) - (required_fields | {"group_name"})
                or type(payload.get("canvas_revision")) is not int or payload["canvas_revision"] < 1):
            _fail("切分需要固定画布版本、节点和所选宫格", "invalid_canvas_grid")
        group_name = payload.get("group_name", "")
        if not isinstance(group_name, str) or len(group_name) > 100 or "\x00" in group_name:
            _fail("分组名称最长 100 字", "invalid_canvas_grid")
        rows, columns, cells = payload["rows"], payload["columns"], payload["cells"]
        if type(rows) is not int or type(columns) is not int or not 1 <= rows <= 8 or not 1 <= columns <= 8 or not isinstance(cells, list) or not 1 <= len(cells) <= rows * columns:
            _fail("宫格行列需为1至8，且必须选择至少一格", "invalid_canvas_grid")
        seen = set()
        for cell in cells:
            if (not isinstance(cell, dict) or set(cell) != {"row", "column"} or type(cell["row"]) is not int or
                    type(cell["column"]) is not int or not 1 <= cell["row"] <= rows or not 1 <= cell["column"] <= columns or
                    (cell["row"], cell["column"]) in seen):
                _fail("所选宫格无效、越界或重复", "invalid_canvas_grid")
            seen.add((cell["row"], cell["column"]))

        def build(media):
            import io
            from vsc.production.image_tools import split_grid_image
            content = self._read_verified_local_media_bytes(media)
            outputs = []
            for item in split_grid_image(content, rows, columns, cells):
                staged = self.storage.stage_upload(io.BytesIO(item["bytes"]), "grid-%s-%s.png" % (item["row"], item["column"]))
                outputs.append(self.storage.commit_upload(staged["staged_upload"]))
            return outputs

        return self.store.split_canvas_image(project_id, payload, build=build, **kw)

    def transform_canvas_image(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        required_fields = {"canvas_id", "canvas_revision", "node_id", "operation", "settings"}
        if (not isinstance(payload, dict) or not required_fields.issubset(payload)
                or set(payload) - (required_fields | {"in_place", "group_name"})
                or type(payload.get("canvas_revision")) is not int or payload["canvas_revision"] < 1):
            _fail("图片本地编辑需要固定画布版本、节点、操作和参数", "invalid_canvas_transform")
        _key(payload.get("node_id"))
        op = payload.get("operation")
        settings = payload.get("settings")
        if op not in {"crop", "rotate", "color_adjust", "doodle"} or not isinstance(settings, dict):
            _fail("图片本地编辑仅支持裁剪、旋转、调色和涂鸦", "invalid_canvas_transform")
        if "in_place" in payload and type(payload["in_place"]) is not bool:
            _fail("就地替换标志须为布尔值", "invalid_canvas_transform")
        group_name = payload.get("group_name")
        if group_name is not None and (not isinstance(group_name, str) or len(group_name) > 100 or "\x00" in group_name):
            _fail("分组名称最长 100 字", "invalid_canvas_transform")

        def build(media):
            import io
            from vsc.production.canvas_image_ops import (
                crop_image_bytes, rotate_flip_image_bytes, color_adjust_image_bytes, doodle_overlay_image_bytes,
            )
            content = self._read_verified_local_media_bytes(media)
            if op == "crop":
                out_bytes = crop_image_bytes(
                    content,
                    x=settings.get("x", 0.0),
                    y=settings.get("y", 0.0),
                    w=settings.get("w", 1.0),
                    h=settings.get("h", 1.0),
                )
                norm = {
                    "x": round(float(settings.get("x", 0.0)), 4),
                    "y": round(float(settings.get("y", 0.0)), 4),
                    "w": round(float(settings.get("w", 1.0)), 4),
                    "h": round(float(settings.get("h", 1.0)), 4),
                    "ratio": str(settings.get("ratio", settings.get("ratioKey", "original")))[:20],
                }
                suffix = "裁剪"
            elif op == "rotate":
                deg = settings.get("degrees", settings.get("angle", 0.0))
                flip_x = bool(settings.get("flip_x", settings.get("flipX", False)))
                flip_y = bool(settings.get("flip_y", settings.get("flipY", False)))
                out_bytes = rotate_flip_image_bytes(
                    content,
                    degrees=deg,
                    flip_x=flip_x,
                    flip_y=flip_y,
                )
                norm = {
                    "degrees": round(float(deg), 2),
                    "flip_x": flip_x,
                    "flip_y": flip_y,
                }
                suffix = "旋转翻转"
            elif op == "color_adjust":
                raw_filter = str(settings.get("filter_id", settings.get("filterId", "original")) or "original")
                filter_id = "original" if raw_filter == "none" else raw_filter
                strength = settings.get("strength", settings.get("filter_intensity", 100))
                brightness = settings.get("brightness", settings.get("lightness", 0))
                out_bytes = color_adjust_image_bytes(
                    content,
                    filter_id=filter_id,
                    strength=strength,
                    hue=settings.get("hue", 0),
                    saturation=settings.get("saturation", 0),
                    brightness=brightness,
                    contrast=settings.get("contrast", 0),
                )
                norm = {
                    "filter_id": filter_id[:40],
                    "strength": int(strength),
                    "hue": int(settings.get("hue", 0)),
                    "saturation": int(settings.get("saturation", 0)),
                    "brightness": int(brightness),
                    "contrast": int(settings.get("contrast", 0)),
                }
                suffix = "调色滤镜"
            else:
                strokes = settings.get("strokes", [])
                out_bytes = doodle_overlay_image_bytes(content, strokes)
                norm = {"stroke_count": len(strokes) if isinstance(strokes, list) else 0}
                suffix = "涂鸦"
            staged = self.storage.stage_upload(io.BytesIO(out_bytes), f"canvas-{op}.png")
            return self.storage.commit_upload(staged["staged_upload"]), norm, suffix

        return self.store.transform_canvas_image(project_id, payload, build=build, **kw)

    def capture_canvas_panorama(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        required_fields = {"canvas_id", "canvas_revision", "node_id", "mode"}
        if (not isinstance(payload, dict) or not required_fields.issubset(payload)
                or set(payload) - (required_fields | {"yaw", "pitch", "fov", "group_name"})
                or type(payload.get("canvas_revision")) is not int or payload["canvas_revision"] < 1):
            _fail("全景截图需要固定画布版本、节点和截图模式", "invalid_canvas_panorama")
        _key(payload.get("node_id"))
        mode = payload.get("mode")
        if mode not in {"current", "four", "twelve"}:
            _fail("全景截图模式须为当前视角、4大视角或12大视角", "invalid_canvas_panorama")
        yaw = _number(payload.get("yaw", 0.0), -720.0, 720.0)
        pitch = _number(payload.get("pitch", 0.0), -89.0, 89.0)
        fov = _number(payload.get("fov", 75.0), 30.0, 120.0)
        group_name = payload.get("group_name")
        if group_name is not None and (not isinstance(group_name, str) or len(group_name) > 100 or "\x00" in group_name):
            _fail("分组名称最长 100 字", "invalid_canvas_panorama")
        normalized_payload = dict(payload, yaw=yaw, pitch=pitch, fov=fov)

        def build(media):
            import io
            from vsc.production.canvas_image_ops import capture_panorama_views
            content = self._read_verified_local_media_bytes(media)
            views = capture_panorama_views(content, mode=mode, yaw_deg=yaw, pitch_deg=pitch, fov_deg=fov)
            outputs = []
            for idx, view in enumerate(views):
                staged = self.storage.stage_upload(io.BytesIO(view["bytes"]), f"panorama-{mode}-{idx + 1}.png")
                outputs.append({"staged": self.storage.commit_upload(staged["staged_upload"]), "view": view})
            return outputs

        return self.store.capture_canvas_panorama(project_id, normalized_payload, build=build, **kw)

    def replace_canvas_node_media(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        from vsc.adapters.persistence.postgres.values import checked_id
        required_fields = {"canvas_id", "canvas_revision", "node_id", "media_id"}
        if (not isinstance(payload, dict) or not required_fields.issubset(payload)
                or set(payload) - (required_fields | {"title"})
                or type(payload.get("canvas_revision")) is not int or payload["canvas_revision"] < 1):
            _fail("替换素材需要固定画布版本、节点和目标素材", "invalid_canvas_replace_media")
        _key(payload.get("node_id"))
        checked_id(payload.get("canvas_id"))
        checked_id(payload.get("media_id"))
        if "title" in payload and payload["title"] is not None:
            if not isinstance(payload["title"], str) or not 1 <= len(payload["title"].strip()) <= 200 or "\x00" in payload["title"]:
                _fail("节点标题须为 1–200 字", "invalid_canvas_replace_media")
        return self.store.replace_canvas_node_media(project_id, payload, **kw)

    def creative_canvas_history(self, project_id, canvas_id):
        return self.store.creative_canvas_history(project_id, canvas_id)

    def prepare_creative_canvas(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        document = self.store.get_creative_canvas(project_id, payload.get("canvas_id"), payload.get("canvas_revision"))
        for node in document["document"]["nodes"]:
            if node.get("media_id"):
                self._verify_media(project_id, node["media_id"])
        return self.store.prepare_creative_canvas(project_id, payload, **kw)
