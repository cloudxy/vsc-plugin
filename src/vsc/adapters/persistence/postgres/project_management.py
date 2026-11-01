"""Organization and tombstones under the original project lock and receipts."""
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, insert, update, delete, func, or_
from vsc.assets.resource_service import ResourceError
from . import schema as S
from .values import checked_id, clean, new_id

OBJECT_TABLES={'creative_objects','works','episodes','scenes','sequences','shots','asset_identities'}
ACTIVE_TASKS={'created','queued','submitted','running','polling','submission_unknown','awaiting_upload','uploaded'}
TASK_TABLES={'spatial_plan_tasks','generation_jobs','preview_jobs','edit_render_jobs','spatial_exports','media_import_items','text_tool_attempts','canvas_agent_turns','intelligent_tasks','script_suggestion_runs','parse_attempts','edit_preview_jobs','edit_preview_attempts'}
MANAGEMENT_ACTIONS={'management_'+x for x in ('rename','folder_create','folder_update','folder_move','folder_order','folder_remove','move','trash','restore','purge','retention')}


def inactive_project_ids():
    return select(S.management_project_states.c.project_id).where(S.management_project_states.c.state!='active')


def project_state(conn,p):
    return conn.execute(select(S.management_project_states.c.state).where(S.management_project_states.c.project_id==p)).scalar_one_or_none() or 'active'


def hidden_object_ids(conn,p):
    hidden=set(conn.execute(select(S.management_object_states.c.object_id).where(S.management_object_states.c.project_id==p,S.management_object_states.c.state!='active')).scalars())
    edges=[]
    for table in (S.episodes,S.scenes,S.sequences,S.shots):edges.extend(conn.execute(select(table.c.parent_id,table.c.id).where(table.c.project_id==p)).all())
    while True:
        previous=len(hidden);hidden.update(child for parent,child in edges if parent in hidden)
        if len(hidden)==previous:return hidden


def management_project_guard(conn,p):
    if project_state(conn,p)!='active':raise ResourceError('项目已回收或永久停用，请从项目管理恢复；固定历史资料仍可回看','project_recycled',409)


def management_object_guard(conn,p,identifier):
    management_project_guard(conn,p)
    if checked_id(identifier) in hidden_object_ids(conn,p):raise ResourceError('此对象或其父级已回收，请先恢复原关系','object_recycled',409)


def management_transaction_guard(conn,p,action,payload):
    if action in MANAGEMENT_ACTIONS:return
    # Verified settlement of an existing order must survive project recycling.
    if action=="commerce_gateway_event":
        from vsc.assets.commerce import is_verified_commerce_notification
        if is_verified_commerce_notification(p,payload):return
    management_project_guard(conn,p)
    hidden=hidden_object_ids(conn,p)
    if not hidden:return
    keys={'object_id','object_ids','shot_id','shot_ids','asset_id','episode_id','episode_ids','scene_id','sequence_id','target_object_id','scope_object_id','parent_id','scope'}
    found=set()
    typed={'edit_version_id':'edit_revisions','run_version_id':'artifact_versions','draft_version_id':'artifact_versions','artifact_id':'artifact_versions','source_artifact_id':'artifact_versions','canvas_id':'creative_canvases','spatial_scene_id':'spatial_scenes','spatial_version_id':'spatial_scene_versions','workflow_id':'intelligent_workflows','job_id':'generation_jobs','candidate_id':'binding_candidates','slot_id':'binding_slots','unit_id':'text_tool_units'}
    contextual={'job_id':'edit_render_jobs' if 'edit_export' in action else None,'version_id': 'intelligent_versions' if 'intelligent' in action else 'creative_canvas_versions' if 'canvas' in action else 'spatial_scene_versions' if 'spatial' in action else None,'task_id':'intelligent_tasks' if 'intelligent' in action else 'spatial_plan_tasks' if 'spatial' in action else None,'turn_id':'canvas_agent_turns' if 'canvas' in action else None,'export_id':'spatial_exports' if 'spatial' in action else 'edit_render_jobs' if 'edit' in action else None,'restore_version_id':'edit_revisions' if 'edit_workspace' in action else None}
    typed.update({k:v for k,v in contextual.items() if v})
    resolver=ProjectManagementRepository()
    def visit(value,key=None):
        if isinstance(value,dict):
            for k,v in value.items():visit(v,k)
        elif isinstance(value,list):
            for v in value:visit(v,key)
        elif isinstance(value,str):
            if key in keys:found.add(value)
            if key in typed:
                table=S.metadata.tables[typed[key]]
                row=conn.execute(select(table).where(table.c.project_id==p,table.c.id==checked_id(value))).mappings().first()
                if row:found.update(resolver._management_targets(conn,p,table,dict(row)))
    visit(payload)
    if found & hidden:raise ResourceError('写入范围包含已回收对象，请先恢复','object_recycled',409)


