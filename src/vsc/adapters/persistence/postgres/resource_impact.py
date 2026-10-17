"""Conservative comparison of immutable artifact evidence under a revision pin."""
from sqlalchemy import select,text
from . import schema as S
from vsc.assets.resource_service import Conflict


def compare_artifacts(store,p,source,replacement,revision):
    with store.engine.connect().execution_options(isolation_level='REPEATABLE READ') as conn,conn.begin():
        conn.execute(text('SET TRANSACTION READ ONLY'))
        if store._project(conn,p)['revision']!=revision:
            raise Conflict('影响报告快照已变化，请刷新','graph_revision_changed')
        rows=[store._one(conn,S.artifact_versions,p,i) for i in (source,replacement)]
        evidence=[]
        for row in rows:
            deps=set(conn.execute(select(S.artifact_dependencies.c.dependency_id).where(S.artifact_dependencies.c.project_id==p,S.artifact_dependencies.c.artifact_id==row['id'])).scalars())
            scopes=set(conn.execute(select(S.artifact_object_scopes.c.object_id).where(S.artifact_object_scopes.c.project_id==p,S.artifact_object_scopes.c.artifact_id==row['id'])).scalars())
            evidence.append((row['sha256'],row['artifact_type'],row['project_wide'],deps,scopes))
        if evidence[0]==evidence[1]:
            return {'status':'unchanged','reason':'固定正文SHA、类型、依赖版本与范围完全一致；内容输入未变化'}
        return {'status':'changed','reason':'固定正文、依赖或范围不同；列出实际消费者待复核，差异不自动等于必须重做'}
