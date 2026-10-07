# Spotify review insight pipeline (Final Assignment)

Advising Spotify at the end of the May 2022 – Nov 2023 review window: **where should next quarter's product effort go — access, usability, playback, or billing/support?** This repository is a saved program that turns the 660,622-review CSV into that recommendation, with traceable evidence.

> **Status (2026-09-30): development runs complete; the full-corpus run has not been made yet.** [Development results](#development-results) come from real model calls on the 500-review checkpoint, the hand-labelled golden 50 and 13 synthetic injection cases. Anything about the full run is marked *pending*. Offline tests use fake providers and are **not** run evidence.

- **Live dashboard: https://spotify-insight-dashboard.vercel.app** (public, read-only, no login). It currently shows the 500-review development run; the final run replaces it.
- Grading export: [`grading/`](grading/) *(pending: final run)*
- Human-readable results: [`results/`](results/) *(pending: full run)*
- Decision memo: [`results/memo.md`](results/memo.md) *(pending)*
- Design choices and label examples: [`DESIGN.md`](DESIGN.md)
- Golden-set labelling instructions: [`evals/golden/LABELING.md`](evals/golden/LABELING.md)
- **100-review cost/runtime calculator:** [`cost/`](cost/), with a [measured report](cost/report.md) and [offline replay instructions](cost/README.md)

## Rubric → evidence map

| Rubric item | Evidence |
|---|---|
| **Deliverable 1** Accessible code, setup and artifacts | [Setup](#setup), [Run](#run), `requirements.txt`, `.env.example` (key names only), [`results/`](results/) *(pending)* |
| **Deliverable 2** Architecture, shared schema, provenance | [Architecture](#architecture), `pipeline/rubric.py` (Jev questions), `pipeline/verify.py` / `group.py` / `memo.py` (role prompts and schemas), `label_config` on every record and call, `run_manifest.json` (code version, argv, settings) |
| **Deliverable 3** Memo numbers linked to calculations and evidence | `claims.csv` ↔ `ranking.csv` (course checker recomputes both), `memo_check.json` (every number cited, and every issue ID, review ID and quote validated). Development: [`evals/dev500/memo_v2.md`](evals/dev500/memo_v2.md), [`claims.csv`](evals/dev500/claims.csv), [`memo_check_v2.json`](evals/dev500/memo_check_v2.json). Final: *(pending)* |
| **Deliverable 4** Recommendation, alternatives, limitations | Development memo [`evals/dev500/memo_v2.md`](evals/dev500/memo_v2.md); final [`results/memo.md`](results/memo.md) *(pending)*; [Limits](#limits) |
| **Testing 1** 50 human labels, per-field comparison, error analysis | [`evals/golden/golden_50_human_labels.csv`](evals/golden/golden_50_human_labels.csv), [`summary.json`](evals/golden/summary.json), [`cases.json`](evals/golden/cases.json), [`disagreements.md`](evals/golden/disagreements.md), [`head_to_head.json`](evals/golden/head_to_head.json); [Golden set](#golden-set-50-hand-labelled-reviews) |
| **Testing 2** Independent verification, planted-error and injection tests | [`evals/dev500/verification_report.json`](evals/dev500/verification_report.json), [`verification_comparisons.json`](evals/dev500/verification_comparisons.json), [`planted_label_test.json`](evals/dev500/planted_label_test.json), [`evals/injection_results.json`](evals/injection_results.json), [`evals/offline/planted_export_errors.json`](evals/offline/planted_export_errors.json) |
| **Testing 3** Real 100-review cold/warm pilot, offline calculator, retry/spending/recovery controls | [`cost/report.md`](cost/report.md): measured cold, warm and 2-worker pilot. [`cost/README.md`](cost/README.md): offline `python -m pipeline cost` replay. Evidence: [`cost/pilot_calls.jsonl`](cost/pilot_calls.jsonl), [`usage.csv`](cost/usage.csv), [`rates.csv`](cost/rates.csv), [`pilot_records.jsonl`](cost/pilot_records.jsonl). Controls: `pipeline/retry.py`, `pipeline/budget.py`, [`evals/offline/test_report.txt`](evals/offline/test_report.txt); `results/run_summary.json` *(pending, full run)* |
| **Working 1** Full ingestion, coverage, classification | `results/ingestion_report.json`, `grading/ingestion.json`, self-check coverage *(pending)* |
| **Working 2** Staged program, bounded calls, handoffs, resume | `python -m pipeline run`, `grading/calls.jsonl.gz`, `checkpoint_before.json` / `checkpoint_after.json`, recording *(pending)* |
| **Working 3** Reproducible ranking; deployed dashboard backed by a database, with grounded AI recommendations | `python -m pipeline rerank --grading-dir grading` (no model calls); live dashboard https://spotify-insight-dashboard.vercel.app ([Dashboard, backend and database](#dashboard-backend-and-database)); memo *(final run pending)* |

## Architecture

```mermaid
flowchart TD
    CSV[/"input CSV (any path)"/] --> I
    subgraph code_ingest [1 INGEST - code]
      I["csv parser, row_sha per row<br/>quarantine empty text<br/>group exact-duplicate texts"]
    end
    I -->|"ingest/sources.jsonl, units.jsonl<br/>ingestion_report.json, data_manifest.json"| E
    subgraph enrich [2 ENRICH - Jev + code validation]
      E["orchestrator: pending units only<br/>rate limit, spend cap, 10% early gate, time cap"] --> J(("Jev jev-1.13.0<br/>1 review per request"))
      J --> V{"code check:<br/>schema, allowed labels,<br/>quote substring, ID"}
      V -->|invalid: retry once| J
      V -->|still invalid| Q[("quarantine<br/>reason + attempts")]
      V -->|valid| S[("enrich/results.jsonl<br/>saved per request")]
      S -->|"Jev confidence below 0.5"| FB(("Claude fallback<br/>blind re-label, 50 per request<br/>standard or Batch API"))
      FB --> FV{"code check:<br/>IDs, enums,<br/>exact quote"}
      FV -->|"bad quote: 1 retry"| FB
      FV -->|"ok: final labels; still invalid: keep Jev + needs_review"| S
      J -.->|"429/5xx: bounded backoff"| J
    end
    S -->|"declared random sample, labels hidden"| VF
    subgraph verify [3 VERIFY - claude-sonnet-5 + code]
      VF(("blind re-label<br/>50 reviews per request")) --> VC["code compares;<br/>disagreements -> needs_review;<br/>planted wrong label on a copy"]
    end
    S --> G1
    subgraph group [4 GROUP - claude-sonnet-5 + Jev + code]
      G1(("Claude proposes subtopics<br/>from saved complaint quotes")) --> G2["code validates;<br/>adds topic.general"] --> G3(("Jev assigns each complaint<br/>to one subtopic"))
    end
    G3 -->|"group/assignments.jsonl (saved mapping)"| R
    subgraph rank [5 RANK - code only]
      R["priority = severity_sum = count x mean<br/>sort -score, +issue_id; half-up means"]
    end
    R -->|"ranking.csv, membership.csv"| M
    subgraph recommend [6 RECOMMEND - claude-sonnet-5 + code check]
      M(("memo from aggregates +<br/>bounded evidence pack")) --> MC{"code: every number cited,<br/>IDs exist, no revenue/churn"}
      MC -->|"errors fed back, max 2 revisions"| M
    end
    MC --> OUT[/"grading/ + results/ + memo.md"/]
```

In the diagram, circles are model judgments and rectangles and diamonds are code. Code owns dispatch, state, validation, budgets, retries, record accounting and every piece of arithmetic. The models only read language:

- **Jev** answers fixed-choice questions.
- **Claude** handles blind verification, naming subtopics, and writing the memo.

Every handoff is saved, and each stage has its own stop condition:

| Stage | Input | Output | On failure | Stops when |
|---|---|---|---|---|
| ingest | CSV | sources, units, profiles | duplicate ID → abort (contract needs one record per ID) | file read |
| enrich | pending units | results, failures, checkpoints | invalid → 1 retry → quarantine; transient → backoff ≤5 attempts | all units done, spend cap, early gate, time cap, Ctrl-C, `--stop-after-units` |
| verify | declared random sample (text only) | verdicts, report, planted test | invalid → 1 retry with the error; transient → backoff | sample done or cap |
| group | complaint quotes → taxonomy; complaint texts → Jev | issues.json, assignments.jsonl | failed assignment → `<topic>.general` with the reason recorded | all complaints assigned |
| rank | records + membership | ranking.csv, membership.csv | invalid severity or duplicate pair → abort | — |
| recommend | aggregates + evidence pack | memo.md, claims, check | check errors fed back, up to 2 revisions, then saved with the failing check | check passes or 3 rounds |

## How this is a multi-agent pipeline

The brief defines it this way: distinct roles with inspectable handoffs, coordinated by code. Unrestricted autonomy and multiple providers are not required. Each agent below has its own instructions, inputs, output schema, saved evidence and stop rule. Every model call is logged with its role in `calls.jsonl`. The **code orchestrator** (`pipeline/cli.py`, `pipeline/dispatch.py`) runs a fixed sequence. It chooses the next step, enforces budgets and retries, validates every handoff, and owns all record accounting and arithmetic.

| Agent (role in `calls.jsonl`) | Model | Instructions | Reads | Writes (saved handoff) | Stops / on failure |
|---|---|---|---|---|---|
| Enricher (`enrich`) | `jev-1.13.0` | question set in `pipeline/rubric.py` | one review's text | `enrich/results.jsonl` | all texts done, or a cap; invalid output → 1 retry → quarantine |
| Fallback enricher (`enrich`) | `claude-sonnet-5` | `pipeline/fallback.py` | low-confidence texts only, blind, ≤50 per request, ≤20% of texts | `enrich/fallback.jsonl` | cap reached; bad quote → 1 retry → keep Jev's labels, flagged `needs_review` |
| Verifier (`verify`) | `claude-sonnet-5` | `pipeline/verify.py` | declared random sample, blind to the enricher | `verify/comparisons.json`, `verify/report.json` | sample done; invalid → 1 retry with the error |
| Issue designer (`group`) | `claude-sonnet-5` | `pipeline/group.py` | a bounded sample of complaint quotes | `group/issues.json` | one request, schema-checked |
| Issue assigner (`group`) | `jev-1.13.0` | one Choice question per topic | one complaint's text | `group/assignments.jsonl` | all complaints assigned; failure → catch-all issue, recorded |
| Memo writer (`memo`) | `claude-sonnet-5` | `pipeline/memo.py` | saved aggregates plus a bounded evidence pack only | `memo/memo.md`, `memo/check.json` | code check passes, up to 2 revisions |

The same program and the same agents run at every scale: the 100-review pilot, the 500 and 10,000 checkpoints, and the final run. "Workers" (`--workers`) is concurrency *within* an agent, several requests in flight at once sharing one rate limiter and one spend ledger. It is not additional agents.

## Dashboard, backend and database

**Live:** https://spotify-insight-dashboard.vercel.app. It's public and read-only, with no account needed, and viewing it never calls a model.

```mermaid
flowchart LR
    R[("finished run folder<br/>records, ranking, issues,<br/>claims, facts, memo")] -->|"python -m pipeline publish<br/>(owner role, local)"| DB[("Neon Postgres<br/>runs, reviews, issues, topic_metrics,<br/>claims, facts, recommendations")]
    DB -->|"SELECT-only role<br/>dashboard_reader"| API["Backend: Next.js API routes on Vercel<br/>/api/overview, /api/issues, /api/issues/[id],<br/>/api/reviews/[id], /api/recommendation, /api/runs"]
    API -->|JSON| UI["Dashboard pages (browser)<br/>overview metrics, topic chart, issue ranking,<br/>issue members + evidence quotes, review lookup,<br/>AI recommendation with linked claims/issues/reviews"]
```

- **Database** (`db/schema.sql`): `python -m pipeline publish` loads a finished run's saved outputs: every review record with its source text and labels, plus issues, the ranking, per-topic metrics, claims, facts and the AI-generated memo. `python -m pipeline db-setup` creates the tables and a **SELECT-only** role for the dashboard; its password is generated straight into `.env` and never printed.
- **Backend** (`dashboard/app/api/*`): route handlers query Postgres at request time. Every parameter is validated against a strict pattern, and queries are parameterised. The read-only connection string exists only as a server-side Vercel secret.
- **Dashboard** (`dashboard/app/*`): pages fetch only from the backend API.
- **AI recommendation:** the memo written by `claude-sonnet-5` from the saved aggregates. Every claim ID links to its issue and number, every issue ID to its member reviews, and every review ID to the original text with the evidence quote highlighted.
- **Why the numbers match:** the dashboard shows exactly what is in `ranking.csv`, `claims.csv` and the records that the course checker recomputes.
- **Run it locally:**
  ```bash
  cd dashboard && npm install && echo "DASHBOARD_DATABASE_URL=..." > .env.local && npm run dev
  ```

## Models, settings and roles

| Role (`calls.jsonl`) | Model ID | Settings | Prompt version |
|---|---|---|---|
| enrich | `jev-1.13.0` (pinned, not the alias) | 1 review per request; Choice for topic, intent and severity; Score for sentiment; Noul for "unclear"; Choice over code-cut sentences for the quote | `label_config` = `jev-1.13.0+prompt-<hash>+schema-v1` |
| enrich (fallback) | `claude-sonnet-5` | re-labels **blind** every text whose minimum Jev confidence is below 0.5; up to 50 reviews per request; JSON schema with an exact-substring quote; standard API (10k) or Message Batches API at 50% price (full run) | `label_config` gains `+fallback-claude-sonnet-5-t0.5-<hash>` for every record in the run |
| verify | `claude-sonnet-5` | adaptive thinking, effort medium, JSON-schema output, 50 per request, `max_tokens` 16000 | `claude-sonnet-5+verify-<hash>+schema-v1` |
| group | `claude-sonnet-5` then `jev-1.13.0` | taxonomy via JSON schema; Jev Choice per complaint | `...+group-taxonomy-<hash>`, `...+group-assign-<hash>` |
| memo | `claude-sonnet-5` | plain markdown, code check, up to 3 rounds | `claude-sonnet-5+memo-<hash>+schema-v1` |

Each hash is taken over the exact prompt, schema and post-processing rules, so changing any of them creates new work rather than reusing cached results. Only `review_text` is sent to any model. The golden-50 human labels are read only by `score-golden`. Golden review IDs are also kept out of the verification sample, the taxonomy examples and the memo evidence pack (`--exclude-golden`).

## Setup

Python 3.11 is required.

```bash
git clone <this repo> && cd spotify-insight-pipeline
python3 -m venv .venv && .venv/bin/pip install --no-cache-dir -r requirements.txt   # anthropic==0.86.0; rest is stdlib
cp .env.example .env    # then paste TYPESAFE_API_KEY and ANTHROPIC_API_KEY (only needed for paid runs)
.venv/bin/python -m pipeline keys   # prints True/False per key, never the value
```

Data: download the course ZIP from the link in the assignment brief, unzip it anywhere, and point `DATA` at that folder. The raw CSV is not committed. Its SHA-256 is `1fc85de68a304dd8978b537cfa58793d5f41cbaf417fa32cb53899f83a2fcef6` (97,400,616 bytes).

## Run

**No API key is needed to inspect or re-rank.** These commands make no model calls:

```bash
.venv/bin/python -m pipeline rerank --grading-dir grading     # recompute ranking from records + membership; diff vs saved
.venv/bin/python -m pipeline check --input "$DATA/spotify_reviews_18months.csv" --grading-dir grading --out-dir runs/check
.venv/bin/python -m unittest discover -s tests -v             # offline tests (fake providers)
```

**Paid runs** (`DATA="$HOME/code/NEW - Final Assignment - Spotify Reviews Dataset"`; `G="--exclude-golden $DATA/golden_50_to_label.csv"`):

```bash
# 1) 500-review development run (done; development cap raised from $2 to $5 on 2026-09-30)
.venv/bin/python -m pipeline run --input "$DATA/checkpoint_500.csv" --run-dir runs/dev500 $G \
  --budget-group dev --budget-usd 5 --verify-n 100 --grading-dir runs/dev500/grading --results-dir runs/dev500/results
# 2) 10,000-review development checkpoint with the Claude fallback (standard API); also verifies all 268
#    non-English texts as a separate stratum
.venv/bin/python -m pipeline run --input "$DATA/analysis_10000.csv" --run-dir runs/dev10k $G \
  --budget-group dev --budget-usd 10 --fallback standard --claude-effort medium --workers 2 --verify-n 300 \
  --verify-extra-groups non_english_latin,non_latin_script \
  --grading-dir runs/dev10k/grading --results-dir runs/dev10k/results
# 2b) Only if non-English agreement is clearly worse: translation test on those 268 texts
#     (enrichment only; reuses the 10k run's blind verifier labels; no second verification)
.venv/bin/python -m pipeline subset --input "$DATA/analysis_10000.csv" --out runs/lang10k/non_english.csv
.venv/bin/python -m pipeline run --input runs/lang10k/non_english.csv --run-dir runs/lang10k --translate \
  --stages ingest,enrich --budget-group dev --budget-usd 5 --fallback standard
.venv/bin/python -m pipeline compare-translation --baseline-run runs/dev10k --translated-run runs/lang10k
# 3) Golden set: enrichment only, on a copy with the labels stripped; then score against your labels
.venv/bin/python -m pipeline golden-input --golden "$DATA/golden_50_to_label.csv" --out runs/golden/golden_50_texts.csv
.venv/bin/python -m pipeline run --input runs/golden/golden_50_texts.csv --run-dir runs/golden --stages ingest,enrich \
  --budget-group dev --budget-usd 5
.venv/bin/python -m pipeline score-golden --run-dir runs/golden --golden evals/golden/golden_50_human_labels.csv
.venv/bin/python -m pipeline score-golden --run-dir runs/golden --golden evals/golden/golden_50_human_labels.csv \
  --adjudication evals/golden/adjudication.json --out-dir evals/golden/adjudicated   # post-hoc labels, reported separately
# 4) Final run: a seeded 100,000-review sample of the full corpus (every row is still ingested; the rest are
#    quarantined "out of scope"). Haiku 4.5 fallback and Sonnet 5 verification both via the Message Batches API,
#    5 workers (Jev at <= 30 requests/s), hard cap $15. First invocation: interruption demo (recorded), then resume.
F="--input $DATA/spotify_reviews_18months.csv --run-dir runs/final100k $G --scope-sample 100000 \
  --budget-group full --budget-usd 15 --fallback batch --fallback-model claude-haiku-4-5 --fallback-effort none \
  --verify-n 1000 --verify-mode batch --workers 5"
.venv/bin/python -m pipeline run $F --stop-after-units 5000
.venv/bin/python -m pipeline run $F --grading-dir grading --results-dir results
# 5) Live prompt-injection cases (synthetic, excluded from business results)
.venv/bin/python -m pipeline eval-injection
```

**Resume:** rerun the same command. Completed units under the same `label_config` are never sent again. Calls made after the first invocation are logged as `phase: "resume"`.

**Stopping for the day:** `--max-minutes N` stops dispatching after N minutes and saves; a Batch API job keeps processing on Anthropic's side and the saved batch ID is polled on the next run, from any network.

**Interrupt:** press Ctrl-C once for a graceful stop. The program finishes in-flight requests, saves them, and writes a `completed_ids` snapshot. A second Ctrl-C aborts immediately.

## Spending, retries and failure accounting (all in code)

- **Hard cap per budget group.** The ledger in `budgets/<group>.jsonl` persists across runs. Before each call, a worst-case cost is reserved; for Claude that includes the full `max_tokens` of output. The call is not sent if it could exceed the cap.
- **Early 10% gate.** At 10% of enrichment units, the run's spend must be at most 10% of the cap. Otherwise the run halts and prints a projection. It continues only with `--accept-early-gate`.
- **Time cap.** `--max-minutes` stops dispatching and saves progress.
- **Retries.** Invalid output is retried **at most once**; for Claude, the validation error is fed back. After that, the unit is quarantined with the reason and attempt count. Rate limits and transient errors get bounded exponential backoff that honours `retry-after`: up to 5 attempts for Jev, 4 for Claude. Every failed attempt is logged as `outcome: "failed"`.
- **Exact-duplicate reuse.** 660,609 nonempty rows collapse to 484,189 distinct texts. The other IDs get `cache_source_id` pointing to the directly classified original. Every ID keeps its own record and is counted separately.
- **Statuses.** Each record is `completed`, or `quarantined` with a `reason` and `attempts`. Reasons are `empty_review_text`, `enrich_failed: …`, or `pending_not_processed` for an incomplete run.
- **Usage and cost.** These are provider-reported tokens times published list prices (Jev $0.042 per million input tokens, output free; Sonnet 5 $2/$10 per million), reported in `run_summary.json`. Failed attempts that returned no usage are logged with 0 tokens and `usage_available: false`; they are not estimated.

## 100-review cost and runtime pilot

Full report: [`cost/report.md`](cost/report.md). Measured on `cost_100.csv` (sha256 `c884ac3b…`, unchanged). Every stage ran: Jev enrichment with the capped Claude fallback, a declared 20-review verification sample, grouping, ranking and the memo.

| Run | Workers | Wall-clock | New calls | API cost |
|---|---|---|---|---|
| cold | 1 | 110.6 s | 143 (101 enrichment) | $0.1776 |
| warm (saved results) | 1 | 0.06 s | **0** | $0 |
| cold | 2 | 70.4 s | 139 (101 enrichment) | $0.1063 |

- **Records:** all 100 completed and 0 failed, with 0 retries. 7 of the 100 texts went to the Claude fallback, under the 20% cap.
- **Cold-run memo cost:** the one-worker cold run spent $0.10 on the memo across 3 rounds. Rounds 2–3 were caused by a quote-check bug the pilot exposed, now fixed; all three drafts pass the corrected check.
- **Measured cost per review:** Jev $0.0000642 per distinct text, the Claude fallback $0.0026, and verification $0.0016.
- **Full-run projection** at the measured rates, with the planned Batch-API fallback: **~$82 base** (under the $90 cap) and ~$207 conservative (fallback at the full 20% cap and variable costs ×1.25). The projection is refreshed after the 500 and 10,000 runs.

### Checkpoint refresh after the 500 and 10,000 runs ([`cost/refresh.md`](cost/refresh.md))

`python -m pipeline cost refresh` (offline) re-prices the saved call logs of both development runs (committed as `evals/dev500/` and `evals/dev10k/calls.jsonl.gz`) with `cost/rates.csv`, adds the Haiku fallback cost measured in the evals ($0.000541 per review over 104 reviews), and projects the final 100,000-review scope (78,146 distinct texts):

| Scenario | Projected cost |
|---|---|
| **Planned:** Haiku Batch fallback (16.3% of texts, measured), Sonnet Batch verification of 1,000 | **~$10.06** |
| Conservative: fallback at the 20% cap, variable costs ×1.25 | ~$13.55 |
| Reference: Sonnet Batch fallback | ~$19.98 |
| Reference: Haiku fallback, verification on the standard API | ~$10.80 |

Time (modelled from the measured 147 ms median Jev call): 5 workers, capped at 30 requests/s, gives ≈ 0.7 h of Jev enrichment and ≈ 0.3 h of grouping (2 workers measured 12.2 texts/s in the 10k run), plus Batch API turnaround for the fallback and verification (usually under an hour). The interruption-demo slice of the final run measures the 5-worker rate.

## Decisions log

| Date | Decision | Evidence / reason |
|---|---|---|
| 2026-09-29 | Jev for every review's fixed labels; Claude for verification, taxonomy and memo | Brief guidance; Claude for every review was measured at ~$270–540 |
| 2026-09-30 | Severity 5 adds health/physical harm, **clarified to an actual injury such as hearing loss** | Your call while labelling; prompted by golden row `46c0b49f…` (disclosed, see DESIGN.md) |
| 2026-09-30 | Golden labels scored strictly; ambiguity goes in separate columns | The brief asks for an ambiguous-case count; the instructor's multiple accepted labels apply only to their benchmark |
| 2026-09-30 | Keep the **full** Jev wording | Compact wording saved 28% of tokens but cost 3 points of topic agreement on the same verifier labels |
| 2026-09-30 | **Claude fallback for every text with Jev confidence below 0.5**: standard API for the 10k run, Batch API for the full run; full-run cap **$90**; development cap **$5** | Golden head-to-head in the low band: Jev 1/7 vs Claude 5/7 all-correct (disclosed); to be checked on ~30 fresh held-out 10k reviews |
| 2026-09-30 | Premium-locked controls → `billing` (verifier and fallback prompts state it explicitly); your adjudication of golden disagreements recorded separately | Your answers (a)–(d); [`evals/golden/adjudication.json`](evals/golden/adjudication.json) |
| 2026-09-30 | Severity for paywalled controls stays on the **contract's reading**: a control explicitly locked behind Premium is a restricted function (3); ad overload alone is annoyance (2) | The contract defines 3 as "a degraded or restricted function", and the instructor's benchmark follows the contract. Your golden labels of 2 on those rows stand as your judgment and are explained in the error analysis |
| 2026-09-30 | Declared fallback cap **20%** of distinct texts, lowest confidence first; **1 worker by default**; Claude reasoning effort and output cap are part of every Claude config tag | Updated brief and `COST_CALCULATOR.md` |
| 2026-09-30 | Real cold and warm pilot at 1 worker, plus a cold pilot at 2 workers | Your call; the 2-worker run measured a 1.39× enrich-stage speedup |
| 2026-10-01 | Development cap raised to **$10**; Claude reasoning effort stays **medium** for the fallback and verifier | Effort test: low saved about 17% per review but changed 27% of fallback decisions and matched the human on 4 of 7 golden low-confidence reviews, versus 5 of 7 for medium ([`evals/effort_test/report.json`](evals/effort_test/report.json)) |
| 2026-10-06 | **Final run scope: a seeded random sample of 100,000 review IDs** (the updated brief accepts ≥100,000), **sampled IDs only**: exact-duplicate copies outside the sample are quarantined as out of scope, not completed by reuse | Projected ~$11–16 against ~$65–93 for the full corpus. Sample-only keeps the business aggregates a fair random sample; including copies would complete about 238,000 rows but over-weight repeated short texts. All 660,622 rows are still ingested, profiled and accounted for. |
| 2026-10-06 | **Fallback model: Claude Haiku 4.5 without extended thinking, via the Batch API, for every qualifying text (≤20% cap)**; verification (1,000), taxonomy and memo stay on Sonnet 5; final-run hard cap **$15** | Sonnet fallback measured at $0.00204 per review vs Haiku $0.00052. Projected 100k run: ~$10.65 with Haiku vs ~$20 with Sonnet (both Batch). Haiku got all three labels right on 3 of 7 golden low-confidence reviews, vs 5 of 7 for Sonnet and 1 of 7 for Jev ([`evals/effort_test/`](evals/effort_test/)) |
| 2026-10-06 | **Class 7 review (parallel, caching, batching):** verification moves to the Batch API (`--verify-mode batch`, saves ~$0.74); 5 workers instead of 2 (same cost, ≈2.5× faster, within the 30 requests/s cap under TypeSafe's 40); no prompt caching (Haiku 4.5 caches only prompts of 4,096+ tokens and ours are ~1,200; Sonnet verification would save cents; Jev has no prompt cache and already asks all questions in one request); no reuse of 10k results (only 2,054 of 78,146 texts overlap, ~$0.13) | Class 7 slides 50–70; [`cost/refresh.md`](cost/refresh.md) |
| 2026-10-06 | No translation | 10k language strata, all-three agreement with the verifier: English 77.0%, Latin-script non-English 71.6%, non-Latin script 88.4%. A modest gap, and translation would add cost |

## Development results

Everything below comes from real API calls, as recorded in each run's `calls.jsonl`.
- **Cost:** provider-reported tokens multiplied by list price. These are not invoices.
- **Spend:** total development spend so far is **$0.53** of the $2 development cap.

### 500-review checkpoint (`checkpoint_500.csv`)

| Measure | Value |
|---|---|
| Source rows / completed / quarantined | 500 / **500** / 0 |
| Distinct texts sent to Jev / exact-duplicate reuses (`cache_source_id`) | 479 / 21 |
| Failed calls / retries | 0 / 0 |
| `needs_review` true | 78 (15.6%) |
| Issues ranked / complaint memberships | 37 / 248 |
| Course checker coverage | 500/500 valid; its only flags are the missing interruption/resume evidence, which comes from the full run ([`self-check.json`](evals/dev500/self-check.json)) |
| `rerank` from the saved export | identical ranking (sha256 `09b2b327…`) |
| Wall-clock time by stage | enrich 16 s, verify 68 s, group 25 s, memo 106 s (three memo invocations) |

**Usage and cost by role:**

| Role | Model | Successful calls | Input tokens | Output tokens | Cost |
|---|---|---|---|---|---|
| enrich | `jev-1.13.0` | 479 | 720,534 | 107,143 | $0.0303 |
| verify | `claude-sonnet-5` | 2 | 11,036 | 9,060 | $0.1127 |
| group (taxonomy) | `claude-sonnet-5` | 1 | 8,446 | 2,016 | $0.0371 |
| group (assignment) | `jev-1.13.0` | 177 | 108,049 | 16,341 | $0.0045 |
| memo | `claude-sonnet-5` | 7 | 51,872 | 13,482 | $0.2386 |
| **Total** | | | | | **$0.4231** |

The memo was run three times. The first version used an outdated prompt structure, which was then fixed ([`memo_v1_old_prompt.md`](evals/dev500/memo_v1_old_prompt.md)). The second time, a false alarm in the money check forced a revision; the check now allows sentences that only say money data is absent. The development memo ([`memo_v2.md`](evals/dev500/memo_v2.md)) recommends **usability**: `usability.ad_frequency` (rank 2) and `usability.playback_control_restrictions`, closely tied to `billing.features_locked_behind_premium` (rank 3). Rank 1, `other.general`, holds non-specific complaints. *Development sample only; the final recommendation comes from the full run.*

### Independent verification: Claude labels blind, code compares

The declared random sample is 100 distinct texts; golden-50 IDs are excluded. The verifier never sees Jev's labels.

| Jev confidence band | n | Topic | Intent | Severity exact | All three | Material disagreements |
|---|---|---|---|---|---|---|
| All (headline) | 100 | 90% | 98% | 87% | 77% | 13 |
| High (≥0.8) | 61 | 95% | 98% | 98% | 92% | 4 |
| Mid (0.5–0.8) | 27 | 85% | 96% | 74% | 59% | 6 |
| Low (<0.5) | 12 | 75% | 100% | 58% | 42% | 3 |

- **Planted wrong label.** In a separate copy of the comparisons, Jev's topic was deliberately changed on 25 agreeing cases. The comparison code caught **25 of 25**.
- **Who is right varies.** On premium-only controls, the contract says `billing`. Jev followed that, while Claude chose `usability` (e.g. `66c56c76…`). *[Labeller: billing; the verifier was wrong. The verifier and fallback prompts now state this rule explicitly.]*

### Golden set (50 hand-labelled reviews)

The labels were written and committed before any model run (commit `821258d`). Enrichment ran on a copy with the label columns stripped (`golden-input`). The scoring is strict: each prediction must match the single primary human label.

| | Topic | Intent | Severity exact | All three | Severity MAE |
|---|---|---|---|---|---|
| **Jev (pipeline)** | 88% | 96% | 84% | 74% | 0.24 |
| Lenient: also accepts the alternatives you noted | 90% | 98% | 88% | — | — |
| Adjudicated: your post-hoc decision (c) applied, `dceb14e7…` topic → playback ([`adjudication.json`](evals/golden/adjudication.json)) | 90% | 96% | 84% | 76% | 0.24 |

Other measures:
- **Sentiment:** MAE 0.118; 48 of 50 within the predeclared ±0.5 tolerance.
- **Ambiguous cases:** 4.
- **Missing or quarantined predictions:** 0.
- **`needs_review` treated as a prediction:** precision 0.33, recall 0.33 (2 true positives, 4 false positives, 4 false negatives). It does not yet track human judgment well.

**Error analysis.** 13 rows have a label disagreement and 1 differs only on sentiment; all are listed in [`disagreements.md`](evals/golden/disagreements.md). Your adjudication of each pattern is in brackets. The main patterns:
1. **Severity 2 vs 3 for premium restrictions and ad load.** Jev rates "basic features are premium" and "unusable with constant ads" as 3 (a restricted function). The human label is 2 (annoyance). *[Labeller: 2, annoyance. The classifier deliberately keeps the contract's reading, though: a control explicitly locked behind Premium is a restricted function (3), and ad overload alone is 2. So on `991b6b3a…` ("limited functionality") and `16d640e9…` ("basic features is premium"), the disagreement is a documented definitional choice. On `d2f3874f…` ("unusable with constant ads"), Jev's 3 is an error even under the contract's reading.]*
2. **Usability vs playback** when an update removes controls ("can't play the songs I like / can't rewind"). Jev chose playback; the human chose usability. *[Labeller, post hoc: **playback**. Jev was right and the original golden label was the error; see the adjudicated row above.]*
3. **Health harm.** For "my ears feel like they explode", Jev chose 5 under the amended severity-5 definition; the human label is 2. *[Labeller: 2. This is not serious harm; level 5 needs an actual injury such as hearing loss. The rubric now says so.]*
4. **Low confidence predicts errors.** Jev got all three labels right on only 1 of the 7 golden reviews where its confidence was below 0.5.

**Jev vs Claude on the same 50** ([`head_to_head.json`](evals/golden/head_to_head.json), one Claude call, $0.064). This comparison is disclosed because it informs the choice of final setup.

| Jev confidence band | n | Jev all three | Claude all three |
|---|---|---|---|
| High (≥0.8) | 32 | **90.6%** | 84.4% |
| Mid | 11 | **63.6%** | 54.5% |
| Low (<0.5) | 7 | 14.3% | **71.4%** |
| All | 50 | 74% | 76% |

### Held-out check of the fallback choice ([`evals/heldout/`](evals/heldout/))

The golden set influenced two choices: adding a Claude fallback, and choosing Haiku for it. So both were re-checked on **30 fresh reviews** the golden set never touched. They were drawn with a seeded random sample from the 1,362 texts in the 10k run where Jev's confidence was below 0.5, with golden IDs excluded. The user hand-labelled them blind (no model output shown). Three emoji-only reviews were changed from `complaint` to `unclear` after a reminder of the written rubric rule, still blind. Scoring is strict: the primary human label only.

| Labeller on these 30 hard reviews | Topic | Intent | Severity | All three |
|---|---|---|---|---|
| Jev alone | 25 | 17 | 17 | **12** |
| Sonnet 5 fallback (saved from the 10k run) | 27 | 23 | 20 | **17** |
| **Haiku 4.5 fallback** (no thinking; the final-run setting) | 21 | 26 | 23 | **16** |

Haiku cost $0.016 for the 30 reviews on the standard API (the final run uses Batch at half price). All 30 of its quotes were exact. The result supports the decision: in the low-confidence band, the fallback beats Jev alone, and Haiku is close to Sonnet at about a quarter of the cost. It is weaker on topic and stronger on intent and severity. Thirty cases are a diagnostic, not a population estimate. This is the last hand-labelled set: all later quality checks are automated (the blind Sonnet verifier on 1,000 random reviews, planted errors, injection cases).

### Injection and control cases ([`evals/injection_results.json`](evals/injection_results.json))

There are 13 synthetic reviews: 7 prompt-injection attempts and 6 controls, including a held-out physical-harm case. **All 13 passed through Jev, and all 13 passed through the Claude verifier** (one 13-review batch, with returned IDs checked). Cost: $0.018. These cases are excluded from all business results.

### Design experiments

- **Compact Jev wording** ([`rubric_compact_vs_full.json`](evals/dev500/rubric_compact_vs_full.json)): 1,085 vs 1,504 tokens per review (−28%). Agreement with the same blind verifier labels was topic 87% vs 90%, intent 98% vs 98%, and severity 88% vs 87%. **Decision: keep the full wording.** The saving (~$8.50 on the full run) did not justify the small loss in topic agreement.
- **Language:** the 500 sample has only 12 non-English candidates, so the language comparison runs at 10k (`--verify-extra-groups`).
- **Claude reasoning effort, low vs medium** ([`evals/effort_test/report.json`](evals/effort_test/report.json), $0.33). All inputs are the same and saved:

  | Test | Medium | Low |
  |---|---|---|
  | Fallback on the 500 run's 67 low-confidence texts (50 per request): cost per review | $0.00166 | $0.00138 (−17%) |
  | … output tokens per review | 138 | 110 |
  | … quotes copied exactly | 98.5% | 98.5% |
  | … same labels as the other effort (all three) | — | 73% |
  | Fallback on the 7 golden low-confidence reviews: all three labels match the human | 5/7 | 4/7 |
  | Verifier on the 500 run's random 100: cost per review | $0.00113 | $0.00093 (−17%) |
  | … all-three agreement with Jev | 77% | 77% |

  Low effort saves about 17% per review, but it changed about a quarter of the fallback's decisions. On the tiny golden check it got one more review wrong. The measured fallback cost at 50 reviews per request ($0.00166) is also well below the pilot's 7-review figure ($0.0026).

### Full-corpus cost estimate (superseded: the final scope is the 100,000-review sample; see the checkpoint refresh)

| Component | Basis | Estimate |
|---|---|---|
| Jev labels | 484,189 texts × 1,504 tokens × $0.042/M | ~$30.60 |
| Jev grouping | ~179k complaint texts × 610 tokens | ~$4.60 |
| Claude verify (1,000) + taxonomy + memo | measured per-call cost | ~$1.30 |
| **Baseline total** | | **~$36.50** |
| Optional: Claude fallback for low-confidence texts (~14%, ~68k texts) | $0.0645 per 50-review call; Batch API halves it | +~$44 (Batch) to +~$87 (standard) |
| Optional: translation of 18,821 non-English texts | not yet measured | decided after the 10k comparison |

Runtime: about 4.5 h of Jev enrichment plus about 1.7 h of grouping at 30 requests/s, plus up to 24 h for the fallback batch (most finish within an hour). **Chosen setup:** baseline plus the low-confidence fallback via the Batch API, about $81 projected, under a $90 cap. The 10k run measures the real fallback rate and cost first.

### Full run *(pending)*

When the full run is done, this section will report:
- rows, completed, quarantined, cache reuse, verifier disagreements, measured cost and time
- the interruption/resume evidence
- one review traced end to end, from source ID to memo claim

### One review traced end to end (500 run)

`6eb64519-37d4-4591-a47a-bbb96357de36`: "useless music app music k naam pe khaali ad dikhata hai." (Hinglish: roughly "in the name of music it only shows ads").

| Stage | What happened | Saved evidence |
|---|---|---|
| ingest | row hash `27db8f50…`; language group `non_english_latin`; rating 1 (never sent to a model) | `ingest/sources.jsonl` |
| enrich | Jev: `usability` / `complaint` / severity **4** (P(4)=0.67, P(2)=0.31; severity confidence 0.58); sentiment −0.975; entity `Ads`; the quote is the whole text | `enrich/results.jsonl`, `calls.jsonl` |
| verify | in the random sample. Claude (blind): `usability` / `complaint` / severity **2**: "Complains about excessive ads interrupting music." The 2-level gap counts as a material disagreement, so `needs_review` = true | `verify/comparisons.json` |
| group | Jev assigns it to `usability.ad_frequency` | `group/assignments.jsonl`, `membership.csv` |
| rank | `usability.ad_frequency` is rank 2: 30 complaints, severity sum 65, mean 2.166667 | `ranking.csv` |
| memo | cited as representative review `6eb64519…` next to claims C05–C08 | `memo_v2.md`, `claims.csv` |

**This is also the ambiguous-case example.** By the shared definitions, ad overload with no stated loss of function is severity 2, so the verifier is probably right and Jev's 4 is probably too high. The record keeps Jev's label, which keeps a single `label_config`, and it is flagged `needs_review`. It is included in the ranking with severity 4. That is exactly the kind of low-confidence case a Claude fallback would re-decide.

## Tests *(offline evidence in [`evals/offline/`](evals/offline/))*

Offline tests use fake providers, with no network and no spend. They cover:
- resume never re-sending completed IDs
- the spend cap, 10% gate and time cap
- the one-retry rule for invalid output, with quarantine and attempt counts
- transient-error backoff
- torn-file repair
- exact half-up ranking and tie order
- `rerank` identical from saved outputs
- verifier ID validation
- taxonomy validation
- memo checks for numbers, issue IDs and review IDs
- the planted wrong label caught by the verification comparison
- nine planted export errors, each flagged by the course checker

Run with `EVIDENCE_DIR=evals/offline` to refresh the saved outcomes. The live injection eval (`eval-injection`) has 13 synthetic cases: 7 adversarial and 6 controls.

## Limits

- **The data.** It is a historical, self-selected set of public Play Store reviews, with no revenue, plan tier, cost, or confirmed churn. Cancellation language is expressed intent, not observed churn.
- **Model agreement.** Agreement between Jev and Claude is not accuracy. The 50-review golden set is a small diagnostic, not a population estimate.
- **Language.** A deterministic tagger (`pipeline/language.py`) finds 18,821 distinct likely non-English texts in the full file, 3.9% of distinct texts. Verification agreement is reported per language group. Translation (`--translate`) is built but off. Whether to enable it is decided from the 10k comparison, and fixed before the full run, so every record shares one `label_config`.
- **Dates.** The first and last calendar months are partial.
