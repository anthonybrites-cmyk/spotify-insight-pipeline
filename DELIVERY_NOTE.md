# Delivery note: Spotify review insight pipeline

Anthony Brites · Final Assignment (Classes 6–7) · submitted with the repository below and one screen recording.

## Links

- **Repository:** https://github.com/anthonybrites-cmyk/spotify-insight-pipeline (branch `main`). Start with the [README](README.md): it has the rubric-to-evidence map.
- **Live dashboard:** https://spotify-insight-dashboard.vercel.app (public, read-only; Next.js on Vercel, Neon Postgres, SELECT-only database role).
- **Interruption/resume recording:** `Screen Recording 2026-10-06 at 7.01.13 PM.mov` (18.7 MB, sha256 `4e6825aebc624e5928fe1443ffc140c06d52b3c9c60f12b7b5aabe0961ae2bf2`). It shows a Ctrl-C stop of the real final run and the resume with the same command. Written evidence: [`evals/recovery/`](evals/recovery/).

## What was run

One saved program (`python -m pipeline run`) takes the course CSV and runs ingest → enrich → verify → group → rank → recommend, then writes the `grading/` export. Code owns the IDs, retries, spending cap, checkpoints and every number; models answer narrow, schema-checked questions.

- **Scope:** a seeded random sample of **100,000 of the 660,622 reviews** (the updated brief allows at least 100,000). All 660,622 rows are ingested and accounted for: 100,000 completed, 560,609 `out_of_scope`, 13 `empty_review_text`.
- **Models:** Jev `jev-1.13.0` (TypeSafe) labels every text and assigns complaints to issues. When Jev is unsure (confidence below 0.5), `claude-haiku-4-5` re-labels blind through the Batch API, capped at 20% of texts; it handled 17.2%. `claude-sonnet-5` blind-verifies 1,000 random texts (Batch API), proposes the issue taxonomy and drafts the memo. Ranking is plain arithmetic.
- **Cost and time:** $10.63 at list prices (cap $15), about 1.5 hours of active run time, 108,706 model requests.
- **Checks:** the course checker accounts for every row with 0 missing, duplicate or invalid records (its one flag, `unfinished_classification`, is expected for the declared scope). The ranking reproduces exactly from the export with no model calls. 25 of 25 planted wrong labels were detected. 13 of 13 injection cases passed. The memo passed every number, ID and quote check.

## Recommendation (from [`results/memo.md`](results/memo.md))

Prioritize **usability**: reduce ad frequency (`usability.ad_frequency`, 5,488 complaints) and fix the cluster of control issues (`usability.playback_controls_limited`, `usability.shuffle_control`, `usability.queue_playlist_management`), together with the closely related `billing.features_locked_behind_premium` (4,490 complaints, the highest severity sum among specific issues). Playback crashes have the highest mean severity of any named issue and are proposed as a fast follow. The largest bucket, `other.general` (14,039), is vague "bad app" complaints and is not actionable on its own.

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
