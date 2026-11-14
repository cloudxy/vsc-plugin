"""A single project task view without copied task state or browser workers."""
from vsc.assets.resource_service import ResourceError
from vsc.assets.task_notifications import TaskNotificationsService


class TaskCenterService(TaskNotificationsService):
    def get_task_origin(self,project_id,kind,identifier):
        from vsc.adapters.persistence.postgres.schema_task_notifications import ORIGINS
        if kind not in ORIGINS:raise ResourceError('未知任务类型')
        from vsc.adapters.persistence.postgres.task_center import TaskCenterRepository
        return TaskCenterRepository(self.store).origin(project_id,kind,identifier)

    def get_task_center(self,project_id,offset=0,limit=24,kind=None,status=None,episode_id=None,group=None):
        if (type(offset)is not int or not 0<=offset<=10000 or type(limit)is not int or not 1<=limit<=100
                or kind not in {None,"","generation","editing","spatial","spatial_plan","lyrics","import","text","text_batch","canvas","intelligent"}
                or status is not None and (not isinstance(status,str) or len(status)>40)
                or group not in {None,'','attention','running','result','ended','unknown'}):
            raise ResourceError("任务筛选或分页无效")
        from vsc.adapters.persistence.postgres.task_center import TaskCenterRepository
        return TaskCenterRepository(self.store).query(project_id,offset,limit,kind or None,status or None,episode_id,group or None)
