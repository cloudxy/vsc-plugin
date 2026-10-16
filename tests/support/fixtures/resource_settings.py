"""Fresh non-secret provider configuration for isolated tests."""
from copy import deepcopy
from vsc.production.resource_settings import PRESETS


def configuration(**kw):
    value = deepcopy(PRESETS[0])
    value.pop("id")
    value.pop("label")
    value.update(model_key="doubao-seedream-test", model_version="1", enabled=True)
    value.update(kw)
    return value
