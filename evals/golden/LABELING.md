# Hand-labelling the golden 50

Fill in `golden_50_human_labels.csv` yourself, using only the definitions in `GRADING_CONTRACT.md`. Do this **before** you look at any pipeline output for these review IDs. These human labels are never sent to a model; `python -m pipeline score-golden` reads them only after classification.

| Column | What to write |
|---|---|
| `topic` | One of `access, usability, playback, downloads, catalog, billing, support, other`. If two are genuinely defensible, write both separated by `\|`, e.g. `playback\|downloads`. That row then counts as ambiguous. |
| `intent` | One of `cancellation, complaint, request, praise, unclear`, applying the precedence order. Use `a\|b` only if genuinely ambiguous. |
| `severity` | An integer 1–5, or `2\|3` if genuinely ambiguous. |
| `sentiment` | A number from -1 to 1, e.g. -1, -0.5, 0, 0.5, 1. Agreement tolerance is predeclared as ±0.5. |
| `entities` | Optional. Features, plans or devices named in the text, separated by `;`. |
| `evidence_quote` | Copy the exact words from the review that justify your label. |
| `needs_review` | `true` if a careful reader would need more context, otherwise `false`. |

Leave `review_id` and the six source columns unchanged. Save the file as CSV (UTF-8).
