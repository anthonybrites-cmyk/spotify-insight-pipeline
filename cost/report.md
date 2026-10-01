# 100-review cost and runtime report

Generated 2026-10-01T06:59:31+00:00 by `python -m pipeline cost replay` from saved usage and `rates.csv`. Offline: no provider calls, no API key. Costs = billed units × editable rates; measured results never change when projection inputs change.

## Measured pilot runs

| Run | Kind | Workers | Wall-clock s | New calls (enrich / downstream) | API cost USD | per 1,000 rows | per completed record | rows/s |
|---|---|---|---|---|---|---|---|---|
| cold-w1 | cold | 1 | 110.588 | 101 / 42 | 0.177592 | 1.775917 | 0.001776 | 0.90 |
| cold-w1-warm | warm | 1 | 0.06 | 0 / 0 | 0.000000 | 0.000000 | 0.000000 | 1666.67 |
| cold-w2 | cold | 2 | 70.433 | 101 / 38 | 0.106308 | 1.063082 | 0.001063 | 1.42 |

### Stages: cold-w1

| Stage | Provider / model | Effort | Tier | Requests ok / attempts / failed | Reviews sent | Max batch | Input | Cache write | Cache read | Output | Max output/request | API USD | Stage s | Summed call s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| enrich_fallback | anthropic `claude-sonnet-5` | medium | standard | 1 / 1 / 0 | 7 | 7 | 2,632 | 0 | 0 | 1,326 | 1,326 | 0.018524 | 31.8 | 12.841 |
| enrich_jev | typesafe `jev-1.13.0` | n/a | standard | 100 / 100 / 0 | 100 | 1 | 152,841 | 0 | 0 | 22,363 | 293 | 0.006419 | 31.8 | 18.908 |
| group_assign | typesafe `jev-1.13.0` | n/a | standard | 37 / 37 / 0 | 37 | 1 | 21,246 | 0 | 0 | 3,245 | 119 | 0.000892 | 19.3 | 6.961 |
| group_taxonomy | anthropic `claude-sonnet-5` | medium | standard | 1 / 1 / 0 | 0 | 0 | 3,147 | 0 | 0 | 1,402 | 1,402 | 0.020314 | 19.3 | 12.353 |
| memo | anthropic `claude-sonnet-5` | medium | standard | 3 / 3 / 0 | 0 | 0 | 22,930 | 0 | 0 | 5,417 | 1,902 | 0.100030 | 39.3 | 39.279 |
| verify | anthropic `claude-sonnet-5` | medium | standard | 1 / 1 / 0 | 20 | 20 | 3,416 | 0 | 0 | 2,458 | 2,458 | 0.031412 | 20.1 | 20.061 |

Stage seconds come from the run log (wall-clock per stage; enrich includes the fallback, group includes taxonomy and assignment). Summed call seconds can exceed wall-clock when calls overlap.

### Stages: cold-w2

| Stage | Provider / model | Effort | Tier | Requests ok / attempts / failed | Reviews sent | Max batch | Input | Cache write | Cache read | Output | Max output/request | API USD | Stage s | Summed call s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| enrich_fallback | anthropic `claude-sonnet-5` | medium | standard | 1 / 1 / 0 | 7 | 7 | 2,629 | 0 | 0 | 1,514 | 1,514 | 0.020398 | 22.8 | 13.308 |
| enrich_jev | typesafe `jev-1.13.0` | n/a | standard | 100 / 100 / 0 | 100 | 1 | 152,841 | 0 | 0 | 22,363 | 293 | 0.006419 | 22.8 | 18.841 |
| group_assign | typesafe `jev-1.13.0` | n/a | standard | 35 / 35 / 0 | 35 | 1 | 20,020 | 0 | 0 | 2,889 | 103 | 0.000841 | 14.6 | 6.472 |
| group_taxonomy | anthropic `claude-sonnet-5` | medium | standard | 1 / 1 / 0 | 0 | 0 | 3,142 | 0 | 0 | 1,321 | 1,321 | 0.019494 | 14.6 | 11.301 |
| memo | anthropic `claude-sonnet-5` | medium | standard | 1 / 1 / 0 | 0 | 0 | 6,212 | 0 | 0 | 1,710 | 1,710 | 0.029524 | 14.8 | 14.741 |
| verify | anthropic `claude-sonnet-5` | medium | standard | 1 / 1 / 0 | 20 | 20 | 3,416 | 0 | 0 | 2,280 | 2,280 | 0.029632 | 18.3 | 18.245 |

Stage seconds come from the run log (wall-clock per stage; enrich includes the fallback, group includes taxonomy and assignment). Summed call seconds can exceed wall-clock when calls overlap.

## Full-run projection (estimates)

Base run `cold-w1`. Measured rates: Jev $0.0000642 per distinct text (1.000 attempts per success); fallback rate 0.070 (declared cap 0.2) at $0.002646 per review (measured fallback cost per review); verify $0.001571 per review × 1000; grouping assigns 0.370 of texts at $0.0000241 each; fixed overhead once: taxonomy $0.020314, memo $0.100030.

Full run: 660,622 rows, 660,609 nonempty classifications, 13 empty-text quarantines, 484,189 distinct texts with reuse. Budget $90.

| Scenario | Texts classified | Fallback fraction | Fallback price | Jev | Fallback | Verify | Taxonomy | Assign | Memo | **Total** | Budget |
|---|---|---|---|---|---|---|---|---|---|---|---|
| base (reuse, standard fallback) | 484,189 | 0.070 | standard | 31.08 | 89.69 | 1.57 | 0.02 | 4.32 | 0.10 | **126.78** | ⚠️ OVER |
| base (reuse, Batch-API fallback) | 484,189 | 0.070 | batch (est. 50%) | 31.08 | 44.85 | 1.57 | 0.02 | 4.32 | 0.10 | **81.94** | within |
| conservative (reuse, Batch-API fallback) | 484,189 | 0.200 | batch (est. 50%) | 38.85 | 160.16 | 1.96 | 0.02 | 5.40 | 0.13 | **206.52** | ⚠️ OVER |
| no reuse (base, Batch-API fallback) | 660,609 | 0.070 | batch (est. 50%) | 42.41 | 61.19 | 1.57 | 0.02 | 5.89 | 0.10 | **111.18** | ⚠️ OVER |

Notes: *base (reuse, standard fallback)*: measured pilot rates; exact-text reuse; *base (reuse, Batch-API fallback)*: planned full-run setup; Batch price is an estimate until measured; *conservative (reuse, Batch-API fallback)*: fallback at the declared cap; all variable costs x1.25 for retries/longer texts; *no reuse (base, Batch-API fallback)*: every nonempty row classified separately.

## Time projection (modelled)

One-worker pilot: 0.318 s of enrich stage per distinct text. Measured 2-worker enrich speedup: 1.39. At 24 workers, capped at 30 requests/s: ~30.0 texts/s → enrich ≈ 4.5 h, grouping ≈ 1.7 h. modelled, not measured: scaled from the one-worker pilot and capped at the rate limit; Batch-API fallback adds provider turnaround (most batches < 1 h, up to 24 h).

## Controls

- Spending limit: $90 (scenarios above flag any overrun). The pipeline enforces it in code by reserving worst-case cost before every call.
- Output-token cap per Claude request: 16,000; largest measured output 2,458; worst case one request's output $0.160000.
- Maximum workers: 24 (pilot measured at 1, and 2 where available).
- Declared maximum fallback fraction: 0.2.
- Local compute: unknown: runs on a personal laptop; not metered, not included in API spend.
