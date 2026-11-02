"""Member-specific task reading state, separate from project authoring revisions."""
from vsc.assets.resource_service import ResourceError


class TaskNotificationsService:
    def get_task_notifications(self,project_id,*,limit=20,cursor=None,unread_only=False):
        if type(limit)is not int or not 1<=limit<=100 or type(unread_only)is not bool or cursor is not None and (not isinstance(cursor,str) or len(cursor)>1000):raise ResourceError('通知筛选或分页无效')
        from vsc.adapters.persistence.postgres.task_notifications import TaskNotificationRepository
        return TaskNotificationRepository(self.store).list(project_id,limit,cursor,unread_only)

    def read_task_notifications(self,project_id,payload):
        if not isinstance(payload,dict) or set(payload) not in ({'ids'},{'through_sequence'}):raise ResourceError('已读操作需指定所见通知或读取位置')
        if 'ids' in payload and (not isinstance(payload['ids'],list) or not 1<=len(payload['ids'])<=100 or not all(isinstance(v,str) for v in payload['ids']) or len(set(payload['ids']))!=len(payload['ids'])):raise ResourceError('一次选择1至100条不同通知')
        if 'through_sequence' in payload and (type(payload['through_sequence'])is not int or payload['through_sequence']<0):raise ResourceError('已读位置无效')
        from vsc.adapters.persistence.postgres.task_notifications import TaskNotificationRepository
        return TaskNotificationRepository(self.store).read(project_id,payload)
