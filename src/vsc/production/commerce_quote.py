"""Pin an explicitly selected billing account into the existing production draft."""
from vsc.assets.resource_service import ResourceError,Conflict
from vsc.assets.access_control import current_principal


def attach_commerce_quote(service,project_id,document,quote,request):
    operations=[dict(operation=row["operation"],model_id=row["model"]["id"],native_units=row["native_units"])
                for row in quote["generation_quote"]["jobs"]]
    payload={"operations":operations,"account_actor":request.get("commerce_account_actor")}
    if "commerce_account_actor" in request:
        if payload["account_actor"] is not None and (not isinstance(payload["account_actor"],str) or not payload["account_actor"].strip()):
            raise ResourceError("请选择承担本次制作的额度账户","commerce_account_required")
        principal=current_principal()
        priced=service.preview_commerce_charge(project_id,payload,actor=principal.actor if principal else None)
    else:
        priced=service._commerce().preview_charge(project_id,payload)
        if priced["enabled"]:
            raise ResourceError("项目已启用商业额度，请明确选择本次制作的承担账户","commerce_account_required")
    if priced["revision"]!=quote["revision"]:raise Conflict("报价期间项目已改变，请重新预览")
    if priced["enabled"]:document["commerce_charge"]=priced["commerce_charge"]
    return priced
