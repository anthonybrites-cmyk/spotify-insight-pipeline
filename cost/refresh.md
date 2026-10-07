# Cost calculator refresh: 500 and 10,000 checkpoints

Generated 2026-10-07T01:46:06+00:00 by `python -m pipeline cost refresh` from the saved call logs of the development runs and `rates.csv`. Offline: no provider calls. Measured values are billed units × editable rates; projections are estimates.

## Measured checkpoints

| Checkpoint | Input | Distinct texts | Workers | Wall-clock s | API cost (rates.csv) | Provider-reported total |
|---|---|---|---|---|---|---|
| 500 | `checkpoint_500.csv` | 479 | 24 | 214.6 | $0.4231 | $0.4231 |
| 10000 | `analysis_10000.csv` | 8,448 | 2 | 2701.5 | $4.4328 | $4.3236 |

The rates.csv column prices every billed attempt, including failed attempts that returned usage; the provider-reported total in the run summary counts successful calls only, so the two can differ slightly.

### Stages: 500

| Stage | Model | Mode | Requests ok / attempts | Reviews sent | Input tokens | Output tokens | USD | Median call ms |
|---|---|---|---|---|---|---|---|---|
| enrich_jev | `jev-1.13.0` | standard | 479 / 479 | 479 | 720,534 | 107,143 | 0.030262 | - |
| group_assign | `jev-1.13.0` | standard | 177 / 177 | 177 | 108,049 | 16,341 | 0.004538 | - |
| group_taxonomy | `claude-sonnet-5` | standard | 1 / 1 | 0 | 8,446 | 2,016 | 0.037052 | - |
| memo | `claude-sonnet-5` | standard | 7 / 7 | 0 | 51,872 | 13,482 | 0.238564 | - |
| verify | `claude-sonnet-5` | standard | 2 / 2 | 100 | 11,036 | 9,060 | 0.112672 | - |

Stage wall-clock seconds: {'enrich': 16.1, 'group': 24.6, 'ingest': 0.0, 'rank': 0.0, 'recommend': 105.8, 'verify': 68.1}.

### Stages: 10000

| Stage | Model | Mode | Requests ok / attempts | Reviews sent | Input tokens | Output tokens | USD | Median call ms |
|---|---|---|---|---|---|---|---|---|
| enrich_fallback | `claude-sonnet-5` | standard | 38 / 39 | 1,374 | 200,534 | 248,649 | 2.887558 | 72713 |
| enrich_jev | `jev-1.13.0` | standard | 8448 / 8448 | 8,448 | 12,953,477 | 1,899,099 | 0.544046 | 147.0 |
| group_assign | `jev-1.13.0` | standard | 3169 / 3169 | 3,169 | 1,971,039 | 315,335 | 0.082784 | 186 |
| group_taxonomy | `claude-sonnet-5` | standard | 1 / 1 | 0 | 16,020 | 2,582 | 0.057860 | 25934 |
| memo | `claude-sonnet-5` | standard | 1 / 1 | 0 | 6,244 | 1,878 | 0.031268 | 17493 |
| verify | `claude-sonnet-5` | standard | 12 / 12 | 560 | 67,129 | 69,502 | 0.829278 | 53002.5 |

Stage wall-clock seconds: {'enrich': 1758.3, 'group': 316.7, 'ingest': 0.2, 'rank': 0.0, 'recommend': 17.5, 'verify': 608.8}.

## Fallback model measured in evals

`claude-haiku-4-5` without extended thinking: 104 reviews, $0.056212 on the standard API → $0.000541 per review (sources: `evals/effort_test/calls.jsonl`, `evals/heldout/calls.jsonl`).

## Projection: 100,000-review seeded sample (78,146 distinct texts)

From the `10000` checkpoint: Jev $0.0000644 per text (retries included); fallback rate 0.163 (cap 0.2); verify $0.001481 per review standard × 1,000; grouping assigns 0.375 of texts at $0.0000261; fixed once: taxonomy $0.057860, memo $0.031268. Batch API prices are 50% of standard (estimate until the final run measures them).

| Scenario | Fallback fraction | Jev | Fallback | Verify | Taxonomy | Assign | Memo | **Total** | Cap |
|---|---|---|---|---|---|---|---|---|---|
| planned: Haiku Batch fallback, Sonnet Batch verify | 0.163 | 5.03 | 3.43 | 0.74 | 0.06 | 0.77 | 0.03 | **10.06** | within $15 |
| conservative: same, fallback at cap, x1.25 | 0.200 | 6.29 | 5.28 | 0.93 | 0.06 | 0.96 | 0.04 | **13.55** | within $15 |
| reference: Sonnet Batch fallback, Sonnet Batch verify | 0.163 | 5.03 | 13.36 | 0.74 | 0.06 | 0.77 | 0.03 | **19.98** | OVER $15 |
| reference: Haiku Batch fallback, Sonnet standard verify | 0.163 | 5.03 | 3.43 | 1.48 | 0.06 | 0.77 | 0.03 | **10.80** | within $15 |

Notes: *planned: Haiku Batch fallback, Sonnet Batch verify*: measured 10000 rates; Haiku cost from evals at Batch price (est. 50%); *conservative: same, fallback at cap, x1.25*: fallback at the declared 20% cap; variable costs x1.25 for retries/longer texts; *reference: Sonnet Batch fallback, Sonnet Batch verify*: the setup before the Haiku decision; *reference: Haiku Batch fallback, Sonnet standard verify*: before verification moved to the Batch API.

## Time projection (modelled)

Measured Jev call: median 147.0 ms, mean 163.3 ms. At 2 workers that models 12.2 texts/s; at 5 workers, capped at 30 requests/s: 30.0 texts/s → Jev enrichment ≈ 0.72 h, grouping ≈ 0.27 h. Fallback and verification: Batch API: provider turnaround (most batches finish within 1 h; up to 24 h). modelled from the measured mean Jev call time x workers, capped at the request-rate limit; the first slice of the final run (interruption demo) measures the planned worker count.
