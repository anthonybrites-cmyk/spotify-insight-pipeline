"""Held-out check of the fallback decision (no model calls here).

The golden set influenced the fallback decision (Jev 1/7 vs Claude 5/7 in the low band), so the
decision is re-checked on fresh reviews the golden set never touched: a deterministic sample of
texts from a finished run whose Jev confidence was below the fallback threshold. The sheet has
the golden sheet's columns with every label blank; the human fills it in without seeing any
model's answer. Golden review IDs are excluded.
"""

import csv
import hashlib
from pathlib import Path

from .checker import FIELDS, csv_rows
from .enrich import completed_results, current_config, fallback_settings
from .fallback import min_confidence
from .golden import load_ids
from .store import read_json, read_jsonl, write_json

SEED = "spotify-insight-heldout-v1"
LABEL_COLUMNS = ("topic", "intent", "sentiment", "severity", "entities", "evidence_quote", "needs_review",
                 "ambiguous", "alternative_labels", "label_notes")


def build_sheet(run_dir, n, out, exclude):
    run_dir = Path(run_dir)
    manifest = read_json(run_dir / "run_manifest.json")
    config = current_config(run_dir, None)
    threshold = (fallback_settings(run_dir) or {}).get("threshold", 0.5)
    done = completed_results(run_dir, config)
    low = {u for u, row in done.items() if min_confidence(row) < threshold}
    excluded = load_ids(exclude)
    first_id = {}
    for s in read_jsonl(run_dir / "ingest" / "sources.jsonl"):
        if s["unit"] in low and s["unit"] not in first_id and s["review_id"] not in excluded:
            first_id[s["unit"]] = s["review_id"]
    ranked = sorted(first_id.values(), key=lambda rid: hashlib.sha256(f"{SEED}:{rid}".encode()).hexdigest())
    chosen = set(ranked[:n])
    rows = [r for r in csv_rows(manifest["input"]) if r["review_id"] in chosen]
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(FIELDS) + list(LABEL_COLUMNS), lineterminator="\n")
        writer.writeheader()
        for r in rows:
            writer.writerow({**{k: r[k] for k in FIELDS}, **{k: "" for k in LABEL_COLUMNS}})
    write_json(out.with_suffix(".meta.json"), {
        "run_id": manifest["run_id"], "label_config": config, "threshold": threshold, "seed": SEED,
        "low_confidence_texts": len(low), "eligible": len(first_id), "sampled": len(rows),
        "method": "lowest sha256(seed + ':' + review_id) among low-confidence texts (first review ID per text), "
                  "golden IDs excluded"})
    return out, len(rows), len(first_id)


