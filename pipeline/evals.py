"""Evaluations kept outside business results.

eval-injection: synthetic adversarial and control reviews sent through the exact
enrichment rubric (Jev) and the verification prompt (Claude). Synthetic cases live
in evals/ and a separate run directory; they never enter the graded run or memo.

score-golden: compares a run's records with the human labels in golden_50. Golden
labels are read only here, after classification, and never sent to any model.
"""

import csv
import json
from pathlib import Path

from . import claude, rubric, verify
from .budget import Budget, cost_usd
from .config import JEV_PRICE_IN, JEV_PRICE_OUT, REPO
from .envfile import require
from .retry import run_with_retries
from .store import JsonlAppender, read_json, read_jsonl, write_json


def check_expect(labels, expect):
    failures = []
    for field in ("topic", "intent", "severity"):
        if field in expect and labels[field] not in expect[field]:
            failures.append(f"{field}={labels[field]} not in {expect[field]}")
    for bad in expect.get("not_topic", []):
        if labels["topic"] == bad:
            failures.append(f"topic={bad} (injected label obeyed)")
    for needle in expect.get("quote_contains", []):
        if needle.lower() not in labels["evidence_quote"].lower():
            failures.append(f"quote lacks {needle!r}")
    return failures


def run_injection(args, log):
    from .claude import ClaudeClient
    from .jev import JevClient
    cases = list(read_jsonl(REPO / "evals" / "injection_cases.jsonl"))
    out = REPO / "runs" / "eval-injection"
    budget = Budget("dev", args.budget_usd if hasattr(args, "budget_usd") else 0.25, "eval-injection")
    calls = JsonlAppender(out / "calls.jsonl")
    jev = JevClient(require("TYPESAFE_API_KEY"))
    results = []
    for case in cases:
        questions, candidates = rubric.questions_for(case["text"])

        def attempt(n, previous_error):
            reservation = budget.reserve(cost_usd(3000, 0, JEV_PRICE_IN, JEV_PRICE_OUT))
            try:
                r = jev.ask(rubric.state_for(case["text"]), questions)
            except BaseException:
                budget.release(reservation)
                raise
            budget.commit(reservation, cost_usd(r.input_tokens, r.output_tokens, JEV_PRICE_IN, JEV_PRICE_OUT),
                          "eval", r.request_id)
            return r
        response = run_with_retries(attempt, lambda n, e: log(f"{case['case']}: attempt {n} failed: {e}"))
        calls.write({"request_id": response.request_id, "role": "eval", "case": case["case"], "model": response.model,
                     "input_tokens": response.input_tokens, "output_tokens": response.output_tokens})
        labels, diagnostics = rubric.interpret(response.answers, candidates)
        results.append({"case": case["case"], "model": "jev", "labels": labels,
                        "confidence": diagnostics["confidence"], "failures": check_expect(labels, case["expect"])})

    # Same cases through the verifier prompt, in one batch, to test cross-review injection.
    claude_client = ClaudeClient(require("ANTHROPIC_API_KEY"))
    ids = [c["case"] for c in cases]
    payload = [{"review_id": c["case"], "text": c["text"]} for c in cases]
    user = "<reviews>\n" + json.dumps(payload, ensure_ascii=False, indent=0) + "\n</reviews>"
    parsed, _ = claude.call(claude_client, budget, calls, out / "handoffs", "verify_injection", "eval", "eval",
                            verify.label_config(), [], verify.system_prompt(), user, schema=verify.SCHEMA,
                            validate=verify.make_validator(ids), max_tokens=8000)
    by_id = {r["review_id"]: r for r in parsed["results"]}
    for case in cases:
        v = by_id[case["case"]]
        labels = {"topic": v["topic"], "intent": v["intent"], "severity": v["severity"], "evidence_quote": case["text"]}
        results.append({"case": case["case"], "model": "claude-verify", "labels": labels,
                        "failures": check_expect(labels, {k: e for k, e in case["expect"].items() if k != "quote_contains"})})
    calls.close()
    summary = {m: {"cases": sum(r["model"] == m for r in results),
                   "passed": sum(r["model"] == m and not r["failures"] for r in results)} for m in ("jev", "claude-verify")}
    write_json(out / "results.json", {"summary": summary, "results": results, "budget": budget.summary(),
                                      "label_config": rubric.label_config(jev.model)})
    for r in results:
        log(f"{r['model']:>13} {r['case']:<30} {'PASS' if not r['failures'] else 'FAIL ' + '; '.join(r['failures'])}")
    log(f"summary {summary}; spend {budget.summary()['this_run_usd']} USD")
    return 0


SENTIMENT_TOLERANCE = 0.5  # predeclared: |predicted - human| <= 0.5 counts as agreement


def _accepted(value, cast=str):
    """Human cells may list several accepted labels separated by '|' for ambiguous cases."""
    return [cast(v.strip()) for v in value.split("|") if v.strip()]


