# Hand-labelling the golden 50

Fill in `golden_50_human_labels.csv` yourself, using the shared definitions from `GRADING_CONTRACT.md` summarized below.
- Label **before** you look at any pipeline output for these review IDs.
- Label the **text only**; ignore the star rating, likes, version and date.
- Your labels are never sent to a model. `python -m pipeline score-golden` reads them only after classification.

## Suggested order for each review

1. Read the text and list the problems it reports, if any.
2. **intent**: walk down the precedence list and stop at the first one that applies.
3. **severity**: rate the worst problem.
4. **topic**: the topic of that worst problem.
5. **sentiment**, **evidence_quote**, **entities**, **needs_review**.

## topic: exactly one of 8 labels

| Label | Use for |
|---|---|
| `access` | Login, signup, password, verification codes, logged out, account access |
| `usability` | Navigation, controls, layout/design, queue or playlist management, shuffle/repeat, **ads interrupting** |
| `playback` | Won't play, stops/skips, crashes, freezing, lag, connection errors, audio quality, battery/data/storage |
| `downloads` | Downloading, saved/offline music, downloads disappearing, offline listening |
| `catalog` | Missing songs/artists, search, discovery, recommendations, lyrics availability |
| `billing` | Price, charges, refunds, subscriptions, paywalls, Premium not activating, controls explicitly locked behind Premium |
| `support` | Contacting customer support and its response |
| `other` | General praise/criticism with no specific feature, unrelated content, slogans, gibberish |

Rules:
- **Several problems:** pick the one with the **highest severity**. On a tie, pick the one **mentioned first**.
- **Positive review:** pick the **first specific feature praised**. General praise ("great app") is `other`.
- **Paid plans:** mentioning Premium alone is **not** `billing`. "Paid but Premium isn't active" **is** `billing`. "I pay for Premium and it keeps crashing" is `playback`.

## intent: precedence order, first match wins

1. `cancellation`: the writer explicitly says they are leaving, uninstalling, cancelling or switching, **or threatens to**.
2. `complaint`: any negative experience, including mixed praise + criticism and a generic "bad app".
3. `request`: asks for a change or feature without reporting a failure.
4. `praise`: only positive.
5. `unclear`: meaningless, unrelated, or a bare boycott/political slogan with no product complaint and no personal departure.

## severity: integer 1–5

| Level | Meaning |
|---|---|
| 1 | No reported problem: praise, neutral/unclear, or a pure feature request |
| 2 | Dislike, generic criticism, minor annoyance, too many ads, cosmetic; no functional loss |
| 3 | A function degraded or restricted, but some use or a workaround remains |
| 4 | A core task clearly blocked: can't log in, can't play anything, app won't open |
| 5 | Explicit serious health, financial, privacy or data harm: charged wrongly, money taken, data exposed, library deleted, actual physical injury such as hearing loss (not discomfort or "this is dangerous") |

Rules:
- `praise`, `request` and `unclear` are always 1. A `complaint` is at least 2.
- Anger, 1 star, an expensive plan, a crash mentioned on its own, or a cancellation threat do **not** by themselves raise severity.
- Rate only the impact the text states; do not invent it.

## sentiment: number from -1 to 1

Use one of five values:

| Value | Meaning |
|---|---|
| `-1` | Very negative |
| `-0.5` | Negative |
| `0` | Neutral or mixed |
| `0.5` | Positive |
| `1` | Very positive |

The predeclared agreement tolerance is ±0.5, so a prediction one step away counts as agreeing.

## entities: optional, separated by `;`

Name the product features, plans or devices mentioned in the text. Leave the cell blank if there are none. Where one fits, use these names, because the scorer matches names without regard to capitalisation: Premium, Free tier, Family plan, Duo, Student plan, Shuffle, Queue, Playlists, Library, Liked songs, Lyrics, Podcasts, Audiobooks, Radio, DJ, Wrapped, Discover Weekly, Daily Mix, Downloads, Offline mode, Ads, Search, Android Auto, Bluetooth, Chromecast, Smartwatch, Widget, Lock screen, Sleep timer, Equalizer, Spotify Connect, Login, Customer support.

Other named things, such as an artist or a device, are fine too.

## evidence_quote: exact words from the review

