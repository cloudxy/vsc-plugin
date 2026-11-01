"""Application lifespan owns consumers; original queues own business state."""
from vsc.assets.resource_service import ResourceError


class ExecutionRuntime:
    def __init__(self, service, *, enabled=False, generation=None, preview=None, first_cut=None):
        self.service, self.enabled = service, enabled
        self.generation, self.preview = generation, preview
        self.first_cut = first_cut
        self.error = None

    def start(self):
        if not self.enabled:
            return self
        if self.service is None or self.service.storage is None:
            self.error = "storage_not_configured"
            return self
        from vsc.production.runtime import GenerationRuntime
        from vsc.post.edit_preview import EditPreviewWorker
        from vsc.post.first_cut_worker import FirstCutWorker
        from vsc.configuration import get_config
        self.generation = self.generation or GenerationRuntime(self.service,
            workers=int(get_config("VSC_GENERATION_WORKERS", 4)),
            project_concurrency=int(get_config("VSC_GENERATION_PROJECT_CONCURRENCY", 4)),
            provider_concurrency=int(get_config("VSC_GENERATION_PROVIDER_CONCURRENCY", 4)))
        self.preview = self.preview or EditPreviewWorker(self.service.store, self.service.storage)
        self.service.edit_preview_worker = self.preview
        self.first_cut = self.first_cut or FirstCutWorker(self.service.store, self.service.storage)
        self.service.first_cut_worker = self.first_cut
        self.generation.start()
        self.preview.start()
        self.first_cut.start()
        return self

    def status(self):
        return {
            "enabled": self.enabled, "error": self.error,
            "generation": self.generation.health() if self.generation else {
                "available": False, "status": "unavailable", "accepting_submissions": False},
            "edit_preview": self.preview.status() if self.preview else {"running": False, "available": False},
            "first_cut": self.first_cut.status() if self.first_cut else {"running": False, "available": False},
            "scope": "application",
            "message": ("后台仅执行已有授权的任务；暂停不会取消已提交的远端任务。"
                        if self.enabled else "本次服务只读，后台制作未启动。"),
        }

    def control(self, action):
        if not self.enabled or self.generation is None or self.preview is None:
            raise ResourceError("本次服务未启用后台执行", "runtime_unavailable", 409)
        if action == "pause":
            self.generation.stop_new_submissions()
            self.preview.stop()
            if self.first_cut:
                self.first_cut.stop()
        elif action == "resume":
            self.generation.resume_submissions()
            self.preview.start()
            if self.first_cut:
                self.first_cut.start()
        else:
            raise ResourceError("选择暂停后续任务或继续处理", "invalid_runtime_action")
        return self.status()

    def stop(self):
        if self.generation:
            self.generation.stop()
        if self.preview:
            self.preview.stop()
        if self.first_cut:
            self.first_cut.stop()
        return self.status()

    def has_live_workers(self):
        state = self.status()
        return bool(state["generation"]["available"] or state["edit_preview"]["running"]
                    or state["edit_preview"].get("finishing") or state["first_cut"]["running"]
                    or state["first_cut"].get("finishing"))
