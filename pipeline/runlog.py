"""run_log.jsonl (stage starts/stops) and run_summary.json (statuses, usage, cost, time, resume evidence)."""

import time
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal

from .store import JsonlAppender, read_json, read_jsonl, write_json


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RunLog:
    def __init__(self, run_dir, invocation_id):
        self.run_dir = run_dir
        self.invocation_id = invocation_id
        self.log = JsonlAppender(run_dir / "run_log.jsonl")

    def event(self, event, **details):
        self.log.write({"at": now(), "invocation": self.invocation_id, "event": event, **details})
        self.log.flush()

    @contextmanager
    def stage(self, name):
        start = time.monotonic()
        self.event("stage_start", stage=name)
        outcome = {"status": "ok"}
        try:
            yield outcome
        except BaseException as e:
            outcome["status"] = f"error: {type(e).__name__}: {e}"[:300]
            raise
        finally:
            self.event("stage_end", stage=name, elapsed_s=round(time.monotonic() - start, 1), **outcome)

    def close(self):
        self.log.close()


def summarize(run_dir, records, budget_summary, caps):
    calls = list(read_jsonl(run_dir / "calls.jsonl"))
    usage = defaultdict(Counter)
    cost = defaultdict(Decimal)
    for c in calls:
        key = f"{c['role']}|{c['model']}"
        usage[key]["calls_" + c["outcome"]] += 1
        usage[key]["input_tokens"] += c.get("input_tokens", 0)
        usage[key]["output_tokens"] += c.get("output_tokens", 0)
        usage[key]["failed_attempts_without_usage"] += c["outcome"] == "failed" and not c.get("usage_available", True)
        usage[key]["review_ids_sent"] += len(c.get("review_ids", []))
        cost[key] += Decimal(c.get("cost_usd", "0"))
    stage_time = defaultdict(float)
    invocations = set()
    for e in read_jsonl(run_dir / "run_log.jsonl"):
        invocations.add(e["invocation"])
        if e["event"] == "stage_end":
            stage_time[e["stage"]] += e["elapsed_s"]
    statuses = Counter(r["status"] for r in records)
    reasons = Counter(r["reason"].split(":")[0] for r in records if r["status"] == "quarantined")
    enrich_state = read_json(run_dir / "enrich" / "state.json", {})
    summary = {
        "generated_at": now(),
        "records": {"total": len(records), "by_status": dict(statuses), "quarantine_reasons": dict(reasons),
                    "completed_via_cache_reuse": sum(1 for r in records if r.get("cache_source_id")),
                    "needs_review": sum(1 for r in records if r.get("needs_review"))},
        "usage_by_role_model": {k: {**dict(v), "cost_usd_list_price": str(cost[k])} for k, v in sorted(usage.items())},
        "total_cost_usd_list_price": str(sum(cost.values(), Decimal(0))),
        "cost_basis": "provider-reported tokens x published list prices; not an invoice",
        "elapsed_seconds_by_stage_all_invocations": {k: round(v, 1) for k, v in stage_time.items()},
        "elapsed_seconds_total": round(sum(stage_time.values()), 1),
        "invocations": len(invocations),
        "budget": budget_summary, "caps": caps,
        "enrich_invocations": enrich_state.get("invocations", []),
        "early_gate": enrich_state.get("early_gate"),
        "resume_evidence": {"first_stop_snapshot": enrich_state.get("first_stop_snapshot")},
    }
    write_json(run_dir / "run_summary.json", summary)
    return summary