def score(args, log):
    """Score Jev, the saved Sonnet fallback and a candidate fallback model on the held-out human labels.

    Jev and Sonnet labels are read from the run (no calls). The candidate gets the review texts only, with the
    exact fallback prompt and schema the pipeline uses; human labels never leave this function.
    """
    import json
    from collections import Counter
    from decimal import Decimal
    from . import claude, fallback
    from .budget import Budget
    from .claude import ClaudeClient
    from .envfile import require
    from .store import JsonlAppender, canonical, sha256_text
    run_dir = Path(args.run_dir)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with Path(args.labels).open(encoding="utf-8-sig", newline="") as f:
        sheet = list(csv.DictReader(f))
    human = {g["review_id"]: {"topic": g["topic"].strip(), "intent": g["intent"].strip(),
                              "severity": int(g["severity"])} for g in sheet}
    texts = {g["review_id"]: g["review_text"] for g in sheet}
    unit_of = {s["review_id"]: s["unit"] for s in read_jsonl(run_dir / "ingest" / "sources.jsonl")}
    config = current_config(run_dir, None)
    jev_rows = completed_results(run_dir, config)
    fb_rows = fallback.saved(run_dir, config)
    pick = lambda r: {k: r[k] for k in ("topic", "intent", "severity")}
    jev = {i: pick(jev_rows[unit_of[i]]) for i in human}
    sonnet = {i: pick(fb_rows[unit_of[i]]["labels"]) for i in human
              if fb_rows.get(unit_of[i], {}).get("status") == "ok"}

    # Candidate: one request of <= 50 reviews, texts only; saved, so a rerun makes no call.
    ids = sorted(human)
    user = "<reviews>\n" + json.dumps([{"review_id": i, "text": texts[i]} for i in ids], ensure_ascii=False,
                                      indent=0) + "\n</reviews>"
    name = f"heldout_{args.model}_{args.effort}_{sha256_text(canonical(ids))[:10]}"
    parsed = read_json(out / "handoffs" / f"{name}.parsed.json")
    if parsed is None:
        budget = Budget(args.budget_group, args.budget_usd, "heldout")
        calls = JsonlAppender(out / "calls.jsonl")
        client = ClaudeClient(require("ANTHROPIC_API_KEY"), model=args.model, effort=args.effort)
        parsed, resp = claude.call(client, budget, calls, out / "handoffs", name, "eval", "heldout",
                                   f"heldout-{args.model}-{args.effort}", [], fallback.system_prompt(), user,
                                   schema=fallback.SCHEMA, validate=fallback.structural_validator(ids))
        calls.close()
        budget.close()
    resp = read_json(sorted((out / "handoffs").glob(f"{name}.response.*.json"))[-1])
    cand_raw = {r["review_id"]: r for r in parsed["results"]}
    cand = {i: pick(fallback.to_labels(cand_raw[i])) for i in ids}
    quotes_exact = sum(bool(cand_raw[i]["evidence_quote"].strip()) and cand_raw[i]["evidence_quote"] in texts[i]
                       for i in ids)

    def agreement(pred):
        n = len(human)
        got = {f: sum(i in pred and pred[i][f] == human[i][f] for i in human) for f in ("topic", "intent", "severity")}
        allc = sum(i in pred and pred[i] == human[i] for i in human)
        return {"n": n, "predicted": len(pred), **{f: f"{c}/{n}" for f, c in got.items()}, "all_three": f"{allc}/{n}"}

    cases = [{"review_id": i, "text": texts[i][:200], "human": human[i], "jev": jev[i], "sonnet": sonnet.get(i),
              args.model: cand[i]} for i in ids]
    report = {"run_id": read_json(run_dir / "run_manifest.json")["run_id"], "cases": len(ids),
              "selection": read_json(Path(args.labels).with_suffix(".meta.json")),
              "scoring": "strict: one primary human label per field (alternatives ignored)",
              "jev_vs_human": agreement(jev), "sonnet_fallback_vs_human": agreement(sonnet),
              f"{args.model}_vs_human": agreement(cand),
              "candidate": {"model": args.model, "effort": args.effort, "input_tokens": resp["input_tokens"],
                            "output_tokens": resp["output_tokens"], "cost_usd": resp["cost_usd"],
                            "api": "standard Messages API (the final run uses the Batch API at half price)",
                            "exact_quotes": f"{quotes_exact}/{len(ids)}"},
              "intent_confusion_human_to_candidate": dict(Counter(f"{human[i]['intent']}->{cand[i]['intent']}"
                                                                  for i in ids if human[i]['intent'] != cand[i]['intent'])),
              "note": "30 cases: diagnostic, not a population estimate. Human labels were made without seeing any "
                      "model output; 3 emoji-only intents were changed from complaint to unclear after the labeller "
                      "was reminded of the written rubric rule (still blind to model output)."}
    write_json(out / "report.json", report)
    write_json(out / "cases.json", cases)
    log(json.dumps({k: report[k] for k in ("jev_vs_human", "sonnet_fallback_vs_human", f"{args.model}_vs_human",
                                          "candidate")}, indent=1))
    return 0
