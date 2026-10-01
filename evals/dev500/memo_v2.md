## Recommendation

Product effort should prioritize **usability** next quarter, specifically the two monetization-adjacent friction points `usability.ad_frequency` and `usability.playback_control_restrictions` (often compounded by `billing.features_locked_behind_premium`). These issues combine high complaint volume with high severity and represent the clearest, most specific, fixable defects in the data, ahead of vaguer catch-all complaints.

## Evidence

**usability.ad_frequency** — 30 complaints, severity sum 65, mean severity 2.166667, priority score 65 [C05][C06][C07][C08]. Customers describe ads as disruptive and tied to the free tier: "it's literally useless if u hv not taken premium" (review `e5e6c55f-3069-4b7c-9807-f8b5d5bf2726`), and "useless music app music k naam pe khaali ad dikhata hai." (review `6eb64519-37d4-4591-a47a-bbb96357de36`).

**usability.playback_control_restrictions** — 10 complaints, severity sum 30, mean severity 3.000000, priority score 30 [C17][C18][C19][C20]. Users report being blocked from basic playback controls: "For free subscription I find this to be a cancerous and even dangerous app while driving." (review `08d3a5a9-1ec1-4b10-a5c8-393da33843e1`), and "Can't repeat and play specific part.please solve this matter." (review `e16a4550-43e7-4ae1-b538-a65cc652c31b`).

**billing.features_locked_behind_premium** — 21 complaints, severity sum 63, mean severity 3.000000, priority score 63 [C09][C10][C11][C12] — the highest mean severity among the top-ranked specific issues, closely tied to the usability complaints above: "It's impossible to use the app without prime And the recommended song is so bad" (review `074efbfd-f69e-46ca-9cea-e5204a192a2a`).

Together these three specific issues, plus the large `other.general` bucket (71 complaints, severity sum 143, priority score 143 [C01][C02][C04]), account for a large share of ranked complaints (top 3 issues represent 49.2% of ranked complaint memberships [F09]), making the ad/control/premium-lock cluster the single largest addressable driver of complaints.

## Alternatives considered

- **Playback (reliability)**: `playback.general` has 10 complaints, severity sum 36, mean severity 3.600000 [C13][C14][C15][C16], and `playback.app_crash_freeze` has 7 complaints, severity sum 27, mean severity 3.857143 [C25][C26][C27][C28] — the highest mean severities in the dataset, but lower complaint volume than usability issues. At the topic level, playback totals 36 complaint/cancellation reviews with severity sum 126 [F18][F19]. If crash/freeze volume grows, this should be revisited.
- **Billing/support**: Topic-level billing totals 36 complaint/cancellation reviews, severity sum 113 [F20][F21], similar in scale to playback but concentrated in the single `billing.features_locked_behind_premium` issue already covered above; no separate support-specific issue reached top ranks.
- **Access**: Topic-level access totals only 8 complaint/cancellation reviews, severity sum 32 [F24][F25] — the smallest topic by volume, so it ranks lowest priority unless new data shows growth.
- **Usability (overall)**: Topic-level usability totals 75 complaint/cancellation reviews, severity sum 192 [F14][F15], the largest of any topic, reinforcing it as the top priority area.

## Limits

This analysis is based on a self-selected set of reviews (500 source reviews, 500 completed classifications [F01][F02]), not a representative sample of all users. There is no revenue, plan-tier, or confirmed churn data; cancellation-intent reviews (30 [F06]) indicate intent only, not confirmed cancellations. 78 completed reviews were flagged needs_review [F07], and verification agreement (topic agreement 90.0% [F11], intent agreement 98.0% [F12], severity mean absolute difference 0.14 [F13]) reflects agreement between two models, not ground-truth accuracy. 479 distinct review texts were sent to the classifier with duplicates reused [F08], which may understate independent signal. No reviews were quarantined for empty text or other failures (0, 0 [F03][F04]).