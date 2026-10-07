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

# Only these model IDs may be called (the brief asks for a model allowlist).
MODEL_ALLOWLIST = {"jev": ("jev-1.13.0",), "claude": ("claude-sonnet-5", "claude-haiku-4-5")}
# Per-model list prices (USD per 1M tokens: input, output), from the dated rows in cost/rates.csv.
CLAUDE_PRICES = {"claude-sonnet-5": (Decimal("2"), Decimal("10")), "claude-haiku-4-5": (Decimal("1"), Decimal("5"))}

CLAUDE_BATCH_DISCOUNT = Decimal("0.5")  # Message Batches API bills 50% of standard token prices

# Claude fallback for low-confidence Jev labels (decided 2026-09-30: threshold 0.5 on the minimum of the
# topic/intent/severity confidences). Per-review estimates are only used by the 10% early gate to project
# fallback spend that has not happened yet. Measured in the cold 100-review pilot (cost/report.md):
# $0.0185 for a 7-review standard request = $0.0026 per review; Batch API bills half. Refresh after 10k.
FALLBACK_THRESHOLD = 0.5
FALLBACK_EST_USD_PER_REVIEW = {"standard": Decimal("0.0026"), "batch": Decimal("0.0013")}  # claude-sonnet-5
# Measured per-review fallback cost by model (standard API; the Batch API bills half):
# Sonnet 5 medium $0.00204 (10k run), Haiku 4.5 without thinking $0.00052 (evals/effort_test).
FALLBACK_EST_BY_MODEL = {"claude-sonnet-5": Decimal("0.0021"), "claude-haiku-4-5": Decimal("0.00055")}
FALLBACK_BATCH_POLL_S = 60

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
