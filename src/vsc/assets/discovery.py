"""Installed, versioned creation methods; no invented remote catalog or capability."""
from hashlib import sha256
from vsc.bootstrap import repository_root
from vsc.assets.resource_service import ResourceError

TUTORIALS={
    'production':('短剧制作与跨集资产复用','docs/guide/production-v2.md'),
    'workspace':('工作区、媒体与服务接入','docs/guide/workspace-setup.md'),
    'canvas':('画布创作与操作','docs/guide/creative-workbench.md'),
}


def discovery(service):
    from vsc.adapters.persistence.postgres.discovery import discover
    from vsc.production.canvas_agent import SKILLS
    result=discover(service.store)
    root=repository_root();skills=[]
    for identifier,item in SKILLS.items():
        path=root/'skills'/identifier/'SKILL.md'
        if not path.is_file():continue
        skills.append(dict(id=identifier,**item,sha256=sha256(path.read_bytes()).hexdigest()))
    result['skills']=skills
    result['tutorials']=[dict(id=key,title=title,sha256=sha256((root/path).read_bytes()).hexdigest()) for key,(title,path) in TUTORIALS.items() if (root/path).is_file()]
    return result


def tutorial(identifier):
    if identifier not in TUTORIALS:raise ResourceError('教程不存在','not_found',404)
    title,name=TUTORIALS[identifier];path=repository_root()/name
    if not path.is_file():raise ResourceError('当前安装包没有此教程','not_found',404)
    content=path.read_text('utf-8')
    return {'id':identifier,'title':title,'content':content,'sha256':sha256(content.encode()).hexdigest()}
