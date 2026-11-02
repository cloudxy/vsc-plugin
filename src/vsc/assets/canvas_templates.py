"""Copy fixed templates without transporting executions or approvals."""
from vsc.assets.service_operations import fields,text
class CanvasTemplatesServiceMixin:
    def _canvas_templates(self):
        from vsc.adapters.persistence.postgres.canvas_templates import CanvasTemplatesRepository
        return CanvasTemplatesRepository(self.store)
    def _template_payload(self,p,payload):
        fields(payload,'source_project_id template_id episode_id title');text(payload['title'],'新画布名称',200)
        self.authorize_access(p,'edit');self.authorize_access(payload['source_project_id'],'read')
    def preview_canvas_template_copy(self,p,payload):
        self._template_payload(p,payload);return self._canvas_templates().preview(p,payload)
    def copy_fixed_canvas_template(self,p,payload,**kw):
        self._validate_write(payload,**kw);self._template_payload(p,payload)
        for identifier in self._canvas_templates().media_ids(payload['source_project_id'],payload['template_id']):self._verify_media(payload['source_project_id'],identifier)
        return self._canvas_templates().copy(p,payload,**kw)
