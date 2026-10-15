"""Legacy CLI/module aliases; imported callers share canonical module globals."""
import importlib
import runpy
import sys


def expose(legacy_name, canonical_name, namespace):
    if legacy_name == "__main__":
        # Keep argv[0] as the user's scripts entry (argparse and worker CLIs).
        runpy.run_module(canonical_name, run_name="__main__", alter_sys=False)
        return
    module = importlib.import_module(canonical_name)
    # Normal imports return the canonical object, so patches and caches are shared.
    sys.modules[legacy_name] = module
    # Also retain read access for callers using an unregistered importlib spec.
    namespace.update(module.__dict__)