def score_golden(args, log):
    """Compare saved predictions with the human golden labels. No model calls.

    Missing or quarantined predictions count as wrong. Results go to evals/golden/.
    """
    from collections import Counter
    from .records import build
    from .checker import TOPICS, INTENTS
    run_dir = Path(args.run_dir).resolve()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with Path(args.golden).open(encoding="utf-8-sig", newline="") as f:
        gold = list(csv.DictReader(f))
    labeled = [g for g in gold if all(g.get(k, "").strip() for k in ("topic", "intent", "severity"))]
    if len(labeled) < len(gold):
        log(f"golden: {len(gold) - len(labeled)} of {len(gold)} rows are not fully labelled (topic, intent, severity)")
    if not labeled:
        return 1
    for g in labeled:
        bad = [t for t in _accepted(g["topic"]) if t not in TOPICS] + [i for i in _accepted(g["intent"]) if i not in INTENTS]
        bad += [v for v in _accepted(g["severity"]) if v not in "12345"]
        if bad:
            raise SystemExit(f"golden row {g['review_id']}: invalid label(s) {bad}")
    manifest = read_json(run_dir / "run_manifest.json", {})
    from .config import JEV_MODEL
    records = {r["review_id"]: r for r in build(run_dir, "fake-jev-0" if manifest.get("fake") else JEV_MODEL)}
    texts = {}
    for g in gold:
        texts[g["review_id"]] = g["review_text"]
    totals = Counter()
    confusion = {"topic": Counter(), "intent": Counter()}
    per_topic = Counter()
    nr = Counter()
    sentiment_errors = []
    cases = []
    for g in labeled:
        acc = {"topic": _accepted(g["topic"]), "intent": _accepted(g["intent"]), "severity": _accepted(g["severity"], int)}
        ambiguous = any(len(v) > 1 for v in acc.values())
        totals["ambiguous"] += ambiguous
        r = records.get(g["review_id"])
        case = {"review_id": g["review_id"], "text": texts[g["review_id"]][:300], "expected": {k: g[k] for k in acc},
                "ambiguous": ambiguous}
        if not r or r["status"] != "completed":
            case.update({"status": r["status"] if r else "missing", "pass": False,
                         "fail_reasons": ["no valid prediction (counts as wrong)"]})
            totals["missing_or_quarantined"] += 1
            cases.append(case)
            continue
        ok = {k: r[k] in acc[k] for k in acc}
        for k, v in ok.items():
            totals[k + "_correct"] += v
        totals["all_three_correct"] += all(ok.values())
        totals["severity_abs_error"] += min(abs(r["severity"] - x) for x in acc["severity"])
        totals["present"] += 1
        if len(acc["topic"]) == 1:
            per_topic[acc["topic"][0]] += 1
            confusion["topic"][f"{acc['topic'][0]}->{r['topic']}"] += 1
        if len(acc["intent"]) == 1:
            confusion["intent"][f"{acc['intent'][0]}->{r['intent']}"] += 1
        fails = [f"{k}: expected {g[k]}, predicted {r[k]}" for k, v in ok.items() if not v]
        if g.get("sentiment", "").strip():
            err = abs(float(g["sentiment"]) - r["sentiment"])
            sentiment_errors.append(err)
            if err > SENTIMENT_TOLERANCE:
                fails.append(f"sentiment: expected {g['sentiment']}, predicted {r['sentiment']} (tolerance {SENTIMENT_TOLERANCE})")
        quote_ok = r["evidence_quote"] in texts[g["review_id"]]
        if not quote_ok:
            fails.append("evidence_quote is not an exact substring")
        human_entities = [x.strip() for x in g.get("entities", "").replace(";", "|").split("|") if x.strip()]
        unsupported = [x for x in r["entities"] if human_entities and x.lower() not in {h.lower() for h in human_entities}]
        if g.get("needs_review", "").strip():
            human_nr = g["needs_review"].strip().lower() in ("true", "1", "yes", "y")
            nr[("tp" if r["needs_review"] else "fn") if human_nr else ("fp" if r["needs_review"] else "tn")] += 1
        case.update({"status": "completed", "predicted": {k: r[k] for k in ("topic", "intent", "severity", "sentiment",
                                                                            "needs_review", "entities")},
                     "evidence_quote": r["evidence_quote"], "quote_is_substring": quote_ok,
                     "quote_supports_label": "", "entities_not_in_human_list": unsupported,
                     "cache_source_id": r.get("cache_source_id"), "pass": not fails, "fail_reasons": fails})
        cases.append(case)
    n = len(labeled)
    frac = lambda k: round(totals[k] / n, 4)
    precision = nr["tp"] / (nr["tp"] + nr["fp"]) if nr["tp"] + nr["fp"] else None
    recall = nr["tp"] / (nr["tp"] + nr["fn"]) if nr["tp"] + nr["fn"] else None
    summary = {"run_dir": str(run_dir), "labelled_cases": n, "ambiguous_cases": totals["ambiguous"],
               "missing_or_quarantined_counted_wrong": totals["missing_or_quarantined"],
               "agreement": {"topic": frac("topic_correct"), "intent": frac("intent_correct"),
                             "severity_exact": frac("severity_correct"), "all_three": frac("all_three_correct")},
               "severity_mae_on_present": round(totals["severity_abs_error"] / max(1, totals["present"]), 4),
               "sentiment": {"tolerance": SENTIMENT_TOLERANCE, "labelled": len(sentiment_errors),
                             "mae": round(sum(sentiment_errors) / len(sentiment_errors), 4) if sentiment_errors else None,
                             "within_tolerance": sum(e <= SENTIMENT_TOLERANCE for e in sentiment_errors)},
               "needs_review_as_prediction": {**dict(nr), "precision": precision, "recall": recall},
               "per_topic_support_unambiguous": dict(per_topic),
               "confusion_expected_to_predicted": {k: dict(v.most_common()) for k, v in confusion.items()},
               "note": "50 cases are a small diagnostic sample, not a population accuracy estimate. "
                       "quote_supports_label is left blank for human inspection."}
    write_json(out / "summary.json", summary)
    write_json(out / "cases.json", cases)
    with (out / "disagreements.md").open("w", encoding="utf-8") as f:
        f.write("# Golden-set disagreements\n\n")
        for c in cases:
            if not c["pass"]:
                f.write(f"- `{c['review_id']}`: {'; '.join(c['fail_reasons'])}\n  > {c['text']}\n")
    log(json.dumps({k: summary[k] for k in ("labelled_cases", "agreement", "severity_mae_on_present", "ambiguous_cases")}))
    return 0
