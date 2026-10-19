"""Read-only CLI consumer of the same workbench application used by the panel."""
import argparse,json,sys
from vsc.configuration import get_config
from vsc.assets.workbench import Workbench,SECTIONS
from vsc.assets.resource_service import ResourceError
from vsc.project.resource_catalog import ResourceCatalog


def main(argv=None):
    parser=argparse.ArgumentParser(description='VSC 创作工作台只读查询')
    parser.add_argument('project_id')
    parser.add_argument('--projects-root',default='projects')
    parser.add_argument('--database-env',default='VSC_DATABASE_URL')
    parser.add_argument('--section',choices=sorted(SECTIONS),default='overview')
    for key in ('object-id','query','kind','status','purpose','version','association','entity-id'):
        parser.add_argument('--'+key,default='' if key=='query' else None)
    parser.add_argument('--limit',type=int,default=24)
    parser.add_argument('--offset',type=int,default=0)
    parser.add_argument('--revision',type=int)
    args=parser.parse_args(argv);service=None
    try:
        if get_config(args.database_env):
            from vsc.bootstrap import service_from_environment
            service=service_from_environment(args.database_env)
        catalog=ResourceCatalog(args.projects_root,service=service)
        opts={key:getattr(args,key) for key in ('object_id','section','query','kind','status','purpose','version','association','entity_id','limit','offset','revision')}
        print(json.dumps(Workbench(catalog).query(args.project_id,**opts),ensure_ascii=False,indent=2,default=str))
    except (ResourceError,OSError,ValueError) as error:
        print(json.dumps({'error':getattr(error,'code','invalid_input'),'message':str(error)},ensure_ascii=False),file=sys.stderr)
        raise SystemExit(1)
    finally:
        if service:service.store.close()


if __name__ == '__main__':
    main()