def filter_management_rows(conn,p,table,rows):
    management_project_guard(conn,p)
    hidden=hidden_object_ids(conn,p)
    if not hidden:return rows
    resolver=ProjectManagementRepository()
    return [row for row in rows if not (resolver._management_targets(conn,p,table,dict(row)) & hidden)]


class ProjectManagementRepository:
    def management_filter_active_projects(self,items):
        with self.engine.connect() as conn:
            inactive=set(conn.execute(inactive_project_ids()).scalars())
        return [row for row in items if row['id'] not in inactive]

    def management_recycled_projects(self):
        with self.engine.connect() as conn:
            rows=clean([dict(r) for r in conn.execute(select(S.projects,S.management_project_states.c.state,S.management_project_states.c.changed_at,S.management_project_states.c.reason).join(S.management_project_states,S.projects.c.id==S.management_project_states.c.project_id).where(S.management_project_states.c.state=='trashed').order_by(S.management_project_states.c.changed_at.desc())).mappings()])
        if hasattr(self,'access_filter_projects'):rows=self.access_filter_projects(rows)
        return {'items':rows,'total':len(rows)}

    def management_snapshot(self,project_id,folder_id=None,kind=None,q='',offset=0,limit=100):
        p=checked_id(project_id)
        if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=200:raise ResourceError('分页范围不合法')
        if kind not in {None,'object','media','trashed'} or not isinstance(q,str) or len(q)>200:raise ResourceError('筛选条件不合法')
        with self.engine.connect().execution_options(isolation_level='REPEATABLE READ') as conn:
            project=self._project(conn,p);hidden=hidden_object_ids(conn,p)
            folders=[dict(r) for r in conn.execute(select(S.management_folders).where(S.management_folders.c.project_id==p).order_by(S.management_folders.c.ordinal,S.management_folders.c.id)).mappings()]
            if folder_id and folder_id!='unfiled' and folder_id not in {r['id'] for r in folders}:raise ResourceError('文件夹不属于当前项目','folder_scope')
            memberships={}
            for table,key,typ in [(S.object_folder_memberships,'object_id','object'),(S.media_folder_memberships,'media_id','media')]:
                memberships.update({(typ,r[key]):r['folder_id'] for r in conn.execute(select(table).where(table.c.project_id==p)).mappings()})
            states={r['object_id']:dict(r) for r in conn.execute(select(S.management_object_states).where(S.management_object_states.c.project_id==p)).mappings()}
            policy=conn.execute(select(S.management_retention).where(S.management_retention.c.project_id==p)).mappings().first();days=policy['days'] if policy else None
            purged=set()
            for identifier,state in states.items():
                if state['state']=='purged':purged.update(self._descendant_ids(conn,p,identifier))
            items=[]
            for row in conn.execute(select(S.creative_objects).where(S.creative_objects.c.project_id==p)).mappings():
                state=states.get(row['id'],{});current=state.get('state','active')
                if row['id'] in purged:continue
                trashed=row['id'] in hidden
                if (kind=='trashed')!=trashed:continue
                items.append(dict(row,type='object',state=current if current!='active' else 'parent_trashed' if trashed else 'active',changed_at=state.get('changed_at'),reason=state.get('reason'),folder_id=memberships.get(('object',row['id']))))
            from .media_recycle import recycled_ids
            recycled=set(conn.execute(recycled_ids(p)).scalars())
            if kind not in {'object','trashed'}:
                for row in conn.execute(select(S.media_items.c.id,S.media_items.c.name,S.media_items.c.modality,S.media_items.c.created_at).where(S.media_items.c.project_id==p)).mappings():
                    if row['id'] not in recycled:items.append(dict(row,type='media',kind=row['modality'],title=row['name'],state='active',folder_id=memberships.get(('media',row['id']))))
            if kind=='media':items=[r for r in items if r['type']=='media']
            if folder_id:items=[r for r in items if r.get('folder_id')==(None if folder_id=='unfiled' else folder_id)]
            if q:items=[r for r in items if q.casefold() in (r.get('title','')+' '+r.get('display_code','')+' '+r['id']).casefold()]
            for row in items:
                if row.get('changed_at') and days:row['due_at']=row['changed_at']+timedelta(days=days);row['expired']=row['due_at']<=datetime.now(timezone.utc)
            items.sort(key=lambda r:(r['type'],str(r.get('created_at','')),r['id']))
            return clean(dict(project=project,project_id=p,revision=project['revision'],state=project_state(conn,p),folders=folders,items=items[offset:offset+limit],total=len(items),offset=offset,next_offset=offset+limit if offset+limit<len(items) else None,retention_days=days,automatic_deletion=False,physical_delete_available=False,released_bytes=0))

    def _management_targets(self,conn,p,table,row,seen=None):
        seen=set(seen or ());token=(table.name,tuple(row.get(c.name) for c in table.primary_key.columns))
        if token in seen or len(seen)>16:return set()
        seen.add(token);targets=set()
        if table.name in OBJECT_TABLES and row.get('id'):targets.add(row['id'])
        if table.name=='artifact_versions':targets.update(conn.execute(select(S.artifact_object_scopes.c.object_id).where(S.artifact_object_scopes.c.project_id==p,S.artifact_object_scopes.c.artifact_id==row['id'])).scalars())
        for constraint in table.foreign_key_constraints:
            elements=list(constraint.elements)
            target=elements[0].column.table
            if 'project_id' not in target.c or all(fk.parent.name=='project_id' for fk in elements):continue
            values=[(fk.column.name,row.get(fk.parent.name)) for fk in elements]
            if any(value is None for _,value in values):continue
            parent=conn.execute(select(target).where(*(target.c[column]==value for column,value in values))).mappings().first()
            if parent:
                if target.name in OBJECT_TABLES:targets.add(parent['id'])
                else:targets.update(self._management_targets(conn,p,target,dict(parent),seen))
        return targets

    def _management_protections(self,conn,p,ids,permanent=False,whole=False):
        reasons=[]
        for name in TASK_TABLES:
            table=S.metadata.tables.get(name)
            if table is None or 'status' not in table.c:continue
            for row in conn.execute(select(table).where(table.c.project_id==p,table.c.status.in_(ACTIVE_TASKS))).mappings():
                targets=self._management_targets(conn,p,table,dict(row))
                if whole or not targets or targets & ids:reasons.append({'code':'in_flight','table':name,'id':row['id'],'message':'仍有等待、在途或待接续任务'});break
        if permanent:
            structural=OBJECT_TABLES|{'object_folder_memberships','management_object_states','management_project_states','management_retention','management_folders','media_folder_memberships'}
            for table in S.metadata.tables.values():
                if table.name in structural or 'project_id' not in table.c:continue
                columns={fk.parent.name for fk in table.foreign_keys if fk.column.table.name in OBJECT_TABLES and fk.column.name=='id'}
                if columns and conn.execute(select(table.c.project_id).where(table.c.project_id==p,or_(*(table.c[c].in_(ids) for c in columns))).limit(1)).first():reasons.append({'code':'referenced','table':table.name,'message':'仍有固定资料、版本或使用关系引用'})
            if whole:
                for table in (S.artifact_versions,S.media_items,S.source_versions):
                    if conn.execute(select(table.c.id).where(table.c.project_id==p).limit(1)).first():reasons.append({'code':'project_evidence','table':table.name,'message':'项目仍有原始资料或固定证据'})
        return reasons

    def management_command(self,project_id,payload,actor,**kw):
        op=payload.get('operation')
        fields={'rename':{'title'},'folder_create':{'title','parent_id'},'folder_update':{'folder_id','title'},'folder_move':{'folder_id','parent_id'},'folder_order':{'parent_id','folder_ids'},'folder_remove':{'folder_id'},'move':{'target_type','target_id','folder_id'},'trash':{'target_type','target_id','reason'},'restore':{'target_type','target_id','reason'},'purge':{'target_type','target_id','reason','confirm_name'},'retention':{'days'}}
        if op not in fields or set(payload)-({'operation'}|fields[op]):raise ResourceError('管理字段不合法','management_payload')
        def apply(conn,project):
            p=project['id'];state=project_state(conn,p)
            if state=='purged':raise ResourceError('项目已永久停用，不能恢复或修改','project_purged',409)
            if state!='active' and op not in {'restore','purge','retention'}:raise ResourceError('请先恢复项目','project_recycled',409)
            def title():
                value=payload.get('title')
                if not isinstance(value,str) or not value.strip() or len(value)>200:raise ResourceError('名称需为1至200字')
                return value.strip()
            def folder(identifier):
                return self._one(conn,S.management_folders,p,checked_id(identifier)) if identifier else None
            if op=='rename':
                conn.execute(update(S.projects).where(S.projects.c.id==p).values(name=title()));return {'name':title()}
            if op=='retention':
                days=payload.get('days')
                if days is not None and (type(days)is not int or not 1<=days<=36500):raise ResourceError('留存天数需为1至36500，或留空不设期限')
                old=conn.execute(select(S.management_retention.c.id).where(S.management_retention.c.project_id==p)).scalar_one_or_none()
                if old:conn.execute(update(S.management_retention).where(S.management_retention.c.project_id==p).values(days=days,actor=actor,created_at=datetime.now(timezone.utc)))
                else:conn.execute(insert(S.management_retention).values(project_id=p,id=new_id(),days=days,actor=actor))
                return {'retention_days':days,'automatic_deletion':False}
            if op.startswith('folder_'):
                identifier=checked_id(payload['folder_id']) if payload.get('folder_id') else None
                current=folder(identifier) if identifier else None;parent=payload.get('parent_id');folder(parent)
                if op not in {'folder_create','folder_order'} and not current:raise ResourceError('需要当前项目文件夹','folder_required')
                if op in {'folder_create','folder_move'}:
                    cursor=parent;visited=set()
                    while cursor:
                        if cursor==identifier or cursor in visited:raise ResourceError('文件夹不能移入自身或后代','folder_cycle')
                        visited.add(cursor);cursor=folder(cursor)['parent_id']
                    maximum=conn.execute(select(func.max(S.management_folders.c.ordinal)).where(S.management_folders.c.project_id==p,S.management_folders.c.parent_id==parent)).scalar_one_or_none()
                    values={'parent_id':parent,'ordinal':(maximum if maximum is not None else -1)+1}
                    if op=='folder_create':identifier=new_id();conn.execute(insert(S.management_folders).values(project_id=p,id=identifier,title=title(),**values))
                    else:conn.execute(update(S.management_folders).where(S.management_folders.c.project_id==p,S.management_folders.c.id==identifier).values(**values))
                elif op=='folder_update':conn.execute(update(S.management_folders).where(S.management_folders.c.project_id==p,S.management_folders.c.id==identifier).values(title=title()))
                elif op=='folder_order':
                    ids=payload.get('folder_ids');rows=list(conn.execute(select(S.management_folders.c.id,S.management_folders.c.ordinal).where(S.management_folders.c.project_id==p,S.management_folders.c.parent_id==parent)))
                    if not isinstance(ids,list) or len(ids)!=len(rows) or set(ids)!={r.id for r in rows}:raise ResourceError('排序需包含当前父级的全部文件夹','folder_order_scope')
                    start=max([r.ordinal for r in rows]+[-1])+1
                    for n,i in enumerate(ids):conn.execute(update(S.management_folders).where(S.management_folders.c.project_id==p,S.management_folders.c.id==i).values(ordinal=start+n))
                    for n,i in enumerate(ids):conn.execute(update(S.management_folders).where(S.management_folders.c.project_id==p,S.management_folders.c.id==i).values(ordinal=n))
                elif op=='folder_remove':
                    for table,column in [(S.management_folders,'parent_id'),(S.object_folder_memberships,'folder_id'),(S.media_folder_memberships,'folder_id')]:
                        if conn.execute(select(table.c.id).where(table.c.project_id==p,table.c[column]==identifier).limit(1)).first():raise ResourceError('文件夹仍有子目录或内容，请先移动内容','folder_not_empty')
                    conn.execute(delete(S.management_folders).where(S.management_folders.c.project_id==p,S.management_folders.c.id==identifier))
                return {'folder_id':identifier,'operation':op}
            typ=payload.get('target_type');identifier=payload.get('target_id')
            if typ not in {'project','object','media'}:raise ResourceError('目标类型不合法')
            if typ=='project':
                if identifier!=p:raise ResourceError('不能跨项目管理','management_scope')
                row=project;ids=set(conn.execute(select(S.creative_objects.c.id).where(S.creative_objects.c.project_id==p)).scalars())
            elif typ=='object':row=self._one(conn,S.creative_objects,p,checked_id(identifier));ids=self._descendant_ids(conn,p,identifier)
            else:row=self._one(conn,S.media_items,p,checked_id(identifier));ids=set()
            if op=='move':
                if typ=='project':raise ResourceError('项目内目录不能跨项目移动项目')
                if typ=='object':management_object_guard(conn,p,identifier)
                destination=payload.get('folder_id');folder(destination)
                table,key=(S.object_folder_memberships,'object_id') if typ=='object' else (S.media_folder_memberships,'media_id')
                conn.execute(delete(table).where(table.c.project_id==p,table.c[key]==identifier))
                if destination:conn.execute(insert(table).values(project_id=p,id=new_id(),**{key:identifier},folder_id=destination))
                return {'target_id':identifier,'folder_id':destination}
            if typ=='media':raise ResourceError('素材回收与恢复请使用原素材回收入口；物理清理尚不可用','use_media_recycle')
            reason=payload.get('reason')
            if not isinstance(reason,str) or not reason.strip() or len(reason)>2000:raise ResourceError('请填写操作原因，最多2000字')
            table=S.management_project_states if typ=='project' else S.management_object_states
            where=[table.c.project_id==p]+([table.c.object_id==identifier] if typ=='object' else [])
            old=conn.execute(select(table).where(*where)).mappings().first();current=old['state'] if old else 'active'
            if current=='purged':raise ResourceError('此对象已永久停用','object_purged',409)
            desired={'trash':'trashed','restore':'active','purge':'purged'}[op]
            if current==desired:return {'target_id':identifier,'state':desired,'unchanged':True}
            if op=='restore' and typ=='object':
                ancestors=self._descendant_ids(conn,p,identifier,include_ancestors=True)-ids
                if ancestors & hidden_object_ids(conn,p) or state!='active':raise ResourceError('请先恢复项目及全部父级关系','restore_parent_first',409)
            if op in {'trash','purge'}:
                if op=='purge' and (current!='trashed' or payload.get('confirm_name')!=(row.get('title') or row.get('name'))):raise ResourceError('永久停用须先回收并完整输入目标名称','purge_confirmation')
                reasons=self._management_protections(conn,p,ids,permanent=op=='purge',whole=typ=='project')
                if reasons:return {'target_id':identifier,'status':'protected','state':current,'reasons':reasons,'released_bytes':0}
            if op=='purge':conn.execute(delete(S.object_folder_memberships).where(S.object_folder_memberships.c.project_id==p,S.object_folder_memberships.c.object_id.in_(ids)))
            values={'state':desired,'reason':reason.strip(),'actor':actor,'changed_at':datetime.now(timezone.utc)}
            if old:conn.execute(update(table).where(*where).values(**values))
            else:conn.execute(insert(table).values(project_id=p,id=new_id(),**({'object_id':identifier} if typ=='object' else {}),**values))
            return {'target_id':identifier,'target_type':typ,'state':desired,'previous_state':current,'reason':values['reason'],'changed_at':values['changed_at'],'released_bytes':0,'audit_retained':True}
        return self._mutate(project_id,'management_'+str(op),payload,actor=actor,callback=apply,**kw)
