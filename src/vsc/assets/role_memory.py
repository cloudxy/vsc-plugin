"""Role memory application interface and session-bound human decisions."""
from dataclasses import dataclass
import secrets

_SESSION_PROOF = object()


@dataclass(frozen=True)
class HumanMemoryDecision:
    actor: str
    confirmation_id: str
    _proof: object


def verified_memory_decision(actor):
    """Trusted HTTP adapter calls this only after its session/CSRF guard."""
    return HumanMemoryDecision(actor, secrets.token_urlsafe(32), _SESSION_PROOF)


def require_human_memory_decision(proof, actor):
    from vsc.assets.resource_service import ResourceError
    if not isinstance(proof, HumanMemoryDecision) or proof._proof is not _SESSION_PROOF or proof.actor != actor:
        raise ResourceError("记忆决定需要面板中已验证的人工会话；--by 或自报 human 无法批准", "human_confirmation_required", 403)


class RoleMemoryService:
    def list_role_memories(self, project_id, **filters):
        return self.store.list_role_memories(project_id, **filters)

    def retrieve_role_memories(self, project_id, **query):
        return self.store.retrieve_role_memories(project_id, **query)

    def get_role_dispatch(self, project_id, dispatch_id):
        return self.store.get_role_dispatch(project_id, dispatch_id)

    def resume_role_summary(self, project_id, dispatch_id, role):
        return self.store.resume_role_summary(project_id, dispatch_id, role)

    def propose_role_memory(self, project_id, payload, **kw):
        return self._write("propose_role_memory", project_id, payload, **kw)

    def decide_role_memory(self, project_id, payload, *, human_decision=None, **kw):
        require_human_memory_decision(human_decision, kw.get("actor"))
        self._validate_write(payload, **kw)
        return self.store.decide_role_memory(project_id, payload,
            confirmation_id=human_decision.confirmation_id, **kw)

    def create_role_dispatch(self, project_id, payload, **kw):
        return self._write("create_role_dispatch", project_id, payload, **kw)

    def consume_role_dispatch(self, project_id, payload, **kw):
        return self._write("consume_role_dispatch", project_id, payload, **kw)

    def return_role_dispatch(self, project_id, payload, **kw):
        return self._write("return_role_dispatch", project_id, payload, **kw)
