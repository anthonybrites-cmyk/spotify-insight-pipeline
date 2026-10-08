# 100-review cost and runtime report

Generated 2026-10-08T06:25:35+00:00 by `python -m pipeline cost replay` from saved usage and `rates.csv`. Offline: no provider calls, no API key. Costs = billed units × editable rates; measured results never change when projection inputs change.

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

## Chosen setup and scaling decision (from `decision.json`)

The projections above are the calculator's required full-corpus estimate from the 100-review pilot, made with the plan of that time. After the 500 and 10,000 refreshes ([`refresh.md`](refresh.md)) the final setup was decided on 2026-10-06:

- **Scope:** seeded random sample of 100,000 of the 660,622 review IDs (78,146 distinct texts; seed spotify-insight-scope-100k-v1). The brief allows a scope of at least 100,000; every other row is ingested and accounted for as out_of_scope.
- **Budget:** $15 hard cap (budget group `full`): the instructor guided about $10 for 100,000 reviews; the refreshed projection was $10.06 base and $13.55 conservative.
- **Concurrency:** 5 workers, 30 requests/s: 10k run: median Jev call 147 ms and no rate-limit errors at 2 workers (12.2 texts/s); 5 workers reach the self-imposed 30 requests/s cap, below TypeSafe's published 40. Same cost, about 2.5x faster.
- **Fallback limit:** `claude-haiku-4-5` (effort none, Message Batches (50% price)) when min(topic, intent, severity confidence) < 0.5, at most 20% of texts, 8,000 output tokens per request: about a third of Sonnet 5's cost per review; on 30 held-out hard reviews Haiku got all three labels right on 16 vs Sonnet 17 and Jev 12.
- **Verification:** `claude-sonnet-5` on 1,000 random texts, Message Batches (50% price).
- **Memo:** `claude-opus-5-5` (effort high): one bounded call; chosen after human review of Sonnet 5 drafts.
- **Not used:** prompt caching: Haiku 4.5 caches only prompts of 4,096+ tokens (ours ~1,200); Sonnet verification would save cents; Jev has no prompt cache; translation: 10k language comparison showed a small gap; reuse of 10k results: only 2,054 of 78,146 texts overlap (~$0.13).
- **Outcome:** run `final100k-0f02b2df` cost $10.89 (10.63 run + 0.26 memo regenerations) at list prices in about 1.5 h of active run time ([`../results/run_summary.json`](../results/run_summary.json)).
