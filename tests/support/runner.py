"""Configured unittest discovery, conservative impact selection and timing."""
import argparse
import ast
from collections import Counter, defaultdict, deque
from fnmatch import fnmatchcase
import json
from pathlib import Path
import subprocess
import sys
import time
import unittest

from support.paths import ROOT
TESTS = ROOT / "tests"
CONFIG = TESTS / "config.json"


class ConfigurationError(ValueError):
    pass


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def discover(root=ROOT):
    tests = root / "tests"
    if str(tests) not in sys.path:
        sys.path.insert(0, str(tests))
    suite = unittest.TestLoader().discover(str(tests), pattern="test_*.py", top_level_dir=str(tests))
    cases = list(flatten(suite))
    broken = [case for case in cases if isinstance(case, unittest.loader._FailedTest)]
    if broken:
        raise ConfigurationError("测试导入失败：" + "; ".join(str(case._exception) for case in broken))
    loaded_files = {Path(sys.modules[case.__class__.__module__].__file__).resolve() for case in cases}
    physical_files = {path.resolve() for path in tests.rglob("test_*.py")}
    if physical_files - loaded_files:
        missing = sorted(str(path.relative_to(tests.resolve())) for path in physical_files - loaded_files)
        raise ConfigurationError("测试文件未被发现或没有测试：" + ", ".join(missing) + "；检查目录 __init__.py")
    return cases


def read_config(path=CONFIG):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("version") != 2 or not isinstance(data.get("modules"), dict):
        raise ConfigurationError("tests/config.json 需要 version=2 与 modules")
    return data


def metadata(case, config):
    module = case.__class__.__module__
    rule = config["modules"][module]
    return {"owner": rule["owner"], "layer": rule["layer"]}


def validate_config(cases, config, root=ROOT):
    if "aliases" in config or "path_aliases" in config:
        raise ConfigurationError("测试配置须使用当前模块和路径，不接受 aliases/path_aliases")
    modules = {case.__class__.__module__ for case in cases}
    declared = set(config["modules"])
    if modules != declared:
        raise ConfigurationError(f"测试配置不完整：未配置={sorted(modules-declared)}，已失效={sorted(declared-modules)}")
    ids = [case.id() for case in cases]
    if len(ids) != len(set(ids)):
        raise ConfigurationError("发现重复测试 ID；检查跨模块 TestCase 导入")
    layers = set(config.get("layers", []))
    if not layers:
        raise ConfigurationError("需要声明 layers")
    for module, rule in config["modules"].items():
        if not isinstance(rule.get("owner"), str) or not rule["owner"] or rule.get("layer") not in layers:
            raise ConfigurationError(f"{module}: 缺少有效 owner/layer")
        parts = module.split(".")
        if (len(parts) != 3 or parts[:2] != [rule["owner"], rule["layer"]] or
                not all(part.isidentifier() for part in parts) or not parts[2].startswith("test_")):
            raise ConfigurationError(f"{module}: 测试路径必须为 <owner>/<layer>/test_*.py，并与配置一致")
        if "overrides" in rule:
            raise ConfigurationError(f"{module}: 混合层级须拆为独立文件，不再使用 overrides")
        path = root / "tests" / (module.replace(".", "/") + ".py")
        if not path.is_file():
            raise ConfigurationError(f"测试文件不存在：{path}")
        for package in (path.parent, path.parent.parent):
            if not (package / "__init__.py").is_file():
                raise ConfigurationError(f"测试目录缺少包标记：{package}/__init__.py")
        for pattern in rule.get("sources", []):
            if not list(root.glob(pattern)):
                raise ConfigurationError(f"{module}: source 不存在：{pattern}")
        reject_test_imports(path)
    for path in (root / "tests/support").rglob("*.py"):
        reject_test_imports(path)
    for consumer, sources in config.get("dependencies", {}).items():
        for relative in [consumer, *sources]:
            if not (root / relative).is_file():
                raise ConfigurationError(f"依赖文件不存在：{relative}")
    return Counter(metadata(case, config)["layer"] for case in cases)


def reject_test_imports(path):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
        names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or "", *(alias.name for alias in node.names)] if isinstance(node, ast.ImportFrom) else []
        if any(any(part.startswith("test_") for part in name.split(".")) for name in names):
            raise ConfigurationError(f"{path}: 禁止导入其他测试模块；公共夹具应放在 support/")


