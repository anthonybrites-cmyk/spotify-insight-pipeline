"""Stage 1: ingest. Read every row, hash it, quarantine empty texts, group exact-duplicate texts.

Handoffs written to <run>/ingest/:
  sources.jsonl   one line per source row: review_id, source_sha256, unit (text hash) or null
  units.jsonl     one line per distinct nonempty text: unit, text, original_id, member_count
  ingestion.json  full-file deterministic profile from the course helper
  summary.json    counts and input identity
"""

from .checker import csv_rows, profile, row_sha
from .store import JsonlAppender, read_json, sha256_file, sha256_text, write_json


def run(input_csv, run_dir, log=print):
    out = run_dir / "ingest"
    input_sha = sha256_file(input_csv)
    existing = read_json(out / "summary.json")
    if existing and existing.get("input_sha256") == input_sha and existing.get("complete"):
        log(f"ingest: already complete for {input_sha[:12]}; reusing saved handoff")
        return existing
    for name in ("sources.jsonl", "units.jsonl"):
        (out / name).unlink(missing_ok=True)

    sources = JsonlAppender(out / "sources.jsonl")
    units = {}
    order = []
    ids = set()
    rows = empty = duplicate_ids = 0
    for row in csv_rows(input_csv):
        rows += 1
        rid = row["review_id"]
        if rid in ids:
            duplicate_ids += 1
            raise ValueError(f"duplicate review_id {rid}: the contract needs one record per ID")
        ids.add(rid)
        text = row["review_text"]
        if not text.strip():
            empty += 1
            sources.write({"review_id": rid, "source_sha256": row_sha(row), "unit": None,
                           "quarantine_reason": "empty_review_text"})
            continue
        unit = sha256_text(text)
        if unit not in units:
            units[unit] = {"unit": unit, "text": text, "original_id": rid, "member_count": 0}
            order.append(unit)
        units[unit]["member_count"] += 1
        sources.write({"review_id": rid, "source_sha256": row_sha(row), "unit": unit})
    sources.close()
    unit_file = JsonlAppender(out / "units.jsonl")
    for unit in order:
        unit_file.write(units[unit])
    unit_file.close()

    log("ingest: profiling full file with the course helper")
    write_json(out / "ingestion.json", profile(input_csv))
    summary = {"input_path": str(input_csv), "input_sha256": input_sha, "input_bytes": input_csv.stat().st_size,
               "rows": rows, "empty_review_text": empty, "nonempty": rows - empty,
               "distinct_nonempty_texts": len(order), "duplicate_review_ids": duplicate_ids,
               "exact_duplicate_rows_reusable": rows - empty - len(order), "complete": True}
    write_json(out / "summary.json", summary)
    log(f"ingest: {rows} rows, {empty} empty quarantined, {len(order)} distinct texts")
    return summary


def load_units(run_dir):
    from .store import read_jsonl
    return list(read_jsonl(run_dir / "ingest" / "units.jsonl"))


def load_sources(run_dir):
    from .store import read_jsonl
    return list(read_jsonl(run_dir / "ingest" / "sources.jsonl"))
