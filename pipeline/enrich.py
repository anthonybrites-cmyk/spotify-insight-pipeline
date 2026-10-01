"""Stage 2: enrich. One Jev request per distinct review text (1 <= 50 reviews per request).

Handoffs in <run>/enrich/:
  questions_<config>.json  the fixed question set sent with every request (the prompt)
  results.jsonl            one line per completed unit, saved as each request returns
  failures.jsonl           latest failure reason per unit (retried on resume)
  state.json               invocations, phases, early-gate result
  checkpoints/*.json       completed_ids snapshots at every stop and at completion

Resume: units already completed under the same label_config are never re-sent.
The first invocation's calls are phase "initial"; later invocations are "resume".
"""

import math
import time
from datetime import datetime, timezone
from decimal import Decimal

from . import rubric, translate
from .config import EARLY_GATE_FRACTION
from .dispatch import Task, run_tasks
from .entities import extract
from .ingest import load_sources, load_units
from .store import JsonlAppender, read_json, read_jsonl, write_json


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def current_config(run_dir, fallback_model):
    """label_config of the latest enrichment invocation (includes the translation tag when used)."""
    state = read_json(run_dir / "enrich" / "state.json", {})
    if state.get("invocations"):
        return state["invocations"][-1]["label_config"]
    return rubric.label_config(fallback_model)


def completed_results(run_dir, config):
    done = {}
    for row in read_jsonl(run_dir / "enrich" / "results.jsonl"):
        if row["label_config"] == config:
            done[row["unit"]] = row
    return done


def completed_ids(run_dir, done_units):
    return sorted(s["review_id"] for s in load_sources(run_dir) if s["unit"] in done_units)


def snapshot(run_dir, name, done_units, meta):
    ids = completed_ids(run_dir, done_units)
    path = run_dir / "enrich" / "checkpoints" / f"{name}.json"
    write_json(path, {"completed_ids": ids, "completed_units": len(done_units), **meta})
    return path, len(ids)


def validate(task, response):
    try:
        labels, diagnostics = rubric.interpret(response.answers, task.candidates)
    except rubric.InvalidAnswer:
        raise
    except Exception as e:  # malformed payload shapes are invalid answers, not crashes
        raise rubric.InvalidAnswer(f"{type(e).__name__}: {e}")
    return labels, diagnostics


