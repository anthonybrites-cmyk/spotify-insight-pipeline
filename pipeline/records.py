"""Assemble exactly one final record per source ID from the saved stage handoffs."""

from .enrich import completed_results
from .group import load_assignments
from .ingest import load_sources
from .rubric import label_config as enrich_config
from .store import read_json, read_jsonl

LABEL_FIELDS = ("topic", "intent", "sentiment", "severity", "entities", "evidence_quote", "needs_review")


def build(run_dir, jev_model):
    config = enrich_config(jev_model)
    done = completed_results(run_dir, config)
    failures = {}
    for f in read_jsonl(run_dir / "enrich" / "failures.jsonl"):
        if f["label_config"] == config:
            failures[f["unit"]] = f
    disagreements = set(read_json(run_dir / "verify" / "disagreement_units.json", []))
    assignments, _ = load_assignments(run_dir) if (run_dir / "group" / "issues.json").exists() else ({}, None)

    records = []
    for s in load_sources(run_dir):
        base = {"review_id": s["review_id"], "source_sha256": s["source_sha256"]}
        if s["unit"] is None:
            records.append({**base, "status": "quarantined", "reason": s["quarantine_reason"], "attempts": 0})
            continue
        row = done.get(s["unit"])
        if row is None:
            failure = failures.get(s["unit"])
            if failure:
                records.append({**base, "status": "quarantined", "reason": f"enrich_failed: {failure['reason']}",
                                "attempts": failure.get("attempts", 0)})
            else:  # never attempted: the run is incomplete, and this row is disclosed as such
                records.append({**base, "status": "quarantined", "reason": "pending_not_processed", "attempts": 0})
            continue
        record = {**base, "status": "completed", **{k: row[k] for k in LABEL_FIELDS}, "label_config": config}
        if s["unit"] in disagreements:
            record["needs_review"] = True
        if s["review_id"] != row["review_id"]:
            record["cache_source_id"] = row["review_id"]
        record["attempts"] = 0 if "cache_source_id" in record else row.get("attempts", 1)
        if record["intent"] in ("complaint", "cancellation"):
            record["issue_id"] = assignments.get(s["unit"])
        records.append(record)
    return records
