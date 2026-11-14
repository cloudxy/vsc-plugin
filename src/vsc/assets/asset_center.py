"""Catalog discovery and explicit multi-project use of original shared media."""
from vsc.assets.resource_service import ResourceError


KINDS = {"character", "location", "prop", "voice", "blocking", "other"}
CATALOG_KINDS = KINDS | {"creature"}
CREATURE_TAG = "生物/异兽"
CENTER_ORDERS = {"", "title", "latest", "heat"}
OFFICIAL_DIMENSIONS = {
    "role_level": {"lead", "supporting", "extra", "unspecified"},
    "gender": {"female", "male", "other", "unspecified"},
    "age_band": {"child", "teen", "young_adult", "middle_aged", "senior", "unspecified"},
}


class AssetCenterService:
    def _library_media(self):
        from vsc.adapters.persistence.postgres.library_media import LibraryMediaRepository
        return LibraryMediaRepository(self.store, self.storage)

    def official_asset_detail(self, entry_id, actor):
        from vsc.adapters.persistence.postgres.values import checked_id
        return self._library_media().detail(checked_id(entry_id), actor)

    def official_media_recycle(self, actor, offset=0, limit=24):
        self._actor(actor)
        self._center_page(offset, limit)
        return self._library_media().recycle(actor, offset, limit)

    def official_media_recycle_content(self, version_id, member_key, actor):
        from vsc.adapters.persistence.postgres.values import checked_id
        return self._library_media().recycle_content(checked_id(version_id), member_key, actor)

    def official_media_cleanup(self, payload, actor):
        self._actor(actor)
        repo = self._library_media()
        repo.publisher(actor)
        from vsc.adapters.persistence.postgres.values import checked_id
        if not isinstance(payload, dict) or set(payload) != {'library_version_id', 'member_key'} or not isinstance(payload.get('member_key'), str):
            raise ResourceError('继续清理需要固定媒体成员')
        return repo._cleanup(checked_id(payload['library_version_id']), payload['member_key'])

    def attach_official_backup(self, payload, actor):
        self._actor(actor)
        if not isinstance(payload, dict) or set(payload) != {'entry_id', 'library_version_id', 'member_key', 'reason'}:
            raise ResourceError('备份关联需要原官方资产、固定媒体和依据')
        from vsc.adapters.persistence.postgres.values import checked_id
        checked_id(payload['entry_id']); checked_id(payload['library_version_id'])
        if any(not isinstance(payload[k], str) or not 1 <= len(payload[k]) <= 2000 for k in ('member_key', 'reason')):
            raise ResourceError('备份媒体或关联依据无效')
        return self._library_media().attach_backup(payload, actor)

    def official_media_command(self, payload, actor):
        self._actor(actor)
        fields = {'library_version_id', 'member_key', 'operation', 'expected_revision', 'reason', 'command_key'}
        if not isinstance(payload, dict) or set(payload) != fields:
            raise ResourceError('媒体操作需要固定成员、原版本、理由和请求标识')
        from vsc.adapters.persistence.postgres.values import checked_id
        checked_id(payload['library_version_id'])
        if (not isinstance(payload['operation'], str) or payload['operation'] not in {'trash', 'restore', 'purge'} or type(payload['expected_revision']) is not int
                or payload['expected_revision'] < 0 or any(not isinstance(payload[k], str) or not payload[k].strip()
                or len(payload[k]) > maximum for k, maximum in (('member_key', 80), ('reason', 2000), ('command_key', 200)))):
            raise ResourceError('媒体操作字段无效')
        return self._library_media().command(payload, actor)

    def _center(self):
        from vsc.adapters.persistence.postgres.asset_center import AssetCenterRepository
        return AssetCenterRepository(self.store, self.storage)

    @staticmethod
    def _center_page(offset, limit):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise ResourceError("分页范围无效")

    def search_asset_center(self, filters, actor=None):
        allowed = {
            "query",
            "tag",
            "form_name",
            "asset_kind",
            "workspace_id",
            "review_status",
            "offset",
            "limit",
            "media_only",
            "source",
            "role_level",
            "role_tag",
            "gender",
            "age_band",
            "order_by",
        }
        if not isinstance(filters, dict) or set(filters) - allowed:
            raise ResourceError("素材检索字段无效")
        self._center_page(filters.get("offset", 0), filters.get("limit", 24))
        if "media_only" in filters and type(filters["media_only"]) is not bool:
            raise ResourceError("媒体筛选必须是布尔值")
        for key in allowed - {"offset", "limit", "media_only"}:
            if filters.get(key) is not None and (not isinstance(filters[key], str) or len(filters[key]) > 200):
                raise ResourceError("素材检索文字过长")
        source = filters.get("source", "shared")
        if source not in {"shared", "official"}:
            raise ResourceError("素材来源筛选无效")
        allowed_kinds = KINDS if source == "official" else CATALOG_KINDS
        if filters.get("asset_kind") and filters["asset_kind"] not in allowed_kinds:
            raise ResourceError("资产类型筛选无效")
        if filters.get("order_by", "") not in CENTER_ORDERS:
            raise ResourceError("素材排序方式无效")
        for key, values in OFFICIAL_DIMENSIONS.items():
            if filters.get(key) and filters[key] not in values:
                raise ResourceError("人物筛选值无效")
        if len(filters.get("role_tag") or "") > 80:
            raise ResourceError("人物角色标签过长")
        if source == "official" and any(filters.get(k) for k in ("tag", "form_name", "workspace_id", "review_status")):
            raise ResourceError("官方目录请使用官方人物分类筛选")
        if source == "shared" and any(filters.get(k) for k in (*OFFICIAL_DIMENSIONS, "role_tag")):
            raise ResourceError("人物分类筛选需要选择官方来源")
        return self._center().search(dict(filters, offset=filters.get("offset", 0), limit=filters.get("limit", 24)), actor)

    def official_asset_capabilities(self, actor):
        self._actor(actor)
        return self._center().official_capabilities(actor)

    def publish_official_asset(self, payload, actor):
        """Classify a fixed library version; the original license remains authoritative."""
        self._actor(actor)
        required = {
            "entry_id",
            "library_version_id",
            "asset_kind",
            "role_level",
            "role_tag",
            "gender",
            "age_band",
            "notes",
            "command_key",
        }
        if not isinstance(payload, dict) or set(payload) != required:
            raise ResourceError("官方发布需要固定库版本、人物分类和发布说明")
        from vsc.adapters.persistence.postgres.values import checked_id
        for key in ("entry_id", "library_version_id"):
            checked_id(payload[key])
        if not isinstance(payload["asset_kind"], str) or payload["asset_kind"] not in KINDS:
            raise ResourceError("官方资产类型无效")
        for key, values in OFFICIAL_DIMENSIONS.items():
            if not isinstance(payload[key], str) or payload[key] not in values:
                raise ResourceError("官方人物分类无效")
        for key, maximum in (("role_tag", 80), ("notes", 4000), ("command_key", 200)):
            if not isinstance(payload[key], str) or not payload[key].strip() or len(payload[key]) > maximum:
                raise ResourceError("官方发布文字字段无效")
        if payload["asset_kind"] != "character" and any(payload[k] != "unspecified" for k in OFFICIAL_DIMENSIONS):
            raise ResourceError("人物分类仅适用于人物资产")
        return self._center().publish_official(dict(payload, role_tag=payload["role_tag"].strip()), actor)

    def edit_asset_catalog(self, payload, actor):
        self._actor(actor)
        required = {
            "entry_id",
            "library_version_id",
            "expected_revision",
            "asset_kind",
            "form_name",
            "workspace_id",
            "review_status",
            "notes",
            "tags",
            "command_key",
        }
        if not isinstance(payload, dict) or set(payload) != required:
            raise ResourceError("目录编辑需要固定素材版本、原目录版本和完整字段")
        if (
            type(payload["expected_revision"]) is not int
            or payload["expected_revision"] < 0
            or payload["asset_kind"] not in CATALOG_KINDS
            or payload["review_status"] not in {"draft", "confirmed", "returned"}
        ):
            raise ResourceError("目录类型、版本或确认状态无效")
        for key, maximum in (("form_name", 200), ("notes", 4000), ("command_key", 200)):
            if not isinstance(payload[key], str) or len(payload[key]) > maximum:
                raise ResourceError("目录文本格式无效")
        if not payload["command_key"] or (payload["review_status"] != "draft" and not payload["notes"].strip()):
            raise ResourceError("确认或退回需要明确说明")
        tags = payload["tags"]
        if not isinstance(tags, list) or len(tags) > 50 or any(not isinstance(t, str) or not 1 <= len(t.strip()) <= 80 for t in tags):
            raise ResourceError("标签需要1–80字，每项最多50个")
        normalized_tags = sorted(set(t.strip() for t in tags))
        stored_kind = payload["asset_kind"]
        if stored_kind == "creature":
            stored_kind = "other"
            if CREATURE_TAG not in normalized_tags:
                if len(normalized_tags) >= 50:
                    raise ResourceError("生物/异兽分类需要保留1个分类标签位，最多填写49个附加标签")
                normalized_tags = sorted(set(normalized_tags) | {CREATURE_TAG})
        from vsc.adapters.persistence.postgres.values import checked_id
        for key in ("entry_id", "library_version_id"):
            checked_id(payload[key])
        if payload["workspace_id"]:
            checked_id(payload["workspace_id"])
            self.authorize_workspace(payload["workspace_id"], "manage")
        return self._center().edit(dict(payload, asset_kind=stored_kind, tags=normalized_tags), actor)

    def asset_center_cart(self, actor):
        self._actor(actor)
        return self._center().cart(actor)

    def change_asset_center_cart(self, payload, actor):
        self._actor(actor)
        if (
            not isinstance(payload, dict)
            or set(payload) != {"library_version_id", "member_key", "active"}
            or type(payload["active"]) is not bool
            or not isinstance(payload["member_key"], str)
        ):
            raise ResourceError("请选择固定素材成员与加入或移除操作")
        from vsc.adapters.persistence.postgres.values import checked_id
        checked_id(payload["library_version_id"])
        return self._center().cart_change(payload, actor)

    def clear_asset_center_cart(self, actor):
        self._actor(actor)
        return self._center().cart_clear(actor)

    def import_asset_center_item(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        if set(payload) - {"cart_id", "target_object_id", "asset_kind", "role"} or not payload.get("cart_id") or not payload.get("role"):
            raise ResourceError("导入需要选取项、目标对象或新资产类型以及用途")
        if bool(payload.get("target_object_id")) == bool(payload.get("asset_kind")):
            raise ResourceError("请选择已有对象或新建资产之一")
        if payload.get("asset_kind") and payload["asset_kind"] not in {"character", "location", "prop", "voice", "creature"}:
            raise ResourceError("新建资产类型无效")
        from vsc.adapters.persistence.postgres.values import checked_id
        checked_id(payload["cart_id"])
        if payload.get("target_object_id"):
            checked_id(payload["target_object_id"])
        return self._center().import_item(project_id, payload, **kw)

    def request_asset_download(self, payload, actor):
        self._actor(actor)
        if (
            not isinstance(payload, dict)
            or set(payload) != {"library_version_id", "member_key", "command_key"}
            or any(not isinstance(payload[k], str) or not 1 <= len(payload[k]) <= 200 for k in payload)
        ):
            raise ResourceError("下载需要固定版本、媒体成员和请求标识")
        result = self._center().download(payload, actor)
        from urllib.parse import quote
        return dict(
            result,
            url="/api/v1/library/versions/"
            + quote(payload["library_version_id"], safe="")
            + "/members/"
            + quote(payload["member_key"], safe="")
            + "/content",
        )

    def asset_download_history(self, actor, offset=0, limit=24):
        self._actor(actor)
        self._center_page(offset, limit)
        return self._center().downloads(actor, offset, limit)
