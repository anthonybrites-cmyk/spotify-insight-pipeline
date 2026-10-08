# Delivery note: Spotify review insight pipeline

Anthony Brites · Final Assignment (Classes 6–7). The deliverable is the public repository below, submitted by URL through the course portal; this note, the evidence and the recording are all inside it.

## Links

- **Repository:** https://github.com/anthonybrites-cmyk/spotify-insight-pipeline (branch `main`). Start with the [README](README.md): it has the rubric-to-evidence map.
- **Live dashboard:** https://spotify-insight-dashboard.vercel.app (public, read-only; Next.js on Vercel, Neon Postgres, SELECT-only database role).
- **Interruption/resume recording:** [`evals/recovery/interruption_resume_terminal.mp4`](evals/recovery/interruption_resume_terminal.mp4) (80 s). It shows a Ctrl-C stop of the real final run, the saved checkpoint, and the resume with the same command (`phase=resume`, completed work not re-sent). It is cropped to the terminal panel from the original full-screen capture (`Screen Recording 2026-10-06 at 7.01.13 PM.mov`, sha256 `4e6825ae…`), kept by the author. Written evidence: [`evals/recovery/`](evals/recovery/).

## What was run

One saved program (`python -m pipeline run`) takes the course CSV and runs ingest → enrich → verify → group → rank → recommend, then writes the `grading/` export. Code owns the IDs, retries, spending cap, checkpoints and every number; models answer narrow, schema-checked questions.

- **Scope:** a seeded random sample of **100,000 of the 660,622 reviews** (the updated brief allows at least 100,000). All 660,622 rows are ingested and accounted for: 100,000 completed, 560,609 `out_of_scope`, 13 `empty_review_text`.
- **Models:** Jev `jev-1.13.0` (TypeSafe) labels every text and assigns complaints to issues. When Jev is unsure (confidence below 0.5), `claude-haiku-4-5` re-labels blind through the Batch API, capped at 20% of texts; it handled 17.2%. `claude-sonnet-5` blind-verifies 1,000 random texts (Batch API) and proposes the issue taxonomy. `claude-opus-5-5` writes the memo from the saved aggregates and a bounded evidence pack; code checks every number, ID and quote. Ranking is plain arithmetic.
- **Cost and time:** $10.89 at list prices (cap $15), including three memo regenerations; about 1.5 hours of active run time; 108,711 model requests.
- **Checks:** the course checker accounts for every row with 0 missing, duplicate or invalid records (its one flag, `unfinished_classification`, is expected for the declared scope). The ranking reproduces exactly from the export with no model calls. 25 of 25 planted wrong labels were detected. 13 of 13 injection cases passed. The final memo passed every number, ID and quote check. Two earlier drafts also passed the checks but were rejected on review because their arguments were unsupported or incoherent (disclosed in the README).

## Recommendation (from [`results/memo.md`](results/memo.md))

Put next quarter's product effort into **usability** (13,163 complaint/cancellation reviews, severity sum 33,278, the largest topic). Fix `usability.ad_frequency` first (5,488 complaints), then the core listening controls (`usability.playback_controls_limited`, `usability.shuffle_control`). The top-ranked specific issue, `billing.features_locked_behind_premium` (4,490 complaints, severity sum 13,442), overlaps with the controls work, so scope it together with whoever owns free-tier packaging; with no revenue or plan data, this analysis cannot weigh unlocking features. Playback crashes have the highest mean severity (3.50) but lower volume. The largest bucket, `other.general` (14,039), names no specific defect.

## Decisions and disclosures

- **Golden set:** I hand-labelled the 50 golden reviews; the labels were never sent to a model. Strict scoring of the final setup (Jev + Haiku fallback, final prompt): topic 88%, intent 96%, severity 86%, **all three 78%** (Jev alone with the earlier prompt: 74%).
- **Golden-influenced changes, re-checked on fresh cases:** the golden low-confidence results led to adding the Claude fallback and then choosing Haiku for it. Both were re-checked on 30 fresh, held-out hard reviews I labelled blind: Jev alone 12/30 fully correct, Sonnet 17/30, Haiku 16/30.
- **Rubric amendment:** severity 5 also covers an actual physical injury (for example hearing loss). It is annotated in `GRADING_CONTRACT.md` and applied identically to every model's prompt.
- **Adjudication:** after scoring, I answered four questions about golden-set disagreements. One label changed; the original labels file is untouched, and adjudicated scores are reported separately.
- **Cost choices:** Haiku instead of Sonnet for the fallback (about a third of the cost per review, close in accuracy on hard cases); Batch API for the fallback and verification (half price); 5 parallel workers (same cost, ≈2.5× faster). Prompt caching and reuse of 10k results were measured and not worth it.
- **No translation:** the 10k language comparison showed only a small gap for non-English texts.

## Limits

Historical, self-selected Play Store reviews with no revenue, plan or confirmed-churn data; cancellation language is intent, not churn. Results describe the 100,000-review sample. Model-to-model agreement is not accuracy, and the hardest texts (the 17.2% re-labelled by Haiku) are the least reliable: the verifier agreed with 49% of them versus 75% of Jev-only decisions.

## AI assistance

The pipeline, dashboard and documentation were built with Claude Code as a coding assistant. The saved program performs every stage on its own; no step depends on pasting into a chat. All human labels, decisions and the final recommendation review are mine.
