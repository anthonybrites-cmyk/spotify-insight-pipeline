# 100-review cost and runtime calculator

Required by `COST_CALCULATOR.md`. Everything here can be checked **without an API key and without new model calls**.

## Offline replay (default; free)

```bash
.venv/bin/python -m pipeline cost            # same as: python -m pipeline cost replay
.venv/bin/python -m pipeline cost replay --budget 90 --max-workers 24 --fallback-fraction 0.2 --output-cap 16000
.venv/bin/python -m pipeline cost replay --rates my_rates.csv   # edit prices; measured usage stays fixed
```

Replay reads `usage.csv`, `rates.csv`, `pilot_calls.jsonl` and `measurements.json`. It rewrites `report.md` and `report.json`. Importing or running it never calls a provider.

How costs are calculated:
- **Formula:** `item_cost = billed_units × price_usd / per_units`, summed per stage and run. For per-million-token prices, `per_units` is 1,000,000.
- **Billing items** are mutually exclusive: input, cache-write input, cache-read input and output tokens. Claude's output tokens already include its reasoning ("thinking") tokens, so they are never added twice.
- **Tiers:** measured calls are priced at the tier actually used (`standard`). The Batch-API price appears only in projected scenarios, labelled as an estimate.
- **Gaps:** usage the provider didn't report is shown as missing, never zero. A usage item with no matching rate is listed as unpriced.
- **Invariants:** doubling every rate doubles API spend and leaves measured time unchanged. Changing projected volumes (`--distinct`, `--nonempty`, `--verify-n`) never changes the measured pilot results. Tests cover both.

## Paid pilot (explicit; costs money)

```bash
DATA="$HOME/code/NEW - Final Assignment - Spotify Reviews Dataset"
G="--exclude-golden $DATA/golden_50_to_label.csv"
.venv/bin/python -m pipeline cost pilot --input "$DATA/cost_100.csv" --label cold-w1 --workers 1 $G   # cold: empty result cache
.venv/bin/python -m pipeline cost pilot --input "$DATA/cost_100.csv" --warm-of cold-w1 --workers 1 $G  # warm: saved results
.venv/bin/python -m pipeline cost pilot --input "$DATA/cost_100.csv" --label cold-w2 --workers 2 $G   # cold, two workers
.venv/bin/python -m pipeline cost collect --records-from cold-w1   # build the evidence files below (offline)
.venv/bin/python -m pipeline cost replay                           # report (offline)
```

The pilot runs the real pipeline on `cost_100.csv`, unchanged:
- **Stages:** ingest, Jev enrichment with the capped Claude fallback, a declared verification sample of 20, grouping, ranking and the memo.
- **Settings:** standard API, Claude at medium reasoning effort, spend charged to the `dev` budget (cap $5).
- **Cold vs warm:** a cold run refuses to start if its folder already exists, so its result cache is always empty. A warm run reruns the same folder and must make zero new enrichment calls; any downstream calls are counted and reported.

## Files

| File | Contents |
|---|---|
| `rates.csv` | Editable prices, with units, tier, currency, source link and the date each was checked |
| `usage.csv` | One row per billed item per call, with the stage, model, tier and outcome needed to price it |
| `pilot_calls.jsonl` | Every attempted call in the cold and warm runs: run ID, request ID, role, stage, model, effort, attempt, outcome, review IDs, usage, start time and duration |
| `pilot_records.jsonl` | One final result or status per pilot review ID: contract row hash, common labels, `label_config`, and whether Jev or the Claude fallback decided it |
| `measurements.json` | Wall-clock time per run, stage times, new-call counts, record statuses and cache reuse |
| `report.md` / `report.json` | The measured-100 tables, full-run scenarios (base, conservative, no reuse), time model and controls |
| `runs/` | The pilot run folders themselves: every handoff, request and response |