def module_paths(root):
    paths = {}
    # Commands have their own namespace, so scripts/project never shadows tests/project.
    for folder, prefix in (("scripts", "scripts"), ("tests", ""), ("src", ""), ("tools", "tools")):
        base = root / folder
        for path in base.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            parts = path.relative_to(base).with_suffix("").parts
            components = parts[:-1] if parts[-1] == "__init__" else parts
            name = ".".join(([prefix] if prefix else []) + list(components))
            if name:
                paths[name] = path.relative_to(root).as_posix()
    return paths


def dependency_graph(root, config):
    """Local imports plus explicit non-imported CLI/contract inputs in config."""
    paths = module_paths(root)
    reverse = defaultdict(set)
    for module, relative in paths.items():
        tree = ast.parse((root / relative).read_text(encoding="utf-8"), filename=relative)
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                prefix = node.module or ""
                if node.level:
                    package = module.split(".") if relative.endswith("/__init__.py") else module.split(".")[:-1]
                    parent = package[:max(0, len(package) - node.level + 1)]
                    prefix = ".".join([*parent, prefix]).strip(".")
                imports.append(prefix)
                imports.extend((prefix + "." + alias.name).strip(".") for alias in node.names)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                # CLI filenames and spec_from_file_location are real dependencies too.
                name = node.value
                # Lazy imports and subprocess paths are real consumers as well.
                if name in paths:
                    reverse[paths[name]].add(relative)
                if name.endswith(".py"):
                    candidate = name if name.startswith(("scripts/", "tests/", "src/", "tools/")) else "scripts/" + name if "/" in name else None
                    if candidate in paths.values():
                        reverse[candidate].add(relative)
        for name in imports:
            while name:
                if name in paths:
                    reverse[paths[name]].add(relative)
                name = name.rpartition(".")[0]
        parent = module.rpartition(".")[0]
        while parent:
            if parent in paths:
                reverse[paths[parent]].add(relative)
            parent = parent.rpartition(".")[0]
    for module, rule in config["modules"].items():
        for pattern in rule.get("sources", []):
            for source in root.glob(pattern):
                reverse[source.relative_to(root).as_posix()].add(paths[module])
    for consumer, sources in config.get("dependencies", {}).items():
        for source in sources:
            reverse[source].add(consumer)
    catalog = root / "workflow/contracts.json"
    if catalog.is_file():
        for entry in json.loads(catalog.read_text(encoding="utf-8")).get("contracts", []):
            validator = entry.get("validator") or {}
            if validator.get("script"):
                for consumer in ("scripts/kernel/catalog.py", "scripts/project/artifacts.py"):
                    reverse[validator["script"]].add(consumer)
    return reverse, paths


def affected_modules(changed, config, root=ROOT):
    reverse, paths = dependency_graph(root, config)
    queue = deque()
    reasons = defaultdict(set)
    ignored = []
    unknown = []
    for name in changed:
        relative = Path(name).as_posix()
        if Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ConfigurationError(f"变更路径必须相对仓库根目录：{name}")
        if any(fnmatchcase(relative, pattern) for pattern in config.get("non_test_inputs", [])):
            ignored.append(relative)
            continue
        matches = [item for item in config.get("shared_inputs", [])
                   if any(fnmatchcase(relative, pattern) for pattern in item["patterns"])]
        if matches:
            for item in matches:
                for module, rule in config["modules"].items():
                    if item.get("owners") == "all" or rule["owner"] in item.get("owners", []):
                        reasons[paths[module]].add(relative)
                        queue.append(paths[module])
        elif relative in reverse or relative in paths.values():
            reasons[relative].add(relative)
            queue.append(relative)
        else:
            unknown.append(relative)
    if unknown:
        raise ConfigurationError("以下变更没有测试影响映射，请补配置或显式选组：" + ", ".join(unknown))
    while queue:
        source = queue.popleft()
        for consumer in reverse[source]:
            extra = reasons[source] - reasons[consumer]
            if extra:
                reasons[consumer].update(extra)
                queue.append(consumer)
    selected = {module: sorted(reasons[paths[module]]) for module in config["modules"] if reasons[paths[module]]}
    uncovered = [name for name in changed if name not in ignored and
                 not any(name in causes for causes in selected.values())]
    if uncovered:
        raise ConfigurationError("变更未关联到任何测试：" + ", ".join(uncovered))
    return selected, ignored


