"""Catalog discovery and explicit multi-project use of original shared media."""
from vsc.assets.resource_service import ResourceError


KINDS={"character","location","prop","voice","blocking","other"}


class AssetCenterService:
    def _center(self):
        from vsc.adapters.persistence.postgres.asset_center import AssetCenterRepository
        return AssetCenterRepository(self.store,self.storage)

    @staticmethod
    def _center_page(offset,limit):
        if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=100:
            raise ResourceError("分页范围无效")

    def search_asset_center(self, filters, actor=None):
        allowed={"query","tag","form_name","asset_kind","workspace_id","review_status","offset","limit","media_only"}
        if not isinstance(filters,dict) or set(filters)-allowed:raise ResourceError("素材检索字段无效")
        self._center_page(filters.get("offset",0),filters.get("limit",24))
        if "media_only" in filters and type(filters["media_only"]) is not bool:raise ResourceError("媒体筛选必须是布尔值")
        for key in allowed-{"offset","limit","media_only"}:
            if filters.get(key) is not None and (not isinstance(filters[key],str) or len(filters[key])>200):raise ResourceError("素材检索文字过长")
        return self._center().search(dict(filters,offset=filters.get("offset",0),limit=filters.get("limit",24)),actor)

    def edit_asset_catalog(self,payload,actor):
        self._actor(actor)
        required={"entry_id","library_version_id","expected_revision","asset_kind","form_name","workspace_id","review_status","notes","tags","command_key"}
        if not isinstance(payload,dict) or set(payload)!=required:raise ResourceError("目录编辑需要固定素材版本、原目录版本和完整字段")
        if (type(payload["expected_revision"]) is not int or payload["expected_revision"]<0 or payload["asset_kind"] not in KINDS
                or payload["review_status"] not in {"draft","confirmed","returned"}):raise ResourceError("目录类型、版本或确认状态无效")
        for key,maximum in (("form_name",200),("notes",4000),("command_key",200)):
            if not isinstance(payload[key],str) or len(payload[key])>maximum:raise ResourceError("目录文本格式无效")
        if not payload["command_key"] or (payload["review_status"]!="draft" and not payload["notes"].strip()):raise ResourceError("确认或退回需要明确说明")
        tags=payload["tags"]
        if not isinstance(tags,list) or len(tags)>50 or any(not isinstance(t,str) or not 1<=len(t.strip())<=80 for t in tags):raise ResourceError("标签需要1–80字，每项最多50个")
        from vsc.adapters.persistence.postgres.values import checked_id
        for key in ("entry_id","library_version_id"):
            checked_id(payload[key])
        if payload["workspace_id"]:
            checked_id(payload["workspace_id"])
            self.authorize_workspace(payload["workspace_id"],"manage")
        return self._center().edit(dict(payload,tags=sorted(set(t.strip() for t in tags))),actor)

    def asset_center_cart(self,actor):
        self._actor(actor);return self._center().cart(actor)

    def change_asset_center_cart(self,payload,actor):
        self._actor(actor)
        if (not isinstance(payload,dict) or set(payload)!={"library_version_id","member_key","active"}
                or type(payload["active"]) is not bool or not isinstance(payload["member_key"],str)):
            raise ResourceError("请选择固定素材成员与加入或移除操作")
        from vsc.adapters.persistence.postgres.values import checked_id
        checked_id(payload["library_version_id"])
        return self._center().cart_change(payload,actor)

    def import_asset_center_item(self,project_id,payload,**kw):
        self._validate_write(payload,**kw)
        if set(payload)-{"cart_id","target_object_id","asset_kind","role"} or not payload.get("cart_id") or not payload.get("role"):
            raise ResourceError("导入需要选取项、目标对象或新资产类型以及用途")
        if bool(payload.get("target_object_id"))==bool(payload.get("asset_kind")):
            raise ResourceError("请选择已有对象或新建资产之一")
        if payload.get("asset_kind") and payload["asset_kind"] not in {"character","location","prop","voice"}:
            raise ResourceError("新建资产类型无效")
        from vsc.adapters.persistence.postgres.values import checked_id
        checked_id(payload["cart_id"])
        if payload.get("target_object_id"):checked_id(payload["target_object_id"])
        return self._center().import_item(project_id,payload,**kw)

    def request_asset_download(self,payload,actor):
        self._actor(actor)
        if (not isinstance(payload,dict) or set(payload)!={"library_version_id","member_key","command_key"}
                or any(not isinstance(payload[k],str) or not 1<=len(payload[k])<=200 for k in payload)):
            raise ResourceError("下载需要固定版本、媒体成员和请求标识")
        result=self._center().download(payload,actor)
        from urllib.parse import quote
        return dict(result,url="/api/v1/library/versions/"+quote(payload["library_version_id"],safe="")+"/members/"+quote(payload["member_key"],safe="")+"/content")

    def asset_download_history(self,actor,offset=0,limit=24):
        self._actor(actor);self._center_page(offset,limit)
        return self._center().downloads(actor,offset,limit)
