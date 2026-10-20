"""Human proof for explicit provider receipt reconciliation, never resubmission."""
from dataclasses import dataclass
import secrets

_SESSION_PROOF = object()


@dataclass(frozen=True)
class HumanGenerationRecovery:
    actor: str
    confirmation_id: str
    _proof: object


def verified_generation_recovery(actor):
    """Only a trusted adapter after verified session and explicit confirmation."""
    return HumanGenerationRecovery(actor, secrets.token_urlsafe(32), _SESSION_PROOF)


def require_generation_recovery(proof, actor):
    from vsc.assets.resource_service import ResourceError
    if (not isinstance(proof, HumanGenerationRecovery) or proof._proof is not _SESSION_PROOF
            or proof.actor != actor):
        raise ResourceError("生成对账需要已验证人工会话及明确决定", "human_confirmation_required", 403)
