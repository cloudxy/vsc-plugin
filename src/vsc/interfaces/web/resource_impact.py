"""Read-only impact report route using the shared evidence query."""
from fastapi import Request
from vsc.assets.resource_impact import ResourceImpact


def install_impact_routes(router,catalog,etag):
    impact=ResourceImpact(catalog)

    @router.get('/{project_id}/impact')
    def report(project_id:str,request:Request,source:str,replacement:str=None,depth:int=4,limit:int=100,revision:int=None):
        return etag(request,impact.query(project_id,source=source,replacement=replacement,depth=depth,limit=limit,revision=revision))
