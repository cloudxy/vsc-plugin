"""Typed creative documents and their original generation-task consumer.

The canvas owns editing history only. Media, approvals and task states remain
owned by their original repositories; preparing a node never submits a provider.
"""
from copy import deepcopy
import math
import re

from vsc.assets.resource_service import ResourceError


NODE_TYPES = {
    "text": {"label": "文本", "inputs": {}, "output": "text"},
    "image": {"label": "图片", "inputs": {"prompt": "text", "reference": "image"}, "output": "image"},
    "video": {"label": "视频", "inputs": {"prompt": "text", "first_frame": "image", "last_frame": "image",
              "reference_image": "image", "reference_video": "video", "reference_audio": "audio"}, "output": "video"},
    "audio": {"label": "音频", "inputs": {"prompt": "text", "reference_audio": "audio"}, "output": "audio"},
}


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
        if not isinstance(node, dict) or set(node) - {"id", "type", "title", "x", "y", "text", "params", "media_id", "job_id", "group"}:
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
        if kind == "text" and (node.get("media_id") or node.get("job_id")):
            _fail("文本节点不能伪装媒体或生成任务")
        row = {"id": key, "type": kind, "title": title.strip(), "x": _number(node.get("x", 0), -100000, 100000),
            "y": _number(node.get("y", 0), -100000, 100000), "text": content, "params": deepcopy(params), "group": group,
            "media_id": node.get("media_id") or None, "job_id": node.get("job_id") or None}
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
        expected = NODE_TYPES[by_id[target]["type"]]["inputs"].get(port)
        if source == target or expected != by_id[source]["type"]:
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
        "y": _number(viewport.get("y", 0), -100000, 100000), "zoom": _number(viewport.get("zoom", 1), .2, 3)}}


class CreativeCanvasService:
    def canvas_agent_options(self, project_id):
        from vsc.production.canvas_agent import SKILLS,GrokBuildCanvasAgent
        tree=self.get_project_tree(project_id)
        backend=getattr(self,"canvas_agent_backend",None) or GrokBuildCanvasAgent()
        return {"skills":[dict(value,id=key) for key,value in SKILLS.items()],"models":self.list_models(),
            "nodes":tree["nodes"],"revision":tree["revision"],"host_available":backend.available(),"provider_submit":False}

    def list_canvas_agent_sessions(self,project_id,canvas_id):return self.store.list_canvas_agent_sessions(project_id,canvas_id)
    def get_canvas_agent_turn(self,project_id,turn_id):return self.store.get_canvas_agent_turn(project_id,turn_id)
    def preview_canvas_agent_run(self,project_id,turn_id):return self.preview_creative_canvas_run(project_id,self.store.get_canvas_agent_run_request(project_id,turn_id))
    def create_canvas_agent_turn(self,project_id,payload,**kw):return self._write("create_canvas_agent_turn",project_id,payload,**kw)
    def execute_canvas_agent_turn(self,project_id,turn_id):
        self.authorize_access(project_id,"execute")
        from vsc.production.canvas_agent import execute_agent
        return execute_agent(self,project_id,turn_id)
    def decide_canvas_agent_turn(self,project_id,payload,**kw):
        self._validate_write(payload,**kw)
        if payload.get("outcome") not in {"confirm","reject","stop"}:_fail("请选择确认、拒绝或停止")
        return self.store.decide_canvas_agent_turn(project_id,payload,build_preview=self.preview_creative_canvas_run,**kw)

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
        return self.store.propose_canvas_fallback(p,payload,build_preview=self.preview_canvas_fallback,**kw)

    def propose_creative_canvas_run(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        if set(payload) != {"request", "preview_sha256"}:
            _fail("保存运行草稿需要所预览的请求与摘要")
        return self.store.propose_creative_canvas_run(project_id, payload, build_preview=self.preview_creative_canvas_run, **kw)

    def list_creative_canvases(self, project_id, episode_id=None):
        return self.store.list_creative_canvases(project_id, episode_id)

    def get_creative_canvas(self, project_id, canvas_id, version=None):
        result = self.store.get_creative_canvas(project_id, canvas_id, version)
        result["node_types"] = deepcopy(NODE_TYPES)
        for node in result["document"]["nodes"]:
            if node.get("media_id"):
                node["preview_url"] = "/api/v1/projects/%s/media/%s/content" % (project_id, node["media_id"])
        result["execution_steps"] = self.store.list_canvas_execution_steps(project_id,result["version_id"])
        result["capabilities"] = {"edit": True, "prepare": True, "provider_submit": False, "agent": True}
        return result

    def create_creative_canvas(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        payload = dict(payload, document=normalize_document(payload.get("document", {})))
        return self.store.create_creative_canvas(project_id, payload, **kw)

    def save_creative_canvas(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        payload = dict(payload, document=normalize_document(payload.get("document")))
        return self.store.save_creative_canvas(project_id, payload, **kw)

    def copy_creative_canvas(self, project_id, payload, **kw):
        return self._write("copy_creative_canvas", project_id, payload, **kw)

    def creative_canvas_history(self, project_id, canvas_id):
        return self.store.creative_canvas_history(project_id, canvas_id)

    def prepare_creative_canvas(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        # A receipt is checked by the transaction before a stale revision. This
        # read supplies byte verification only; it cannot authorize a new run.
        document = self.store.get_creative_canvas(project_id, payload.get("canvas_id"), payload.get("canvas_revision"))
        for node in document["document"]["nodes"]:
            if node.get("media_id"):
                self._verify_media(project_id, node["media_id"])
        return self.store.prepare_creative_canvas(project_id, payload, **kw)
