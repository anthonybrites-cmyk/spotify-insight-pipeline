# Spotify review insight pipeline (Assignment 5)

A saved program that takes an input CSV and runs **ingest → enrich → verify → group → rank → recommend**, with no chat pasting between stages. It writes the compact grading folder required by `GRADING_CONTRACT.md`.

- **Grading folder:** [`grading/`](grading/). It is produced by the full run and is not present yet.
- **Design choices and label examples:** [`DESIGN.md`](DESIGN.md)
- **Status:** the pipeline is built and tested offline. No real model calls have been made yet, so no costs or results are reported here.

## Models and roles

| Stage | Role in `calls.jsonl` | Model | What it does |
|---|---|---|---|
| ingest | — | code | Hashes every row (course `row_sha`), quarantines 13 empty texts, groups exact-duplicate texts |
| enrich | `enrich` | Jev `jev-1.13.0` (TypeSafe) | One review per request. Returns topic, intent and severity choices, a sentiment score, an "unclear" yes/no, and evidence-sentence selection |
| verify | `verify` | `claude-sonnet-5` | Labels a declared 1,000-record sample blind (50 reviews per request); code compares its labels with Jev's |
| group | `group` | `claude-sonnet-5`, then Jev | Claude proposes a subtopic list from saved complaint quotes; Jev assigns each complaint to one subtopic |
| rank | — | code | Baseline ranking using exact integer and Decimal arithmetic |
| recommend | `memo` | `claude-sonnet-5` | Memo written from saved aggregates; code checks every number in it against `claims.csv` or listed facts |

Only `review_text` is sent to any model. Stars, likes, app version and timestamp are never model inputs. The golden-50 human labels are read only by `score-golden`, after classification.

## Setup

```bash
cd ~/code/spotify-insight-pipeline
python3 -m venv .venv && .venv/bin/pip install --no-cache-dir -r requirements.txt
```

Paste your keys into `.env`. It is git-ignored; see `.env.example`. Then confirm they load without printing them:

```bash
.venv/bin/python -m pipeline keys
```

## Run

`DATA` is the folder containing the course CSVs.

```bash
DATA="$HOME/code/Final Assignment - Spotify Reviews Dataset"
# 1) 500-review development run
.venv/bin/python -m pipeline run --input "$DATA/checkpoint_500.csv" --run-dir runs/dev500 \
  --budget-group dev --budget-usd 2 --verify-n 100 --grading-dir runs/dev500/grading
# 2) 10,000-review development checkpoint (shares the $2 dev budget)
.venv/bin/python -m pipeline run --input "$DATA/analysis_10000.csv" --run-dir runs/dev10k \
  --budget-group dev --budget-usd 2 --verify-n 300 --grading-dir runs/dev10k/grading
# 3) Full run: stop after 5,000 enrichment requests (interruption demo), then resume
.venv/bin/python -m pipeline run --input "$DATA/spotify_reviews_18months.csv" --run-dir runs/full \
  --budget-group full --budget-usd 40 --verify-n 1000 --stop-after-units 5000
.venv/bin/python -m pipeline run --input "$DATA/spotify_reviews_18months.csv" --run-dir runs/full \
  --budget-group full --budget-usd 40 --verify-n 1000 --grading-dir grading
# 4) Zero-API self-check (the reference and the report stay outside grading/)
.venv/bin/python -m pipeline check --input "$DATA/spotify_reviews_18months.csv" --grading-dir grading --out-dir runs/full/check
```

`python -m pipeline check` wraps the three `check_submission.py` commands from the contract. The vendored copy in `vendor/` is verified byte-for-byte against the course file.

**Resume:** rerun the same command. Completed units are loaded from `enrich/results.jsonl`, and none is sent again under the same `label_config`. Calls made after the first invocation are logged with `phase: "resume"`.

**Interrupt:** press Ctrl-C once. The program stops sending, finishes in-flight requests, saves them, and writes a `completed_ids` snapshot. Pressing Ctrl-C a second time aborts immediately. Saved results are fsynced, and a torn final line is repaired on the next start.

## Spending controls (all in code)

- **Hard cap per budget group.** The ledger in `budgets/<group>.jsonl` persists across runs and resumes. Every call reserves a worst-case estimate first; Claude calls reserve the full `max_tokens` of output. The call is not sent if committed plus in-flight spend plus the estimate would exceed the cap. The dev cap is $2 for the 500 and 10k runs combined; the full run is capped at $40.
- **Early 10% gate.** When 10% of enrichment units are done, the run's spend so far must be at most 10% of the cap. Otherwise the run halts and prints a linear projection. It continues only with `--accept-early-gate`.
- **Exact-duplicate reuse.** 660,609 nonempty reviews collapse to 484,189 distinct texts, so each distinct text is classified once. The other IDs get `cache_source_id` pointing to the original. Each original ID keeps its own record and counts separately in the aggregates.
- **Retries** are exponential backoff with jitter, honouring `retry-after`, up to 5 attempts for Jev and 3 for Claude. Every failed attempt is logged as `outcome: "failed"`. SDK retries are disabled so all retry behaviour lives in `pipeline/retry.py`.
- **Usage source.** Cost is computed only from provider-reported token usage times published list prices (Jev $0.042 per million input tokens, output free; Sonnet 5 $2/$10 per million). When a failed attempt returns no usage, it is logged with 0 tokens and `usage_available: false`; it is not estimated.

## Outputs per run (`runs/<name>/`)

Every handoff is saved: `ingest/` (sources, units, profile), `enrich/` (question set, results with Jev probabilities, failures, checkpoints), `verify/` (sample declaration, every request and response, report), `group/` (taxonomy input, request and response, issues, assignments), `rank/`, `memo/` (inputs, every draft, number check), `calls.jsonl`, and `spend.json`.

## Tests

```bash
.venv/bin/python -m unittest discover -s tests -v   # offline, fake providers, no spend
RUN_SLOW=1 .venv/bin/python -m unittest tests.test_pipeline.TestProvenance.test_full_file_ingestion_counts
.venv/bin/python -m pipeline eval-injection          # LIVE: 12 synthetic cases through Jev + the verifier (tiny spend, dev budget)
```

The offline tests cover:
- resume never re-sending completed IDs
- the hard cap and the early gate
- retried and logged transient and invalid answers
- torn-file repair
- exact half-up ranking arithmetic and tie order
- validators for verifier IDs, the taxonomy, and memo numbers
- nine planted export errors, each confirmed flagged by the course checker

Fake providers exist only for tests. Their records contain `fake` in `label_config`, and export refuses them without `--allow-fake`.

## Limits

This is a historical snapshot of self-selected public reviews. There is no revenue, plan tier, cost or confirmed churn data. Cancellation intent is not a confirmed cancellation. Agreement between Jev and Claude is not accuracy. The golden-50 score and the instructor's sample are the accuracy diagnostics.