def changed_files(root=ROOT, since=None):
    def git(*args):
        result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=True)
        return result.stdout.decode("utf-8").split("\0")
    files = git("diff", "--name-only", "-z", "--diff-filter=ACDMRT", since or "HEAD")
    files += git("ls-files", "--others", "--exclude-standard", "-z")
    return sorted({name for name in files if name})


class TimedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.timings = []
        self.subtests = 0

    def startTest(self, test):
        self.started = time.perf_counter()
        super().startTest(test)

    def addSubTest(self, test, subtest, err):
        self.subtests += 1
        super().addSubTest(test, subtest, err)

    def stopTest(self, test):
        self.timings.append({"id": test.id(), "seconds": time.perf_counter() - self.started})
        super().stopTest(test)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--all", action="store_true", help="最终全量测试")
    selection.add_argument("--changed", action="store_true", help="当前暂存/未暂存/未跟踪变更")
    selection.add_argument("--since", help="相对 Git revision 的变更（含当前工作区）")
    selection.add_argument("--files", nargs="+", help="显式变更路径")
    selection.add_argument("--test", nargs="+", help="当前领域、层级、模块、类或方法 ID")
    selection.add_argument("--layer", help="配置中的 unit/integration/system 分组")
    selection.add_argument("--check-config", action="store_true", help="只检查配置覆盖")
    parser.add_argument("--list", action="store_true", help="只列出选择及其原因")
    parser.add_argument("--durations", type=int, default=5, help="最慢测试数量")
    parser.add_argument("--report", type=Path, help="写 JSON 报告，建议系统临时目录")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.durations < 0:
            raise ConfigurationError("durations 不得为负数")
        config = read_config()
        cases = discover()
        counts = validate_config(cases, config)
        if args.check_config:
            print(f"TEST CONFIG: PASS methods={len(cases)} layers={dict(counts)}")
            return 0
        reasons = {}
        if args.changed or args.since or args.files:
            changed = args.files if args.files is not None else changed_files(since=args.since)
            reasons, ignored = affected_modules(changed, config)
            selected = [case for case in cases if case.__class__.__module__ in reasons]
            if ignored:
                print("非运行时变更（另做文档/引用检查）：" + ", ".join(ignored))
        elif args.test:
            for selector in args.test:
                if not any(case.id() == selector or case.id().startswith(selector + ".") for case in cases):
                    raise ConfigurationError(f"测试选择无匹配：{selector}")
            targets = set(args.test)
            selected = [case for case in cases if any(case.id() == target or case.id().startswith(target + ".") for target in targets)]
        elif args.layer:
            if args.layer not in config["layers"]:
                raise ConfigurationError(f"未知 layer：{args.layer}")
            selected = [case for case in cases if metadata(case, config)["layer"] == args.layer]
        else:
            selected = cases
        print(f"TEST PLAN: selected={len(selected)}/{len(cases)}", flush=True)
        if args.list:
            for case in selected:
                info = metadata(case, config)
                cause = ",".join(reasons.get(case.__class__.__module__, []))
                print(f"{case.id()} [{info['owner']}/{info['layer']}]" + (f" <- {cause}" if cause else ""))
            return 0
        if not selected:
            print("没有需运行的测试；新代码无映射会报错，不会被当作通过。")
            return 0
        started = time.perf_counter()
        result = unittest.TextTestRunner(verbosity=2 if args.verbose else 1, resultclass=TimedResult).run(unittest.TestSuite(selected))
        elapsed = time.perf_counter() - started
        timings = sorted(result.timings, key=lambda item: item["seconds"], reverse=True)
        print(f"TEST RESULT: methods={result.testsRun} subtests={result.subtests} skipped={len(result.skipped)} elapsed={elapsed:.3f}s")
        for item in timings[:args.durations]:
            print(f"DURATION {item['seconds']:.3f}s {item['id']}")
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps({"success": result.wasSuccessful(), "methods": result.testsRun,
                "subtests": result.subtests, "skipped": len(result.skipped), "elapsed_seconds": elapsed,
                "test_seconds": sum(item["seconds"] for item in timings), "timings": timings,
                "selection_reasons": reasons}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return 0 if result.wasSuccessful() else 1
    except (ConfigurationError, OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"TEST CONFIG: FAIL {exc}", file=sys.stderr)
        return 2
