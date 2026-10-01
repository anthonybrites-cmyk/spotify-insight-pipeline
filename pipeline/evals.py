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
from .store import JsonlAppender, canonical, read_json, read_jsonl, sha256_text, write_json


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
                            verify.label_config(claude_client.model, claude_client.effort), [], verify.system_prompt(), user, schema=verify.SCHEMA,
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


def _alternatives(cell):
    """Parse 'severity=4; topic=downloads' into {field: [values]} (secondary, lenient scoring only)."""
    alts = {}
    for part in cell.replace("|", ";").split(";"):
        if "=" in part:
            field, value = (x.strip() for x in part.split("=", 1))
            if field in ("topic", "intent", "severity") and value:
                alts.setdefault(field, []).append(int(value) if field == "severity" else value)
    return alts


def _truthy(cell):
    return cell.strip().lower() in ("true", "1", "yes", "y")


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
    adjudication = getattr(args, "adjudication", None)
    if adjudication:
        # Post-hoc labeller decisions, applied to a copy and reported separately from the original labels.
        changes = read_json(adjudication)["label_changes"]
        by_id = {g["review_id"]: g for g in gold}
        for ch in changes:
            if by_id[ch["review_id"]][ch["field"]].strip() != ch["original"]:
                raise SystemExit(f"adjudication does not match the original label for {ch['review_id']}")
            by_id[ch["review_id"]][ch["field"]] = ch["adjudicated"]
        log(f"golden: applying {len(changes)} adjudicated label change(s) from {adjudication}")
    labeled = [g for g in gold if all(g.get(k, "").strip() for k in ("topic", "intent", "severity"))]
    if len(labeled) < len(gold):
        log(f"golden: {len(gold) - len(labeled)} of {len(gold)} rows are not fully labelled (topic, intent, severity)")
    if not labeled:
        return 1
    for g in labeled:
        bad = []
        if g["topic"].strip() not in TOPICS:
            bad.append(f"topic={g['topic']!r}")
        if g["intent"].strip() not in INTENTS:
            bad.append(f"intent={g['intent']!r}")
        if g["severity"].strip() not in ("1", "2", "3", "4", "5"):
            bad.append(f"severity={g['severity']!r}")
        alts = _alternatives(g.get("alternative_labels", ""))
        bad += [f"alternative topic {t!r}" for t in alts.get("topic", []) if t not in TOPICS]
        bad += [f"alternative intent {i!r}" for i in alts.get("intent", []) if i not in INTENTS]
        bad += [f"alternative severity {v!r}" for v in alts.get("severity", []) if v not in (1, 2, 3, 4, 5)]
        if bad:
            raise SystemExit(f"golden row {g['review_id']}: one primary label per column required; invalid: {bad}")
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
        primary = {"topic": g["topic"].strip(), "intent": g["intent"].strip(), "severity": int(g["severity"])}
        alts = _alternatives(g.get("alternative_labels", ""))
        ambiguous = _truthy(g.get("ambiguous", "")) or bool(alts)
        totals["ambiguous"] += ambiguous
        r = records.get(g["review_id"])
        case = {"review_id": g["review_id"], "text": texts[g["review_id"]][:300], "expected": primary,
                "alternatives": alts, "ambiguous": ambiguous, "label_notes": g.get("label_notes", "")}
        if not r or r["status"] != "completed":
            case.update({"status": r["status"] if r else "missing", "pass": False,
                         "fail_reasons": ["no valid prediction (counts as wrong)"]})
            totals["missing_or_quarantined"] += 1
            cases.append(case)
            continue
        # Headline (strict): the single primary human label. Secondary (lenient): primary or a noted alternative.
        ok = {k: r[k] == v for k, v in primary.items()}
        lenient = {k: ok[k] or r[k] in alts.get(k, []) for k in primary}
        for k in primary:
            totals[k + "_correct"] += ok[k]
            totals[k + "_lenient"] += lenient[k]
        totals["all_three_correct"] += all(ok.values())
        totals["severity_abs_error"] += abs(r["severity"] - primary["severity"])
        totals["present"] += 1
        per_topic[primary["topic"]] += 1
        confusion["topic"][f"{primary['topic']}->{r['topic']}"] += 1
        confusion["intent"][f"{primary['intent']}->{r['intent']}"] += 1
        fails = [f"{k}: expected {primary[k]}, predicted {r[k]}" + (" (matches a noted alternative)" if lenient[k] else "")
                 for k, v in ok.items() if not v]
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
            human_nr = _truthy(g["needs_review"])
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
    summary = {"run_dir": str(run_dir), "labels": "adjudicated (post-hoc, disclosed)" if adjudication else "original",
               "labelled_cases": n, "ambiguous_cases": totals["ambiguous"],
               "missing_or_quarantined_counted_wrong": totals["missing_or_quarantined"],
               "agreement": {"topic": frac("topic_correct"), "intent": frac("intent_correct"),
                             "severity_exact": frac("severity_correct"), "all_three": frac("all_three_correct")},
               "agreement_basis": "strict: one primary human label per field; missing/quarantined count as wrong",
               "secondary_lenient_agreement": {"topic": frac("topic_lenient"), "intent": frac("intent_lenient"),
                                               "severity_exact": frac("severity_lenient"),
                                               "note": "also accepts alternatives noted in alternative_labels; "
                                                       "reported separately, never as the headline"},
               "severity_mae_on_present": round(totals["severity_abs_error"] / max(1, totals["present"]), 4),
               "sentiment": {"tolerance": SENTIMENT_TOLERANCE, "labelled": len(sentiment_errors),
                             "mae": round(sum(sentiment_errors) / len(sentiment_errors), 4) if sentiment_errors else None,
                             "within_tolerance": sum(e <= SENTIMENT_TOLERANCE for e in sentiment_errors)},
               "needs_review_as_prediction": {**dict(nr), "precision": precision, "recall": recall},
               "per_topic_support": dict(per_topic),
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


def write_subset(args, log):
    """Write the rows of an input CSV whose review text falls in the given language groups."""
    from . import language
    from .checker import FIELDS, csv_rows
    groups = set(g.strip() for g in args.groups.split(","))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(FIELDS), lineterminator="\n")
        writer.writeheader()
        for row in csv_rows(args.input):
            if row["review_text"].strip() and language.group(row["review_text"]) in groups:
                writer.writerow({k: row[k] for k in FIELDS})
                n += 1
    log(f"subset: wrote {n} rows in groups {sorted(groups)} to {out}")
    return 0


