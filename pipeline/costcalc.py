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
        rows_in = meas["input"]["rows"]
        measured[label] = {"kind": m["kind"], "workers": m["workers"], "wall_clock_seconds": m["wall_clock_seconds"],
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

    report = {"generated_at": now(), "rates_file": str(args.rates), "missing_rates": [list(k) for k in missing],
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
          "| Run | Kind | Workers | Wall-clock s | New calls (enrich / downstream) | API cost USD | per 1,000 rows | per completed record | rows/s |",
          "|---|---|---|---|---|---|---|---|---|"]
    for label, m in r["measured"].items():
        down = sum(m["new_downstream_calls"].values())
        L.append(f"| {label} | {m['kind']} | {m['workers']} | {m['wall_clock_seconds']} | {m['new_enrichment_calls']} / {down} | "
                 f"{money(m['api_cost_usd'])} | {money(m['cost_per_1000_input_rows']) if m['cost_per_1000_input_rows'] is not None else '-'} | "
                 f"{money(m['cost_per_completed_record']) if m['cost_per_completed_record'] is not None else '-'} | "
                 f"{money(m['throughput_rows_per_s'], '0.01') if m['throughput_rows_per_s'] else '-'} |")
    for label, m in r["measured"].items():
        if m["kind"] != "cold":
            continue
        L += ["", f"### Stages: {label}", "",
              "| Stage | Provider / model | Effort | Tier | Requests ok / attempts / failed | Reviews sent | Max batch | Input | Cache write | Cache read | Output | Max output/request | API USD | Stage s | Summed call s |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        stage_secs = m["stage_seconds"]
        stage_map = {"enrich_jev": "enrich", "enrich_fallback": "enrich", "verify": "verify",
                     "group_taxonomy": "group", "group_assign": "group", "memo": "recommend"}
        for name, s in m["stages"].items():
            u = s["usage"]
            L.append(f"| {name} | {'/'.join(s['provider'])} `{'/'.join(s['model'])}` | {'/'.join(s['effort']) or 'n/a'} | "
                     f"{'/'.join(s['price_tier'])} | {s['requests_succeeded']} / {s['attempts']} / {s['failed_attempts']} | "
                     f"{s['reviews_sent']} | {s['max_batch_size']} | {u['input_tokens']:,} | {u['cache_write_input_tokens']:,} | "
                     f"{u['cache_read_input_tokens']:,} | {u['output_tokens']:,} | {s['max_output_tokens_one_request']:,} | "
                     f"{money(s['api_cost_usd'])} | {stage_secs.get(stage_map.get(name, name), '-')} | {s['summed_call_seconds']} |")
        L += ["", "Stage seconds come from the run log (wall-clock per stage; enrich includes the fallback, group "
              "includes taxonomy and assignment). Summed call seconds can exceed wall-clock when calls overlap."]
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
    raise SystemExit(f"unknown cost command {cmd}")