def run(run_dir, client, budget, calls, stop, max_new=None, accept_gate=False, translator=None, log=print,
        **dispatch_kw):
    out = run_dir / "enrich"
    config = rubric.label_config(client.model, translate.tag(translator.model) if translator else None)
    write_json(out / f"questions_{config.replace('+', '_')}.json",
               {"label_config": config, "state_shape": {"review": "<review_text>"},
                "fixed_questions": rubric.fixed_questions(),
                "quote_question": {"instructions": rubric.QUOTE_INSTRUCTIONS,
                                   "criteria": "one option per sentence cut from the review by code"},
                "classification_input_fields": ["review_text"],
                "translation": ({"enabled": True, "model": translator.model, "tag": translate.tag(translator.model),
                                 "system_prompt": translate.SYSTEM, "schema": translate.SCHEMA,
                                 "groups": list(translate.TRANSLATION_GROUPS), "effort": translate.EFFORT}
                                if translator else {"enabled": False})})
    state = read_json(out / "state.json", {"invocations": []})
    same_config = [inv for inv in state["invocations"] if inv["label_config"] == config]
    phase = "resume" if same_config else "initial"

    units = load_units(run_dir)
    done = completed_results(run_dir, config)
    pending = [u for u in units if u["unit"] not in done]
    total = len(units)
    gate_at = math.ceil(total * EARLY_GATE_FRACTION)
    log(f"enrich: {len(done)}/{total} units already complete; {len(pending)} pending; phase={phase}; config={config}")
    invocation = {"started": now(), "phase": phase, "label_config": config, "pending_at_start": len(pending),
                  "completed_at_start": len(done), "spend_before_usd": str(budget.run_committed)}
    state["invocations"].append(invocation)
    write_json(out / "state.json", state)
    if not pending:
        return finish(run_dir, state, invocation, done, None, log)

    translations = {}
    if translator:
        translations = translate.saved(run_dir, config)
        window = pending[:max_new] if max_new else pending
        todo = [u for u in window if translate.needs_translation(u) and u["unit"] not in translations]
        if todo and stop.reason is None:
            log(f"enrich: translating {len(todo)} non-English texts before classification")
            translate.run(run_dir, translator, budget, calls, todo, config, phase, stop, log=log)
            translations = translate.saved(run_dir, config)
        if stop.reason:
            return finish(run_dir, state, invocation, done, stop.reason, log)

    results = JsonlAppender(out / "results.jsonl")
    failures = JsonlAppender(out / "failures.jsonl")
    counters = {"ok": 0, "failed": 0, "last_log": time.monotonic()}

    def tasks():
        for u in pending:
            translation = None
            if translator and translate.needs_translation(u):
                saved_tr = translations.get(u["unit"])
                if saved_tr is None:
                    continue  # never classify a candidate without its translation under this config
                if saved_tr["meaningful"] and not saved_tr["is_english"] and saved_tr["translation"].strip():
                    translation = saved_tr["translation"]
            questions, candidates = rubric.questions_for(u["text"], translated=bool(translation))
            task = Task(key=u["unit"], review_id=u["original_id"], state=rubric.state_for(u["text"], translation),
                        questions=questions, text_len=len(u["text"]) + len(translation or ""))
            task.candidates = candidates
            task.text = u["text"]
            task.language_group = u.get("language_group")
            task.translation_used = bool(translation)
            yield task

    def on_outcome(outcome):
        task = outcome.task
        if outcome.response is not None:
            labels, diagnostics = outcome.parsed
            row = {"unit": task.key, "review_id": task.review_id, "label_config": config, **labels,
                   "entities": extract(task.text), "model": outcome.response.model,
                   "request_id": outcome.response.request_id, "diagnostics": diagnostics,
                   "attempts": outcome.attempts, "completed_at": now(), "phase": phase,
                   "language_group": task.language_group, "translation_used": task.translation_used}
            results.write(row)
            done[task.key] = row
            counters["ok"] += 1
        else:
            failures.write({"unit": task.key, "review_id": task.review_id, "label_config": config,
                            "reason": outcome.error, "attempts": outcome.attempts, "at": now()})
            counters["failed"] += 1
        if counters["ok"] % 200 == 0:
            results.flush()
            failures.flush()
        if "early_gate" not in state and len(done) >= gate_at:
            gate = budget.early_gate(budget.run_committed, Decimal(len(done)) / Decimal(total), EARLY_GATE_FRACTION)
            state["early_gate"] = {**gate, "evaluated_at": now(), "accepted_override": bool(accept_gate)}
            write_json(out / "state.json", state)
            log(f"enrich: early cost gate at {len(done)}/{total} units: spend ${gate['spend_at_gate_usd']} "
                f"vs allowed ${gate['allowed_at_gate_usd']}; linear projection ${gate['linear_projection_usd']}; "
                f"{'PASSED' if gate['passed'] else 'FAILED'}")
            if not gate["passed"] and not accept_gate:
                stop.set("early_gate")
        if time.monotonic() - counters["last_log"] > 15:
            counters["last_log"] = time.monotonic()
            log(f"enrich: {len(done)}/{total} complete, {counters['failed']} failed this invocation, "
                f"run spend ${budget.run_committed:.4f}")

    if state.get("early_gate") and not state["early_gate"]["passed"] and not accept_gate \
            and not state["early_gate"].get("accepted_override"):
        log("enrich: the early cost gate failed earlier; rerun with --accept-early-gate after reviewing the projection")
        results.close(); failures.close()
        return "early_gate"
    reason = run_tasks(tasks(), client, budget, "enrich", phase, config, validate, on_outcome, stop, calls,
                       max_new=max_new, log=log, **dispatch_kw)
    if reason is None and max_new is not None and len(done) < len(units):
        reason = "stop_after"  # a deliberate stop, even when the remaining units were not yet translatable
    results.close()
    failures.close()
    return finish(run_dir, state, invocation, done, reason, log, counters)


def finish(run_dir, state, invocation, done, reason, log, counters=None):
    out = run_dir / "enrich"
    units_total = sum(1 for _ in read_jsonl(run_dir / "ingest" / "units.jsonl"))
    invocation.update({"ended": now(), "stop_reason": reason, "completed_at_end": len(done),
                       "succeeded_this_invocation": (counters or {}).get("ok", 0),
                       "failed_this_invocation": (counters or {}).get("failed", 0)})
    complete = len(done) == units_total
    meta = {"phase": invocation["phase"], "label_config": invocation["label_config"], "saved_at": now(),
            "stop_reason": reason}
    if complete:
        path, n = snapshot(run_dir, "enrich_complete", done, meta)
        invocation["snapshot"] = path.name
        log(f"enrich: all {units_total} units complete; snapshot {path.name} ({n} review IDs)")
    else:
        tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        path, n = snapshot(run_dir, f"enrich_stop_{tag}_{reason}", done, meta)
        invocation["snapshot"] = path.name
        state.setdefault("first_stop_snapshot", path.name)
        log(f"enrich: stopped ({reason}); {len(done)}/{units_total} units saved; snapshot {path.name} ({n} review IDs)")
    write_json(out / "state.json", state)
    return None if complete else (reason or "incomplete")
