"""Golden-50 helpers that never expose human answer labels to a model.

load_ids() reads only the review_id column. strip_labels() writes a copy containing
only the six source fields, so a run on the golden texts cannot see the labels.
"""

import csv
from pathlib import Path

from .checker import FIELDS


def load_ids(path):
    if not path:
        return frozenset()
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        return frozenset(row["review_id"] for row in csv.DictReader(f))


def strip_labels(path, out):
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open(encoding="utf-8-sig", newline="") as f, out.open("w", encoding="utf-8", newline="") as g:
        writer = csv.DictWriter(g, fieldnames=list(FIELDS), lineterminator="\n")
        writer.writeheader()
        for row in csv.DictReader(f):
            writer.writerow({k: row[k] for k in FIELDS})
    return out
