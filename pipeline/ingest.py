"""Stage 1: ingest. Read every row, hash it, quarantine empty texts, group exact-duplicate texts.

Handoffs written to <run>/ingest/:
  sources.jsonl          one line per source row: review_id, source_sha256, unit (text hash) or null
  units.jsonl            one line per distinct nonempty text: unit, text, original_id, member_count
  ingestion.json         full-file deterministic profile from the course helper (grading export)
  ingestion_report.json  profile + missing values, text-length distribution, expected-value checks
  data_manifest.json     input identity (path, bytes, SHA-256) and dataset provenance
  summary.json           counts and input identity
"""

from .checker import FIELDS, csv_rows, profile, row_sha
from . import language
from .config import FULL_CSV_SHA256
from .store import JsonlAppender, read_json, sha256_file, sha256_text, write_json

# Published facts for the course's full file (dataset README / manifest.json).
FULL_EXPECTED = {"records": 660622, "empty_review_text": 13, "missing_app_version": 159701,
                 "duplicate_review_ids": 0, "distinct_nonempty_texts": 484189}
LENGTH_BUCKETS = [0, 1, 11, 21, 51, 101, 201, 501, 1001]


def percentile(sorted_values, q):
    if not sorted_values:
        return None
    return sorted_values[min(len(sorted_values) - 1, int(q * len(sorted_values)))]


def run(input_csv, run_dir, log=print):
    out = run_dir / "ingest"
    input_sha = sha256_file(input_csv)
    existing = read_json(out / "summary.json")
    if (existing and existing.get("input_sha256") == input_sha and existing.get("complete")
            and existing.get("language_version") == language.version()):
        log(f"ingest: already complete for {input_sha[:12]}; reusing saved handoff")
        return existing
    for name in ("sources.jsonl", "units.jsonl"):
        (out / name).unlink(missing_ok=True)

    sources = JsonlAppender(out / "sources.jsonl")
    units = {}
    order = []
    ids = set()
    rows = empty = duplicate_ids = 0
    missing = {k: 0 for k in FIELDS}
    lengths = []
    for row in csv_rows(input_csv):
        rows += 1
        for k in FIELDS:
            missing[k] += not row[k].strip()
        lengths.append(len(row["review_text"]))
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
            units[unit] = {"unit": unit, "text": text, "original_id": rid, "member_count": 0,
                           "language_group": language.group(text)}
            order.append(unit)
        units[unit]["member_count"] += 1
        sources.write({"review_id": rid, "source_sha256": row_sha(row), "unit": unit})
    sources.close()
    unit_file = JsonlAppender(out / "units.jsonl")
    for unit in order:
        unit_file.write(units[unit])
    unit_file.close()

    log("ingest: profiling full file with the course helper")
    course_profile = profile(input_csv)
    write_json(out / "ingestion.json", course_profile)
    lengths.sort()
    buckets = {}
    for lo, hi in zip(LENGTH_BUCKETS, LENGTH_BUCKETS[1:] + [None]):
        label = f"{lo}+" if hi is None else f"{lo}-{hi - 1}"
        buckets[label] = sum(1 for n in lengths if n >= lo and (hi is None or n < hi))
    lang_distinct, lang_rows = {}, {}
    for unit in order:
        g = units[unit]["language_group"]
        lang_distinct[g] = lang_distinct.get(g, 0) + 1
        lang_rows[g] = lang_rows.get(g, 0) + units[unit]["member_count"]
    observed = {"records": rows, "empty_review_text": empty, "missing_app_version": missing["app_version"],
                "duplicate_review_ids": duplicate_ids, "distinct_nonempty_texts": len(order)}
    is_full = input_sha == FULL_CSV_SHA256
    report = {"input_sha256": input_sha, "input_bytes": input_csv.stat().st_size, "course_profile": course_profile,
              "missing_values_by_field": missing,
              "review_text_length_chars": {"min": lengths[0] if lengths else None, "median": percentile(lengths, .5),
                                           "p90": percentile(lengths, .9), "p99": percentile(lengths, .99),
                                           "max": lengths[-1] if lengths else None, "histogram": buckets},
              "observed": observed,
              "language_groups": {"method": f"deterministic heuristic (pipeline/language.py, version {language.version()})",
                                  "distinct_texts": dict(sorted(lang_distinct.items())),
                                  "rows": dict(sorted(lang_rows.items()))},
              "expected_checks": ({k: {"expected": v, "observed": observed[k], "ok": observed[k] == v}
                                   for k, v in FULL_EXPECTED.items()} if is_full else "not the course full file"),
              "quarantine_rule": "review_text empty after stripping whitespace -> quarantined, reason empty_review_text",
              "missing_app_version_rule": "kept and classified; app_version is never a model input",
              "row_hash": "check_submission.row_sha: SHA-256 of compact JSON of the six original fields, no normalization"}
    write_json(out / "ingestion_report.json", report)
    write_json(out / "data_manifest.json", {
        "input_path": str(input_csv), "input_bytes": input_csv.stat().st_size, "input_sha256": input_sha,
        "is_course_full_file": is_full, "fields": list(FIELDS),
        "dataset": {"source": "BwandoWando, 3.4 Million Spotify Google Store Reviews, Kaggle, version 2 (CC0)",
                    "course_extract_window": "2022-05-17 inclusive to 2023-11-17 exclusive",
                    "full_csv_sha256": FULL_CSV_SHA256}})
    summary = {"input_path": str(input_csv), "input_sha256": input_sha, "input_bytes": input_csv.stat().st_size,
               "rows": rows, "empty_review_text": empty, "nonempty": rows - empty,
               "distinct_nonempty_texts": len(order), "duplicate_review_ids": duplicate_ids,
               "exact_duplicate_rows_reusable": rows - empty - len(order), "language_version": language.version(),
               "language_groups_distinct": dict(sorted(lang_distinct.items())), "complete": True}
    write_json(out / "summary.json", summary)
    log(f"ingest: {rows} rows, {empty} empty quarantined, {len(order)} distinct texts")
    return summary


def load_units(run_dir):
    """Distinct texts to classify. Under a saved scope (ingest/scope.json) only in-scope texts are returned,
    each represented by its first sampled review ID so cache provenance always points at a sampled record."""
    from .store import read_json, read_jsonl
    units = list(read_jsonl(run_dir / "ingest" / "units.jsonl"))
    scope = read_json(run_dir / "ingest" / "scope.json")
    if scope is None:
        return units
    rep = scope["representative"]
    return [{**u, "original_id": rep[u["unit"]]} for u in units if u["unit"] in rep]


def load_sources(run_dir):
    from .store import read_jsonl
    return list(read_jsonl(run_dir / "ingest" / "sources.jsonl"))
