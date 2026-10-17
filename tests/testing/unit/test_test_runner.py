"""Regression checks for test selection: omitted/unknown inputs must fail visibly."""
import copy
import io
import json
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch

from support import runner


def case(module, method="test_ok"):
    cls = type("Sample", (unittest.TestCase,), {"__module__": module, method: lambda self: None})
    return cls(method)


class TestEngineering(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="vsc-test-selection-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        files = {
            "scripts/example/base.py": "VALUE = 1\n",
            "scripts/example/consumer.py": "from scripts.example import base\n",
            "scripts/kernel/catalog.py": "# validators are dispatched from JSON\n",
            "scripts/project/artifacts.py": "# validators are dispatched from JSON\n",
            "tests/support/shared.py": "from scripts.example import consumer\n",
            "tests/sample/unit/test_one.py": "from support.shared import fixture\n",
            "tests/sample/unit/test_two.py": "from support.shared import fixture\n",
            "tests/sample/unit/test_other.py": "# unrelated\n",
            "tests/sample/unit/test_cli.py": "CLI = 'scripts/example/base.py'\n",
            "tests/sample/unit/test_kernel.py": "CLI = 'kernel/catalog.py'\n",
        }
        for name, content in files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            if name.startswith("tests/sample/"):
                for package in (path.parent, path.parent.parent):
                    (package / "__init__.py").touch()
        self.config = {"version": 2, "layers": ["unit", "integration", "system"],
            "modules": {module: {"owner": "sample", "layer": "unit", "sources": []}
                        for module in ("sample.unit.test_one", "sample.unit.test_two", "sample.unit.test_other", "sample.unit.test_cli", "sample.unit.test_kernel")},
            "non_test_inputs": ["docs/**"],
            "shared_inputs": [{"patterns": ["tests/config.json"], "owners": "all"}]}
        self.cases = [case(module) for module in self.config["modules"]]

    def test_config_requires_complete_unique_discovery_and_live_overrides(self):
        self.assertEqual(runner.validate_config(self.cases, self.config, self.root), {"unit": 5})
        bad_configs = []
        missing = copy.deepcopy(self.config)
        missing["modules"].pop("sample.unit.test_one")
        bad_configs.append(("missing_module", missing))
        stale = copy.deepcopy(self.config)
        stale["modules"]["sample.unit.test_missing"] = stale["modules"]["sample.unit.test_one"]
        bad_configs.append(("stale_module", stale))
        override = copy.deepcopy(self.config)
        override["modules"]["sample.unit.test_one"]["overrides"] = {"MissingClass": "unit"}
        bad_configs.append(("stale_override", override))
        for field, value in (("owner", "different"), ("layer", "integration")):
            mismatch = copy.deepcopy(self.config)
            mismatch["modules"]["sample.unit.test_one"][field] = value
            bad_configs.append(("path_" + field, mismatch))
        stale_alias = copy.deepcopy(self.config)
        stale_alias["aliases"] = {"test_old": ["sample.unit.test_missing"]}
        bad_configs.append(("stale_alias", stale_alias))
        for name, config in bad_configs:
            with self.subTest(case=name), self.assertRaises(runner.ConfigurationError):
                runner.validate_config(self.cases, config, self.root)
        with self.assertRaisesRegex(runner.ConfigurationError, "重复测试 ID"):
            runner.validate_config([*self.cases, self.cases[0]], self.config, self.root)
        flat = copy.deepcopy(self.config)
        flat["modules"]["test_flat"] = {"owner": "sample", "layer": "unit", "sources": []}
        (self.root / "tests/test_flat.py").write_text("# accidental flat test\n")
        with self.assertRaisesRegex(runner.ConfigurationError, "测试路径必须"):
            runner.validate_config([*self.cases, case("test_flat")], flat, self.root)
        path = self.root / "tests/sample/unit/test_one.py"
        for source in ("from sample.unit.test_two import fixture\n", "from . import test_two\n"):
            path.write_text(source)
            with self.subTest(import_source=source), self.assertRaisesRegex(runner.ConfigurationError, "禁止导入其他测试模块"):
                runner.validate_config(self.cases, self.config, self.root)

    def test_nested_test_file_without_package_is_not_silently_omitted(self):
        root = self.root / "discovery"
        hidden = root / "tests/missing_package/test_hidden.py"
        hidden.parent.mkdir(parents=True)
        hidden.write_text("import unittest\nclass Hidden(unittest.TestCase):\n    def test_ok(self): pass\n")
        with patch.object(sys, "path", list(sys.path)), \
                self.assertRaisesRegex(runner.ConfigurationError, "test_hidden.py"):
            runner.discover(root)

    def test_import_and_shared_fixture_consumers_are_transitive(self):
        selected, _ = runner.affected_modules(["scripts/example/base.py"], self.config, self.root)
        self.assertEqual(set(selected), {"sample.unit.test_one", "sample.unit.test_two", "sample.unit.test_cli"})
        selected, _ = runner.affected_modules(["tests/support/shared.py"], self.config, self.root)
        self.assertEqual(set(selected), {"sample.unit.test_one", "sample.unit.test_two"})

    def test_contract_dispatch_adds_dynamic_validator_dependency(self):
        path = self.root / "workflow/contracts.json"
        path.parent.mkdir()
        path.write_text(json.dumps({"contracts": [{"validator": {"script": "scripts/example/base.py"}}]}))
        selected, _ = runner.affected_modules(["scripts/example/base.py"], self.config, self.root)
        self.assertIn("sample.unit.test_kernel", selected)

    def test_package_initializers_affect_submodule_consumers(self):
        (self.root / "tests/support").mkdir(exist_ok=True)
        (self.root / "tests/support/__init__.py").write_text("")
        (self.root / "tests/support/fixture.py").write_text("VALUE = 1\n")
        (self.root / "tests/sample/unit/test_one.py").write_text("from support.fixture import VALUE\n")
        selected, _ = runner.affected_modules(["tests/support/__init__.py"], self.config, self.root)
        self.assertEqual(set(selected), {"sample.unit.test_one", "sample.unit.test_two"})

    def test_relative_package_reexports_keep_indirect_consumers(self):
        (self.root / "tests/support").mkdir(exist_ok=True)
        (self.root / "tests/support/__init__.py").write_text("from .fixture import VALUE\n")
        (self.root / "tests/support/fixture.py").write_text("VALUE = 1\n")
        (self.root / "tests/sample/unit/test_one.py").write_text("from support.fixture import VALUE\n")
        (self.root / "tests/sample/unit/test_reexport.py").write_text("from support import VALUE\n")
        self.config["modules"]["sample.unit.test_reexport"] = {"owner": "sample", "layer": "unit", "sources": []}
        selected, _ = runner.affected_modules(["tests/support/fixture.py"], self.config, self.root)
        self.assertEqual(set(selected), {"sample.unit.test_one", "sample.unit.test_two", "sample.unit.test_reexport"})

    def test_grouped_entries_and_tools_keep_dependency_identity(self):
        files = {
            "src/vsc/__init__.py": "",
            "src/vsc/domain/__init__.py": "",
            "src/vsc/domain/base.py": "VALUE = 1\n",
            "scripts/example/base.py": "from vsc.domain.base import VALUE\n",
            "tools/__init__.py": "",
            "tools/maintenance/__init__.py": "",
            "tools/maintenance/check.py": "from vsc.domain.base import VALUE\n",
            "tests/sample/unit/test_other.py": "from tools.maintenance import check\n",
        }
        for relative, source in files.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source)
        selected, _ = runner.affected_modules(["src/vsc/domain/base.py"], self.config, self.root)
        self.assertEqual(set(selected), {"sample.unit.test_one", "sample.unit.test_two", "sample.unit.test_cli", "sample.unit.test_other"})
        selected, _ = runner.affected_modules(["tools/maintenance/check.py"], self.config, self.root)
        self.assertEqual(set(selected), {"sample.unit.test_other"})
        selected, _ = runner.affected_modules(["src/vsc/domain/__init__.py"], self.config, self.root)
        self.assertEqual(set(selected), {"sample.unit.test_one", "sample.unit.test_two", "sample.unit.test_cli", "sample.unit.test_other"})

    def test_shared_config_selects_all_and_docs_select_none(self):
        selected, _ = runner.affected_modules(["tests/config.json"], self.config, self.root)
        self.assertEqual(set(selected), set(self.config["modules"]))
        selected, ignored = runner.affected_modules(["docs/example.md"], self.config, self.root)
        self.assertEqual(selected, {})
        self.assertEqual(ignored, ["docs/example.md"])

    def test_grouped_scripts_do_not_shadow_test_owner_packages(self):
        files = {
            "scripts/project/state.py": "from vsc.project.state import main\n",
            "tests/project/__init__.py": "",
            "tests/project/state.py": "VALUE = 1\n",
        }
        for relative, content in files.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        paths = runner.module_paths(self.root)
        self.assertEqual(paths["scripts.project.state"], "scripts/project/state.py")
        self.assertEqual(paths["project.state"], "tests/project/state.py")

    def test_unmapped_deleted_or_escaping_inputs_are_not_silently_skipped(self):
        for name in ("scripts/new_feature.py", "scripts/deleted.py", "../outside.py", "/outside.py"):
            with self.subTest(path=name), self.assertRaises(runner.ConfigurationError):
                runner.affected_modules([name], self.config, self.root)
        (self.root / "scripts/unreferenced.py").write_text("VALUE = 1\n")
        with self.assertRaisesRegex(runner.ConfigurationError, "未关联到任何测试"):
            runner.affected_modules(["scripts/unreferenced.py"], self.config, self.root)

    def test_multiple_changes_keep_union_and_provenance(self):
        selected, _ = runner.affected_modules(["scripts/example/base.py", "tests/sample/unit/test_other.py"], self.config, self.root)
        self.assertEqual(set(selected), {"sample.unit.test_one", "sample.unit.test_two", "sample.unit.test_cli", "sample.unit.test_other"})
        self.assertEqual(selected["sample.unit.test_two"], ["scripts/example/base.py"])

    def test_failed_subtest_fails_runner_and_remains_visible(self):
        class Failure(unittest.TestCase):
            def test_cases(self):
                for value in (1, 2):
                    with self.subTest(value=value):
                        self.assertEqual(value, 1)
        stream = io.StringIO()
        result = unittest.TextTestRunner(stream=stream, resultclass=runner.TimedResult).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(Failure))
        self.assertFalse(result.wasSuccessful())
        self.assertEqual((result.testsRun, result.subtests), (1, 2))
        self.assertIn("value=2", stream.getvalue())
        self.assertEqual(len(result.timings), 1)

    def test_explicit_selection_and_listing_do_not_run_test_lifecycle(self):
        example = self.cases[0]
        with patch.object(runner, "read_config", return_value=self.config), \
                patch.object(runner, "discover", return_value=self.cases), \
                patch.object(runner, "validate_config", return_value={"unit": 5}), \
                patch.object(example, "run", side_effect=AssertionError("must not run")), \
                patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(runner.main(["--test", "sample.unit.test_one", "--list"]), 0)
            self.assertIn("selected=1/5", output.getvalue())
            self.assertEqual(runner.main(["--test", "sample.unit.test_one.Sample.test_ok", "--list"]), 0)
            self.assertEqual(output.getvalue().count("selected=1/5"), 2)
        with patch.object(runner, "read_config", return_value=self.config), \
                patch.object(runner, "discover", return_value=self.cases), \
                patch.object(runner, "validate_config", return_value={"unit": 5}), \
                patch("sys.stderr", new_callable=io.StringIO):
            self.assertEqual(runner.main(["--test", "does_not_exist"]), 2)


if __name__ == "__main__":
    unittest.main()
