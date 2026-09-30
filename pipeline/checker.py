"""Import the course-provided check_submission.py so hashing and profiling match exactly."""

import importlib.util

from .config import CHECKER_SHA256, VENDOR_CHECKER
from .store import sha256_file


def _load():
    actual = sha256_file(VENDOR_CHECKER)
    if actual != CHECKER_SHA256:
        raise RuntimeError(f"vendor/check_submission.py was modified (sha256 {actual})")
    spec = importlib.util.spec_from_file_location("check_submission", VENDOR_CHECKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cs = _load()
row_sha = cs.row_sha
csv_rows = cs.csv_rows
profile = cs.profile
mean_string = cs.mean_string
FIELDS = cs.FIELDS
TOPICS = cs.TOPICS
INTENTS = cs.INTENTS
