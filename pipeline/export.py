"""Export the compact grading folder described in GRADING_CONTRACT.md."""

import csv
import gzip
import io
import shutil

from .checker import FIELDS  # noqa: F401  (documents that hashing follows the course helper)
from .store import canonical, read_json, read_jsonl, sha256_file, write_json

RECORD_ORDER = ("review_id", "source_sha256", "status", "reason", "topic", "intent", "sentiment", "severity",
                "entities", "evidence_quote", "needs_review", "label_config", "cache_source_id", "attempts")


def contract_record(r):
    return {k: r[k] for k in RECORD_ORDER if k in r}


def claims_csv(claims):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["claim_id", "issue_id", "metric", "value"], lineterminator="\n")
    writer.writeheader()
    writer.writerows(claims)
    return buf.getvalue()


def write_gz_jsonl(path, rows):
    with gzip.open(path, "wt", encoding="utf-8", compresslevel=6) as f:
        for row in rows:
            f.write(canonical(row) + "\n")


def run(run_dir, grading_dir, records, claims, allow_fake=False, log=print, results_dir=None):
    configs = {r["label_config"] for r in records if r["status"] == "completed"}
    if any("fake" in c for c in configs) and not allow_fake:
        raise SystemExit("refusing to export: records come from the offline fake provider (tests only)")
    enrich_state = read_json(run_dir / "enrich" / "state.json", {})
    snapshots = run_dir / "enrich" / "checkpoints"
    before_name = enrich_state.get("first_stop_snapshot")
    after_path = snapshots / "enrich_complete.json"
    grading_dir.mkdir(parents=True, exist_ok=True)
    for stale in ("records.jsonl", "calls.jsonl", "records.jsonl.gz", "calls.jsonl.gz"):
        (grading_dir / stale).unlink(missing_ok=True)

    ingest_summary = read_json(run_dir / "ingest" / "summary.json")
    verify = read_json(run_dir / "verify" / "report.json")
    group = read_json(run_dir / "group" / "summary.json")
    run_json = {
        "version": "a5-audit-v1",
        "analysis_count": ingest_summary["rows"],
        "analysis_sha256": ingest_summary["input_sha256"],
        "classification_input_fields": ["review_text"],
        "allow_multi_issue": False,
        "input_file": ingest_summary["input_path"].rsplit("/", 1)[-1],
        "declared_scope": {"records": ingest_summary["rows"], "classify_nonempty": ingest_summary["nonempty"],
                           "quarantine_empty": ingest_summary["empty_review_text"],
                           "distinct_texts_sent_to_model": ingest_summary["distinct_nonempty_texts"]},
        "label_configs": sorted(configs),
        "stages": ["ingest", "enrich", "verify", "group", "rank", "recommend"],
        "verification": {"label_config": (verify or {}).get("verify_label_config"),
                         "sample": (verify or {}).get("strata", {}).get("all", {}).get("n")},
        "grouping": {"assign_label_config": (group or {}).get("assign_label_config")},
        "resume_snapshots": {"before": before_name, "after": after_path.name if after_path.exists() else None},
    }
    write_json(grading_dir / "run.json", run_json)
    shutil.copyfile(run_dir / "ingest" / "ingestion.json", grading_dir / "ingestion.json")
    write_gz_jsonl(grading_dir / "records.jsonl.gz", (contract_record(r) for r in records))
    write_gz_jsonl(grading_dir / "calls.jsonl.gz", read_jsonl(run_dir / "calls.jsonl"))
    for name in ("membership.csv", "ranking.csv"):
        shutil.copyfile(run_dir / "rank" / name, grading_dir / name)
    (grading_dir / "claims.csv").write_text(claims_csv(claims), encoding="utf-8")

    if before_name:
        before = read_json(snapshots / before_name)
        write_json(grading_dir / "checkpoint_before.json", {"completed_ids": before["completed_ids"],
                                                            "saved_at": before.get("saved_at"),
                                                            "stop_reason": before.get("stop_reason")})
    else:
        log("export: WARNING no interruption snapshot exists; run the resume demonstration (--stop-after-units)")
    if after_path.exists():
        after = read_json(after_path)
        write_json(grading_dir / "checkpoint_after.json", {"completed_ids": after["completed_ids"],
                                                           "saved_at": after.get("saved_at")})
    for src, dst in (("memo/memo.md", "memo.md"), ("group/issues.json", "issues.json"),
                     ("verify/report.json", "verification_report.json")):
        if (run_dir / src).exists():
            shutil.copyfile(run_dir / src, grading_dir / dst)
    manifest = {p.name: sha256_file(p) for p in sorted(grading_dir.iterdir()) if p.is_file() and p.name != "MANIFEST.json"}
    write_json(grading_dir / "MANIFEST.json", manifest)
    log(f"export: wrote {grading_dir} ({len(records)} records)")
    if results_dir:
        export_results(run_dir, results_dir, records, claims, log)


