"""Fresh Vendor policy dictionaries for isolated tests."""


def refresh_policy(**changes):
    policy = {
        "mode": "candidate_review",
        "scheduler": "manual",
        "automatic_adoption": False,
        "analysis_required_for": ["changed_referenced_skill", "new_skill", "deleted_referenced_skill"],
        "candidate_retention_days": 90,
        "max_candidate_snapshots_per_source": 3,
    }
    policy.update(changes)
    return policy
