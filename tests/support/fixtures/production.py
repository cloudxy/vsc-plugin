"""Offline queue fixture shared by production, formal runs and inspection tests."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
from unittest import mock

from support.paths import ROOT
from support.fixtures.media import production_media
import vsc.adapters.providers.volc_ark.api as A
import vsc.production.production as P


class ProductionFixture:
    """Mixin for TestCase lifecycle; immutable media is shared, project state is private."""
    @classmethod
    def setUpClass(cls):
        for kind, content in production_media().items():
            setattr(cls, kind, content)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        (self.project / "vsc.json").write_text(json.dumps({"project_id": "test-project"}))
        for name, template in (("bible.json", "asset-bible.json"), ("state.json", "scene-state.json")):
            value = json.loads((ROOT / "templates" / template).read_text())
            value["project_id"] = "test-project"
            (self.project / name).write_text(json.dumps(value))
        self.batch = {"format": P.FORMAT, "project_id": "test-project", "id": "batch-1", "max_remote_jobs": 3,
                      "max_attempts": 3, "budget": {"max_images": 1, "max_video_seconds": 10}, "jobs": [
                          {"id": "image", "kind": "image", "depends_on": [], "args": {
                              "out": "takes", "name": "image", "prompt": "--literal $(do-not-run)", "purpose": "asset"}},
                          self.video("first", "SH-001", ["image"], {"job": "image", "output": "image"}),
                          self.video("second", "SH-002", ["first"], {"job": "first", "output": "last_frame"})]}
        self.calls, self.argv, self.fail_download = [], [], None

    def video(self, identifier, shot, dependencies, first):
        return {"id": identifier, "kind": "video", "depends_on": dependencies, "args": {
            "out": "takes", "name": identifier, "prompt": "走向门口", "shot": shot, "bible": {"path": "bible.json"},
            "state": {"path": "state.json"}, "first_frame_ref": first, "duration": 5, "no_audio": True}}

    def fake_call(self, path, payload=None):
        self.calls.append((path, payload))
        if path == "/images/generations":
            return {"data": [{"url": "https://fake/image"}], "usage": {"images": 1}}
        if path == "/contents/generations/tasks":
            return {"id": "task-" + str(sum(item[0] == path for item in self.calls))}
        return {"status": "succeeded", "content": {"video_url": "https://fake/" + path.split("/")[-1],
                                                      "last_frame_url": "https://fake/last-" + path.split("/")[-1]},
                "usage": {"seconds": 5}, "duration": 5}

    def fake_download(self, url, target):
        if self.fail_download and self.fail_download in url:
            self.fail_download = None
            raise A.ArkError("offline interrupted download")
        target.write_bytes(self.mp4 if target.suffix == ".mp4" else self.jpeg if target.suffix == ".jpeg" else self.png)

    def runner(self, argv, script=None):
        self.argv.append(argv)
        with mock.patch.object(A, "api_key", return_value="offline-test-key"), \
                mock.patch.object(A, "call", side_effect=self.fake_call), mock.patch.object(A, "download", side_effect=self.fake_download):
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = A.main(argv)
        if code:
            raise RuntimeError("adapter failed")

    def plan(self, batch=None):
        return P.build_plan(self.project, batch or self.batch)

    def run_queue(self, plan=None):
        plan = plan or self.plan()
        return P.run(self.project, plan, plan["plan_sha256"], self.runner)