def compare_translation(args, log):
    """Same blind verifier labels (from the baseline run), two Jev label sets: baseline vs translated.

    The translated run only needs stages ingest,enrich; no second verification pass. No model calls here.
    """
    from decimal import Decimal
    from .enrich import current_config, final_results
    from .config import JEV_MODEL
    base_dir, tr_dir = Path(args.baseline_run).resolve(), Path(args.translated_run).resolve()
    base = final_results(base_dir, current_config(base_dir, JEV_MODEL))
    translated = final_results(tr_dir, current_config(tr_dir, JEV_MODEL))
    comparisons = [c for c in read_json(base_dir / "verify" / "comparisons.json") if c["unit"] in translated]
    rows, totals = [], {"n": 0, "base_missing": 0}
    for key in ("baseline", "variant"):
        for f in ("topic", "intent", "severity"):
            totals[f"{key}_{f}"] = 0
        totals[f"{key}_material"] = 0
    for c in comparisons:
        b = base.get(c["unit"])
        if b is None:
            totals["base_missing"] += 1
            continue
        totals["n"] += 1
        v = c["verifier"]
        t = translated[c["unit"]]
        for key, labels in (("baseline", b), ("variant", t)):
            for f in ("topic", "intent", "severity"):
                totals[f"{key}_{f}"] += labels[f] == v[f]
            totals[f"{key}_material"] += (labels["topic"] != v["topic"] or labels["intent"] != v["intent"]
                                          or abs(labels["severity"] - v["severity"]) >= 2)
        rows.append({"review_id": c["review_id"], "verifier": v, "baseline_jev": {k: b[k] for k in v},
                     "variant_jev": {k: t[k] for k in v}, "translation_used": t.get("translation_used")})
    n = totals["n"] or 1
    calls = list(read_jsonl(tr_dir / "calls.jsonl"))
    tr_calls = [c for c in calls if c["role"] == "enrich" and "translation_handoffs" in c.get("handoff", "")]
    def jev_tokens(run):
        enrich_calls = [c for c in read_jsonl(run / "calls.jsonl")
                        if c["role"] == "enrich" and c["model"].startswith("jev") and c["outcome"] == "succeeded"]
        return round(sum(c["input_tokens"] for c in enrich_calls) / len(enrich_calls), 1) if enrich_calls else None
    shared = set(base) & set(translated)
    changes = {f: sum(base[u][f] != translated[u][f] for u in shared) for f in ("topic", "intent", "severity")}
    report = {"units_compared": totals["n"], "baseline_missing": totals["base_missing"],
              "label_changes_vs_baseline_all_shared_units": {"units": len(shared), **changes},
              "jev_input_tokens_per_enrich_request": {"baseline": jev_tokens(base_dir), "variant": jev_tokens(tr_dir)},
              "agreement_with_blind_verifier": {
                  key: {f: round(totals[f"{key}_{f}"] / n, 4) for f in ("topic", "intent", "severity")}
                  | {"material_disagreement_rate": round(totals[f"{key}_material"] / n, 4)}
                  for key in ("baseline", "variant")},
              "translation_calls": {"succeeded": sum(c["outcome"] == "succeeded" for c in tr_calls),
                                    "failed": sum(c["outcome"] == "failed" for c in tr_calls),
                                    "input_tokens": sum(c["input_tokens"] for c in tr_calls),
                                    "output_tokens": sum(c["output_tokens"] for c in tr_calls),
                                    "cost_usd_list_price": str(sum(Decimal(c.get("cost_usd", "0")) for c in tr_calls))},
              "note": "Verifier labels come from the baseline run and are blind (original text only). "
                      "Agreement is not accuracy.",
              "rows": rows}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_json(out, report)
    log(json.dumps({k: report[k] for k in ("units_compared", "agreement_with_blind_verifier", "translation_calls",
                                           "label_changes_vs_baseline_all_shared_units",
                                           "jev_input_tokens_per_enrich_request")}, indent=1))
    return 0


