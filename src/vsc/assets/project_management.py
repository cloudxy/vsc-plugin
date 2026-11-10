"""Project organization uses original identities, transaction receipts and media recycle."""
class ProjectManagementServiceMixin:
    def management_filter_active_projects(self,items):
        return self.store.management_filter_active_projects(items)

    def management_snapshot(self,project_id,**filters):
        return self.store.management_snapshot(project_id,**filters)

    def management_recycled_projects(self):
        return self.store.management_recycled_projects()

    def management_recycle_items(self, **filters):
        return self.store.management_recycle_items(**filters)

    def management_command(self,project_id,payload,**kw):
        from vsc.assets.resource_service import ResourceError
        self._validate_write(payload,**kw)
        if payload.get('operation') not in {'rename','edit','folder_create','folder_update','folder_move','folder_order','folder_remove','move','trash','restore','purge','retention'}:
            raise ResourceError('请选择有效的项目管理操作','management_operation')
        return self.store.management_command(project_id,payload,**kw)
