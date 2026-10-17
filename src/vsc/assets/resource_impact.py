"""Evidence-only actual consumer report; never turns associations into redo orders."""
from .resource_graph import ResourceGraph,validate_query
from .resource_service import ResourceError


class ResourceImpact:
    def __init__(self,catalog):
        self.catalog=catalog

    def query(self,project_id,*,source,replacement=None,depth=4,limit=100,revision=None):
        validate_query(focus=source,depth=depth,limit=limit,revision=revision)
        if replacement:validate_query(focus=replacement)
        reader=self.catalog._reader(project_id)
        if reader is not None:
            return dict(project_id=project_id,revision=reader.project()['revision'],source=source,replacement=replacement,
                comparison={'status':'unknown','reason':'旧权威尚无完整固定消费者索引'},consumers=[],summary={'affected_pending_review':0,'unaffected':0,'unknown':0},
                truncated=True,truncation_reasons=['legacy_relations_unindexed'],warnings=['旧权威缺少索引不表示没有影响。'],read_only=True)
        graph=ResourceGraph(self.catalog).query(project_id,focus=source,mode='impact',depth=depth,limit=limit,revision=revision)
        comparison={'status':'unknown','reason':'未提供替代版本；按实际登记消费者列为待复核，不自动要求重做'}
        if replacement:
            # Reuse graph node lookup for project isolation, and compare immutable evidence only.
            other=ResourceGraph(self.catalog).query(project_id,focus=replacement,depth=0,limit=1,revision=graph['revision'])
            if source==replacement:
                comparison={'status':'unchanged','reason':'来源与替代是同一固定对象，没有发生替换'}
            elif source.startswith('artifact:') and replacement.startswith('artifact:'):
                from vsc.adapters.persistence.postgres.resource_impact import compare_artifacts
                comparison=compare_artifacts(self.catalog.service.store,project_id,source.split(':',1)[1],replacement.split(':',1)[1],graph['revision'])
            elif source.startswith('media:') and replacement.startswith('media:'):
                comparison={'status':'unknown','reason':'不同素材登记的用途、权利与批准须分别核对；不能仅按文件名或共享字节继承批准'}
        summary={'affected_pending_review':0,'unaffected':0,'unknown':0};consumers=[]
        for node in graph['nodes']:
            if node['id']==source:continue
            impact=node.get('impact',{})
            classification='unaffected' if comparison['status']=='unchanged' else impact.get('classification','unknown')
            row={key:node[key] for key in ('id','kind','entity_id','label')}
            row.update(impact,classification=classification)
            if classification=='unaffected':row['reason']=comparison['reason']+'；这不重新批准或重绑任何版本'
            consumers.append(row);summary[classification]+=1
        return dict(project_id=project_id,revision=graph['revision'],source=source,replacement=replacement,comparison=comparison,
            summary=summary,consumers=consumers,truncated=graph['truncated'],truncation_reasons=graph['truncation_reasons'],
            warnings=['范围仅含登记的固定输入、加工、当前采用和时间线/渲染用料。未登记依赖和截断部分尚无法判断。'],read_only=True)
