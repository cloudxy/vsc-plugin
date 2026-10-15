"""Stable legacy series API over separate context, media and boundary domains.

Legacy callers patch module-level dependencies. Forward those writes to the
owning domain and references shared by the original single module.
"""
import sys as _sys
from types import ModuleType as _ModuleType
from vsc.production import context as _context
from vsc.assets import registry as _registry
from vsc.story import boundaries as _boundaries
from vsc.interfaces.cli import series as _cli

_DOMAINS = (_cli, _boundaries, _registry, _context)
_OWNERS = {name: module for module in _DOMAINS for name in vars(module)
           if not name.startswith("_")}
for _name in ("_artifact_document", "_scope", "_boundary_shots", "_boundary_signature",
              "_boundary_status", "_select", "_media_references"):
    _OWNERS[_name] = _context
for _name, _module in _OWNERS.items():
    globals()[_name] = getattr(_module, _name)


class _LegacyFacade(_ModuleType):
    def __getattribute__(self, name):
        owners = _ModuleType.__getattribute__(self, "_OWNERS")
        if name in owners:
            return getattr(owners[name], name)
        return _ModuleType.__getattribute__(self, name)

    def __setattr__(self, name, value):
        owners = _ModuleType.__getattribute__(self, "_OWNERS")
        if name in owners:
            original = getattr(owners[name], name)
            for module in _ModuleType.__getattribute__(self, "_DOMAINS"):
                if vars(module).get(name) is original:
                    setattr(module, name, value)
        _ModuleType.__setattr__(self, name, value)


if __name__ == "__main__":
    raise SystemExit(_cli.main())
_sys.modules[__name__].__class__ = _LegacyFacade
