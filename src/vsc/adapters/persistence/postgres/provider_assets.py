"""Original entity versions pin provider registration attempts and receipts."""
import json
from sqlalchemy import select,insert,update
from vsc.assets.resource_service import ResourceError
from . import schema as S
from .values import new_id,clean


class ProviderAssetRepository:
    def __init__(self,store):self.store=store
    def list(self,p,unit_id):
        with self.store.engine.connect() as conn:
            project=self.store._project(conn,p);self.store._text_unit(conn,p,unit_id)
            rows=conn.execute(select(S.provider_asset_registrations).where(S.provider_asset_registrations.c.project_id==p,S.provider_asset_registrations.c.unit_id==unit_id).order_by(S.provider_asset_registrations.c.created_at)).mappings()
            return clean({'items':[dict(r) for r in rows],'revision':project['revision']})
    def start(self,p,payload,provider,account_scope,caller,**kw):
        def work(conn,project):
            unit,version,doc=self.store._overseas_fixed(conn,project,payload,True)
            entity=next((r for r in doc['entities'] if r['key']==payload['entity_key']),None)
            if not entity or not entity['media_id']:raise ResourceError('先为实体选择固定参考图','asset_reference_required')
            media=self.store._media(conn,p,entity['media_id'])
            if media['modality']!='image':raise ResourceError('供应商资产注册需要参考图','asset_reference_required')
            prior=conn.execute(select(S.provider_asset_registrations).where(S.provider_asset_registrations.c.project_id==p,S.provider_asset_registrations.c.unit_id==unit['id'],S.provider_asset_registrations.c.entity_key==entity['key'],S.provider_asset_registrations.c.media_id==media['id'],S.provider_asset_registrations.c.provider==provider,S.provider_asset_registrations.c.account_scope==account_scope).order_by(S.provider_asset_registrations.c.created_at.desc()).limit(1)).mappings().first()
            if prior and (prior['status']!='failed' or not payload.get('new_attempt')):return dict(prior,created=False)
            from .workbench_generation import working_media
            _,gaps=working_media(self.store,conn,p,media['id'],'identity_face' if entity['kind']=='character' else 'location_master')
            if gaps:raise ResourceError('资产参考当前不可用：'+','.join(gaps),'asset_reference_required')
            row=dict(project_id=p,id=new_id(),unit_id=unit['id'],source_version_id=version['id'],entity_key=entity['key'],asset_id=entity['asset_id'] or None,media_id=media['id'],blob_id=media['blob_id'],media_sha256=media['sha256'],provider=provider,account_scope=account_scope,status='running',created_by=kw['actor'])
            conn.execute(insert(S.provider_asset_registrations).values(**row));return dict(row,created=True,caller=caller)
        return self.store._mutate(p,'start_provider_asset_registration',dict(payload,provider=provider,account_scope=account_scope),callback=work,**kw)
    def finish(self,p,payload,**kw):
        def work(conn,project):
            row=self.store._one(conn,S.provider_asset_registrations,p,payload['id'])
            if row['status'] in {'completed','failed'}:return row
            receipt=payload.get('receipt');values=dict(status=payload['status'],receipt=receipt,remote_asset_id=receipt['remote_asset_id'] if receipt else None,error_code=payload.get('error_code'))
            conn.execute(update(S.provider_asset_registrations).where(S.provider_asset_registrations.c.project_id==p,S.provider_asset_registrations.c.id==row['id']).values(**values));return dict(row,**values)
        return self.store._mutate(p,'finish_provider_asset_registration',payload,callback=work,**kw)
