"""Optional classification scope: a seeded random sample of review IDs (the brief accepts >= 100,000).

Ingestion still reads, hashes and profiles every row. Only units (distinct texts) that contain a sampled
review ID are classified. Each such unit is represented by its first *sampled* member in file order, so
every record that reuses the result points (cache_source_id) at a completed, directly classified record.

include_duplicates=False: only the sampled IDs are completed; their exact-duplicate copies outside the
sample are quarantined as out of scope (a clean random sample for the business aggregates).
include_duplicates=True: every copy of a sampled text is completed by exact-text reuse (more coverage at
no extra model cost, but frequently repeated texts are then over-represented in the aggregates).
"""

import hashlib

from .ingest import load_sources
from .store import read_json, write_json

SEED = "spotify-insight-scope-100k-v1"


def build(run_dir, sample_size, include_duplicates, seed=SEED):
    """Select the sample (deterministic) and save ingest/scope.json. Returns the scope dict."""
    path = run_dir / "ingest" / "scope.json"
    settings = {"sample_size": sample_size, "include_duplicates": include_duplicates, "seed": seed,
                "method": "lowest sha256(seed + ':' + review_id) among nonempty rows"}
    existing = read_json(path)
    if existing and existing["settings"] == settings:
        return existing
    sources = load_sources(run_dir)
    nonempty = [s for s in sources if s["unit"] is not None]
    ranked = sorted(nonempty, key=lambda s: hashlib.sha256(f"{seed}:{s['review_id']}".encode()).hexdigest())
    sampled = {s["review_id"] for s in ranked[:sample_size]}
    representative = {}
    for s in sources:  # file order: the first sampled member of each unit represents it
        if s["review_id"] in sampled and s["unit"] not in representative:
            representative[s["unit"]] = s["review_id"]
    scope = {"settings": settings, "sampled_ids": sorted(sampled), "representative": representative}
    write_json(path, scope)
    return scope


def load(run_dir):
    return read_json(run_dir / "ingest" / "scope.json")


def in_scope_record(scope, review_id, unit):
    """Whether this source row is classified under the scope (None scope = everything)."""
    if scope is None or unit is None:
        return unit is not None
    if unit not in scope["representative"]:
        return False
    return scope["settings"]["include_duplicates"] or review_id in set(scope["sampled_ids"])


def describe(scope):
    if scope is None:
        return "full corpus"
    s = scope["settings"]
    return (f"random sample of {s['sample_size']:,} review IDs (seed {s['seed']})"
            + ("; exact duplicates of sampled texts included" if s["include_duplicates"] else ""))
