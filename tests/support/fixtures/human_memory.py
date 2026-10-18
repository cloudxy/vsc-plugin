"""Synthetic trusted-adapter decisions; actor labels alone are never approvals."""
from vsc.assets.role_memory import verified_memory_decision
from vsc.project.role_runtime_legacy import content_sha, mutate_memory
from vsc.project.state import project_state
import uuid


def decide_legacy_memory(project, memory_id, actor="test-human", outcome="approved"):
    state = project_state(project)
    item = next(m for m in state["memories"] if m["id"] == memory_id)
    return mutate_memory(project, "decide", {"version_id": memory_id, "content_sha256": content_sha(item),
        "outcome": outcome, "reason": "测试的可信适配器确认"}, actor=actor,
        expected_revision=state["revision"], idempotency_key=uuid.uuid4().hex,
        human_decision=verified_memory_decision(actor))
