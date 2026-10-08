## Recommendation

Put next quarter's product effort into **usability**. It is the largest specific topic, with 13163 complaint/cancellation reviews [F14] and a severity sum of 33278 [F15]. Fix `usability.ad_frequency` first, then the core listening controls in `usability.playback_controls_limited` and `usability.shuffle_control`. The largest specific issue, `billing.features_locked_behind_premium`, is closely related to the controls work, so scope that work together with whoever owns free-tier packaging.

## Evidence

- **`usability.ad_frequency`**
  - 5488 complaints [C09], severity sum 11849 [C10], mean severity 2.159074 [C11].
  - It covers too many ads, ads that play too often, and ad breaks that run too long.
  - Example: "Today I almost got into an accident because of unexpected loud ad music" (08a1f178-3e7a-4d65-9da3-dee293dd0061).
- **`billing.features_locked_behind_premium`**
  - This is the top-ranked specific issue: 4490 complaints [C05], severity sum 13442 [C06], mean severity 2.993764 [C07].
  - Customers say skipping, repeating and seeking now require Premium.
  - Example: "it has started charging money for even playing the playlist normally" (33a171b5-b930-48c3-8560-97b8deb538be).
  - Example: "you need premium to do anything I am planning on switching to yt music instead of this now" (a0d2ccd3-ebb3-46b9-bbf7-212bb0ec8e84). This is cancellation intent, not a confirmed departure.
- **`usability.playback_controls_limited`**
  - 1592 complaints [C17], severity sum 4797 [C18], mean severity 3.013191 [C19].
  - Example: "The new update is so bad I can't even swith the previous song back and I can't even listen to my playlist." (9a2f9235-5c31-4726-baf5-dbb5910e345c).
- **`usability.shuffle_control`**
  - 1679 complaints [C21], severity sum 4787 [C22], mean severity 2.851102 [C23].
  - It covers shuffle that cannot be turned off or plays songs in an unwanted order.
- **`usability.queue_playlist_management`**
  - 1357 complaints [C25], severity sum 4121 [C26].

The highest-ranked issue overall is the catch-all `other.general`, with 14039 complaints [C01] and severity sum 28433 [C02]. These complaints name no specific defect, so they cannot direct a fix. `usability.general` is also a catch-all, with 1862 complaints [C13].

## Alternatives considered

- **Billing/support**
  - Billing has 6875 complaint/cancellation reviews [F18] and a severity sum of 20158 [F19].
  - Support has only 118 reviews [F28] and a severity sum of 362 [F29].
  - Billing's top issue is large, but fixing it means changing free-versus-Premium packaging rather than fixing a defect.
  - Without revenue or plan-tier data, this analysis cannot weigh the trade-offs of unlocking features.
  - `billing.general` is a catch-all, with 1496 complaints [C33].
  - If leadership is open to revisiting free-tier limits, billing could share priority with usability.
- **Playback**
  - Playback has 5615 reviews [F20] and a severity sum of 18451 [F21].
  - `playback.app_crashes_freezes` has the highest mean severity among the ranked issues, at 3.501724 [C31]. Its volume is smaller: 1160 complaints [C29] and severity sum 4062 [C30].
  - `playback.general` is a catch-all, with 1222 complaints [C37].
  - Crash telemetry showing wider impact than reviews suggest would raise playback's priority.
- **Access**
  - Access has only 1610 reviews [F22] and a severity sum of 6291 [F23], so it ranks lowest of the main candidate areas.

## Limits

- **Review data:** App reviews are self-selected and historical, not a representative survey of users. The data contains no revenue, plan tier or confirmed churn.
- **Cancellation intent:** The 4327 cancellation-intent reviews [F06] show stated intent, not actual cancellations.
- **Classification scope:** Classification covered a seeded random sample of review IDs [F00].
  - 100000 reviews completed classification [F02], out of 660622 source reviews [F01].
  - 560609 reviews were outside the scope [F99], so all counts describe the classified reviews only.
  - 13 reviews were quarantined for empty text [F03], and 0 for other failures [F04].
- **Needs-review flag:** 13974 completed reviews were flagged needs_review [F07]. They are included in every count and ranking; the flag only marks them for human inspection.
- **Concentration:** The top three issues hold 53.9 percent of ranked complaint memberships [F09], and that share includes the `other.general` catch-all.
- **Verification:** A second model checked a 1000-text sample [F10].
  - Topic agreement was 84.6 percent [F11].
  - Intent agreement was 91.2 percent [F12].
  - Severity differed by a mean of 0.155 levels [F13].
  - These figures measure agreement between two models, not accuracy.