"""100-review cost and runtime calculator (COST_CALCULATOR.md).

  python -m pipeline cost replay      (DEFAULT, offline) recompute everything from cost/usage.csv x cost/rates.csv
  python -m pipeline cost pilot ...   (PAID, explicit) run the real pipeline on cost_100.csv, cold or warm
  python -m pipeline cost collect     (offline) turn the pilot run folders into the cost/ evidence files

Importing this module or running `replay` never calls a provider and needs no API key.

Arithmetic rules (all Decimal):
  item_cost = billed_units x price_usd / per_units      (per_units = 1,000,000 for per-MTok prices)
  input, cache-write, cache-read and output tokens are separate, mutually exclusive items; Anthropic's
  output_tokens already include thinking tokens, so reasoning is never added twice.
  Only the tier actually used is applied to measured calls; the Batch API discount appears only in
  projected scenarios, labelled as an estimate.
"""

import csv
import json
import time
from collections import defaultdict
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from .config import REPO
from .store import read_json, read_jsonl, write_json

COST = REPO / "cost"
RUNS = COST / "runs"
D = Decimal
ITEMS = ("input_tokens", "cache_write_input_tokens", "cache_read_input_tokens", "output_tokens")
FULL = {"rows": 660622, "nonempty": 660609, "empty": 13, "distinct": 484189}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def provider_of(model):
    return "typesafe" if model.startswith(("jev", "fake-jev")) else "anthropic"


def stage_of(call):
    """Stage name for reporting: the contract role, with the enrich fallback and the group sub-steps split out."""
    role, model, handoff = call["role"], call["model"], call.get("handoff", "")
    if role == "enrich":
        return "enrich_fallback" if provider_of(model) == "anthropic" else "enrich_jev"
    if role == "group":
        return "group_taxonomy" if provider_of(model) == "anthropic" else "group_assign"
    return role


def money(x, places="0.000001"):
    return str(D(x).quantize(D(places), rounding=ROUND_HALF_UP))


# ----------------------------------------------------------------------------- paid pilot (explicit command)

def pilot(args, log):
    """Run the real pipeline on cost_100.csv. Cold: a new, empty run folder. Warm: rerun an existing cold folder."""
    from . import cli
    label = args.label
    run_dir = RUNS / label
    if args.warm_of:
        source = RUNS / args.warm_of
        if not source.exists():
            raise SystemExit(f"no cold pilot named {args.warm_of}")
        run_dir = source
        kind = "warm"
    else:
        if run_dir.exists():
            raise SystemExit(f"{run_dir} exists; a cold pilot needs an empty result cache (choose a new --label)")
        kind = "cold"
    calls_before = sum(1 for _ in read_jsonl(run_dir / "calls.jsonl"))
    argv = ["run", "--input", str(args.input), "--run-dir", str(run_dir), "--budget-group", args.budget_group,
            "--budget-usd", str(args.budget_usd), "--verify-n", str(args.verify_n), "--fallback", "standard",
            "--fallback-max-fraction", str(args.fallback_max_fraction), "--claude-effort", args.claude_effort,
            "--workers", str(args.workers)]
    if args.exclude_golden:
        argv += ["--exclude-golden", str(args.exclude_golden)]
    if getattr(args, "offline_fake", False):  # TESTS ONLY
        argv += ["--offline-fake"]
    started = now()
    t0 = time.monotonic()
    code = cli.main(argv)
    wall = time.monotonic() - t0
    calls_after = list(read_jsonl(run_dir / "calls.jsonl"))
    new_calls = calls_after[calls_before:]
    invocation = read_json(run_dir / "run_manifest.json")["invocations"][-1]["id"]
    measurement = {"label": args.warm_of + "-warm" if kind == "warm" else label, "kind": kind,
                   "run_folder": run_dir.name, "invocation": invocation, "workers": args.workers,
                   "started_at": started, "wall_clock_seconds": round(wall, 3), "exit_code": code,
                   "new_calls": len(new_calls),
                   "new_enrichment_calls": sum(c["role"] == "enrich" for c in new_calls),
                   "new_downstream_calls": {r: sum(c["role"] == r for c in new_calls) for r in ("verify", "group", "memo")},
                   "settings": {"input": Path(args.input).name, "verify_n": args.verify_n, "fallback": "standard",
                                "fallback_max_fraction": args.fallback_max_fraction, "claude_effort": args.claude_effort,
                                "budget_group": args.budget_group, "budget_usd": args.budget_usd}}
    path = run_dir / "pilot_measurements.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(measurement, sort_keys=True) + "\n")
    log(f"pilot {measurement['label']}: {kind}, {args.workers} worker(s), wall {wall:.1f}s, "
        f"{len(new_calls)} new calls ({measurement['new_enrichment_calls']} enrichment); exit {code}")
    return code


# ----------------------------------------------------------------------------- collect evidence (offline)

