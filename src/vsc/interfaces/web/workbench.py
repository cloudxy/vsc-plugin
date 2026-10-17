"""Read-only workbench route; authentication/project authorization stays on router."""
from fastapi import Request
from vsc.assets.workbench import Workbench


def install_workbench_routes(router,catalog,etag):
    workbench=Workbench(catalog)

    @router.get('/{project_id}/workbench')
    def query(project_id:str,request:Request,object_id:str=None,section:str='overview',query:str='',
              limit:int=24,offset:int=0,revision:int=None,kind:str=None,status:str=None,purpose:str=None,
              version:str=None,association:str=None,entity_id:str=None):
        return etag(request,workbench.query(project_id,object_id=object_id,section=section,query=query,
            limit=limit,offset=offset,revision=revision,kind=kind,status=status,purpose=purpose,
            version=version,association=association,entity_id=entity_id))