def check_golden(args, log):
    """Validate the hand-labelled golden file (no model calls). Errors block scoring; warnings are for review."""
    from .checker import FIELDS, INTENTS, TOPICS, csv_rows
    path = Path(args.golden)
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames
        rows = list(reader)
    errors, warnings = [], []
    required = list(FIELDS) + ["topic", "intent", "sentiment", "severity", "entities", "evidence_quote", "needs_review"]
    missing_cols = [c for c in required if c not in header]
    if missing_cols:
        errors.append(f"missing columns: {missing_cols}")
    source = {r["review_id"]: r for r in csv_rows(args.source)} if args.source else {}
    if source and set(source) != {r.get("review_id") for r in rows}:
        errors.append("review_id set differs from the course golden file")
    for n, r in enumerate(rows, start=2):  # spreadsheet row number (header is row 1)
        rid = r.get("review_id", "")
        where = f"row {n} ({rid[:8]})"
        if source.get(rid) and any(source[rid][k] != r[k] for k in FIELDS):
            changed = [k for k in FIELDS if source[rid][k] != r[k]]
            errors.append(f"{where}: source column(s) changed: {changed}")
        topic, intent, sev = r.get("topic", "").strip(), r.get("intent", "").strip(), r.get("severity", "").strip()
        if topic not in TOPICS:
            errors.append(f"{where}: topic {topic!r} not one of the 8 labels")
        if intent not in INTENTS:
            errors.append(f"{where}: intent {intent!r} not allowed")
        if sev not in ("1", "2", "3", "4", "5"):
            errors.append(f"{where}: severity {sev!r} must be one integer 1-5")
        try:
            s = float(r.get("sentiment", ""))
            if not -1 <= s <= 1:
                errors.append(f"{where}: sentiment {s} outside -1..1")
        except ValueError:
            errors.append(f"{where}: sentiment {r.get('sentiment')!r} is not a number")
        nr = r.get("needs_review", "").strip().lower()
        if nr not in ("true", "false"):
            errors.append(f"{where}: needs_review {r.get('needs_review')!r} must be true or false")
        quote = r.get("evidence_quote", "")
        if not quote.strip():
            errors.append(f"{where}: evidence_quote is empty")
        elif quote not in r.get("review_text", ""):
            hint = " (matches after trimming spaces)" if quote.strip() in r.get("review_text", "") else ""
            errors.append(f"{where}: evidence_quote is not an exact substring of review_text{hint}")
        amb = r.get("ambiguous", "").strip().lower()
        if amb not in ("", "true", "false"):
            errors.append(f"{where}: ambiguous {r.get('ambiguous')!r} must be true, false or blank")
        alts = r.get("alternative_labels", "").strip()
        if alts:
            for part in alts.replace("|", ";").split(";"):
                if part.strip() and "=" not in part:
                    errors.append(f"{where}: alternative_labels part {part.strip()!r} should look like field=value")
            if amb != "true":
                warnings.append(f"{where}: alternative_labels given but ambiguous is not true")
        if "|" in topic + intent + sev:
            errors.append(f"{where}: use one primary label; put alternatives in alternative_labels")
        if sev in ("1", "2", "3", "4", "5") and intent in INTENTS:
            if intent in ("praise", "request", "unclear") and sev != "1":
                warnings.append(f"{where}: intent {intent} with severity {sev}; shared definition says severity 1")
            if intent == "complaint" and sev == "1":
                warnings.append(f"{where}: complaint with severity 1; shared definition puts complaints at >= 2")
    summary = {"file": str(path), "rows": len(rows), "errors": errors, "warnings": warnings,
               "counts": {"needs_review_true": sum(r.get("needs_review", "").strip().lower() == "true" for r in rows),
                          "ambiguous_true": sum(r.get("ambiguous", "").strip().lower() == "true" for r in rows),
                          "with_label_notes": sum(bool(r.get("label_notes", "").strip()) for r in rows)}}
    write_json(Path(args.out), summary)
    log(f"golden check: {len(rows)} rows, {len(errors)} errors, {len(warnings)} warnings")
    for e in errors:
        log("ERROR   " + e)
    for w in warnings:
        log("WARNING " + w)
    return 0 if not errors else 1