def collect(args, log):
    """Build cost/pilot_records.jsonl, pilot_calls.jsonl, usage.csv and measurements.json from pilot folders."""
    from .export import contract_record
    from .records import build
    runs = sorted(p for p in RUNS.iterdir() if (p / "pilot_measurements.jsonl").exists())
    if not runs:
        raise SystemExit("no pilot runs under cost/runs; run `python -m pipeline cost pilot` first (paid)")
    measurements, calls_out = [], []
    for run in runs:
        manifest = read_json(run / "run_manifest.json")
        ms = list(read_jsonl(run / "pilot_measurements.jsonl"))
        by_invocation = {m["invocation"]: m for m in ms}
        stage_time = defaultdict(lambda: defaultdict(float))
        for e in read_jsonl(run / "run_log.jsonl"):
            if e["event"] == "stage_end":
                stage_time[e["invocation"]][e["stage"]] += e["elapsed_s"]
        for m in ms:
            m["stage_seconds"] = {k: round(v, 3) for k, v in stage_time[m["invocation"]].items()}
            measurements.append(m)
        for c in read_jsonl(run / "calls.jsonl"):
            m = by_invocation.get(c.get("invocation"))
            calls_out.append({
                "run_label": m["label"] if m else run.name, "run_kind": m["kind"] if m else "unknown",
                "run_id": c.get("run_id", manifest.get("run_id")), "invocation": c.get("invocation"),
                "request_id": c["request_id"], "role": c["role"], "stage": stage_of(c),
                "provider": provider_of(c["model"]), "model": c["model"], "effort": c.get("effort"),
                "label_config": c.get("label_config"), "price_tier": c.get("price_tier", "standard"),
                "worker_limit": c.get("worker_limit"), "attempt": c.get("attempt"), "outcome": c["outcome"],
                "review_ids": c.get("review_ids", []), "batch_size": len(c.get("review_ids", [])),
                "input_tokens": c.get("input_tokens", 0),
                "cache_write_input_tokens": c.get("cache_creation_input_tokens", 0),
                "cache_read_input_tokens": c.get("cache_read_input_tokens", 0),
                "output_tokens": c.get("output_tokens", 0), "usage_available": c.get("usage_available", True),
                "possible_unlogged_charge": bool(c.get("possible_unlogged_charge")),
                "started_at": c.get("started_at"), "duration_ms": c.get("duration_ms"), "error": c.get("error")})
    COST.mkdir(exist_ok=True)
    with (COST / "pilot_calls.jsonl").open("w", encoding="utf-8") as f:
        for c in calls_out:
            f.write(json.dumps(c, ensure_ascii=False, sort_keys=True) + "\n")
    with (COST / "usage.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["request_id", "run_label", "run_kind", "stage", "provider", "model", "price_tier", "outcome",
                    "item", "billed_units", "unit", "usage_status"])
        for c in calls_out:
            for item in ITEMS:
                units = c[item]
                if units or item in ("input_tokens", "output_tokens"):
                    w.writerow([c["request_id"], c["run_label"], c["run_kind"], c["stage"], c["provider"], c["model"],
                                c["price_tier"], c["outcome"], item, units, "token",
                                "reported" if c["usage_available"] else "missing (not estimated)"])
    cold = next((r for r in runs if any(m["kind"] == "cold" for m in read_jsonl(r / "pilot_measurements.jsonl"))
                 and r.name == args.records_from), None)
    if cold is None:
        raise SystemExit(f"cold pilot folder {args.records_from} not found under cost/runs")
    records = build(cold, "jev-1.13.0")
    from .enrich import current_config, final_results
    final = final_results(cold, current_config(cold, "jev-1.13.0"))
    units = {s["review_id"]: s["unit"] for s in read_jsonl(cold / "ingest" / "sources.jsonl")}
    with (COST / "pilot_records.jsonl").open("w", encoding="utf-8") as f:
        for r in records:
            row = contract_record(r)
            row["decided_by"] = final.get(units[r["review_id"]], {}).get("decided_by")
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    summary = read_json(cold / "ingest" / "summary.json")
    write_json(COST / "measurements.json", {
        "collected_at": now(), "input": {"file": Path(summary["input_path"]).name, "sha256": summary["input_sha256"],
                                         "rows": summary["rows"], "distinct_texts": summary["distinct_nonempty_texts"],
                                         "empty_quarantined": summary["empty_review_text"]},
        "records_from": cold.name,
        "record_status": {s: sum(r["status"] == s for r in records) for s in ("completed", "quarantined")},
        "cache_reuse_records": sum(1 for r in records if r.get("cache_source_id")),
        "decided_by": {k: sum(1 for r in final.values() if r.get("decided_by") == k)
                       for k in sorted({r.get("decided_by") for r in final.values()})},
        "runs": measurements})
    log(f"collect: {len(calls_out)} calls from {len(runs)} pilot folder(s); {len(records)} pilot records")
    return 0


# ----------------------------------------------------------------------------- offline replay (default)

def load_rates(path):
    rates = {}
    with Path(path).open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            rates[(r["provider"], r["model"], r["tier"], r["item"])] = {
                "price": D(r["price_usd"]), "per": D(r["per_units"]), "source": r["source_url"],
                "checked_on": r["checked_on"]}
    return rates


def priced_usage(usage_rows, rates):
    """Every usage row priced as billed_units x price / per_units. Missing rates are reported, never zeroed."""
    out, missing = [], set()
    for u in usage_rows:
        key = (u["provider"], u["model"], u["price_tier"], u["item"])
        units = D(u["billed_units"])
        if key not in rates:
            if units:
                missing.add(key)
            cost = None
        else:
            cost = units * rates[key]["price"] / rates[key]["per"]
        out.append({**u, "cost": cost})
    return out, sorted(missing)