**Copy and paste** the part of the text that justifies your topic and severity:
- It must be continuous text from the review.
- Don't fix typos or change punctuation or emoji.
- For a one-line review, the whole text is fine.

## needs_review: `true` or `false`

`true` when you couldn't label confidently, for example:
- the text is too short or vague
- it's in a language you can't read
- it's missing context
- you marked the row `ambiguous`

Otherwise `false`.

## Ambiguous cases: always choose one label

Every `topic`, `intent` and `severity` cell must contain **exactly one** value: your best judgment. If a case is genuinely ambiguous, record that in the extra columns instead:

| Column | What to write |
|---|---|
| `ambiguous` | `true` if another label is genuinely defensible, otherwise leave blank or write `false` |
| `alternative_labels` | The other defensible label(s), e.g. `severity=4` or `topic=downloads; severity=4` |
| `label_notes` | Optional short reason, e.g. "unclear whether all offline listening is blocked" |

Headline agreement is always scored **strictly** against your single primary label. A separate "lenient" figure that also accepts your noted alternatives is reported alongside it, never instead of it. The number of ambiguous cases is reported, as the brief requires.

## Non-English reviews

Label by **meaning**, not language. Non-English is not the same as `unclear`, which means meaningless or unrelated text.
- **Understanding it:** use a translator (Google Translate, DeepL) to understand the text, then apply exactly the same rules as for English.
- **`evidence_quote`:** copy from the **original** text, never the translation; it must exactly match the review.
- **`entities`:** use the usual English names (Premium, Playlists, Ads…).
- **`needs_review`:** `true` if you are relying on a machine translation and aren't confident; otherwise `false`.
- **`label_notes`:** record the language and how you read it, e.g. "Spanish; read via Google Translate".
- **Gibberish:** only genuine gibberish that no translator can interpret is `other` / `unclear` / 1 / 0.

## Worked examples

These are made-up reviews, not from the golden set.

| Review | topic | intent | severity | sentiment | entities | evidence_quote | needs_review |
|---|---|---|---|---|---|---|---|
| Downloaded songs stop playing when I go offline. | downloads | complaint | 3 | -0.5 | Downloads; Offline mode | Downloaded songs stop playing when I go offline. | true |
| I pay for Premium and the app crashes every time I open a playlist. Fix it or I'm cancelling. | playback | cancellation | 3 | -1 | Premium; Playlists | the app crashes every time I open a playlist | false |
| Love the Discover Weekly playlists, but way too many ads. | usability | complaint | 2 | 0 | Discover Weekly; Playlists; Ads | way too many ads | false |
| Charged twice this month and support never replied. | billing | complaint | 5 | -1 | Customer support | Charged twice this month | false |
| Please add a sleep timer for podcasts. | usability | request | 1 | 0 | Sleep timer; Podcasts | Please add a sleep timer for podcasts. | false |
| Great app | other | praise | 1 | 1 | | Great app | false |
| Boycott Spotify!!! | other | unclear | 1 | -0.5 | | Boycott Spotify!!! | false |

Why each example is labelled that way:
- **Downloads offline:** is offline listening fully blocked (4) or only degraded (3)? The text doesn't say, so choose one, 3, since the text doesn't state a total block. Then fill in `ambiguous` = `true`, `alternative_labels` = `severity=4`, and `needs_review` = `true`.
- **Premium crash:** mentioning Premium doesn't make it billing, because the crash is the problem. The threat to cancel makes the intent `cancellation` but doesn't raise severity. Playlists fail, but other use remains, so 3.
- **Discover Weekly + ads:** mixed praise and criticism is a `complaint`. The topic comes from the problem (ads → usability), not from the praised feature.
- **Charged twice:** there are two problems. The financial harm (5) outranks support (2–3), so the topic is billing.
- **Sleep timer:** a request with no failure is always severity 1.
- **Boycott:** a bare slogan is `unclear`.

## Practical tips

- **Editing tool.** Edit in Google Sheets or Numbers and export as **CSV (UTF-8)**. Excel can corrupt emoji and accented characters in the review text.
- **Columns to leave alone.** Change only the 7 label columns. Keep `review_id` and the six source columns exactly as they are.
- **Where the file lives.** Save it back to `evals/golden/golden_50_human_labels.csv`.
