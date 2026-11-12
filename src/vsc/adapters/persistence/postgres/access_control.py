"""Revocation and project writes share one ordered PostgreSQL authority lock."""
from datetime import datetime,timezone
from hashlib import sha256
import json
from sqlalchemy import select,insert,update,delete,text as sql,func,or_,and_,exists,false,literal
from sqlalchemy.dialects.postgresql import insert as pg_insert
from vsc.assets.access_control import Principal,current_principal,denied,secret_hash,label,expires,CAPABILITIES,action_capability
from vsc.assets.resource_service import ResourceError,Conflict
from . import schema as S
from .values import new_id,checked_id,clean,digest


def authority_lock(conn,exclusive=False):
    name='pg_advisory_xact_lock' if exclusive else 'pg_advisory_xact_lock_shared'
    conn.execute(sql('SELECT '+name+'(hashtextextended(current_schema() || :suffix,0))'),{'suffix':':vsc-access-authority'})


class AccessControlRepository:
    def _access_project_query(self, conn, capability='read'):
        if capability not in {'read', 'edit', 'manage'}:
            raise ResourceError('项目目录能力无效', 'invalid_access_input')
        principal, person, share = self._access_principal(conn)
        projects, bindings = S.projects, S.access_projects
        query = select(projects.c.id)
        if principal is None:
            return query
        if principal.api_key_id:
            denied('完整项目目录不接受开放接口凭据')
        if not person:
            if capability == 'read' and principal.local_read and not share:
                return query.where(~exists(select(1).where(bindings.c.project_id == projects.c.id)))
            return query.where(false())
        roles = [role for role, capabilities in CAPABILITIES.items() if capability in capabilities]
        workspaces, members, project_members = S.access_workspaces, S.access_workspace_members, S.access_project_members
        # Exactly the existing _workspace_roles rule: any direct role, ancestor
        # owners only. UNION (not UNION ALL) also bounds malformed cycles.
        ancestry = select(workspaces.c.id.label('workspace_id'), workspaces.c.id.label('ancestor_id')).cte('access_project_ancestry_' + capability, recursive=True)
        ancestry = ancestry.union(select(ancestry.c.workspace_id, workspaces.c.parent_id)
            .join(workspaces, workspaces.c.id == ancestry.c.ancestor_id).where(workspaces.c.parent_id.is_not(None)))
        workspace_grant = exists(select(1).select_from(ancestry.join(members, members.c.workspace_id == ancestry.c.ancestor_id))
            .where(ancestry.c.workspace_id == bindings.c.workspace_id, members.c.identity_id == person['id'],
                members.c.active.is_(True), or_(and_(ancestry.c.ancestor_id == ancestry.c.workspace_id,
                    members.c.role.in_(roles)), members.c.role == 'owner')))
        bound_grant = exists(select(1).where(bindings.c.project_id == projects.c.id, workspace_grant))
        # Keep a direct project's membership check at the same nesting level as
        # projects.  If it is nested inside bound_grant SQLAlchemy includes a
        # second, uncorrelated projects table, turning one grant into access to
        # every bound project.  The join also preserves _access_require's rule
        # that project membership only applies to a project with a binding.
        project_grant = exists(select(1).select_from(project_members.join(bindings,
            bindings.c.project_id == project_members.c.project_id)).where(project_members.c.project_id == projects.c.id,
            project_members.c.identity_id == person['id'], project_members.c.active.is_(True), project_members.c.role.in_(roles)))
        unassigned = and_(literal(bool(principal.local and person['subject_key'].startswith('local:'))),
            ~exists(select(1).where(bindings.c.project_id == projects.c.id)))
        return query.where(or_(bound_grant, project_grant, unassigned))

    def _access_identity(self,conn,identifier):
        row=conn.execute(select(S.access_identities).where(S.access_identities.c.id==checked_id(identifier))).mappings().first()
        if not row or not row['active']:denied('身份已停用或不存在')
        return dict(row)

    def _access_principal(self,conn,principal=None):
        principal=principal if principal is not None else current_principal()
        if principal is None:return None,None,None
        person=self._access_identity(conn,principal.identity_id) if principal.identity_id else None
        if person and principal.actor!=person['actor']:denied('会话身份标签不符')
        if principal.api_key_id:
            from .service_operations import ServiceOperationsRepository
            ServiceOperationsRepository(self).validate_api_key(conn,principal)
            if principal.local or principal.local_read or principal.share_id:denied('API身份不得携带本机或分享权限')
        if principal.credential_id:
            credential=conn.execute(select(S.access_credentials).where(S.access_credentials.c.id==principal.credential_id,S.access_credentials.c.identity_id==principal.identity_id)).mappings().first()
            if not credential or credential['revoked']:denied('登录凭据已撤销')
        share=None
        if principal.share_id:
            share=conn.execute(select(S.access_shares).where(S.access_shares.c.id==principal.share_id)).mappings().first()
            if not share or share['revoked'] or share['expires_at']<=datetime.now(timezone.utc):denied('分享已撤销或到期')
        return principal,person,share

    def _workspace_roles(self,conn,workspace_id,identity_id):
        roles=set();visited=set();cursor=checked_id(workspace_id);first=True
        while cursor:
            if cursor in visited:raise ResourceError('组织父子关系成环','invalid_workspace')
            visited.add(cursor)
            workspace=conn.execute(select(S.access_workspaces).where(S.access_workspaces.c.id==cursor)).mappings().first()
            if not workspace:raise ResourceError('工作室不存在','not_found',404)
            member=conn.execute(select(S.access_workspace_members).where(S.access_workspace_members.c.workspace_id==cursor,S.access_workspace_members.c.identity_id==identity_id,S.access_workspace_members.c.active.is_(True))).mappings().first()
            if member and (first or member['role']=='owner'):roles.add(member['role'])
            first=False;cursor=workspace['parent_id']
        return roles

    def _workspace_require(self,conn,workspace_id,capability,identity_id):
        roles=self._workspace_roles(conn,workspace_id,identity_id)
        if capability not in set().union(*(CAPABILITIES[r] for r in roles)):denied('没有此工作室权限')
        return roles

    def access_workspace_guard(self,conn,workspace_id,capability='manage'):
        authority_lock(conn)
        principal,person,_=self._access_principal(conn)
        if principal is None:return {'trusted_internal':True}
        if not person:denied('工作室需要成员身份')
        return {'workspace_id':workspace_id,'roles':sorted(self._workspace_require(conn,workspace_id,capability,person['id']))}

    def authorize_workspace(self,workspace_id,capability='manage'):
        with self.engine.connect() as conn:
            p,person,_=self._access_principal(conn)
            if p is None:return {'trusted_internal':True}
            if not person:denied('工作室需要已认证成员')
            return {'workspace_id':workspace_id,'roles':sorted(self._workspace_require(conn,workspace_id,capability,person['id']))}

    def _share_media_ids(self,conn,share):
        ids=set(conn.execute(select(S.access_share_media.c.media_id).where(S.access_share_media.c.share_id==share['id'])).scalars())
        if share['mode']=='edit':
            current=conn.execute(select(S.creative_canvases.c.current_version_id).where(S.creative_canvases.c.project_id==share['project_id'],S.creative_canvases.c.id==share['canvas_id'])).scalar_one()
            ids.update(conn.execute(select(S.creative_canvas_nodes.c.media_id).where(S.creative_canvas_nodes.c.project_id==share['project_id'],S.creative_canvas_nodes.c.version_id==current,S.creative_canvas_nodes.c.media_id.is_not(None))).scalars())
        return ids

    def _access_require(self,conn,project_id,capability='read',target_type=None,target_id=None):
        principal,person,share=self._access_principal(conn)
        if principal is None:return {'project_id':project_id,'trusted_internal':True,'capabilities':list(CAPABILITIES['owner'])}
        binding=conn.execute(select(S.access_projects).where(S.access_projects.c.project_id==project_id)).mappings().first()
        roles=set()
        if binding and person:
            roles=self._workspace_roles(conn,binding['workspace_id'],person['id'])
            member=conn.execute(select(S.access_project_members).where(S.access_project_members.c.project_id==project_id,S.access_project_members.c.identity_id==person['id'],S.access_project_members.c.active.is_(True))).mappings().first()
            if member:roles.add(member['role'])
        elif not binding and person and principal.local and person['subject_key'].startswith('local:'):
            roles={'owner'}
        caps=set().union(*(CAPABILITIES[r] for r in roles))
        if principal.api_key_id:
            from .service_operations import ServiceOperationsRepository
            key=ServiceOperationsRepository(self).validate_api_key(conn,principal,project_id,capability)
            caps.intersection_update(key['capabilities'])
        if capability in caps:
            return {'project_id':project_id,'workspace_id':binding['workspace_id'] if binding else None,'current_identity_id':person['id'],'actor':person['actor'],'effective_role':next(r for r in CAPABILITIES if r in roles),'roles':sorted(roles),'capabilities':sorted(caps),'unassigned':not bool(binding),'review_lanes':binding['review_lanes'] if binding else []}
        if share and share['project_id']==project_id:
            allowed=(capability=='read' and target_type=='canvas_version' and target_id==share['canvas_version_id'])
            allowed=allowed or (capability=='read' and target_type=='media' and target_id in self._share_media_ids(conn,share))
            allowed=allowed or (share['mode']=='edit' and capability in {'read','edit'} and target_type=='canvas' and target_id==share['canvas_id'])
            if allowed:return {'project_id':project_id,'share_id':share['id'],'mode':share['mode'],'capabilities':['read','edit'] if share['mode']=='edit' else ['read'],'current_identity_id':person['id'] if person else None}
        # Preserve the pre-existing unauthenticated local read facade only for
        # projects explicitly left unassigned. Bound personal/studio projects are private.
        if not binding and principal.local_read and not person and not share and capability=='read':return {'project_id':project_id,'unassigned':True,'capabilities':['read']}
        denied()

    def authorize_access(self,project_id,capability='read',target_type=None,target_id=None):
        with self.engine.connect() as conn:
            self._project(conn,checked_id(project_id))
            return self._access_require(conn,project_id,capability,target_type,target_id)

    def access_transaction_guard(self,conn,project_id,action,payload,actor):
        principal=current_principal()
        if principal is None:return
        authority_lock(conn,exclusive=action in {'service_api_key_issue','service_api_key_revoke','service_account_close'})
        if principal.actor!=actor:denied('操作身份必须来自当前会话')
        target_type,target_id=None,None
        if action=='save_creative_canvas':target_type,target_id='canvas',payload.get('canvas_id')
        if action=='access_review_mark_read':
            scope=self._access_require(conn,project_id,'read',target_type,target_id)
            if not ({'edit','review'}&set(scope.get('capabilities',[]))):denied('需要项目编辑或审阅权限')
        else:
            scope=self._access_require(conn,project_id,action_capability(action),target_type,target_id)
        if scope.get('share_id') and target_type=='canvas':
            _,_,share=self._access_principal(conn)
            allowed=self._share_media_ids(conn,share)
            document=payload.get('document',{})
            if any(n.get('media_id') and n['media_id'] not in allowed or n.get('job_id') for n in document.get('nodes',[])):denied('协作链接不能新增未共享媒体或任务绑定')
            current=conn.execute(select(S.creative_canvases.c.current_version_id).where(S.creative_canvases.c.project_id==project_id,S.creative_canvases.c.id==target_id)).scalar_one()
            original=self._canvas_document(conn,project_id,self._one(conn,S.creative_canvas_versions,project_id,current))
            references=('shot_id','model_id','spatial_scene_id','spatial_version_id','edit_workspace_id','edit_version_id','tool_draft_id')
            by_id={node['id']:node for node in original['nodes']}
            for node in document.get('nodes',[]):
                prior=by_id.get(node['id'],{})
                if any(node.get(key)!=prior.get(key) for key in references):denied('协作链接不能新增或替换未共享的领域引用')

    def access_filter_projects(self,items):
        if current_principal() is None:return items
        with self.engine.connect() as conn:
            result=[]
            for row in items:
                try:checked_id(row['id'])
                except ResourceError:
                    principal=current_principal()
                    if not principal or principal.local or principal.local_read:result.append(row)
                    continue
                try:scope=self._access_require(conn,row['id'])
                except ResourceError as exc:
                    if exc.code=='access_denied':continue
                    raise
                result.append(dict(row,access_capabilities=scope['capabilities'],read_only=bool(row.get('read_only')) or 'edit' not in scope['capabilities']))
            return result

    def _access_state(self,conn):
        conn.execute(pg_insert(S.access_state).values(id=1,revision=0).on_conflict_do_nothing())
        return conn.execute(select(S.access_state.c.revision).where(S.access_state.c.id==1).with_for_update()).scalar_one()

    def _personal_workspace(self,conn,person):
        existing=conn.execute(select(S.access_workspaces.c.id).where(S.access_workspaces.c.kind=='personal',S.access_workspaces.c.created_by==person['id'])).scalar_one_or_none()
        if existing:return existing
        workspace=new_id();conn.execute(insert(S.access_workspaces).values(id=workspace,name=person['display_name']+'的个人空间',kind='personal',parent_id=None,created_by=person['id']))
        conn.execute(insert(S.access_workspace_members).values(workspace_id=workspace,identity_id=person['id'],role='owner',active=True))
        return workspace

    def ensure_local_access(self,actor):
        with self.engine.begin() as conn:
            authority_lock(conn,True);revision=self._access_state(conn)
            subject='local:'+sha256(actor.encode()).hexdigest()
            row=conn.execute(select(S.access_identities).where(S.access_identities.c.subject_key==subject)).mappings().first()
            if not row:
                row={'id':new_id(),'subject_key':subject,'actor':actor,'display_name':actor,'preferences':{},'active':True}
                conn.execute(insert(S.access_identities).values(**row));self._personal_workspace(conn,row)
                conn.execute(update(S.access_state).where(S.access_state.c.id==1).values(revision=revision+1))
            if not row['active']:denied('本机身份已停用')
            return {'identity_id':row['id'],'actor':row['actor'],'local':True,'workspace_id':self._personal_workspace(conn,row)}

    def authenticate_access(self,secret):
        hashed=secret_hash(secret)
        with self.engine.connect() as conn:
            row=conn.execute(select(S.access_credentials).where(S.access_credentials.c.secret_sha256==hashed,S.access_credentials.c.revoked.is_(False))).mappings().first()
            if row:
                person=self._access_identity(conn,row['identity_id'])
                workspace=conn.execute(select(S.access_workspaces.c.id).where(S.access_workspaces.c.created_by==person['id'],S.access_workspaces.c.kind=='personal')).scalar_one()
                return {'identity_id':person['id'],'actor':person['actor'],'credential_id':row['id'],'local':False,'workspace_id':workspace}
            share=conn.execute(select(S.access_shares).where(S.access_shares.c.secret_sha256==hashed,S.access_shares.c.revoked.is_(False))).mappings().first()
            if not share or share['expires_at']<=datetime.now(timezone.utc):denied('凭据无效或已撤销/到期')
            return {'share_id':share['id'],'actor':'share:'+share['id'],'local':False}

    def accept_access_invitation(self,payload):
        if not isinstance(payload,dict) or set(payload)-{'invitation_secret','credential_secret','display_name','use_current_identity'}:raise ResourceError('邀请加入字段无效')
        invitation_hash=secret_hash(payload.get('invitation_secret'));credential_hash=secret_hash(payload.get('credential_secret'));name=label(payload.get('display_name'))
        use_current=payload.get('use_current_identity',False)
        if type(use_current) is not bool:raise ResourceError('需要明确选择加入身份','invalid_access_input')
        with self.engine.begin() as conn:
            authority_lock(conn,True);revision=self._access_state(conn)
            joining_principal,joining_person,_=self._access_principal(conn) if use_current else (None,None,None)
            if use_current and not joining_person:denied('用当前身份加入需要先登录成员')
            invitation=conn.execute(select(S.access_invitations).where(S.access_invitations.c.secret_sha256==invitation_hash).with_for_update()).mappings().first()
            if not invitation or invitation['revoked'] or invitation['expires_at']<=datetime.now(timezone.utc):denied('邀请已失效')
            if invitation['accepted_by']:
                existing=conn.execute(select(S.access_credentials).where(S.access_credentials.c.identity_id==invitation['accepted_by'],S.access_credentials.c.secret_sha256==credential_hash,S.access_credentials.c.revoked.is_(False))).mappings().first()
                if not existing:denied('邀请已被使用')
                person=self._access_identity(conn,invitation['accepted_by']);credential=existing['id']
                if use_current and joining_person['id']!=person['id']:denied('邀请已由另一身份使用')
            else:
                person=joining_person or {'id':new_id(),'subject_key':'member:'+new_id(),'actor':'member:'+new_id(),'display_name':name,'preferences':{},'active':True};credential=new_id()
                if not joining_person:conn.execute(insert(S.access_identities).values(**person))
                conn.execute(insert(S.access_credentials).values(id=credential,identity_id=person['id'],secret_sha256=credential_hash,revoked=False))
                table=S.access_workspace_members if invitation['workspace_id'] else S.access_project_members
                field='workspace_id' if invitation['workspace_id'] else 'project_id';target=invitation[field]
                current=conn.execute(select(table).where(table.c[field]==target,table.c.identity_id==person['id'])).mappings().first()
                role=current['role'] if current and current['active'] else invitation['role']
                conn.execute(pg_insert(table).values(**{field:target,'identity_id':person['id'],'role':role,'active':True}).on_conflict_do_update(index_elements=[field,'identity_id'],set_={'role':role,'active':True}))
                conn.execute(update(S.access_invitations).where(S.access_invitations.c.id==invitation['id']).values(accepted_by=person['id']))
                self._personal_workspace(conn,person)
                self._access_seat_check(conn)
                self._access_event(conn,'invitation:'+invitation['id'],None,'accept_invitation',digest({'invitation_id':invitation['id'],'credential_sha256':credential_hash}),revision,{'identity_id':person['id'],'invitation_id':invitation['id']})
            return {'identity_id':person['id'],'actor':person['actor'],'credential_id':credential,'local':bool(joining_principal and joining_principal.local),'workspace_id':self._personal_workspace(conn,person)}

    def _access_event(self,conn,key,identity,action,request_sha,revision,response):
        revision+=1;response=clean(dict(response,access_revision=revision))
        conn.execute(update(S.access_state).where(S.access_state.c.id==1).values(revision=revision))
        conn.execute(insert(S.access_commands).values(key=key,identity_id=identity,action=action,request_sha256=request_sha,revision=revision,response=response))
        return response

    def access_snapshot(self):
        with self.engine.connect() as conn:
            principal,person,_=self._access_principal(conn)
            if not principal or not person:denied('账户与组织页面需要成员身份')
            workspaces=[]
            for row in conn.execute(select(S.access_workspaces).order_by(S.access_workspaces.c.created_at)).mappings():
                roles=self._workspace_roles(conn,row['id'],person['id'])
                if roles:workspaces.append({**dict(row),'roles':sorted(roles),'manageable':'owner' in roles})
            managed={r['id'] for r in workspaces if r['manageable']}
            project_rows=[]
            for row in conn.execute(select(S.projects)).mappings():
                try:scope=self._access_require(conn,row['id'])
                except ResourceError:continue
                project_rows.append({'id':row['id'],'name':row['name'],'revision':row['revision'],**scope})
            managed_projects={r['id'] for r in project_rows if 'manage' in r['capabilities']}
            members=[]
            for table,field,ids in [(S.access_workspace_members,'workspace_id',managed),(S.access_project_members,'project_id',managed_projects)]:
                if ids:
                    q=select(table,S.access_identities.c.display_name,S.access_identities.c.actor).join(S.access_identities,table.c.identity_id==S.access_identities.c.id).where(table.c[field].in_(ids))
                    members.extend(dict(r) for r in conn.execute(q).mappings())
            invitations=[{k:v for k,v in dict(r).items() if k!='secret_sha256'} for r in conn.execute(select(S.access_invitations).where(or_(S.access_invitations.c.created_by==person['id'],S.access_invitations.c.workspace_id.in_(managed),S.access_invitations.c.project_id.in_(managed_projects))).order_by(S.access_invitations.c.created_at.desc())).mappings()]
            shares=[{k:v for k,v in dict(r).items() if k!='secret_sha256'} for r in conn.execute(select(S.access_shares).where(or_(S.access_shares.c.created_by==person['id'],S.access_shares.c.project_id.in_(managed_projects))).order_by(S.access_shares.c.created_at.desc())).mappings()]
            credentials=[{k:v for k,v in dict(r).items() if k!='secret_sha256'} for r in conn.execute(select(S.access_credentials).where(S.access_credentials.c.identity_id==person['id'])).mappings()]
            revision=conn.execute(select(S.access_state.c.revision).where(S.access_state.c.id==1)).scalar_one()
            names={row['id']:row['name'] for row in workspaces+project_rows}
            for row in project_rows:
                row['workspace_name']=names.get(row.get('workspace_id'),'尚未归属')
            for row in members+invitations:
                row['scope_name']=names.get(row.get('workspace_id') or row.get('project_id'),'不可访问的范围')
            for row in workspaces:
                row['parent_name']=names.get(row.get('parent_id'))
                row['project_count']=sum(p.get('workspace_id')==row['id'] for p in project_rows)
            return clean({'identity':{k:person[k] for k in ('id','actor','display_name','preferences')},'workspaces':workspaces,'projects':project_rows,'members':members,'invitations':invitations,'shares':shares,'credentials':credentials,'access_revision':revision})

    def access_workspace_resources(self,workspace_id,*,offset=0,limit=24,query=''):
        with self.engine.connect() as conn:
            _,person,_=self._access_principal(conn)
            if not person:denied('工作室需要成员身份')
            self._workspace_require(conn,checked_id(workspace_id),'read',person['id'])
            projects=[]
            for row in conn.execute(select(S.projects.c.id,S.projects.c.name).join(S.access_projects,S.access_projects.c.project_id==S.projects.c.id).where(S.access_projects.c.workspace_id==workspace_id)).mappings():
                try:self._access_require(conn,row['id'])
                except ResourceError:continue
                projects.append(dict(row))
            media=S.media_items
            conditions=[media.c.project_id.in_([row['id'] for row in projects])]
            if query:conditions.append(media.c.name.icontains(query,autoescape=True))
            total=conn.execute(select(func.count()).select_from(media).where(*conditions)).scalar_one()
            rows=conn.execute(select(media.c.id,media.c.project_id,media.c.name,media.c.modality,media.c.created_at).where(*conditions).order_by(media.c.created_at.desc(),media.c.id).offset(offset).limit(limit)).mappings()
            names={row['id']:row['name'] for row in projects}
            items=[{**dict(row),'project_name':names[row['project_id']]} for row in rows]
            return clean({'workspace_id':workspace_id,'projects':projects,'items':items,'total':total,'offset':offset,'limit':limit,'next_offset':offset+limit if offset+limit<total else None})

    def access_bind_new_project(self,conn,project_id,actor):
        principal,person,_=self._access_principal(conn)
        if principal is None:return
        if not person or principal.actor!=actor:denied('新项目需要已认证成员')
        authority_lock(conn)
        workspace=principal.workspace_id or self._personal_workspace(conn,person)
        self._workspace_require(conn,workspace,'edit',person['id'])
        conn.execute(insert(S.access_projects).values(project_id=project_id,workspace_id=workspace,review_lanes=[],assigned_by=person['id']))
        conn.execute(insert(S.access_project_members).values(project_id=project_id,identity_id=person['id'],role='owner',active=True))

    def access_migration_preview(self,project_id,workspace_id):
        with self.engine.connect() as conn:
            self._access_require(conn,project_id,'manage');principal,person,_=self._access_principal(conn)
            if not person:denied()
            self._workspace_require(conn,workspace_id,'manage',person['id']);project=self._project(conn,project_id)
            before=conn.execute(select(S.access_projects).where(S.access_projects.c.project_id==project_id)).mappings().first()
            plan={'project_id':project_id,'project_revision':project['revision'],'from_workspace_id':before['workspace_id'] if before else None,'to_workspace_id':workspace_id,'effect':'新归属权限即时生效；原产物、决定和媒体不改变'}
            return {'plan':plan,'sha256':digest(plan)}

    def access_command(self,action,payload,*,expected_revision,idempotency_key,actor):
        with self.engine.begin() as conn:
            authority_lock(conn,True);revision=self._access_state(conn)
            principal,person,_=self._access_principal(conn)
            if not person or principal.actor!=actor:denied('操作须来自真实成员会话')
            key=person['id']+':'+idempotency_key;request_sha=digest({'action':action,'payload':payload})
            receipt=conn.execute(select(S.access_commands).where(S.access_commands.c.key==key)).mappings().first()
            if receipt:
                if receipt['request_sha256']!=request_sha:raise Conflict('操作标识已经用于不同权限请求','idempotency_conflict')
                return receipt['response']
            if revision!=expected_revision:raise Conflict('身份与权限版本已改变，请重新读取；输入保留','access_revision_conflict')
            result=self._access_apply(conn,person,action,payload)
            if action in {'member','assign-project'}:self._access_seat_check(conn)
            return self._access_event(conn,key,person['id'],action,request_sha,revision,result)

    def access_member_valid(self,project_id,target_actor,conn=None):
        from contextlib import nullcontext
        if current_principal() is None:return True
        with (nullcontext(conn) if conn is not None else self.engine.connect()) as conn:
            person=conn.execute(select(S.access_identities).where(S.access_identities.c.actor==target_actor,S.access_identities.c.active.is_(True))).mappings().first()
            if not person:return False
            binding=conn.execute(select(S.access_projects).where(S.access_projects.c.project_id==project_id)).mappings().first()
            if not binding:return person['subject_key'].startswith('local:')
            direct=conn.execute(select(S.access_project_members.c.identity_id).where(S.access_project_members.c.project_id==project_id,S.access_project_members.c.identity_id==person['id'],S.access_project_members.c.active.is_(True))).scalar_one_or_none()
            return bool(direct or self._workspace_roles(conn,binding['workspace_id'],person['id']))

    def _access_seat_check(self,conn):
        # The commerce contract is optional. Its configured project entitlement
        # is read on this same connection while the authority lock is exclusive.
        try:
            from .commerce import CommerceRepository
        except ImportError:return
        if 'commerce_plan_versions' not in S.metadata.tables:return
        identities=conn.execute(select(S.access_identities.c.id).where(S.access_identities.c.active.is_(True))).scalars().all()
        for project in conn.execute(select(S.access_projects)).mappings():
            entitlement=CommerceRepository(self).entitlements(project['project_id'],conn=conn)
            if not entitlement.get('configured'):continue
            cap=entitlement.get('seat_limit')
            if cap is None:continue
            direct=set(conn.execute(select(S.access_project_members.c.identity_id).where(S.access_project_members.c.project_id==project['project_id'],S.access_project_members.c.active.is_(True))).scalars())
            count=sum(identity in direct or bool(self._workspace_roles(conn,project['workspace_id'],identity)) for identity in identities)
            if count>cap:raise ResourceError('项目有效成员超过已配置席位，请先调整授权或套餐','seat_limit_exceeded',409)

    @staticmethod
    def _validate_preferences(raw, base=None):
        if not isinstance(raw, dict) or set(raw) - {'language', 'compact', 'collaboration'}:
            raise ResourceError('偏好格式无效', 'invalid_access_input')
        merged = dict(base or {})
        if 'language' in raw:
            if not isinstance(raw['language'], str) or not 1 <= len(raw['language'].strip()) <= 32:
                raise ResourceError('偏好格式无效', 'invalid_access_input')
            merged['language'] = raw['language'].strip()
        if 'compact' in raw:
            if type(raw['compact']) is not bool:
                raise ResourceError('偏好格式无效', 'invalid_access_input')
            merged['compact'] = raw['compact']
        if 'collaboration' in raw:
            collab = raw['collaboration']
            if (not isinstance(collab, dict) or set(collab) - {'enabled_on_new_canvas'}
                    or any(type(v) is not bool for v in collab.values())):
                raise ResourceError('偏好格式无效', 'invalid_access_input')
            prior_collab = dict(merged.get('collaboration') or {})
            prior_collab.update(collab)
            merged['collaboration'] = {'enabled_on_new_canvas': bool(prior_collab.get('enabled_on_new_canvas', False))}
        return merged

    def get_user_preferences(self):
        with self.engine.connect() as conn:
            principal, person, _ = self._access_principal(conn)
            if not principal or not person:
                denied('偏好设置需要成员身份')
            stored = dict(person.get('preferences') or {})
            collab = dict(stored.get('collaboration') or {})
            stored['collaboration'] = {'enabled_on_new_canvas': bool(collab.get('enabled_on_new_canvas', False))}
            return clean({'preferences': stored})

    def update_user_preferences(self, payload, *, actor=None):
        if not isinstance(payload, dict):
            raise ResourceError('偏好格式无效', 'invalid_access_input')
        raw = payload['preferences'] if set(payload) == {'preferences'} else payload
        with self.engine.begin() as conn:
            authority_lock(conn, True)
            revision = self._access_state(conn)
            principal, person, _ = self._access_principal(conn)
            if not principal or not person or (actor is not None and principal.actor != actor):
                denied('偏好设置需要真实成员会话')
            merged = self._validate_preferences(raw, base=person.get('preferences') or {})
            conn.execute(update(S.access_identities).where(S.access_identities.c.id == person['id']).values(preferences=merged))
            conn.execute(update(S.access_state).where(S.access_state.c.id == 1).values(revision=revision + 1))
            collab = dict(merged.get('collaboration') or {})
            merged['collaboration'] = {'enabled_on_new_canvas': bool(collab.get('enabled_on_new_canvas', False))}
            return clean({'preferences': merged, 'access_revision': revision + 1})

    def _access_apply(self,conn,person,action,p):
        def exact(keys):
            if set(p)!=set(keys):raise ResourceError('权限操作字段不完整或包含额外字段','invalid_access_input')
        if action=='profile':
            exact({'display_name','preferences'})
            prefs=self._validate_preferences(p['preferences'])
            name=label(p['display_name']);conn.execute(update(S.access_identities).where(S.access_identities.c.id==person['id']).values(display_name=name,preferences=prefs));return {'identity_id':person['id']}
        if action=='workspace':
            exact({'name','parent_id'})
            if p['parent_id']:self._workspace_require(conn,p['parent_id'],'manage',person['id'])
            identifier=new_id();conn.execute(insert(S.access_workspaces).values(id=identifier,name=label(p['name']),kind='substudio' if p['parent_id'] else 'studio',parent_id=p['parent_id'],created_by=person['id']))
            conn.execute(insert(S.access_workspace_members).values(workspace_id=identifier,identity_id=person['id'],role='owner',active=True));return {'workspace_id':identifier}
        if action=='assign-project':
            exact({'project_id','workspace_id','preview_sha256'})
            self._access_require(conn,p['project_id'],'manage');self._workspace_require(conn,p['workspace_id'],'manage',person['id'])
            project=self._project(conn,p['project_id'],lock=True);previous=conn.execute(select(S.access_projects).where(S.access_projects.c.project_id==p['project_id'])).mappings().first()
            plan={'project_id':p['project_id'],'project_revision':project['revision'],'from_workspace_id':previous['workspace_id'] if previous else None,'to_workspace_id':p['workspace_id'],'effect':'新归属权限即时生效；原产物、决定和媒体不改变'}
            if digest(plan)!=p['preview_sha256']:raise Conflict('归属预览已变化，请重新预览')
            conn.execute(pg_insert(S.access_projects).values(project_id=p['project_id'],workspace_id=p['workspace_id'],review_lanes=[],assigned_by=person['id']).on_conflict_do_update(index_elements=['project_id'],set_={'workspace_id':p['workspace_id'],'assigned_by':person['id']}))
            conn.execute(pg_insert(S.access_project_members).values(project_id=p['project_id'],identity_id=person['id'],role='owner',active=True).on_conflict_do_update(index_elements=['project_id','identity_id'],set_={'role':'owner','active':True}))
            return plan
        if action in {'member','invitation'}:
            scope=p.get('scope');target=p.get('scope_id')
            if scope not in {'workspace','project'}:raise ResourceError('成员范围无效')
            if scope=='workspace':self._workspace_require(conn,target,'manage',person['id'])
            else:self._access_require(conn,target,'manage')
            if p.get('role') not in CAPABILITIES:raise ResourceError('成员角色无效')
            if action=='member':
                exact({'scope','scope_id','identity_id','role','active'})
                if type(p['active'])is not bool:raise ResourceError('成员启用状态无效')
                self._access_identity(conn,p['identity_id']);table=S.access_workspace_members if scope=='workspace' else S.access_project_members;field=scope+'_id'
                previous=conn.execute(select(table).where(table.c[field]==target,table.c.identity_id==p['identity_id'])).mappings().first()
                if previous and previous['active'] and previous['role']=='owner' and (not p['active'] or p['role']!='owner'):
                    count=conn.execute(select(func.count()).select_from(table).where(table.c[field]==target,table.c.role=='owner',table.c.active.is_(True))).scalar_one()
                    if count<=1:raise Conflict('不能移除最后一位直接所有者','last_owner')
                conn.execute(pg_insert(table).values(**{field:target,'identity_id':p['identity_id'],'role':p['role'],'active':p['active']}).on_conflict_do_update(index_elements=[field,'identity_id'],set_={'role':p['role'],'active':p['active']}));return {'scope':scope,'scope_id':target,'identity_id':p['identity_id'],'role':p['role'],'active':p['active']}
            exact({'scope','scope_id','role','secret','expires_at'})
            if p['role']=='owner':raise ResourceError('邀请不能直接授予所有者；加入后由当前所有者明确调整')
            identifier=new_id();conn.execute(insert(S.access_invitations).values(id=identifier,workspace_id=target if scope=='workspace' else None,project_id=target if scope=='project' else None,role=p['role'],secret_sha256=secret_hash(p['secret']),expires_at=expires(p['expires_at']),created_by=person['id']))
            return {'invitation_id':identifier,'scope':scope,'scope_id':target}
        if action=='revoke-invitation':
            exact({'invitation_id'});row=conn.execute(select(S.access_invitations).where(S.access_invitations.c.id==p['invitation_id'])).mappings().first()
            if not row:denied()
            if row['workspace_id']:self._workspace_require(conn,row['workspace_id'],'manage',person['id'])
            else:self._access_require(conn,row['project_id'],'manage')
            conn.execute(update(S.access_invitations).where(S.access_invitations.c.id==row['id']).values(revoked=True));return {'invitation_id':row['id'],'revoked':True}
        if action=='credential':
            exact({'secret'});identifier=new_id();conn.execute(insert(S.access_credentials).values(id=identifier,identity_id=person['id'],secret_sha256=secret_hash(p['secret']),revoked=False));return {'credential_id':identifier}
        if action=='revoke-credential':
            exact({'credential_id'});row=conn.execute(select(S.access_credentials).where(S.access_credentials.c.id==p['credential_id'],S.access_credentials.c.identity_id==person['id'])).mappings().first()
            if not row:denied()
            conn.execute(update(S.access_credentials).where(S.access_credentials.c.id==row['id']).values(revoked=True));return {'credential_id':row['id'],'revoked':True}
        if action=='share':
            exact({'project_id','canvas_version_id','mode','secret','expires_at'});self._access_require(conn,p['project_id'],'publish')
            if p['mode'] not in {'view','edit'}:raise ResourceError('分享模式无效')
            version=self._one(conn,S.creative_canvas_versions,p['project_id'],checked_id(p['canvas_version_id']));identifier=new_id()
            conn.execute(insert(S.access_shares).values(id=identifier,project_id=p['project_id'],canvas_id=version['canvas_id'],canvas_version_id=version['id'],mode=p['mode'],secret_sha256=secret_hash(p['secret']),expires_at=expires(p['expires_at']),created_by=person['id']))
            for mid in set(conn.execute(select(S.creative_canvas_nodes.c.media_id).where(S.creative_canvas_nodes.c.project_id==p['project_id'],S.creative_canvas_nodes.c.version_id==version['id'],S.creative_canvas_nodes.c.media_id.is_not(None))).scalars()):
                conn.execute(insert(S.access_share_media).values(project_id=p['project_id'],share_id=identifier,media_id=mid))
            return {'share_id':identifier,'project_id':p['project_id'],'canvas_version_id':version['id'],'mode':p['mode']}
        if action=='revoke-share':
            exact({'share_id'});row=conn.execute(select(S.access_shares).where(S.access_shares.c.id==p['share_id'])).mappings().first()
            if not row:denied()
            self._access_require(conn,row['project_id'],'publish');conn.execute(update(S.access_shares).where(S.access_shares.c.id==row['id']).values(revoked=True));return {'share_id':row['id'],'revoked':True}
        if action=='review-policy':
            exact({'project_id','lanes'});self._access_require(conn,p['project_id'],'manage')
            if not isinstance(p['lanes'],list) or len(set(p['lanes']))!=len(p['lanes']) or set(p['lanes'])-{'character','storyboard','video'}:raise ResourceError('审核线路无效')
            if not conn.execute(select(S.access_projects.c.project_id).where(S.access_projects.c.project_id==p['project_id'])).scalar_one_or_none():raise ResourceError('请先明确项目归属')
            conn.execute(update(S.access_projects).where(S.access_projects.c.project_id==p['project_id']).values(review_lanes=p['lanes']));return {'project_id':p['project_id'],'review_lanes':p['lanes']}
        raise ResourceError('不支持的权限操作','unknown_access_action')

    def access_share_view(self):
        with self.engine.connect() as conn:
            principal,_,share=self._access_principal(conn)
            if not principal or not share:denied('需要有效分享会话')
            version_id=share['canvas_version_id']
            if share['mode']=='edit':version_id=conn.execute(select(S.creative_canvases.c.current_version_id).where(S.creative_canvases.c.project_id==share['project_id'],S.creative_canvases.c.id==share['canvas_id'])).scalar_one()
            version=self._one(conn,S.creative_canvas_versions,share['project_id'],version_id)
            doc=self._canvas_document(conn,share['project_id'],version)
            for node in doc['nodes']:node.pop('job_id',None)
            return clean({'project_id':share['project_id'],'canvas_id':share['canvas_id'],'version_id':version_id,'version':version['version'],'title':version['title'],'document':doc,'mode':share['mode'],'project_revision':self._project(conn,share['project_id'])['revision'],'expires_at':share['expires_at'],'media_ids':sorted(self._share_media_ids(conn,share))})

    def team_review_queue(self,project_id,lane,*,offset=0,limit=24,status=None,episode_id=None,query=''):
        from vsc.assets.team_review import LANES
        with self.engine.connect() as conn:
            project=self._project(conn,project_id);scope=self._access_require(conn,project_id)
            binding=conn.execute(select(S.access_projects).where(S.access_projects.c.project_id==project_id)).mappings().first()
            candidates_table=S.binding_candidates;slots=S.binding_slots;media_table=S.media_items
            latest=select(S.access_review_submissions.c.review_id).where(S.access_review_submissions.c.project_id==project_id,S.access_review_submissions.c.candidate_id==candidates_table.c.id,S.access_review_submissions.c.lane==lane).order_by(S.access_review_submissions.c.created_at.desc(),S.access_review_submissions.c.id.desc()).limit(1).correlate(candidates_table).scalar_subquery()
            submitted=select(S.access_review_submissions.c.id).where(S.access_review_submissions.c.project_id==project_id,S.access_review_submissions.c.candidate_id==candidates_table.c.id,S.access_review_submissions.c.lane==lane).exists()
            conditions=[candidates_table.c.project_id==project_id,slots.c.role.in_(LANES[lane]['roles'])]
            if query:conditions.append(media_table.c.name.icontains(query,autoescape=True))
            if status=='unsubmitted':conditions.append(~submitted)
            elif status=='pending':conditions.extend([submitted,latest.is_(None)])
            elif status:conditions.append(latest.in_(select(S.media_reviews.c.id).where(S.media_reviews.c.project_id==project_id,S.media_reviews.c.outcome==status)))
            if episode_id:
                self._one(conn,S.episodes,project_id,checked_id(episode_id))
                scenes=select(S.scenes.c.id).where(S.scenes.c.project_id==project_id,S.scenes.c.parent_id==episode_id)
                sequences=select(S.sequences.c.id).where(S.sequences.c.project_id==project_id,S.sequences.c.parent_id.in_(scenes))
                shots=select(S.shots.c.id).where(S.shots.c.project_id==project_id,S.shots.c.parent_id.in_(sequences))
                conditions.append(or_(slots.c.target_object_id==episode_id,slots.c.target_object_id.in_(scenes),slots.c.target_object_id.in_(sequences),slots.c.target_object_id.in_(shots)))
            source=candidates_table.join(slots,(slots.c.project_id==candidates_table.c.project_id)&(slots.c.id==candidates_table.c.slot_id)).join(media_table,(media_table.c.project_id==candidates_table.c.project_id)&(media_table.c.id==candidates_table.c.media_id)).join(S.media_blobs,S.media_blobs.c.id==media_table.c.blob_id)
            total=conn.execute(select(func.count()).select_from(source).where(*conditions)).scalar_one()
            page=select(candidates_table,slots.c.role,slots.c.target_object_id,media_table.c.name,media_table.c.modality,S.media_blobs.c.sha256).select_from(source).where(*conditions).order_by(candidates_table.c.created_at.desc(),candidates_table.c.id.desc()).offset(offset).limit(limit)
            candidates=[]
            for row in conn.execute(page).mappings():
                all_revs=[dict(r) for r in conn.execute(select(S.media_reviews).where(S.media_reviews.c.project_id==project_id,S.media_reviews.c.candidate_id==row['id']).order_by(S.media_reviews.c.created_at.desc(),S.media_reviews.c.id.desc())).mappings()]
                acked_ids={(r.get('evidence') or {}).get('review_id') for r in all_revs if r['criteria_version']=='team-read-ack-v1'}
                history=[{**r,'created_by':r['reviewer'],'read_ack':r['id'] in acked_ids,'evidence':{**(r.get('evidence') or {}),**({'read_ack':True} if r['id'] in acked_ids else {})}} for r in all_revs if r['criteria_version']!='team-read-ack-v1']
                candidates.append({**dict(row),'review_history':history})
            submissions=[]
            for row in conn.execute(select(S.access_review_submissions).where(S.access_review_submissions.c.project_id==project_id,S.access_review_submissions.c.lane==lane,S.access_review_submissions.c.candidate_id.in_([c['id'] for c in candidates])).order_by(S.access_review_submissions.c.created_at.desc(),S.access_review_submissions.c.id.desc())).mappings():
                review=self._one(conn,S.media_reviews,project_id,row['review_id']) if row['review_id'] else None
                submissions.append({**dict(row),'review':review,'status':review['outcome'] if review else 'pending'})
            episodes=[dict(row) for row in conn.execute(select(S.creative_objects.c.id,S.creative_objects.c.title,S.creative_objects.c.display_code).join(S.episodes,(S.episodes.c.project_id==S.creative_objects.c.project_id)&(S.episodes.c.id==S.creative_objects.c.id)).where(S.creative_objects.c.project_id==project_id).order_by(S.episodes.c.ordinal,S.episodes.c.id)).mappings()]
            return clean({'lane':lane,'label':LANES[lane]['label'],'enabled':bool(binding and lane in binding['review_lanes']),'candidates':candidates,'submissions':submissions,'episodes':episodes,'total':total,'offset':offset,'limit':limit,'next_offset':offset+limit if offset+limit<total else None,'revision':project['revision'],'capabilities':scope['capabilities']})

    def submit_team_review(self,project_id,payload,**kw):
        from vsc.assets.team_review import LANES
        def work(conn,project):
            principal,person,_=self._access_principal(conn)
            if not person:denied('审核提交需要成员身份')
            binding=conn.execute(select(S.access_projects).where(S.access_projects.c.project_id==project_id)).mappings().first()
            if not binding or payload['lane'] not in binding['review_lanes']:raise ResourceError('项目未启用此审核线路','review_lane_disabled')
            if payload.get('candidate_id'):
                candidate=self._one(conn,S.binding_candidates,project_id,checked_id(payload['candidate_id']))
            else:
                shot_id=checked_id(payload['shot_id']);media_id=checked_id(payload['media_id'])
                default_role='video_take' if payload['lane']=='video' else 'first_frame'
                found=conn.execute(select(S.binding_candidates).join(S.binding_slots,(S.binding_slots.c.project_id==S.binding_candidates.c.project_id)&(S.binding_slots.c.id==S.binding_candidates.c.slot_id)).where(S.binding_candidates.c.project_id==project_id,S.binding_candidates.c.media_id==media_id,S.binding_slots.c.target_object_id==shot_id,S.binding_slots.c.role.in_(LANES[payload['lane']]['roles'])).order_by(S.binding_candidates.c.created_at.desc())).mappings().first()
                if found:candidate=dict(found)
                else:
                    created=self.propose_binding(project_id,{'target_object_id':shot_id,'media_id':media_id,'role':default_role,'slot_key':'workbench'},_transaction=(conn,project),**kw)
                    candidate=self._one(conn,S.binding_candidates,project_id,created['candidate_id'])
            slot=self._one(conn,S.binding_slots,project_id,candidate['slot_id'])
            if slot['role'] not in LANES[payload['lane']]['roles']:raise ResourceError('候选用途与审核线路不同')
            if payload.get('supersedes_id'):
                previous=self._one(conn,S.access_review_submissions,project_id,checked_id(payload['supersedes_id']))
                if previous['lane']!=payload['lane'] or not previous['review_id']:raise ResourceError('重新提交需要同线路已退回记录')
                review=self._one(conn,S.media_reviews,project_id,previous['review_id'])
                if review['outcome'] not in {'fail','needs_changes'}:raise ResourceError('只能从未通过记录重新提交')
            else:
                passed=conn.execute(select(S.access_review_submissions.c.id).join(S.media_reviews,(S.media_reviews.c.project_id==S.access_review_submissions.c.project_id)&(S.media_reviews.c.id==S.access_review_submissions.c.review_id)).where(S.access_review_submissions.c.project_id==project_id,S.access_review_submissions.c.candidate_id==candidate['id'],S.access_review_submissions.c.lane==payload['lane'],S.media_reviews.c.outcome=='pass').limit(1)).scalar_one_or_none()
                if passed:raise Conflict('该候选已通过本线路审核，无需重复提审','review_already_passed')
            active=conn.execute(select(S.access_review_submissions.c.id).where(S.access_review_submissions.c.project_id==project_id,S.access_review_submissions.c.candidate_id==candidate['id'],S.access_review_submissions.c.review_id.is_(None))).scalar_one_or_none()
            if active:return {'submission_id':active,'candidate_id':candidate['id'],'status':'pending'}
            identifier=new_id();conn.execute(insert(S.access_review_submissions).values(id=identifier,project_id=project_id,candidate_id=candidate['id'],lane=payload['lane'],supersedes_id=payload.get('supersedes_id'),submitted_by=person['id']))
            return {'submission_id':identifier,'candidate_id':candidate['id'],'status':'pending'}
        return self._mutate(project_id,'access_review_submit',payload,callback=work,**kw)

    def commit_team_review(self,project_id,payload,**kw):
        def work(conn,project):
            row=self._one(conn,S.access_review_submissions,project_id,checked_id(payload['submission_id']))
            if row['review_id']:raise Conflict('本次固定提交已有审核结论，请刷新或明确重新提交')
            if payload['outcome']=='pass':
                already=conn.execute(select(S.access_review_submissions.c.id).join(S.media_reviews,(S.media_reviews.c.project_id==S.access_review_submissions.c.project_id)&(S.media_reviews.c.id==S.access_review_submissions.c.review_id)).where(S.access_review_submissions.c.project_id==project_id,S.access_review_submissions.c.candidate_id==row['candidate_id'],S.access_review_submissions.c.lane==row['lane'],S.media_reviews.c.outcome=='pass').limit(1)).scalar_one_or_none()
                if already:raise Conflict('该对象当前已处于审核通过状态，无需重复通过','review_already_passed')
            candidate=self._one(conn,S.binding_candidates,project_id,row['candidate_id']);media=self._media(conn,project_id,candidate['media_id'])
            review=self.record_review(project_id,{'candidate_id':candidate['id'],'reviewer_type':'human','criteria_version':'team-'+row['lane']+'-v1','outcome':payload['outcome'],'reason':payload['reason'],'evidence':{'submission_id':row['id'],'media_id':media['id'],'media_sha256':media['sha256']}},_transaction=(conn,project),**kw)
            conn.execute(update(S.access_review_submissions).where(S.access_review_submissions.c.project_id==project_id,S.access_review_submissions.c.id==row['id']).values(review_id=review['id']))
            return {'submission_id':row['id'],'review_id':review['id'],'outcome':payload['outcome'],'candidate_id':candidate['id'],'media_sha256':media['sha256']}
        return self._mutate(project_id,'access_review_commit',payload,callback=work,**kw)

    def batch_commit_team_review(self,project_id,payload,**kw):
        def work(conn,project):
            items=[]
            for sid in payload['submission_ids']:
                row=self._one(conn,S.access_review_submissions,project_id,checked_id(sid))
                if row['review_id']:raise Conflict('批量列表中包含已处理记录，请刷新后重试')
                if payload['outcome']=='pass':
                    already=conn.execute(select(S.access_review_submissions.c.id).join(S.media_reviews,(S.media_reviews.c.project_id==S.access_review_submissions.c.project_id)&(S.media_reviews.c.id==S.access_review_submissions.c.review_id)).where(S.access_review_submissions.c.project_id==project_id,S.access_review_submissions.c.candidate_id==row['candidate_id'],S.access_review_submissions.c.lane==row['lane'],S.media_reviews.c.outcome=='pass').limit(1)).scalar_one_or_none()
                    if already:raise Conflict('该对象当前已处于审核通过状态，无需重复通过','review_already_passed')
                candidate=self._one(conn,S.binding_candidates,project_id,row['candidate_id']);media=self._media(conn,project_id,candidate['media_id'])
                review=self.record_review(project_id,{'candidate_id':candidate['id'],'reviewer_type':'human','criteria_version':'team-'+row['lane']+'-v1','outcome':payload['outcome'],'reason':payload['reason'],'evidence':{'submission_id':row['id'],'media_id':media['id'],'media_sha256':media['sha256'],'batch':True}},_transaction=(conn,project),**kw)
                conn.execute(update(S.access_review_submissions).where(S.access_review_submissions.c.project_id==project_id,S.access_review_submissions.c.id==row['id']).values(review_id=review['id']))
                items.append({'submission_id':row['id'],'review_id':review['id'],'outcome':payload['outcome'],'candidate_id':candidate['id']})
            return {'items':items,'count':len(items),'outcome':payload['outcome']}
        return self._mutate(project_id,'access_review_batch_commit',payload,callback=work,**kw)

    def mark_team_review_read(self,project_id,payload,**kw):
        def work(conn,project):
            cand_id=payload.get('candidate_id')
            if cand_id:
                candidate=self._one(conn,S.binding_candidates,project_id,checked_id(cand_id))
            else:
                media_id=checked_id(payload['media_id'])
                q=select(S.binding_candidates).where(S.binding_candidates.c.project_id==project_id,S.binding_candidates.c.media_id==media_id)
                if payload.get('shot_id'):
                    shot_id=checked_id(payload['shot_id'])
                    q=q.join(S.binding_slots,(S.binding_slots.c.project_id==S.binding_candidates.c.project_id)&(S.binding_slots.c.id==S.binding_candidates.c.slot_id)).where(S.binding_slots.c.target_object_id==shot_id)
                found=conn.execute(q.order_by(S.binding_candidates.c.created_at.desc(),S.binding_candidates.c.id.desc())).mappings().first()
                if not found:raise ResourceError('未找到该媒体的候选记录')
                candidate=dict(found)
            media=self._media(conn,project_id,candidate['media_id'])
            note=str(payload.get('note') or '审阅反馈已阅').strip()[:500] or '审阅反馈已阅'
            verdict_revs=[dict(r) for r in conn.execute(select(S.media_reviews).where(S.media_reviews.c.project_id==project_id,S.media_reviews.c.candidate_id==candidate['id'],S.media_reviews.c.criteria_version!='team-read-ack-v1').order_by(S.media_reviews.c.created_at.desc(),S.media_reviews.c.id.desc())).mappings()]
            if not verdict_revs:
                raise ResourceError('该候选尚无审核意见，无法标记已阅','review_missing_for_read_ack')
            target_rev=next((r for r in verdict_revs if r['id']==payload.get('review_id')),verdict_revs[0])
            row_id=new_id()
            conn.execute(insert(S.media_reviews).values(project_id=project_id,id=row_id,candidate_id=candidate['id'],check_id=None,reviewer=kw['actor'],reviewer_type='human',criteria_version='team-read-ack-v1',context_sha256=None,outcome=target_rev['outcome'],reason=f'[已阅] {note}',evidence={'read_ack':True,'media_id':media['id'],'media_sha256':media['sha256'],'submission_id':payload.get('submission_id'),'review_id':target_rev['id']},project_revision=project['revision']+1))
            return {'candidate_id':candidate['id'],'review_id':target_rev['id'],'ack_id':row_id,'read_ack':True,'outcome':target_rev['outcome']}
        return self._mutate(project_id,'access_review_mark_read',payload,callback=work,**kw)
