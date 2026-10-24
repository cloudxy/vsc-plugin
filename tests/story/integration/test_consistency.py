"""CLI contract dispatch and invalid-record reporting for continuity."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from support.paths import ROOT, SCRIPTS
from support.fixtures.consistency import RecordFixture


class RecordTest(RecordFixture, unittest.TestCase):
    def test_check_reports_invalid_record_before_indexing(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "malformed.json"
            record = self.record()
            record["kind"] = "image"
            record["inputs"].pop("first_frame", None)
            record["outputs"][0].pop("sha256")
            path.write_text(json.dumps(record), "utf-8")
            result = subprocess.run([sys.executable, "-B", str(SCRIPTS / "story/consistency.py"), "check",
                                     "--bible", str(ROOT / "templates/asset-bible.json"),
                                     "--state", str(ROOT / "templates/scene-state.json"), "--record", str(path)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn("INVALID:", result.stderr)
            self.assertIn("sha256", result.stderr)
            self.assertNotIn("Traceback", result.stderr)


class KernelTest(unittest.TestCase):
    def test_world_map_cli_draws_only_declared_coordinates_and_reports_unknown(self):
        import xml.etree.ElementTree as ET
        from support.fixtures.consistency import state
        value=state();scene=value['scenes'][0]
        scene['spatial']={'frame':'floor','unit':'m'}
        scene['baseline']['entities']['主角']['position']={'frame':'floor','x':0,'y':0}
        scene['baseline']['entities']['信封']['position']={'frame':'floor','x':1,'y':0}
        scene['shots'][0]['camera']={'spatial':{'frame':'floor','x':0,'y':-2,'axis':['主角','信封'],'mirrored':False}}
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'state.json';path.write_text(json.dumps(value,ensure_ascii=False))
            command=[sys.executable,'-B',str(SCRIPTS/'story/consistency.py'),'state','map',str(path),'SH-001']
            result=subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            diagram=ET.fromstring(result.stdout)
            self.assertEqual(len(diagram.findall('{http://www.w3.org/2000/svg}circle')),3)
            self.assertIn('world schematic',result.stdout)
            scene['baseline']['entities']['主角']['position']='旧文本位置'
            scene['baseline']['entities']['信封']['position']='旧文本位置'
            path.write_text(json.dumps(value,ensure_ascii=False))
            result=subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(result.returncode,1)
            self.assertIn('依据不足',result.stderr)

    def test_contracts_dispatch_through_the_kernel(self):
        for fmt, template in (("vsc.asset-bible/v1", "asset-bible.json"), ("vsc.scene-state/v1", "scene-state.json"),
                              ("vsc.generation-record/v1", "generation-record.json")):
            result = subprocess.run([sys.executable, "-B", str(SCRIPTS / "kernel/catalog.py"), "contract", "validate", fmt, str(ROOT / "templates" / template)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