def replay(args, log):
    for f in (args.rates, args.usage, args.calls, args.measurements):
        if not Path(f).exists():
            raise SystemExit(f"{f} not found. Offline replay needs saved pilot evidence: run the paid pilot "
                             "(`python -m pipeline cost pilot ...`) and `python -m pipeline cost collect` first.")
    rates = load_rates(args.rates)
    with Path(args.usage).open(encoding="utf-8", newline="") as f:
        usage = list(csv.DictReader(f))
    calls = list(read_jsonl(Path(args.calls)))
    meas = read_json(args.measurements)
    priced, missing = priced_usage(usage, rates)

    # ---- measured, per run label and stage
    measured = {}
    for m in meas["runs"]:
        label = m["label"]
        rows = [p for p in priced if p["run_label"] == label]
        rcalls = [c for c in calls if c["run_label"] == label]
        stages = {}
        for st in sorted({c["stage"] for c in rcalls} | {p["stage"] for p in rows}):
            sc = [c for c in rcalls if c["stage"] == st]
            sp = [p for p in rows if p["stage"] == st]
            stages[st] = {
                "provider": sorted({c["provider"] for c in sc}), "model": sorted({c["model"] for c in sc}),
                "effort": sorted({str(c["effort"]) for c in sc if c["effort"]}),
                "label_config": sorted({c["label_config"] for c in sc if c["label_config"]}),
                "price_tier": sorted({c["price_tier"] for c in sc}),
                "requests_succeeded": sum(c["outcome"] == "succeeded" for c in sc),
                "attempts": len(sc), "failed_attempts": sum(c["outcome"] == "failed" for c in sc),
                "reviews_sent": sum(c["batch_size"] for c in sc if c["outcome"] == "succeeded"),
                "max_batch_size": max([c["batch_size"] for c in sc] or [0]),
                "usage": {item: sum(int(p["billed_units"]) for p in sp if p["item"] == item) for item in ITEMS},
                "max_output_tokens_one_request": max([c["output_tokens"] for c in sc] or [0]),
                "api_cost_usd": sum((p["cost"] for p in sp if p["cost"] is not None), D(0)),
                "unpriced_items": sum(1 for p in sp if p["cost"] is None and D(p["billed_units"])),
                "missing_usage_attempts": sum(1 for c in sc if not c["usage_available"]),
                "possible_unlogged_charges": sum(1 for c in sc if c["possible_unlogged_charge"]),
                "summed_call_seconds": round(sum((c["duration_ms"] or 0) for c in sc) / 1000, 3)}
        api = sum((s["api_cost_usd"] for s in stages.values()), D(0))
        completed = meas["record_status"]["completed"]
        run_summary = read_json(RUNS / m.get("run_folder", label) / "run_summary.json", {}) or {}
        by_status = (run_summary.get("records") or {}).get("by_status") or meas["record_status"]
        jev_requests = stages.get("enrich_jev", {}).get("requests_succeeded", 0)
        unique_texts = meas["input"]["distinct_texts"]
        rows_in = meas["input"]["rows"]
        measured[label] = {"kind": m["kind"], "workers": m["workers"], "wall_clock_seconds": m["wall_clock_seconds"],
                           "records_completed": by_status.get("completed", 0),
                           "records_quarantined": sum(v for k, v in by_status.items() if k != "completed"),
                           "unique_texts": unique_texts, "result_cache_hits": max(unique_texts - jev_requests, 0),
                           "stage_seconds": m.get("stage_seconds", {}), "new_calls": m["new_calls"],
                           "new_enrichment_calls": m["new_enrichment_calls"],
                           "new_downstream_calls": m["new_downstream_calls"], "stages": stages,
                           "api_cost_usd": api,
                           "cost_per_1000_input_rows": api * 1000 / rows_in if rows_in else None,
                           "cost_per_completed_record": api / completed if completed else None,
                           "throughput_rows_per_s": (D(rows_in) / D(str(m["wall_clock_seconds"]))
                                                     if m["wall_clock_seconds"] else None)}

    # ---- projection from the cold, one-worker pilot
    base_label = args.base_run
    if base_label not in measured:
        raise SystemExit(f"--base-run {base_label} not among measured runs {sorted(measured)}")
    b = measured[base_label]
    st = b["stages"]
    distinct_pilot = meas["input"]["distinct_texts"]

    def per(stage, denom_key="reviews_sent"):
        s = st.get(stage)
        if not s or not s[denom_key]:
            return D(0), 0
        return s["api_cost_usd"] / s[denom_key], s[denom_key]

    jev_per_text, _ = per("enrich_jev")
    fb_per_review, fb_sent = per("enrich_fallback")
    ver_per_review, _ = per("verify")
    fb_cost_basis = "measured fallback cost per review"
    if not fb_sent:  # no fallback happened in the pilot: price it like the same model's blind re-label (verify)
        fb_per_review, fb_cost_basis = ver_per_review, "proxy: no fallback in pilot; verify cost per review (same model, similar prompt)"
    assign_per_text, assign_n = per("group_assign")
    taxonomy_once = st.get("group_taxonomy", {}).get("api_cost_usd", D(0))
    memo_once = st.get("memo", {}).get("api_cost_usd", D(0))
    fb_rate = D(fb_sent) / D(distinct_pilot) if distinct_pilot else D(0)
    assign_rate = D(assign_n) / D(distinct_pilot) if distinct_pilot else D(0)
    retry_factor = (D(st["enrich_jev"]["attempts"]) / D(st["enrich_jev"]["requests_succeeded"])
                    if st.get("enrich_jev", {}).get("requests_succeeded") else D(1))
    max_fb = D(str(args.fallback_fraction))
    conservative_bump = D(str(args.conservative_factor))
    batch_fb = D("0.5")  # Message Batches API price; estimate only (the pilot used the standard tier)

    def scenario(name, texts, fb_fraction, factor, fallback_tier_multiplier, note):
        fb_fraction = min(fb_fraction, max_fb)
        items = {
            "enrich_jev": jev_per_text * texts * retry_factor * factor,
            "enrich_fallback": fb_per_review * texts * fb_fraction * factor * fallback_tier_multiplier,
            "verify": ver_per_review * args.verify_n * factor,
            "group_taxonomy": taxonomy_once,
            "group_assign": assign_per_text * texts * assign_rate * factor,
            "memo": memo_once * factor,
        }
        total = sum(items.values(), D(0))
        return {"name": name, "texts_classified": texts, "fallback_fraction": fb_fraction,
                "cost_factor": factor, "fallback_price": "batch (est. 50%)" if fallback_tier_multiplier != 1 else "standard",
                "items_usd": items, "total_usd": total, "over_budget": total > D(str(args.budget)), "note": note}

    distinct = args.distinct
    nonempty = args.nonempty
    scenarios = [
        scenario("base (reuse, standard fallback)", distinct, fb_rate, D(1), D(1),
                 "measured pilot rates; exact-text reuse"),
        scenario("base (reuse, Batch-API fallback)", distinct, fb_rate, D(1), batch_fb,
                 "planned full-run setup; Batch price is an estimate until measured"),
        scenario("conservative (reuse, Batch-API fallback)", distinct, max_fb, conservative_bump, batch_fb,
                 f"fallback at the declared cap; all variable costs x{conservative_bump} for retries/longer texts"),
        scenario("no reuse (base, Batch-API fallback)", nonempty, fb_rate, D(1), batch_fb,
                 "every nonempty row classified separately"),
    ]

    # ---- time projection (modelled from measured per-stage throughput)
    jev_s = b["stage_seconds"].get("enrich", 0) or 0
    two = next((m for m in measured.values() if m["kind"] == "cold" and m["workers"] == 2), None)
    speedup = None
    if two and two["stage_seconds"].get("enrich") and jev_s:
        speedup = D(str(jev_s)) / D(str(two["stage_seconds"]["enrich"]))
    per_text_s = D(str(jev_s)) / D(distinct_pilot) if distinct_pilot else D(0)
    rps_cap = D(str(args.rps_cap))
    workers = args.max_workers
    modeled_rate = min(D(workers) / per_text_s if per_text_s else rps_cap, rps_cap)
    enrich_hours = D(distinct) / modeled_rate / 3600 if modeled_rate else None
    group_hours = D(distinct) * assign_rate / modeled_rate / 3600 if modeled_rate else None

    used_keys = sorted({(p["provider"], p["model"], p["price_tier"], p["item"]) for p in priced
                        if D(p["billed_units"]) and (p["provider"], p["model"], p["price_tier"], p["item"]) in rates})
    with Path(args.rates).open(encoding="utf-8", newline="") as f:
        rate_rows = {(r["provider"], r["model"], r["tier"], r["item"]): r for r in csv.DictReader(f)}
    rates_used = [{k: rate_rows[key][k] for k in ("provider", "model", "tier", "item", "price_usd", "per_units", "unit",
                                                   "currency", "source_url", "checked_on")} for key in used_keys]
    report = {"generated_at": now(), "rates_file": str(args.rates), "missing_rates": [list(k) for k in missing],
              "rates_used": rates_used,
              "measured": measured, "projection_inputs": {
                  "base_run": base_label, "jev_cost_per_distinct_text": jev_per_text, "jev_attempts_per_success": retry_factor,
                  "fallback_cost_per_review": fb_per_review, "fallback_cost_basis": fb_cost_basis,
                  "fallback_rate_measured": fb_rate,
                  "fallback_max_fraction": max_fb, "verify_cost_per_review": ver_per_review, "verify_n_full_run": args.verify_n,
                  "group_assign_rate": assign_rate, "group_assign_cost_per_text": assign_per_text,
                  "fixed_overhead_once": {"group_taxonomy": taxonomy_once, "memo": memo_once},
                  "budget_usd": args.budget, "output_token_cap": args.output_cap, "max_workers": workers},
              "full_run": FULL | {"distinct": distinct, "nonempty": nonempty}, "scenarios": scenarios,
              "time": {"jev_seconds_per_text_one_worker": per_text_s, "measured_2_worker_enrich_speedup": speedup,
                       "rate_limit_rps": rps_cap, "modeled_jev_texts_per_second": modeled_rate,
                       "modeled_enrich_hours": enrich_hours, "modeled_group_assign_hours": group_hours,
                       "note": "modelled, not measured: scaled from the one-worker pilot and capped at the rate limit; "
                               "Batch-API fallback adds provider turnaround (most batches < 1 h, up to 24 h)"},
              "output_cap_check": {
                  "cap": args.output_cap,
                  "largest_measured_output": max([s["max_output_tokens_one_request"] for m in measured.values()
                                                  for s in m["stages"].values()] or [0]),
                  "worst_case_claude_request_usd": D(args.output_cap) * rates.get(
                      ("anthropic", "claude-sonnet-5", "standard", "output_tokens"), {"price": D(0)})["price"] / D(1000000)},
              "local_compute": "unknown: runs on a personal laptop; not metered, not included in API spend"}
    decision = read_json(getattr(args, "decision", None) or (COST / "decision.json"))
    if decision:
        report["decision"] = decision
    COST.mkdir(exist_ok=True)
    out_json = Path(args.out).with_suffix(".json")
    out_json.write_text(json.dumps(report, default=str, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    Path(args.out).write_text(render(report), encoding="utf-8")
    log(f"replay: wrote {args.out} and {out_json} (offline; no provider calls)")
    for s in scenarios:
        log(f"  {s['name']:<42} ${money(s['total_usd'], '0.01')}{'  OVER BUDGET' if s['over_budget'] else ''}")
    return 0


def render(r):
    L = ["# 100-review cost and runtime report", "",
         f"Generated {r['generated_at']} by `python -m pipeline cost replay` from saved usage and `{Path(r['rates_file']).name}`. "
         "Offline: no provider calls, no API key. Costs = billed units × editable rates; measured results never "
         "change when projection inputs change.", ""]
    if r["missing_rates"]:
        L += ["**Unpriced usage (rate missing; left unresolved, not zero):** " + ", ".join("/".join(k) for k in r["missing_rates"]), ""]
    L += ["## Measured pilot runs", "",
          "| Run | Kind | Workers | Records completed / quarantined | Unique texts | Result-cache hits | Wall-clock s | New calls (enrich / downstream) | API cost USD | per 1,000 rows | per completed record | rows/s |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for label, m in r["measured"].items():
        down = sum(m["new_downstream_calls"].values())
        L.append(f"| {label} | {m['kind']} | {m['workers']} | {m['records_completed']} / {m['records_quarantined']} | "
                 f"{m['unique_texts']} | {m['result_cache_hits']} | {m['wall_clock_seconds']} | {m['new_enrichment_calls']} / {down} | "
                 f"{money(m['api_cost_usd'])} | {money(m['cost_per_1000_input_rows']) if m['cost_per_1000_input_rows'] is not None else '-'} | "
                 f"{money(m['cost_per_completed_record']) if m['cost_per_completed_record'] is not None else '-'} | "
                 f"{money(m['throughput_rows_per_s'], '0.01') if m['throughput_rows_per_s'] else '-'} |")
    for label, m in r["measured"].items():
        if m["kind"] != "cold":
            continue
        L += ["", f"### Stages: {label}", "",
              "| Stage | Provider / model | Effort | Tier | Prompt / schema version (`label_config`) | Requests ok / attempts / failed | Reviews sent | Max batch | Input | Cache write | Cache read | Output | Max output/request | API USD | Stage s | Summed call s |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        stage_secs = m["stage_seconds"]
        stage_map = {"enrich_jev": "enrich", "enrich_fallback": "enrich", "verify": "verify",
                     "group_taxonomy": "group", "group_assign": "group", "memo": "recommend"}
        for name, s in m["stages"].items():
            u = s["usage"]
            L.append(f"| {name} | {'/'.join(s['provider'])} `{'/'.join(s['model'])}` | {'/'.join(s['effort']) or 'n/a'} | "
                     f"{'/'.join(s['price_tier'])} | {'<br>'.join('`' + c + '`' for c in s['label_config']) or 'n/a'} | "
                     f"{s['requests_succeeded']} / {s['attempts']} / {s['failed_attempts']} | "
                     f"{s['reviews_sent']} | {s['max_batch_size']} | {u['input_tokens']:,} | {u['cache_write_input_tokens']:,} | "
                     f"{u['cache_read_input_tokens']:,} | {u['output_tokens']:,} | {s['max_output_tokens_one_request']:,} | "
                     f"{money(s['api_cost_usd'])} | {stage_secs.get(stage_map.get(name, name), '-')} | {s['summed_call_seconds']} |")
        L += ["", "Stage seconds come from the run log (wall-clock per stage; enrich includes the fallback, group "
              "includes taxonomy and assignment). Summed call seconds can exceed wall-clock when calls overlap."]
    if r.get("rates_used"):
        L += ["", "### Rates applied to the measured usage (from `rates.csv`; editable)", "",
              "| Provider | Model | Tier | Item | Price | Per units | Unit | Currency | Source | Checked on |",
              "|---|---|---|---|---|---|---|---|---|---|"]
        for x in r["rates_used"]:
            L.append(f"| {x['provider']} | `{x['model']}` | {x['tier']} | {x['item']} | {x['price_usd']} | {x['per_units']} | "
                     f"{x['unit']} | {x['currency']} | [link]({x['source_url']}) | {x['checked_on']} |")
        L += ["", "Result-cache hits = distinct texts completed without a new enrichment request in that run "
                  "(the warm rerun reuses all 100 saved results under unchanged settings)."]
    pi = r["projection_inputs"]
    L += ["", "## Full-run projection (estimates)", "",
          f"Base run `{pi['base_run']}`. Measured rates: Jev ${money(pi['jev_cost_per_distinct_text'], '0.0000001')} per distinct "
          f"text ({money(pi['jev_attempts_per_success'], '0.001')} attempts per success); fallback rate {money(pi['fallback_rate_measured'], '0.001')} "
          f"(declared cap {pi['fallback_max_fraction']}) at ${money(pi['fallback_cost_per_review'])} per review "
          f"({pi['fallback_cost_basis']}); verify "
          f"${money(pi['verify_cost_per_review'])} per review × {pi['verify_n_full_run']}; grouping assigns "
          f"{money(pi['group_assign_rate'], '0.001')} of texts at ${money(pi['group_assign_cost_per_text'], '0.0000001')} each; "
          f"fixed overhead once: taxonomy ${money(pi['fixed_overhead_once']['group_taxonomy'])}, memo ${money(pi['fixed_overhead_once']['memo'])}.", "",
          f"Full run: {r['full_run']['rows']:,} rows, {r['full_run']['nonempty']:,} nonempty classifications, "
          f"{r['full_run']['empty']} empty-text quarantines, {r['full_run']['distinct']:,} distinct texts with reuse. "
          f"Budget ${pi['budget_usd']}.", "",
          "| Scenario | Texts classified | Fallback fraction | Fallback price | Jev | Fallback | Verify | Taxonomy | Assign | Memo | **Total** | Budget |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in r["scenarios"]:
        i = s["items_usd"]
        L.append(f"| {s['name']} | {s['texts_classified']:,} | {money(s['fallback_fraction'], '0.001')} | {s['fallback_price']} | "
                 f"{money(i['enrich_jev'], '0.01')} | {money(i['enrich_fallback'], '0.01')} | {money(i['verify'], '0.01')} | "
                 f"{money(i['group_taxonomy'], '0.01')} | {money(i['group_assign'], '0.01')} | {money(i['memo'], '0.01')} | "
                 f"**{money(s['total_usd'], '0.01')}** | {'⚠️ OVER' if s['over_budget'] else 'within'} |")
    L += ["", "Notes: " + "; ".join(f"*{s['name']}*: {s['note']}" for s in r["scenarios"]) + "."]
    t = r["time"]
    L += ["", "## Time projection (modelled)", "",
          f"One-worker pilot: {money(t['jev_seconds_per_text_one_worker'], '0.001')} s of enrich stage per distinct text. "
          f"Measured 2-worker enrich speedup: {money(t['measured_2_worker_enrich_speedup'], '0.01') if t['measured_2_worker_enrich_speedup'] else 'not measured'}. "
          f"At {pi['max_workers']} workers, capped at {t['rate_limit_rps']} requests/s: ~{money(t['modeled_jev_texts_per_second'], '0.1')} texts/s → "
          f"enrich ≈ {money(t['modeled_enrich_hours'], '0.1')} h, grouping ≈ {money(t['modeled_group_assign_hours'], '0.1')} h. {t['note']}.", "",
          "## Controls", "",
          f"- Spending limit: ${pi['budget_usd']} (scenarios above flag any overrun). The pipeline enforces it in code by reserving worst-case cost before every call.",
          f"- Output-token cap per Claude request: {r['output_cap_check']['cap']:,}; largest measured output {r['output_cap_check']['largest_measured_output']:,}; "
          f"worst case one request's output ${money(r['output_cap_check']['worst_case_claude_request_usd'])}.",
          f"- Maximum workers: {pi['max_workers']} (pilot measured at 1, and 2 where available).",
          f"- Declared maximum fallback fraction: {pi['fallback_max_fraction']}.",
          f"- Local compute: {r['local_compute']}.", ""]
    d = r.get("decision")
    if d:
        L += ["## Chosen setup and scaling decision (from `decision.json`)", "",
              f"The projections above are the calculator's required full-corpus estimate from the 100-review pilot, "
              f"made with the plan of that time. After the 500 and 10,000 refreshes ([`refresh.md`](refresh.md)) the "
              f"final setup was decided on {d['decided_on']}:", "",
              f"- **Scope:** {d['scope']}",
              f"- **Budget:** ${d['budget']['cap_usd']} hard cap (budget group `{d['budget']['group']}`): {d['budget']['why']}.",
              f"- **Concurrency:** {d['concurrency']['workers']} workers, {d['concurrency']['rate_limit_rps']} requests/s: "
              f"{d['concurrency']['why']}",
              f"- **Fallback limit:** `{d['fallback']['model']}` (effort {d['fallback']['effort']}, {d['fallback']['api']}) when "
              f"{d['fallback']['threshold']}, at most {d['fallback']['max_fraction']:.0%} of texts, "
              f"{d['fallback']['max_output_tokens_per_request']:,} output tokens per request: {d['fallback']['why']}.",
              f"- **Verification:** `{d['verification']['model']}` on {d['verification']['sample']:,} random texts, {d['verification']['api']}.",
              f"- **Memo:** `{d['memo']['model']}` (effort {d['memo']['effort']}): {d['memo']['why']}.",
              "- **Not used:** " + "; ".join(f"{k.replace('_', ' ')}: {v}" for k, v in d["not_used"].items()) + ".",
              f"- **Outcome:** run `{d['actual']['run_id']}` cost ${d['actual']['cost_usd_list_price']} at list prices in about "
              f"{d['actual']['active_hours']} h of active run time ([`../{d['actual']['evidence']}`](../{d['actual']['evidence']})).", ""]
    return "\n".join(L)


# ----------------------------------------------------------------------------- checkpoint refresh (offline)

def _rate_model(model):
    """Provider-returned model IDs can carry a date suffix (claude-haiku-4-5-20251001); rates use the alias."""
    import re
    return re.sub(r"-\d{8}$", "", model)


def _price_call(c, rates, missing):
    tier = "batch_50pct" if c.get("mode") == "batch" else "standard"
    model = _rate_model(c["model"])
    total = D(0)
    for item, units in (("input_tokens", c.get("input_tokens", 0)), ("output_tokens", c.get("output_tokens", 0)),
                        ("cache_write_input_tokens", c.get("cache_creation_input_tokens", 0)),
                        ("cache_read_input_tokens", c.get("cache_read_input_tokens", 0))):
        if not units:
            continue
        key = (provider_of(model), model, tier, item)
        if key not in rates:
            missing.add(key)
            continue
        total += D(units) * rates[key]["price"] / rates[key]["per"]
    return total


def measure_run(run_dir, rates, missing):
    """Per-stage usage, cost and timing of a finished development run, from its saved call log (no calls)."""
    from statistics import mean, median
    run_dir = Path(run_dir)
    summary = read_json(run_dir / "run_summary.json")
    manifest = read_json(run_dir / "run_manifest.json")
    if (run_dir / "calls.jsonl").exists():
        calls = list(read_jsonl(run_dir / "calls.jsonl"))
    else:  # committed evidence copy in evals/<run>/
        import gzip
        with gzip.open(run_dir / "calls.jsonl.gz", "rt", encoding="utf-8") as f:
            calls = [json.loads(line) for line in f if line.strip()]
    stages = defaultdict(lambda: {"attempts": 0, "succeeded": 0, "reviews_sent": 0, "input_tokens": 0,
                                  "output_tokens": 0, "cost_usd": D(0), "durations_ms": [], "models": set(),
                                  "modes": set()})
    for c in calls:
        st = stages[stage_of(c)]
        st["attempts"] += 1
        st["succeeded"] += c["outcome"] == "succeeded"
        if c["outcome"] == "succeeded":
            st["reviews_sent"] += len(c.get("review_ids") or [])
        st["input_tokens"] += c.get("input_tokens", 0)
        st["output_tokens"] += c.get("output_tokens", 0)
        st["cost_usd"] += _price_call(c, rates, missing)
        if c.get("duration_ms"):
            st["durations_ms"].append(c["duration_ms"])
        st["models"].add(_rate_model(c["model"]))
        st["modes"].add(c.get("mode", "standard"))
    out = {}
    for name, st in sorted(stages.items()):
        d = st.pop("durations_ms")
        out[name] = {**st, "models": sorted(st["models"]), "modes": sorted(st["modes"]),
                     "median_call_ms": median(d) if d else None, "mean_call_ms": round(mean(d), 1) if d else None}
    ingest = read_json(run_dir / "ingest" / "summary.json") or read_json(run_dir / "ingest_summary.json", {})
    distinct = ingest.get("distinct_nonempty_texts")
    return {"run_id": manifest["run_id"], "input": Path(manifest["input"]).name, "input_sha256": manifest["input_sha256"],
            "workers": manifest.get("workers"), "rps": manifest.get("rps"), "fallback": manifest.get("fallback"),
            "verify_n": manifest.get("verify_n"), "distinct_texts": distinct,
            "jev_texts": out.get("enrich_jev", {}).get("succeeded", 0),
            "stage_seconds": summary.get("elapsed_seconds_by_stage_all_invocations", {}),
            "wall_clock_seconds": summary.get("elapsed_seconds_total"), "stages": out,
            "api_cost_usd": sum((v["cost_usd"] for v in out.values()), D(0)),
            "provider_reported_total_usd": summary.get("total_cost_usd_list_price")}


def _rel(path):
    try:
        return str(Path(path).resolve().relative_to(REPO))
    except ValueError:
        return str(path)


def _reviews_in_request(log_dir, call):
    """Eval calls log no review IDs; count the reviews in the saved request handoff instead."""
    name = call.get("handoff", "").rsplit("/", 1)[-1]
    req = read_json(log_dir / "handoffs" / f"{name}.request.json") or {}
    user = req.get("user", "")
    if "<reviews>" not in user:
        return 0
    return len(json.loads(user.split("<reviews>\n", 1)[1].split("\n</reviews>", 1)[0]))


def refresh(args, log):
    """Checkpoint refresh after the 500 and 10,000 runs: measured rates from their call logs, then a projection
    of the planned final setup. Offline: reads saved logs and cost/rates.csv only."""
    rates = load_rates(args.rates)
    missing = set()
    runs = {label: measure_run(d, rates, missing) for label, d in zip(args.labels, args.run_dirs)}
    # Candidate fallback model, measured outside the runs (evals): cost per review on the standard API.
    cand = {"model": args.fallback_model, "reviews": 0, "cost_usd": D(0), "sources": []}
    for f in args.fallback_evidence:
        for c in read_jsonl(Path(f)):
            if _rate_model(c["model"]) == args.fallback_model and c["outcome"] == "succeeded":
                cand["reviews"] += len(c.get("review_ids") or []) or _reviews_in_request(Path(f).parent, c)
                cand["cost_usd"] += _price_call(c, rates, missing)
        cand["sources"].append(_rel(f))
    cand["cost_per_review_standard"] = cand["cost_usd"] / cand["reviews"] if cand["reviews"] else None

    base = runs[args.base]
    st = base["stages"]
    texts = base["jev_texts"]
    per = lambda name: (st[name]["cost_usd"] / st[name]["reviews_sent"]) if st.get(name, {}).get("reviews_sent") else D(0)
    jev_per_text = per("enrich_jev") * D(st["enrich_jev"]["attempts"]) / D(st["enrich_jev"]["succeeded"])
    fb_rate = D(st.get("enrich_fallback", {}).get("reviews_sent", 0)) / D(texts)
    assign_rate = D(st["group_assign"]["succeeded"]) / D(texts)
    assign_per = per("group_assign")
    verify_per = per("verify")
    fixed = {"group_taxonomy": st.get("group_taxonomy", {}).get("cost_usd", D(0)), "memo": st.get("memo", {}).get("cost_usd", D(0))}
    batch = D("0.5")
    target = args.target_distinct
    cap = D(str(args.fallback_max_fraction))

    def scenario(name, fb_fraction, factor, fb_per, verify_tier, note):
        fb_fraction = min(fb_fraction, cap)
        items = {"enrich_jev": jev_per_text * target * factor,
                 "enrich_fallback": fb_per * target * fb_fraction * factor,
                 "verify": verify_per * args.verify_n * verify_tier * factor,
                 "group_taxonomy": fixed["group_taxonomy"], "group_assign": assign_per * target * assign_rate * factor,
                 "memo": fixed["memo"] * factor}
        total = sum(items.values(), D(0))
        return {"name": name, "fallback_fraction": fb_fraction, "items_usd": items, "total_usd": total,
                "within_cap": total <= D(str(args.budget)), "note": note}

    cand_batch = (cand["cost_per_review_standard"] or D(0)) * batch
    sonnet_fb = per("enrich_fallback")
    factor = D(str(args.conservative_factor))
    scenarios = [
        scenario("planned: Haiku Batch fallback, Sonnet Batch verify", fb_rate, D(1), cand_batch, batch,
                 f"measured {args.base} rates; Haiku cost from evals at Batch price (est. 50%)"),
        scenario("conservative: same, fallback at cap, x" + str(factor), cap, factor, cand_batch, batch,
                 "fallback at the declared 20% cap; variable costs x1.25 for retries/longer texts"),
        scenario("reference: Sonnet Batch fallback, Sonnet Batch verify", fb_rate, D(1), sonnet_fb * batch, batch,
                 "the setup before the Haiku decision"),
        scenario("reference: Haiku Batch fallback, Sonnet standard verify", fb_rate, D(1), cand_batch, D(1),
                 "before verification moved to the Batch API"),
    ]
    jev = st["enrich_jev"]
    lat_s = D(str(jev["mean_call_ms"])) / 1000
    measured_rate = None
    if base["stage_seconds"].get("enrich") and base.get("workers"):
        measured_rate = D(texts) / D(str(base["stage_seconds"]["enrich"]))
    def modeled(workers):
        return min(D(workers) / lat_s, D(str(args.rps_cap)))
    rate = modeled(args.workers)
    time_proj = {"jev_mean_call_s": lat_s, "jev_median_call_ms": jev["median_call_ms"],
                 "base_workers": base["workers"], "planned_workers": args.workers, "rps_cap": args.rps_cap,
                 "modeled_texts_per_s_planned": rate, "modeled_texts_per_s_base_workers": modeled(base["workers"] or 1),
                 "enrich_jev_hours": D(target) / rate / 3600,
                 "group_assign_hours": D(target) * assign_rate / rate / 3600,
                 "verify": "Batch API: provider turnaround (most batches finish within 1 h; up to 24 h)",
                 "fallback": "Batch API: provider turnaround (most batches finish within 1 h; up to 24 h)",
                 "note": "modelled from the measured mean Jev call time x workers, capped at the request-rate limit; "
                         "the first slice of the final run (interruption demo) measures the planned worker count"}
    report = {"generated_at": now(), "rates_file": _rel(args.rates), "missing_rates": sorted(list(k) for k in missing),
              "checkpoints": runs, "candidate_fallback": cand,
              "projection_inputs": {"base": args.base, "jev_cost_per_text_incl_retries": jev_per_text,
                                    "fallback_rate_measured": fb_rate, "fallback_max_fraction": cap,
                                    "sonnet_fallback_cost_per_review_standard": sonnet_fb,
                                    "haiku_fallback_cost_per_review_standard": cand["cost_per_review_standard"],
                                    "verify_cost_per_review_standard": verify_per, "verify_n": args.verify_n,
                                    "group_assign_rate": assign_rate, "group_assign_cost_per_text": assign_per,
                                    "fixed_overhead_once": fixed, "target_distinct_texts": target,
                                    "target_scope": args.target_scope, "budget_usd": args.budget},
              "scenarios": scenarios, "time": time_proj}
    out = Path(args.out)
    out.with_suffix(".json").write_text(json.dumps(report, default=str, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    out.write_text(render_refresh(report), encoding="utf-8")
    log(f"refresh: wrote {out} and {out.with_suffix('.json')} (offline; no provider calls)")
    for s in scenarios:
        log(f"  {s['name']:<58} ${money(s['total_usd'], '0.01')}")
    return 0


def render_refresh(r):
    pi = r["projection_inputs"]
    L = ["# Cost calculator refresh: 500 and 10,000 checkpoints", "",
         f"Generated {r['generated_at']} by `python -m pipeline cost refresh` from the saved call logs of the development "
         f"runs and `{Path(r['rates_file']).name}`. Offline: no provider calls. Measured values are billed units × "
         "editable rates; projections are estimates.", ""]
    if r["missing_rates"]:
        L += ["**Unpriced usage (rate missing; not zero):** " + ", ".join("/".join(k) for k in r["missing_rates"]), ""]
    L += ["## Measured checkpoints", "",
          "| Checkpoint | Input | Distinct texts | Workers | Wall-clock s | API cost (rates.csv) | Provider-reported total |",
          "|---|---|---|---|---|---|---|"]
    for label, m in r["checkpoints"].items():
        L.append(f"| {label} | `{m['input']}` | {m['distinct_texts']:,} | {m['workers']} | {m['wall_clock_seconds']} | "
                 f"${money(m['api_cost_usd'], '0.0001')} | ${money(m['provider_reported_total_usd'] or 0, '0.0001')} |")
    L += ["", "The rates.csv column prices every billed attempt, including failed attempts that returned usage; the "
          "provider-reported total in the run summary counts successful calls only, so the two can differ slightly."]
    for label, m in r["checkpoints"].items():
        L += ["", f"### Stages: {label}", "",
              "| Stage | Model | Mode | Requests ok / attempts | Reviews sent | Input tokens | Output tokens | USD | Median call ms |",
              "|---|---|---|---|---|---|---|---|---|"]
        for name, s in m["stages"].items():
            L.append(f"| {name} | `{'/'.join(s['models'])}` | {'/'.join(s['modes'])} | {s['succeeded']} / {s['attempts']} | "
                     f"{s['reviews_sent']:,} | {s['input_tokens']:,} | {s['output_tokens']:,} | {money(s['cost_usd'])} | "
                     f"{s['median_call_ms'] if s['median_call_ms'] is not None else '-'} |")
        L.append(f"\nStage wall-clock seconds: {m['stage_seconds']}.")
    c = r["candidate_fallback"]
    L += ["", "## Fallback model measured in evals", "",
          f"`{c['model']}` without extended thinking: {c['reviews']} reviews, ${money(c['cost_usd'])} on the standard API "
          f"→ ${money(c['cost_per_review_standard'] or 0)} per review (sources: {', '.join(f'`{x}`' for x in c['sources'])}).",
          "", f"## Projection: {pi['target_scope']} ({pi['target_distinct_texts']:,} distinct texts)", "",
          f"From the `{pi['base']}` checkpoint: Jev ${money(pi['jev_cost_per_text_incl_retries'], '0.0000001')} per text "
          f"(retries included); fallback rate {money(pi['fallback_rate_measured'], '0.001')} (cap {pi['fallback_max_fraction']}); "
          f"verify ${money(pi['verify_cost_per_review_standard'])} per review standard × {pi['verify_n']:,}; grouping assigns "
          f"{money(pi['group_assign_rate'], '0.001')} of texts at ${money(pi['group_assign_cost_per_text'], '0.0000001')}; "
          f"fixed once: taxonomy ${money(pi['fixed_overhead_once']['group_taxonomy'])}, memo ${money(pi['fixed_overhead_once']['memo'])}. "
          f"Batch API prices are 50% of standard (estimate until the final run measures them).", "",
          "| Scenario | Fallback fraction | Jev | Fallback | Verify | Taxonomy | Assign | Memo | **Total** | Cap |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for s in r["scenarios"]:
        i = s["items_usd"]
        L.append(f"| {s['name']} | {money(s['fallback_fraction'], '0.001')} | {money(i['enrich_jev'], '0.01')} | "
                 f"{money(i['enrich_fallback'], '0.01')} | {money(i['verify'], '0.01')} | {money(i['group_taxonomy'], '0.01')} | "
                 f"{money(i['group_assign'], '0.01')} | {money(i['memo'], '0.01')} | **{money(s['total_usd'], '0.01')}** | "
                 f"{'within' if s['within_cap'] else 'OVER'} ${pi['budget_usd']} |")
    L += ["", "Notes: " + "; ".join(f"*{s['name']}*: {s['note']}" for s in r["scenarios"]) + "."]
    t = r["time"]
    L += ["", "## Time projection (modelled)", "",
          f"Measured Jev call: median {t['jev_median_call_ms']} ms, mean {money(t['jev_mean_call_s'] * 1000, '0.1')} ms. "
          f"At {t['base_workers']} workers that models {money(t['modeled_texts_per_s_base_workers'], '0.1')} texts/s; at "
          f"{t['planned_workers']} workers, capped at {t['rps_cap']} requests/s: {money(t['modeled_texts_per_s_planned'], '0.1')} texts/s → "
          f"Jev enrichment ≈ {money(t['enrich_jev_hours'], '0.01')} h, grouping ≈ {money(t['group_assign_hours'], '0.01')} h. "
          f"Fallback and verification: {t['fallback']}. {t['note']}.", ""]
    return "\n".join(L)


# ----------------------------------------------------------------------------- CLI wiring

def add_parser(sub):
    p = sub.add_parser("cost", help="100-review cost/runtime calculator (default: offline replay)")
    cs = p.add_subparsers(dest="cost_command")
    r = cs.add_parser("replay", help="offline: recompute costs and projections from saved usage and editable rates")
    _replay_args(r)
    pl = cs.add_parser("pilot", help="PAID: run the real pipeline on cost_100.csv (cold) or rerun it (warm)")
    pl.add_argument("--input", required=True, type=Path, help="cost_100.csv, unchanged")
    pl.add_argument("--label", default="cold-w1")
    pl.add_argument("--warm-of", help="rerun this existing cold pilot folder with its saved results (warm run)")
    pl.add_argument("--workers", type=int, default=1)
    pl.add_argument("--verify-n", type=int, default=20, help="declared verification sample for the pilot")
    pl.add_argument("--fallback-max-fraction", type=float, default=0.2)
    pl.add_argument("--claude-effort", default="medium", choices=["low", "medium", "high"])
    pl.add_argument("--exclude-golden", type=Path)
    pl.add_argument("--budget-group", default="dev")
    pl.add_argument("--budget-usd", type=float, default=5)
    pl.add_argument("--offline-fake", action="store_true", help="TESTS ONLY: fake providers")
    rf = cs.add_parser("refresh", help="offline: measured rates from the 500/10,000 run logs + final-run projection")
    rf.add_argument("--rates", default=str(COST / "rates.csv"))
    rf.add_argument("--run-dirs", nargs="+", default=[str(REPO / "evals" / "dev500"), str(REPO / "evals" / "dev10k")],
                    help="run folders, or the committed evidence copies in evals/ (calls.jsonl.gz, manifest, summaries)")
    rf.add_argument("--labels", nargs="+", default=["500", "10000"])
    rf.add_argument("--base", default="10000", help="checkpoint whose measured rates drive the projection")
    rf.add_argument("--fallback-model", default="claude-haiku-4-5")
    rf.add_argument("--fallback-evidence", nargs="+", default=[str(REPO / "evals" / "effort_test" / "calls.jsonl"),
                                                               str(REPO / "evals" / "heldout" / "calls.jsonl")])
    rf.add_argument("--fallback-max-fraction", type=float, default=0.2)
    rf.add_argument("--target-distinct", type=int, default=78146, help="distinct texts in the final scope")
    rf.add_argument("--target-scope", default="100,000-review seeded sample")
    rf.add_argument("--verify-n", type=int, default=1000)
    rf.add_argument("--budget", type=float, default=15)
    rf.add_argument("--workers", type=int, default=5)
    rf.add_argument("--rps-cap", type=float, default=30)
    rf.add_argument("--conservative-factor", type=float, default=1.25)
    rf.add_argument("--out", default=str(COST / "refresh.md"))
    c = cs.add_parser("collect", help="offline: build cost/ evidence files from the pilot folders")
    c.add_argument("--records-from", default="cold-w1", help="pilot folder whose records become pilot_records.jsonl")


def _replay_args(r):
    r.add_argument("--rates", default=str(COST / "rates.csv"))
    r.add_argument("--usage", default=str(COST / "usage.csv"))
    r.add_argument("--calls", default=str(COST / "pilot_calls.jsonl"))
    r.add_argument("--measurements", default=str(COST / "measurements.json"))
    r.add_argument("--out", default=str(COST / "report.md"))
    r.add_argument("--base-run", default="cold-w1")
    r.add_argument("--budget", type=float, default=90)
    r.add_argument("--output-cap", type=int, default=16000)
    r.add_argument("--max-workers", type=int, default=24)
    r.add_argument("--rps-cap", type=float, default=30)
    r.add_argument("--fallback-fraction", type=float, default=0.2, help="declared maximum fallback fraction")
    r.add_argument("--conservative-factor", type=float, default=1.25)
    r.add_argument("--verify-n", type=int, default=1000)
    r.add_argument("--distinct", type=int, default=FULL["distinct"])
    r.add_argument("--nonempty", type=int, default=FULL["nonempty"])
    r.add_argument("--decision", default=str(COST / "decision.json"), help="editable record of the chosen setup")


def run(args, log):
    cmd = args.cost_command or "replay"
    if cmd == "replay":
        if not getattr(args, "rates", None):  # bare `cost` -> default offline replay with default arguments
            import argparse
            ns = argparse.ArgumentParser()
            _replay_args(ns)
            args = ns.parse_args([])
        return replay(args, log)
    if cmd == "pilot":
        return pilot(args, log)
    if cmd == "collect":
        return collect(args, log)
    if cmd == "refresh":
        return refresh(args, log)
    raise SystemExit(f"unknown cost command {cmd}")
