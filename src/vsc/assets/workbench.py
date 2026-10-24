"""Authority-aware, read-only creative workbench use case."""
from vsc.assets.resource_service import ResourceError,Conflict,NotFound

SECTIONS=frozenset(('renders','timeline_media','quality_observations','method_evaluations','jobs','overview','children','shots','lines','assets','instances','cues','performances','bindings','materials','versions',
    'candidates','coverage','states','voices','interactions','dispositions','cue_shots','cue_slots','cue_timeline_items',
    'execution_shots','execution_participants','execution_materials','execution_slots','job_attempts','script_status'))


class Workbench:
    def __init__(self,catalog):
        self.catalog=catalog

    def query(self,project_id,*,object_id=None,section='overview',query='',limit=24,offset=0,revision=None,
              kind=None,status=None,purpose=None,version=None,association=None,entity_id=None):
        section='lines' if section=='script_lines' else section
        if section not in SECTIONS or type(limit) is not int or not 1<=limit<=100 or type(offset) is not int or not 0<=offset<=1000000:
            raise ResourceError('工作台集合或分页不合法','invalid_workbench_query')
        if not isinstance(query,str) or len(query)>200 or (revision is not None and (type(revision) is not int or revision<0)):
            raise ResourceError('工作台检索或快照不合法','invalid_workbench_query')
        if association not in (None,'associated','unassociated'):
            raise ResourceError('关联筛选不合法','invalid_workbench_query')
        opts=dict(object_id=object_id,section=section,query=query,limit=limit,offset=offset,revision=revision,
            kind=kind,status=status,purpose=purpose,version=version,association=association,entity_id=entity_id)
        reader=self.catalog._reader(project_id)
        if reader is not None:
            return legacy_workbench(reader,project_id,**opts)
        from vsc.adapters.persistence.postgres.workbench import query_workbench
        return query_workbench(self.catalog.service.store,project_id,**opts)


def legacy_workbench(reader,project_id,**opts):
    project=reader.project(); rev=project['revision']
    if opts['revision'] is not None and opts['revision']!=rev:
        raise Conflict('工作台快照已变化，请刷新','workbench_revision_changed')
    nodes=reader.tree()['nodes']; byid={r['id']:r for r in nodes}; scope=byid.get(opts['object_id'])
    if opts['object_id'] and not scope:raise NotFound()
    selected={opts['object_id']} if scope else set(byid)
    for _ in range(8):selected.update(r['id'] for r in nodes if r.get('parent_id') in selected)
    ancestors=[]; current=scope
    while current and current.get('parent_id') in byid:
        current=byid[current['parent_id']];ancestors.insert(0,current)
    names=('children','shots','assets','materials','versions') if opts['section']=='overview' else (opts['section'],)
    sections={}; summary={}
    for name in names:
        if name=='children':rows=[r for r in nodes if r.get('parent_id')==opts['object_id']]
        elif name=='shots':rows=[r for r in nodes if r['id'] in selected and r['kind']=='shot']
        elif name=='assets':rows=[r for r in nodes if r['id'] in selected and r['kind']=='asset']
        elif name=='versions':
            value=reader.artifacts(opts['object_id']);rows=value.get('items',[]) if isinstance(value,dict) else value
        elif name=='materials':
            # Legacy inventory search belongs to the original reader; preserve its authority.
            value=reader.resources(object_id=opts['object_id'],limit=opts['limit'],offset=opts['offset'])
            rows=value['items']; total=value['total']
            if opts['query'] or any(opts[k] for k in ('kind','status','purpose','version','association','entity_id')):
                sections[name]=dict(items=[],scope_total=total,filtered_total=None,total=None,loaded_count=0,truncated=False,next_offset=None,unsupported_filters=True)
                summary[name]=total;continue
            more=opts['offset']+len(rows)<total
            sections[name]=dict(items=rows,scope_total=total,filtered_total=total,total=total,loaded_count=len(rows),truncated=more,next_offset=opts['offset']+len(rows) if more else None)
            summary[name]=total;continue
        else:rows=[]
        total=len(rows)
        filtered=[dict(r,title=r.get('title') or r.get('name') or r.get('artifact_key') or r['id']) for r in rows
            if opts['query'].casefold() in str(r.get('title') or r.get('name') or r.get('id')).casefold() and (not opts['kind'] or r.get('kind')==opts['kind'])]
        take=min(opts['limit'],6) if opts['section']=='overview' else opts['limit']; page=filtered[opts['offset']:opts['offset']+take];more=opts['offset']+len(page)<len(filtered)
        sections[name]=dict(items=page,scope_total=total,filtered_total=len(filtered),total=len(filtered),loaded_count=len(page),truncated=more,next_offset=opts['offset']+len(page) if more else None);summary[name]=total
    if reader.project()['revision']!=rev:raise Conflict('读取期间旧项目变化，请刷新','workbench_revision_changed')
    return dict(project_id=project_id,revision=rev,scope=scope,ancestors=ancestors,summary=summary,sections=sections,read_only=True,snapshot='legacy_revision_checked',
        gaps=[dict(code='legacy_relations_unindexed',message='旧权威尚未提供完整剧本/声音/实例关系索引；缺项不能推断没有依赖。')],
        warnings=['旧项目继续使用原权威；高级素材检索尚未支持时返回unsupported_filters，不把当前页筛选当全范围搜索。'])
