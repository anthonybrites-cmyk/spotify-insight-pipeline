# Interruption and resume evidence (final 100,000-review run)

Two stops of the real final run (`runs/final100k`), each resumed with the identical command:

1. **Planned stop** with `--stop-after-units 5000` (Jev requests), then resumed. This one was not screen-recorded.
2. **Ctrl-C interrupt, screen-recorded:** a graceful stop while about 5 workers were in flight, then resumed with the same command.

| Phase | Started (UTC) | Ended (UTC) | Units complete at start | at end | Stop reason |
|---|---|---|---|---|---|
| initial | 2026-10-07T01:55:50+00:00 | 2026-10-07T01:59:03+00:00 | 0 | 4420 | stop_after |
| resume | 2026-10-07T01:59:23+00:00 | 2026-10-07T02:01:31+00:00 | 5000 | 7098 | interrupted |
| resume | 2026-10-07T02:01:46+00:00 | running | 8168 | - | - |

"At start" counts distinct texts with a saved Jev result, all of which are skipped (never re-sent). "At end" counts texts with final labels, so it excludes low-confidence texts still waiting for the Haiku fallback batch. That is why each start is higher than the previous end.

- Checkpoint snapshots (completed review IDs at each stop): `enrich_stop_*_stop_after.json.gz`, `enrich_stop_*_interrupted.json.gz`.
- The `phase: "resume"` calls in the call log show that no completed unit was sent again.
- Screen recording: [`interruption_resume_terminal.mp4`](interruption_resume_terminal.mp4) (80 s, 3.5 MB), cropped to the terminal panel from the full-screen original `Screen Recording 2026-10-06 at 7.01.13 PM.mov` (18.7 MB, sha256 `4e6825aebc624e5928fe1443ffc140c06d52b3c9c60f12b7b5aabe0961ae2bf2`), which the author keeps. Cropping removed only the unrelated chat and app sidebar.
