"""Review documents shared by rule tests and actual-media integration tests."""
import json
from pathlib import Path

import media_qa as QA


def write_review(root, report, structured=False):
    root = Path(root)
    qa_path = root / "qa.json"
    qa_path.write_text(json.dumps(report), encoding="utf-8")
    review = {"format": QA.REVIEW_FORMAT, "project_id": "sample", "reviewer": "synthetic reviewer",
              "technical_report": qa_path.name, "technical_report_sha256": QA.sha256(qa_path),
              "assessments": {category: {"result": "pass", "evidence": "SH-001 synthetic evidence"}
                              for category in QA.REVIEW_CATEGORIES},
              "run": {"elapsed_seconds": 1, "cost_amount": 0, "currency": "CNY", "failures": []}}
    if structured:
        review.update(evidence_mode="structured", render_sha256=report["render"]["metadata"]["sha256"],
                      scope={"kind": "complete", "start_frame": 0, "end_frame": 30, "delivery_id": "DEL-001"},
                      assessments={category: {"result": "pass", "evidence": [{"start_frame": 0,
                          "end_frame": 30, "shot_id": "SH-001", "segment_id": "shot-1", "note": "synthetic coverage"}]}
                          for category in QA.REVIEW_CATEGORIES})
    path = root / "review.json"
    path.write_text(json.dumps(review), encoding="utf-8")
    return path
