"""Lifespan-owned consumer of persistent edit export requests."""
import tempfile
import threading

from vsc.post.edit_preview import EditPreviewWorker
from vsc.post.edit_workspace import FirstCutRenderer
from vsc.assets.resource_service import ResourceError


class FirstCutWorker(EditPreviewWorker):
    """Reuse the local worker lifecycle/heartbeat health; own the edit queue."""
    def __init__(self, store, storage, renderer=None, **kw):
        from vsc.adapters.persistence.postgres.editor_workspace import EditorWorkspaceRepository
        super().__init__(store, storage, converter=renderer or FirstCutRenderer(), **kw)
        self.repository = EditorWorkspaceRepository(store)
        self.worker_id = self.worker_id.replace("caption-preview-", "first-cut-")

    def run_once(self, project_id=None):
        if not self.converter.capabilities()["available"]:
            return None
        job = self.repository.claim(self.worker_id, project_id, self.lease_seconds)
        if job is None:
            return None
        stop = threading.Event()
        cancelled = threading.Event()
        def heartbeat():
            while not stop.wait(min(1, max(.1, self.lease_seconds / 3))):
                try:
                    if not self.repository.heartbeat(job, self.worker_id, self.lease_seconds):
                        cancelled.set();return
                except Exception:
                    cancelled.set();return
        pulse = threading.Thread(target=heartbeat, daemon=True)
        pulse.start()
        try:
            fixed = self.repository.prepare(job, self.worker_id)
            paths = {}
            for item in fixed["inputs"]:
                location = next((l for l in item["locations"] if l["storage"] == "local" and l.get("available", True)), None)
                if location is None:
                    raise ResourceError("剪辑素材缺少受控本地副本", "edit_input_missing")
                paths[item["clip_key"]] = {"path": self.storage.verify(location["object_key"], item["blob_sha256"]), "modality": item["modality"]}
            with tempfile.TemporaryDirectory(prefix="vsc-first-cut-") as directory:
                render_options = {'professional_context':fixed['professional_context']} if fixed.get('professional_context') else {}
                output, receipt = self.converter.render(fixed["document"], paths, directory, cancelled=cancelled.is_set, **render_options)
                if cancelled.is_set():raise ResourceError('合成取消或原租约已失效','edit_cancel_requested',409)
                receipt["edit_sha256"] = fixed["edit_sha256"]
                with output.open("rb") as stream:
                    staged = self.storage.stage_upload(stream, "first-cut.mp4")
                blob = self.storage.commit_upload(staged["staged_upload"])
                return self.repository.finish(job, self.worker_id, blob, receipt)
        except Exception as error:
            return self.repository.fail(job, self.worker_id, error)
        finally:
            stop.set()
            pulse.join(timeout=1)
