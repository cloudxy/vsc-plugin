"""Project/run fixture with real snapshots; unrelated creative QA is isolated."""
import json
from pathlib import Path

from _paths import SCRIPTS  # noqa: F401
import vsc_artifacts as artifacts
import vsc_state as state_module
import vsc_audio_run as audio_run
import vsc_production as production


class FixedRunFixture:
    """Real state/profile and immutable file snapshots; upstream content QA is isolated."""
    def __init__(self, project):
        self.project = Path(project)
        self.project.mkdir(parents=True, exist_ok=True)
        profile = {"profile_id": "vsc.synthetic-run", "version": "1", "contract_policy": "production-v2",
                   "stages": [{"id": "animatic", "required": ["vsc.animatic"]}, {"id": "production", "required": []}]}
        self.state = {"schema_version": state_module.SCHEMA, "project_id": "test-project", "title": "Synthetic run fixture",
                      "profile_id": profile["profile_id"], "profile_version": profile["version"], "profile_snapshot": profile,
                      "profile_sha256": state_module.profile_digest(profile), "revision": 0, "objects": [], "sources": [],
                      "artifacts": [], "events": [], "decisions": [], "owner": "synthetic fixture reviewer"}
        self.write_state()

    def write_state(self):
        state_module.write_json(self.project / "vsc.json", self.state)

    def read_state(self):
        self.state = state_module.project_state(self.project)
        return self.state

    def register(self, kind, data, deps=(), status="approved", stage="production"):
        self.read_state()
        identifier = f"A-{len(self.state['artifacts']) + 1:04d}"
        source = self.project / (identifier + "-source.json")
        source.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
        path, sha = artifacts.snapshot(self.project, source, identifier)
        item = {"id": identifier, "type": kind, "stage": stage, "scope": "project", "path": path, "sha256": sha,
                "status": status, "decision": {"by": "synthetic fixture reviewer", "status": status},
                "depends_on": [d["id"] for d in deps], "dependency_versions": {d["id"]: d["sha256"] for d in deps}}
        self.state["artifacts"].append(item)
        self.write_state()
        return item

    def validator(self, project, state, item, **kwargs):
        """Keep approval/hash/dependency checks real while excluding unrelated story contracts."""
        errors = []
        if kwargs.get("require_approved", True) and item.get("status") != "approved":
            errors.append("synthetic fixture is not approved")
        path = Path(project) / item["path"]
        if not path.is_file() or artifacts.digest(path) != item["sha256"]:
            errors.append("synthetic fixture snapshot has changed")
        for identifier in item.get("depends_on", []):
            dependency = next((a for a in state["artifacts"] if a["id"] == identifier), None)
            if not dependency or dependency["sha256"] != item["dependency_versions"].get(identifier):
                errors.append("synthetic fixture dependency has changed")
            elif dependency["status"] != "approved":
                errors.append("synthetic fixture dependency is not approved")
        return errors

    def audio_run(self, text="Synthetic speech", name="voice"):
        request = {"kind": "speech", "argv": ["--name", name, "--text", text, "--speaker", "synthetic-speaker", "--max-chars", "100"]}
        _, _, binding, operation, bound = audio_run.prepare(self.project, request)
        data = {"format": "vsc.production-run/v1", "project_id": self.state["project_id"], "scope": "project",
                "audio_request": {**request, "binding": binding}, "plan_sha256": production.ark.digest_json(binding),
                "approved_inputs": [{"id": "synthetic-input", "sha256": "0" * 64}], "review_after": [], "operations": {operation: bound}}
        return self.register("vsc.production_run", data), data, binding, operation, bound
