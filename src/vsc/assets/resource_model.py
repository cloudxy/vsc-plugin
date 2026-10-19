"""Public resource-model use cases and immutable projection value validation."""
from vsc.assets.taxonomy import CATEGORY_BY_CODE


class ResourceModelService:
    """Shared CLI/web entry points; repository owns locking and typed references."""

    def get_resource_taxonomy(self, project_id):
        return self.store.get_resource_taxonomy(project_id)

    def browse_resources(self, project_id, **options):
        return self.store.browse_resources(project_id, **options)

    def get_shot_designs(self, project_id, **options):
        return self.store.get_shot_designs(project_id, **options)

    def get_resource_requirements(self, project_id, **options):
        return self.store.get_resource_requirements(project_id, **options)

    def get_scene_locations(self, project_id, **options):
        return self.store.get_scene_locations(project_id, **options)

    def get_asset_usage(self, project_id, asset_id):
        return self.store.get_asset_usage(project_id, asset_id)

    def classify_resource(self, project_id, payload, actor=None, **kw):
        from vsc.assets.resource_service import ResourceError, required
        if required(payload, "target_type") not in {"identity", "media", "artifact"}:
            raise ResourceError("分类对象须为identity、media或artifact", "invalid_category_target")
        required(payload, "target_id")
        category = required(payload, "category_code")
        if not isinstance(category, str) or category not in CATEGORY_BY_CODE:
            raise ResourceError("未知资源分类", "unknown_category")
        return self._write("classify_resource", project_id, payload, actor=actor, **kw)


def projection_rows(document, field):
    """Only explicitly declared lists produce projections; absence means none."""
    from vsc.assets.resource_service import ResourceError
    values = document.get(field, [])
    if not isinstance(values, list) or len(values) > 10000 or any(not isinstance(row, dict) for row in values):
        raise ResourceError(field + "必须是最多10000行的对象数组", "invalid_resource_projection")
    return values


def projection_content(row, excluded):
    """Keep creative prose/parameters while rejecting hidden object relations."""
    from vsc.assets.resource_service import ResourceError
    def check(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key.endswith(("_id", "_ids", "_ref", "_refs")):
                    raise ResourceError("对象引用须放有类型字段: " + key, "resource_untyped_reference")
                check(item)
        elif isinstance(value, list):
            for item in value:
                check(item)
    content = {key: value for key, value in row.items() if key not in excluded}
    check(content)
    return content


def projection_text(row, field):
    from vsc.assets.resource_service import ResourceError, required
    value = required(row, field)
    if not isinstance(value, str):
        raise ResourceError(field + "必须为非空文本", "invalid_resource_projection")
    return value
