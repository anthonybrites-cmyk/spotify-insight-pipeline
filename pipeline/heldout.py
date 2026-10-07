"""Held-out check of the fallback decision (no model calls here).

The golden set influenced the fallback decision (Jev 1/7 vs Claude 5/7 in the low band), so the
decision is re-checked on fresh reviews the golden set never touched: a deterministic sample of
texts from a finished run whose Jev confidence was below the fallback threshold. The sheet has
the golden sheet's columns with every label blank; the human fills it in without seeing any
model's answer. Golden review IDs are excluded.
"""

import csv
import hashlib
from pathlib import Path

from .checker import FIELDS, csv_rows
from .enrich import completed_results, current_config, fallback_settings
from .fallback import min_confidence
from .golden import load_ids
from .store import read_json, read_jsonl, write_json

SEED = "spotify-insight-heldout-v1"
LABEL_COLUMNS = ("topic", "intent", "sentiment", "severity", "entities", "evidence_quote", "needs_review",
                 "ambiguous", "alternative_labels", "label_notes")


def build_sheet(run_dir, n, out, exclude):
    run_dir = Path(run_dir)
    manifest = read_json(run_dir / "run_manifest.json")
    config = current_config(run_dir, None)
    threshold = (fallback_settings(run_dir) or {}).get("threshold", 0.5)
    done = completed_results(run_dir, config)
    low = {u for u, row in done.items() if min_confidence(row) < threshold}
    excluded = load_ids(exclude)
    first_id = {}
    for s in read_jsonl(run_dir / "ingest" / "sources.jsonl"):
        if s["unit"] in low and s["unit"] not in first_id and s["review_id"] not in excluded:
            first_id[s["unit"]] = s["review_id"]
    ranked = sorted(first_id.values(), key=lambda rid: hashlib.sha256(f"{SEED}:{rid}".encode()).hexdigest())
    chosen = set(ranked[:n])
    rows = [r for r in csv_rows(manifest["input"]) if r["review_id"] in chosen]
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(FIELDS) + list(LABEL_COLUMNS), lineterminator="\n")
        writer.writeheader()
        for r in rows:
            writer.writerow({**{k: r[k] for k in FIELDS}, **{k: "" for k in LABEL_COLUMNS}})
    write_json(out.with_suffix(".meta.json"), {
        "run_id": manifest["run_id"], "label_config": config, "threshold": threshold, "seed": SEED,
        "low_confidence_texts": len(low), "eligible": len(first_id), "sampled": len(rows),
        "method": "lowest sha256(seed + ':' + review_id) among low-confidence texts (first review ID per text), "
                  "golden IDs excluded"})
    return out, len(rows), len(first_id)
