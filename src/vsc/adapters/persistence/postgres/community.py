"""Local publication history over original project transactions and immutable content."""
from sqlalchemy import select,insert,update,func
from vsc.assets.resource_service import ResourceError,Conflict,NotFound
from vsc.assets.access_control import current_principal,denied
from . import schema as S
from .values import checked_id,new_id,digest,clean,CURRENT_REVISION

class CommunityRepository:
    def __init__(self,store):self.store=store
    def __getattr__(self,name):return getattr(self.store,name)
    def _identity(self,conn):
        principal,person,_=self.store._access_principal(conn)
        if not principal or not person or principal.api_key_id or principal.share_id:denied('社区操作需要当前成员身份')
        return person
    def _event(self,conn,p,v,status,reason,person):
        sequence=conn.scalar(select(func.coalesce(func.max(S.community_events.c.sequence),0)).where(S.community_events.c.project_id==p,S.community_events.c.version_id==v))+1
        identifier=new_id();conn.execute(insert(S.community_events).values(project_id=p,id=identifier,version_id=v,sequence=sequence,status=status,reason=reason,created_by=person));return identifier
    def _last(self,conn,table,p,field,identifier):
        order=table.c.sequence.desc() if 'sequence' in table.c else table.c.created_at.desc()
        return conn.execute(select(table).where(table.c.project_id==p,table.c[field]==identifier).order_by(order,table.c.id.desc()).limit(1)).mappings().first()
    def _version(self,conn,p,identifier):return self._one(conn,S.community_versions,p,identifier)
    def _visible(self,conn,p,version):
        self._access_require(conn,p,'read')
        if version['scope']=='workspace':
            project=conn.execute(select(S.access_projects).where(S.access_projects.c.project_id==p)).mappings().first()
            if not project:raise ResourceError('项目尚未归属工作空间','community_workspace_required')
        return version
    def _detail(self,conn,p,publication_id,version_id=None):
        pub=self._one(conn,S.community_publications,p,publication_id);v=self._version(conn,p,version_id or pub['current_version_id'])
        if v['publication_id']!=pub['id']:raise ResourceError('内容版本不属于此发布')
        self._visible(conn,p,v);events=[dict(r) for r in conn.execute(select(S.community_events).where(S.community_events.c.project_id==p,S.community_events.c.version_id==v['id']).order_by(S.community_events.c.sequence)).mappings()]
        rule=self._one(conn,S.community_rules,p,v['rule_id']);media=self._media(conn,p,v['media_id']) if v['media_id'] else None
        return dict(pub,version=v,status=events[-1]['status'],events=events,rule=rule,modality=media['modality'] if media else 'template',template=self._one(conn,S.canvas_templates,p,v['template_id']) if v['template_id'] else None,history=[dict(r) for r in conn.execute(select(S.community_versions.c.id,S.community_versions.c.version,S.community_versions.c.title).where(S.community_versions.c.project_id==p,S.community_versions.c.publication_id==pub['id']).order_by(S.community_versions.c.version.desc())).mappings()])
    def _published_versions(self,c,p,publication_id):
        latest=select(S.community_events.c.status).where(S.community_events.c.project_id==p,S.community_events.c.version_id==S.community_versions.c.id).order_by(S.community_events.c.sequence.desc()).limit(1).correlate(S.community_versions).scalar_subquery()
        return list(c.execute(select(S.community_versions).where(S.community_versions.c.project_id==p,S.community_versions.c.publication_id==publication_id,latest=='published').order_by(S.community_versions.c.version.desc())).mappings())
    def _listed_detail(self,c,p,identifier,person,manage):
        row=self._detail(c,p,identifier);live=self._published_versions(c,p,identifier)
        if manage or row['created_by']==person['id']:
            if live and live[0]['id']!=row['version']['id']:row['published_version']=self._detail(c,p,identifier,live[0]['id'])
            return row
        return self._detail(c,p,identifier,live[0]['id']) if live else None
    def detail(self,p,identifier,version_id=None):
        with self.engine.connect() as c:
            person=self._identity(c);scope=self._access_require(c,p,'read')
            row=self._detail(c,p,identifier,version_id) if version_id else self._listed_detail(c,p,identifier,person,'manage' in scope['capabilities'])
            if not row or row['status']!='published' and row['created_by']!=person['id'] and 'manage' not in scope['capabilities']:denied('此固定版本未发布或已撤回')
            return clean(dict(row,revision=self._project(c,p)['revision']))
    def snapshot(self,p):
        with self.engine.connect() as c:
            person=self._identity(c);scope=self._access_require(c,p,'read');manage='manage' in scope['capabilities']
            pubs=[self._listed_detail(c,p,r,person,manage) for r in c.execute(select(S.community_publications.c.id).where(S.community_publications.c.project_id==p).order_by(S.community_publications.c.created_at.desc()).limit(100)).scalars()]
            pubs=[r for r in pubs if r is not None]
            rules=[dict(r) for r in c.execute(select(S.community_rules).where(S.community_rules.c.project_id==p).order_by(S.community_rules.c.version.desc())).mappings()]
            channels={}
            for r in c.execute(select(S.distribution_channels).where(S.distribution_channels.c.project_id==p).order_by(S.distribution_channels.c.version.desc())).mappings():channels.setdefault(r['channel_key'],dict(r))
            reports=[]
            for r in c.execute(select(S.community_reports).where(S.community_reports.c.project_id==p,True if manage else S.community_reports.c.reporter_id==person['id']).order_by(S.community_reports.c.created_at.desc()).limit(100)).mappings():
                v=self._version(c,p,r['version_id']);reports.append(dict(r,title=v['title'],content_version=v['version'],decisions=[dict(d) for d in c.execute(select(S.community_moderation).where(S.community_moderation.c.project_id==p,S.community_moderation.c.version_id==v['id']).order_by(S.community_moderation.c.created_at)).mappings()]))
            requests=[self._distribution(c,p,r) for r in c.execute(select(S.distribution_requests.c.id).where(S.distribution_requests.c.project_id==p,True if manage else S.distribution_requests.c.created_by==person['id']).order_by(S.distribution_requests.c.created_at.desc()).limit(100)).scalars()]
            return clean(dict(project_id=p,revision=self._project(c,p)['revision'],capabilities=scope['capabilities'],identity_id=person['id'],publications=pubs,rules=rules,channels=list(channels.values()),reports=reports,distributions=requests))
    def feed(self,query='',offset=0,limit=24):
        access=self.store.access_snapshot();projects=access['projects'];rows=[]
        with self.engine.connect() as c:
            for p in projects:
                for identifier in c.execute(select(S.community_publications.c.id).where(S.community_publications.c.project_id==p['id'])).scalars():
                    live=self._published_versions(c,p['id'],identifier)
                    if not live:continue
                    row=self._detail(c,p['id'],identifier,live[0]['id'])
                    if row['status']=='published' and row['version']['scope']=='workspace' and query.casefold() in row['version']['title'].casefold():rows.append(dict(row,project_name=p['name'],project_id=p['id']))
        rows.sort(key=lambda r:(r['version']['created_at'],r['id']),reverse=True)
        return clean(dict(items=rows[offset:offset+limit],total=len(rows),next_offset=offset+limit if offset+limit<len(rows) else None,projects=projects))
    def save_rule(self,p,payload,**kw):
        def work(c,project):
            person=self._identity(c);prior=c.execute(select(S.community_rules).where(S.community_rules.c.project_id==p).order_by(S.community_rules.c.version.desc()).limit(1)).mappings().first()
            if payload['base_version_id']!=(prior['id'] if prior else None):raise Conflict('规则已有新版本')
            row=dict(project_id=p,id=new_id(),version=prior['version']+1 if prior else 1,title=payload['title'],body=payload['body'],sha256=digest({'title':payload['title'],'body':payload['body']}),created_by=person['id']);c.execute(insert(S.community_rules).values(**row));return row
        return self._mutate(p,'community_rule_save',payload,callback=work,**kw)
    def save_publication(self,p,payload,**kw):
        def work(c,project):
            person=self._identity(c);identifier=payload.get('publication_id');prior=self._one(c,S.community_publications,p,identifier) if identifier else None
            if payload['base_version_id']!=(prior['current_version_id'] if prior else None):raise Conflict('发布内容已有新版本，本机稿保留')
            self._one(c,S.community_rules,p,payload['rule_id']);media=self._media(c,p,payload['media_id']) if payload.get('media_id') else None
            if media:
                if media['modality'] not in {'image','video','audio'}:raise ResourceError('社区作品须是可播放的图像、视频或声音')
                sha=media['sha256']
            else:
                template=self._one(c,S.canvas_templates,p,payload['template_id']);sha=self._one(c,S.creative_canvas_versions,p,template['version_id'])['sha256']
            if not prior:identifier=new_id();c.execute(insert(S.community_publications).values(project_id=p,id=identifier,created_by=person['id']))
            row=dict(project_id=p,id=new_id(),publication_id=identifier,version=self._version(c,p,prior['current_version_id'])['version']+1 if prior else 1,title=payload['title'],description=payload['description'],scope=payload['scope'],rule_id=payload['rule_id'],media_id=media['id'] if media else None,blob_id=media['blob_id'] if media else None,blob_sha256=media['sha256'] if media else None,template_id=payload.get('template_id'),content_sha256=sha,created_by=person['id'])
            self._visible(c,p,row);c.execute(insert(S.community_versions).values(**row));c.execute(update(S.community_publications).where(S.community_publications.c.project_id==p,S.community_publications.c.id==identifier).values(current_version_id=row['id']));event=self._event(c,p,row['id'],'draft','保存固定内容草稿',person['id']);return dict(id=identifier,version_id=row['id'],event_id=event,status='draft')
        return self._mutate(p,'community_publication_save',payload,callback=work,**kw)
    def transition(self,p,payload,**kw):
        def work(c,project):
            person=self._identity(c);v=self._version(c,p,payload['version_id']);last=self._last(c,S.community_events,p,'version_id',v['id'])
            if last['id']!=payload['base_event_id']:raise Conflict('发布状态已改变，请读取原记录')
            if payload['status']=='published':
                pub=self._one(c,S.community_publications,p,v['publication_id'])
                if pub['current_version_id']!=v['id']:raise Conflict('只可发布当前固定版本')
                if last['status']=='restricted':raise ResourceError('内容受限，须由有权治理者明确撤销限制')
                self._check_rights(c,p,v)
            elif last['status']!='published':raise ResourceError('只能撤回实际公开的版本，限制决定由治理历史处理')
            # An explicit publication change retires previous public versions in the same transaction.
            for old in self._published_versions(c,p,v['publication_id']):
                if old['id']!=v['id']:self._event(c,p,old['id'],'withdrawn',('已由新版本替代：' if payload['status']=='published' else '随本次撤回停止公开：')+payload['reason'],person['id'])
            event=self._event(c,p,v['id'],payload['status'],payload['reason'],person['id']);return dict(id=v['publication_id'],version_id=v['id'],event_id=event,status=payload['status'])
        return self._mutate(p,'community_publication_state',payload,callback=work,**kw)
    def _check_rights(self,c,p,v,purpose='publish'):
        from .canvas_templates import CanvasTemplatesRepository
        ids=[v['media_id']] if v['media_id'] else CanvasTemplatesRepository(self.store).media_ids(p,v['template_id'])
        for mid in ids:
            _,gaps=self.store._usable(c,p,mid,purpose)
            blocked=[g for g in gaps if g not in {'technical_check_missing','technical_check_failed'}]
            if blocked:raise ResourceError('固定内容当前不可发布：'+', '.join(blocked),'community_rights_required')
            rights=self.store._latest(c,S.rights_decisions,p,'media_id',mid)
            if not rights or rights['outcome'] not in {'owned','licensed'}:raise ResourceError('发布内容需要明确可分享的权利依据','community_rights_required')
            if rights['outcome']=='licensed' and not {'*',purpose}&set(rights['scope'].get('purposes',[])):raise ResourceError('授权用途未包含发布','community_rights_scope')
    def report(self,p,payload,**kw):
        def work(c,project):
            person=self._identity(c);v=self._visible(c,p,self._version(c,p,payload['version_id']));status=self._last(c,S.community_events,p,'version_id',v['id'])['status']
            if not c.scalar(select(S.community_events.c.id).where(S.community_events.c.project_id==p,S.community_events.c.version_id==v['id'],S.community_events.c.status=='published').limit(1)):raise ResourceError('请选择实际发布过的固定版本')
            row=dict(project_id=p,id=new_id(),version_id=v['id'],rule_id=v['rule_id'],reporter_id=person['id'],reason=payload['reason']);c.execute(insert(S.community_reports).values(**row));return row
        return self._mutate(p,'community_report',payload,callback=work,**kw)
    def moderate(self,p,payload,**kw):
        def work(c,project):
            person=self._identity(c);v=self._version(c,p,payload['version_id']);last=self._last(c,S.community_moderation,p,'version_id',v['id'])
            if payload['base_decision_id']!=(last['id'] if last else None):raise Conflict('此固定版本已有新治理记录')
            if payload['action']=='dismiss' and self._last(c,S.community_events,p,'version_id',v['id'])['status']=='restricted':raise ResourceError('请先明确保留或撤销当前限制')
            if payload['action']=='release' and (not last or last['action']!='restrict'):raise ResourceError('撤销限制需要当前限制决定')
            row=dict(project_id=p,id=new_id(),version_id=v['id'],rule_id=v['rule_id'],report_id=payload.get('report_id'),previous_decision_id=last['id'] if last else None,action=payload['action'],reason=payload['reason'],created_by=person['id']);c.execute(insert(S.community_moderation).values(**row))
            if payload['action'] in {'restrict','release'}:self._event(c,p,v['id'],'restricted' if payload['action']=='restrict' else 'withdrawn','治理决定：'+payload['reason'],person['id'])
            return row
        return self._mutate(p,'community_moderate',payload,callback=work,**kw)
    def save_channel(self,p,payload,**kw):
        def work(c,project):
            person=self._identity(c);prior=c.execute(select(S.distribution_channels).where(S.distribution_channels.c.project_id==p,S.distribution_channels.c.channel_key==payload['channel_key']).order_by(S.distribution_channels.c.version.desc()).limit(1)).mappings().first()
            if payload['base_version_id']!=(prior['id'] if prior else None):raise Conflict('分发配置已有新版本')
            document={k:v for k,v in payload.items() if k!='base_version_id'};row=dict(project_id=p,id=new_id(),version=prior['version']+1 if prior else 1,sha256=digest(document),created_by=person['id'],**document);c.execute(insert(S.distribution_channels).values(**row));return row
        return self._mutate(p,'distribution_channel_save',payload,callback=work,**kw)
    def _distribution(self,c,p,identifier):
        row=self._one(c,S.distribution_requests,p,identifier);v=self._version(c,p,row['version_id']);channel=self._one(c,S.distribution_channels,p,row['channel_id']);events=[dict(e) for e in c.execute(select(S.distribution_events).where(S.distribution_events.c.project_id==p,S.distribution_events.c.request_id==identifier).order_by(S.distribution_events.c.sequence)).mappings()];return dict(row,version=v,channel=channel,events=events,status=events[-1]['status'],last=events[-1])
    def distribution(self,p,identifier):
        with self.engine.connect() as c:return clean(dict(self._distribution(c,p,identifier),revision=self._project(c,p)['revision']))
    def _distribution_event(self,c,p,identifier,status,person,**extra):
        prior=self._last(c,S.distribution_events,p,'request_id',identifier);row=dict(project_id=p,id=new_id(),request_id=identifier,sequence=prior['sequence']+1 if prior else 1,status=status,created_by=person,**extra);c.execute(insert(S.distribution_events).values(**row));return row
    def prepare_distribution(self,p,payload,**kw):
        def work(c,project):
            person=self._identity(c);v=self._version(c,p,payload['version_id']);channel=self._one(c,S.distribution_channels,p,payload['channel_id'])
            if not v['media_id']:raise ResourceError('站外分发需要固定媒体作品')
            if self._last(c,S.community_events,p,'version_id',v['id'])['status']!='published':raise ResourceError('先明确发布此本地固定版本')
            for prior in c.execute(select(S.distribution_requests).where(S.distribution_requests.c.project_id==p,S.distribution_requests.c.version_id==v['id'])).mappings():
                old_channel=self._one(c,S.distribution_channels,p,prior['channel_id'])
                if old_channel['channel_key']==channel['channel_key'] and self._last(c,S.distribution_events,p,'request_id',prior['id'])['status'] not in {'failed','cancelled'}:raise Conflict('此作品已有同渠道分发请求，请读取原回执；未知状态只能查询','distribution_existing_request')
            self._check_rights(c,p,v,'distribution');identifier=new_id();row=dict(project_id=p,id=identifier,version_id=v['id'],channel_id=channel['id'],caption=payload['caption'],request_sha256=digest(dict(version=v['id'],sha256=v['content_sha256'],channel=channel['sha256'],caption=payload['caption'])),request_key='vsc-distribution-'+identifier,created_by=person['id']);c.execute(insert(S.distribution_requests).values(**row));self._distribution_event(c,p,identifier,'prepared',person['id']);return dict(id=identifier,status='prepared',request_sha256=row['request_sha256'])
        return self._mutate(p,'distribution_prepare',payload,callback=work,**kw)
    def start_distribution(self,p,payload,**kw):
        claimed=[False]
        def work(c,project):
            person=self._identity(c);row=self._distribution(c,p,payload['request_id'])
            if payload['request_sha256']!=row['request_sha256']:raise Conflict('分发请求内容已变化')
            if row['status']!='prepared':return dict(id=row['id'],status=row['status'],started=False)
            if self._last(c,S.community_events,p,'version_id',row['version_id'])['status']!='published':raise ResourceError('内容已撤回或受限，不能新提交')
            latest=c.execute(select(S.distribution_channels).where(S.distribution_channels.c.project_id==p,S.distribution_channels.c.channel_key==row['channel']['channel_key']).order_by(S.distribution_channels.c.version.desc()).limit(1)).mappings().one()
            if not latest['enabled']:raise ResourceError('此渠道已停用，不能新提交')
            self._check_rights(c,p,row['version'],'distribution');claimed[0]=True;self._distribution_event(c,p,row['id'],'submitting',person['id']);return dict(id=row['id'],status='submitting',started=True)
        result=self._mutate(p,'distribution_submit',payload,callback=work,**kw)
        return dict(result,started=claimed[0])
    def cancel_prepared_distribution(self,p,identifier,payload,**kw):
        def work(c,project):
            person=self._identity(c);row=self._distribution(c,p,identifier)
            if row['request_sha256']!=payload['request_sha256']:raise Conflict('固定分发请求摘要不匹配')
            if row['status']!='prepared':raise Conflict('原请求已开始提交，请先查询渠道回执，不能本地取消','distribution_query_required')
            event=self._distribution_event(c,p,identifier,'cancelled',person['id']);return dict(id=identifier,status='cancelled',event_id=event['id'])
        return self._mutate(p,'distribution_receipt',dict(request_id=identifier,request_sha256=payload['request_sha256'],action='cancel_prepared'),callback=work,**kw)
    def finish_distribution(self,p,identifier,receipt,**kw):
        def work(c,project):
            person=self._identity(c);row=self._distribution(c,p,identifier)
            if row['status'] in {'completed','failed','cancelled'}:return dict(id=identifier,status=row['status'])
            event=self._distribution_event(c,p,identifier,receipt.status,person['id'],remote_id=receipt.remote_id or row['last'].get('remote_id'),public_url=receipt.public_url,error_code=receipt.error_code);return dict(id=identifier,status=receipt.status,event_id=event['id'])
        return self._mutate(p,'distribution_receipt',dict(request_id=identifier,receipt=receipt.__dict__),callback=work,expected_revision=CURRENT_REVISION,**kw)
