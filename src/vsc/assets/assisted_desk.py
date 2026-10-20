"""Task-oriented reading over the original project authorities."""
from vsc.assets.resource_service import ResourceError
from vsc.assets.workbench import legacy_workbench

BUCKETS = frozenset(("review", "progress", "results"))
STATUS_LABELS = {
    "draft": "等待审阅", "candidate": "等待选择", "approved": "已批准",
    "selected": "已采用", "created": "等待执行", "queued": "等待执行",
    "running": "正在执行", "submitted": "已提交服务", "polling": "正在等待服务",
    "succeeded": "请回看结果", "failed": "执行受阻", "cancelled": "已停止",
    "submission_unknown": "提交结果待核实", "rejected": "已退回",
    "unassociated": "已登记素材", "blocked": "执行受阻", "stale": "旧基线结果待核对",
}


def present(row, *, read_only=False):
    row = dict(row)
    if row.get("kind") == "job":
        row["title"] = {
            "video_clip": "镜头视频", "image": "图像制作", "first_frame": "镜头首帧",
            "dialogue_dry": "对白干声", "dialogue": "对白", "tts": "配音",
            "ambience": "环境声", "music": "配乐", "sfx": "音效",
            "sound_effect": "音效", "asset_ref": "资产参考",
        }.get(row.get("title"), "制作任务")
    row["status_label"] = STATUS_LABELS.get(row.get("status"), "等待回看")
    row["blocked_reason"] = {
        "failed": "本次执行失败。打开任务记录查看原因，原有结果保留。",
        "submission_unknown": "服务提交结果尚未核实。核实前不会再次提交。",
        "created": "任务已登记，等待可用执行器领取。",
    }.get(row.get("status"))
    row["actions"] = ["open"]
    if not read_only and row["ref"]["kind"] == "artifact":
        row["actions"].append("review")
    return row


class AssistedDesk:
    def __init__(self, catalog):
        self.catalog = catalog

    def query(self, project_id, *, bucket="review", object_id=None, limit=24, offset=0, revision=None):
        if bucket not in BUCKETS or type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or not 0 <= offset <= 1000000:
            raise ResourceError("工作台分页或任务范围不合法", "invalid_desk_query")
        if revision is not None and (type(revision) is not int or revision < 0):
            raise ResourceError("工作台版本不合法", "invalid_desk_query")
        reader = self.catalog._reader(project_id)
        if reader is None:
            from vsc.adapters.persistence.postgres.assisted_desk import query_assisted_desk
            return query_assisted_desk(self.catalog.service.store, project_id, bucket=bucket,
                object_id=object_id, limit=limit, offset=offset, revision=revision)
        # Legacy data remains on its reader. Do not infer unindexed approvals or jobs.
        data = legacy_workbench(reader, project_id, section="versions", object_id=object_id,
            limit=limit, offset=offset, revision=revision, query="", kind=None, status=None,
            purpose=None, version=None, association=None, entity_id=None)
        page = data["sections"]["versions"]
        items = []
        if bucket == "results":
            items = [present(dict(id="artifact:"+str(r["id"]), title=r.get("title"),
                kind="artifact", status=r.get("status"), object_id=object_id,
                ref=dict(kind="artifact", id=r["id"], version_id=r["id"])), read_only=True)
                for r in page["items"]]
        total = page["total"] if bucket == "results" else 0
        return dict(project_id=project_id, revision=data["revision"], bucket=bucket, read_only=True,
            items=items, counts={"review": None, "progress": None, "results": page["total"]},
            total=total, offset=offset, limit=limit, next_offset=page["next_offset"] if items else None,
            scope=data["scope"], ancestors=data["ancestors"],
            message="旧项目只读；待审与执行状态未建立完整索引，请从项目资料查看原记录。")
