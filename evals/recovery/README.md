# Interruption, resume and spending-cap evidence (final 100,000-review run)

The real final run (`runs/final100k`, copied to [`../final100k/run/`](../final100k/run/)) stopped four times and was resumed each time with the same command. No completed text was sent to Jev twice: the call log holds exactly one successful labelling call for each of the 78,146 distinct texts ([`../../grading/calls.jsonl.gz`](../../grading/calls.jsonl.gz)).

| # | Invocation (PT, 2026-10-06) | How it stopped | Texts with a saved Jev result at start | Texts with final labels at end | Evidence |
|---|---|---|---|---|---|
| 1 | 18:55, `phase: initial` | **Planned stop** after 5,000 requests (`--stop-after-units 5000`) | 0 | 4,420 | `enrich_stop_20261007T015903_stop_after.json.gz` (21,990 review IDs), the same snapshot as `grading/checkpoint_before.json` |
| 2 | 18:59, `resume` | **Ctrl-C, screen-recorded** ([`interruption_resume_terminal.mp4`](interruption_resume_terminal.mp4)) | 5,000 | 7,098 | `enrich_stop_20261007T020131_interrupted.json.gz` (25,503 review IDs) |
| 3 | 19:01, `resume` | Graceful stop, to restart with a longer time cap | 8,168 | 15,471 | `enrich_stop_20261007T020945_interrupted.json.gz` |
| 4 | 19:09, `resume` | **Spending cap.** Jev labelling finished; the run then refused to submit the Haiku batch, because committed $5.04 + in-flight reservation $9.93 + next call $0.04 would exceed the $15 cap | 18,062 | stopped before the fallback | `run_log.jsonl`: `BudgetExceeded … would exceed cap $15.0`, exit code 3 |
| 5 | 19:51, `resume` | Completed, after the per-request output cap was set from measurements (`--fallback-max-tokens 8000`), with the same $15 cap | 78,146 | all 78,146 texts (100,000 reviews) | `grading/checkpoint_after.json` (100,000 review IDs) |

"At start" counts distinct texts with a saved Jev result; all of them are skipped, never re-sent. "At end" counts texts with final labels, so it leaves out low-confidence texts still waiting for the Haiku fallback batch. That is why each start is higher than the previous end.

- **Checkpoint snapshots** (completed review IDs at each stop) are in this folder and in [`../final100k/run/enrich/checkpoints/`](../final100k/run/enrich/checkpoints/).
- **The spending cap** reserves each request's worst-case cost before dispatch. Invocation 4 shows it stopping cleanly with progress saved; the cause (a 16,000-token worst case reserved for every Haiku request) is explained in the README's [Final run](../../README.md#final-run-100000-review-seeded-sample) section.
- **Screen recording:** [`interruption_resume_terminal.mp4`](interruption_resume_terminal.mp4) (80 s, 3.5 MB), cropped to the terminal panel from the full-screen original `Screen Recording 2026-10-06 at 7.01.13 PM.mov` (18.7 MB, sha256 `4e6825aebc624e5928fe1443ffc140c06d52b3c9c60f12b7b5aabe0961ae2bf2`), which the author keeps. Cropping removed only the unrelated chat and app sidebar.
