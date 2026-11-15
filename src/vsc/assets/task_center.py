"""A single project task view without copied task state or browser workers."""
from vsc.assets.resource_service import ResourceError
from vsc.assets.task_notifications import TaskNotificationsService

TASK_KINDS = {
    "generation",
    "editing",
    "spatial",
    "spatial_plan",
    "lyrics",
    "import",
    "text",
    "text_batch",
    "canvas",
    "intelligent",
}


class TaskCenterService(TaskNotificationsService):
    def get_task_origin(self, project_id, kind, identifier):
        if kind not in TASK_KINDS:
            raise ResourceError("未知任务类型")
        from vsc.adapters.persistence.postgres.task_center import TaskCenterRepository
        return TaskCenterRepository(self.store).origin(project_id, kind, identifier)

    def get_task_center(self, project_id, offset=0, limit=24, kind=None, status=None, episode_id=None, group=None):
        if (
            type(offset) is not int
            or not 0 <= offset <= 10000
            or type(limit) is not int
            or not 1 <= limit <= 100
            or kind not in ({None, ""} | TASK_KINDS)
            or (status is not None and (not isinstance(status, str) or len(status) > 40))
            or group not in {None, "", "attention", "running", "result", "ended", "unknown"}
        ):
            raise ResourceError("任务筛选或分页无效")
        from vsc.adapters.persistence.postgres.task_center import TaskCenterRepository
        return TaskCenterRepository(self.store).query(
            project_id, offset, limit, kind or None, status or None, episode_id, group or None
        )

    def get_account_tasks(self, *, offset=0, limit=24, kind=None, status=None, group=None, project_id=None):
        if (
            type(offset) is not int
            or not 0 <= offset <= 10000
            or type(limit) is not int
            or not 1 <= limit <= 100
            or kind not in ({None, ""} | TASK_KINDS)
            or (status is not None and (not isinstance(status, str) or len(status) > 40))
            or group not in {None, "", "attention", "running", "result", "ended", "unknown"}
        ):
            raise ResourceError("任务筛选或分页无效", "invalid_input")
        from vsc.adapters.persistence.postgres.task_center import TaskCenterRepository
        return TaskCenterRepository(self.store).query_authorized(
            offset=offset,
            limit=limit,
            kind=kind or None,
            status=status or None,
            group=group or None,
            project_id=project_id or None,
        )

    def batch_cancel_account_tasks(self, payload, *, actor, idempotency_key):
        from vsc.adapters.persistence.postgres.task_center import TaskCenterRepository
        return TaskCenterRepository(self.store).batch_cancel(
            payload, actor=actor, idempotency_key=idempotency_key
        )