def export_results(run_dir, out, records, claims, log=print):
    """Human-readable result set named in the assignment brief (separate from the grading adapter)."""
    out.mkdir(parents=True, exist_ok=True)
    enriched_run = {r["unit"]: r for r in read_jsonl(run_dir / "enrich" / "results.jsonl")}
    from .enrich import current_config, final_results
    final = final_results(run_dir, current_config(run_dir, ""))
    units = {s["review_id"]: s["unit"] for s in read_jsonl(run_dir / "ingest" / "sources.jsonl")}
    with gzip.open(out / "enriched.jsonl.gz", "wt", encoding="utf-8") as f:
        for r in records:
            if r["status"] != "completed":
                continue
            diag = enriched_run.get(units[r["review_id"]], {}).get("diagnostics", {})
            f.write(canonical({**r, "jev_confidence": diag.get("confidence"),
                               "severity_rule_applied": diag.get("severity_rule_applied"),
                               "decided_by": final.get(units[r["review_id"]], {}).get("decided_by", "jev")}) + "\n")
    with (out / "quarantine.jsonl").open("w", encoding="utf-8") as f:
        for r in records:
            if r["status"] == "quarantined":
                f.write(canonical(r) + "\n")
    issues = read_json(run_dir / "group" / "issues.json")["issues"]
    members = {}
    for r in records:
        if r["status"] == "completed" and r.get("issue_id"):
            members.setdefault(r["issue_id"], []).append(r["review_id"])
    write_json(out / "issues.json", {iid: {**meta, "member_count": len(members.get(iid, [])),
                                           "member_review_ids": sorted(members.get(iid, []))}
                                     for iid, meta in issues.items()})
    ranking = list(csv.DictReader((run_dir / "rank" / "ranking.csv").open(encoding="utf-8", newline="")))
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["issue_id", "topic", "name", "complaint_count", "severity_sum",
                                             "mean_severity", "priority_score", "rank"], lineterminator="\n")
    writer.writeheader()
    for row in ranking:
        meta = issues[row["issue_id"]]
        writer.writerow({**{k: row[k] for k in ("issue_id", "complaint_count", "severity_sum", "mean_severity",
                                                "priority_score", "rank")}, "topic": meta["topic"], "name": meta["name"]})
    (out / "aggregates.csv").write_text(buf.getvalue(), encoding="utf-8")
    for src, dst in (("rank/ranking.csv", "ranking.csv"), ("rank/membership.csv", "membership.csv"),
                     ("ingest/data_manifest.json", "data_manifest.json"),
                     ("ingest/ingestion_report.json", "ingestion_report.json"), ("run_log.jsonl", "run_log.jsonl"),
                     ("run_summary.json", "run_summary.json"), ("run_manifest.json", "run_manifest.json"),
                     ("memo/memo.md", "memo.md"), ("memo/check.json", "memo_check.json"),
                     ("memo/facts_cited.json", "memo_facts_cited.json"), ("verify/report.json", "verification_report.json"),
                     ("verify/comparisons.json", "verification_comparisons.json"),
                     ("verify/planted_label_test.json", "planted_label_test.json"),
                     ("verify/sample.json", "verification_sample.json"), ("group/summary.json", "group_summary.json")):
        if (run_dir / src).exists():
            shutil.copyfile(run_dir / src, out / dst)
    (out / "claims.csv").write_text(claims_csv(claims), encoding="utf-8")
    log(f"export: wrote results folder {out}")