def golden_head_to_head(args, log):
    """Claude labels the (label-stripped) golden texts blind; compare Jev vs Claude vs the human labels.

    Only review text is sent (from the golden run's ingest, built from the stripped copy). Claude uses the
    verifier prompt and schema; the same code rules Jev gets (praise/request/unclear -> severity 1,
    complaint >= 2) are applied to Claude's labels so the comparison is like for like.
    """
    from collections import Counter
    from .claude import ClaudeClient
    from .config import JEV_MODEL
    from .ingest import load_sources, load_units
    from .records import build
    run_dir = Path(args.golden_run).resolve()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    units = load_units(run_dir)
    unit_of = {s["review_id"]: s["unit"] for s in load_sources(run_dir)}
    ids = [u["original_id"] for u in units]
    payload = [{"review_id": u["original_id"], "text": u["text"]} for u in units]
    user = "<reviews>\n" + json.dumps(payload, ensure_ascii=False, indent=0) + "\n</reviews>"
    budget = Budget("dev", args.budget_usd, "golden-head-to-head")
    calls = JsonlAppender(run_dir / "head_to_head_calls.jsonl")
    client = ClaudeClient(require("ANTHROPIC_API_KEY"))
    handoffs = run_dir / "head_to_head"
    name = f"claude_golden_{sha256_text(verify.label_config(client.model, client.effort) + canonical(ids))[:12]}"
    parsed = read_json(handoffs / f"{name}.parsed.json")
    if parsed is None:
        parsed, _ = claude.call(client, budget, calls, handoffs, name, "eval", "eval",
                                verify.label_config(client.model, client.effort), ids,
                                verify.system_prompt(), user, schema=verify.SCHEMA, validate=verify.make_validator(ids))
    calls.close()
    budget.close()
    claude_by_unit = {}
    by_id = {r["review_id"]: r for r in parsed["results"]}
    for u in units:
        r = dict(by_id[u["original_id"]])
        if r["intent"] in ("praise", "request", "unclear"):
            r["severity"] = 1
        elif r["intent"] == "complaint" and r["severity"] < 2:
            r["severity"] = 2
        claude_by_unit[u["unit"]] = r
    jev_records = {r["review_id"]: r for r in build(run_dir, JEV_MODEL)}
    jev_diag = {r["unit"]: r["diagnostics"] for r in read_jsonl(run_dir / "enrich" / "results.jsonl")}
    with Path(args.golden).open(encoding="utf-8-sig", newline="") as f:
        gold = list(csv.DictReader(f))

    def band(conf):
        return "low(<0.5)" if conf < 0.5 else "mid(0.5-0.8)" if conf < 0.8 else "high(>=0.8)"
    tallies = {}
    rows = []
    for g in gold:
        rid = g["review_id"]
        unit = unit_of[rid]
        human = {"topic": g["topic"].strip(), "intent": g["intent"].strip(), "severity": int(g["severity"])}
        jev = jev_records[rid]
        cl = claude_by_unit[unit]
        conf = jev_diag[unit]["confidence"]
        b = band(min(conf["topic"], conf["intent"], conf["severity"]))
        row = {"review_id": rid, "jev_confidence_band": b, "human": human,
               "jev": {k: jev[k] for k in human}, "claude": {k: cl[k] for k in human}, "claude_reason": cl["reason"]}
        for who in ("jev", "claude"):
            for key in ("all", b):
                t = tallies.setdefault(f"{who}|{key}", Counter())
                t["n"] += 1
                for field in human:
                    t[field] += row[who][field] == human[field]
                t["all_three"] += all(row[who][f] == human[f] for f in human)
                t["severity_abs_error"] += abs(row[who]["severity"] - human["severity"])
        rows.append(row)
    def rates(t):
        n = t["n"]
        return {"n": n, **{k: round(t[k] / n, 4) for k in ("topic", "intent", "severity", "all_three")},
                "severity_mae": round(t["severity_abs_error"] / n, 4)}
    summary = {k: rates(v) for k, v in sorted(tallies.items())}
    usage = list(read_jsonl(run_dir / "head_to_head_calls.jsonl"))
    report = {"comparison": "strict agreement with the single primary human label", "by_model_and_jev_band": summary,
              "claude_model": client.model, "claude_label_config": verify.label_config(client.model, client.effort),
              "claude_calls": [{k: c.get(k) for k in ("request_id", "outcome", "input_tokens", "output_tokens", "cost_usd")}
                               for c in usage],
              "disclosure": "Golden labels were used to compare candidate setups (the brief allows this before choosing "
                            "a final setup); any resulting change must be disclosed and checked on held-out cases.",
              "rows": rows}
    write_json(out / "head_to_head.json", report)
    for k, v in summary.items():
        log(f"{k:22s} {v}")
    return 0
