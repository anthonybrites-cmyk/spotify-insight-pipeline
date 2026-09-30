"""Stage 5: reproducible baseline ranking. Pure code, integer/Decimal arithmetic only.

priority_score = severity_sum = complaint_count x mean_severity (exact).
Order: descending priority_score, then ascending issue_id. Means: 6 dp, half-up.
"""

import csv
import io
from collections import defaultdict

from .checker import mean_string
from .store import read_json, read_jsonl, sha256_text, write_json

RANK_FIELDS = ["rank", "issue_id", "complaint_count", "severity_sum", "mean_severity", "priority_score"]


def compute(members):
    """members: iterable of (issue_id, review_id, severity:int). Returns (membership rows, ranking rows)."""
    pairs, seen = [], set()
    per_issue = defaultdict(list)
    for issue_id, review_id, severity in members:
        if type(severity) is not int or not 1 <= severity <= 5:
            raise ValueError(f"invalid severity for {review_id}: {severity!r}")
        if (issue_id, review_id) in seen:
            raise ValueError(f"duplicate membership {(issue_id, review_id)}")
        seen.add((issue_id, review_id))
        pairs.append((issue_id, review_id))
        per_issue[issue_id].append(severity)
    rows = []
    for issue_id, values in per_issue.items():
        total = sum(values)
        rows.append({"issue_id": issue_id, "complaint_count": len(values), "severity_sum": total,
                     "mean_severity": mean_string(total, len(values)), "priority_score": total})
    rows.sort(key=lambda r: (-r["priority_score"], r["issue_id"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return sorted(pairs), rows


def to_csv(fields, rows):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for r in rows:
        writer.writerow({k: str(r[k]) for k in fields})
    return buf.getvalue()


def run(run_dir, records, log=print):
    """records: final completed records (dicts with review_id, intent, severity, issue_id for complaints)."""
    out = run_dir / "rank"
    members = [(r["issue_id"], r["review_id"], r["severity"]) for r in records
               if r["status"] == "completed" and r["intent"] in ("complaint", "cancellation")]
    pairs, ranking = compute(members)
    membership_csv = to_csv(["issue_id", "review_id"], [{"issue_id": i, "review_id": r} for i, r in pairs])
    ranking_csv = to_csv(RANK_FIELDS, ranking)
    out.mkdir(parents=True, exist_ok=True)
    (out / "membership.csv").write_text(membership_csv, encoding="utf-8")
    (out / "ranking.csv").write_text(ranking_csv, encoding="utf-8")
    write_json(out / "summary.json", {"issues": len(ranking), "memberships": len(pairs),
                                      "ranking_sha256": sha256_text(ranking_csv),
                                      "membership_sha256": sha256_text(membership_csv)})
    log(f"rank: {len(ranking)} issues, {len(pairs)} complaint memberships")
    return ranking


def load(run_dir):
    with (run_dir / "rank" / "ranking.csv").open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))
