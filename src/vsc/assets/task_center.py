"""A single project task view without copied task state or browser workers."""
from vsc.assets.resource_service import ResourceError


class TaskCenterService:
    def get_task_center(self,project_id,offset=0,limit=24,kind=None,status=None):
        if (type(offset)is not int or not 0<=offset<=10000 or type(limit)is not int or not 1<=limit<=100
                or kind not in {None,"","generation","editing","spatial","import","text","canvas","intelligent"}
                or status is not None and (not isinstance(status,str) or len(status)>40)):
            raise ResourceError("任务筛选或分页无效")
        from vsc.adapters.persistence.postgres.task_center import TaskCenterRepository
        return TaskCenterRepository(self.store).query(project_id,offset,limit,kind or None,status or None)
