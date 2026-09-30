"""Fixed configuration: model IDs, prices, caps, and thresholds.

Prices are the published list rates checked on 2026-09-29 (TypeSafe models page;
Anthropic pricing table). Spend is always computed from provider-reported usage
multiplied by these rates; nothing here is a measured cost.
"""

from decimal import Decimal
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
VENDOR_CHECKER = REPO / "vendor" / "check_submission.py"
# SHA-256 of the course-provided check_submission.py; tests assert the vendored copy is unmodified.
CHECKER_SHA256 = "d60bd66d84922d934c65b3d42b2c7d36cc738e8c75e2d6f2b2f58bca3141c26d"
FULL_CSV_SHA256 = "1fc85de68a304dd8978b537cfa58793d5f41cbaf417fa32cb53899f83a2fcef6"

SCHEMA_VERSION = "schema-v1"

# Jev (TypeSafe System One). Pin the versioned ID, not the moving alias, so the
# label_config stays stable across resumes.
JEV_MODEL = "jev-1.13.0"
JEV_URL = "https://api.typesafe.ai/v1/systemone"
JEV_PRICE_IN = Decimal("0.042")   # USD per 1M input tokens
JEV_PRICE_OUT = Decimal("0")      # output tokens are free
JEV_RPS = 30                      # stay under the 40 req/s published limit
JEV_WORKERS = 24
JEV_TIMEOUT_S = 30

# Claude for verify / group-taxonomy / memo. The user named claude-sonnet-5.
CLAUDE_MODEL = "claude-sonnet-5"
CLAUDE_BASE_URL = "https://api.anthropic.com"  # explicit: ignore any ANTHROPIC_BASE_URL in the shell
CLAUDE_PRICE_IN = Decimal("2")
CLAUDE_PRICE_OUT = Decimal("10")
CLAUDE_EFFORT = "medium"
CLAUDE_MAX_TOKENS = 16000
CLAUDE_TIMEOUT_S = 600

MAX_ENRICH_BATCH = 50   # contract limit; Jev uses 1 review per request
VERIFY_BATCH = 50

MAX_ATTEMPTS = 5
BACKOFF_BASE_S = 1.0
BACKOFF_CAP_S = 60.0

# needs_review routing (calibrate on development runs; see DESIGN.md).
UNCLEAR_NOUL_THRESHOLD = 0.5
MIN_CONFIDENCE = {"topic": 0.35, "intent": 0.35, "severity": 0.25}

# Early cost gate: when this fraction of enrichment units is done, the run's
# spend so far must not exceed the same fraction of the budget cap.
EARLY_GATE_FRACTION = Decimal("0.10")

MAX_QUOTE_CANDIDATES = 30
