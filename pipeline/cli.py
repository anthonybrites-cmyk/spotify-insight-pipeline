"""Command-line entry point: python -m pipeline <command> ...

  keys                 show whether each API key is present (never the value)
  run                  ingest -> enrich -> verify -> group -> rank -> recommend [-> export]
  rerank               regenerate the baseline ranking from saved outputs (no model calls) and diff it
  export               rebuild the grading and results folders from a finished run directory
  check                run the course checker (profile, reference, check) against a grading folder
  golden-input         write a copy of golden_50 with only the six source fields (labels stripped)
  score-golden         compare a run's records with your hand-labelled golden_50 file
  eval-injection       live prompt-injection cases through the Jev rubric and the verifier
  subset               rows of a CSV in given language groups (translation test input)
  compare-translation  baseline vs translated Jev labels against the same blind verifier labels
  cost                 100-review cost/runtime calculator: `cost` / `cost replay` (offline, default),
                       `cost pilot` (PAID, explicit), `cost collect` (offline)
"""

import argparse
import subprocess
import sys
import time
import uuid
from pathlib import Path

from . import enrich, export, golden, group, ingest, memo, rank, records, verify
from .budget import Budget, BudgetExceeded
from .retry import AuthFailure
from .config import CLAUDE_MODEL, JEV_MODEL, MODEL_ALLOWLIST, REPO, VENDOR_CHECKER
from .dispatch import StopFlag
from .envfile import key_status, require
from .runlog import RunLog, summarize
from .store import CallLog, JsonlAppender, read_json, write_json

STOP_EXIT = 3
STAGES = ("ingest", "enrich", "verify", "group", "rank", "recommend")


def log(message):
    print(time.strftime("%H:%M:%S"), message, flush=True)


def make_clients(fake, stages, translate=False, fallback=False, effort="medium", max_tokens=16000):
    if fake:
        from .fakes import FakeClaude, FakeJev
        claude_fake = FakeClaude()
        claude_fake.effort, claude_fake.max_tokens = effort, max_tokens
        return FakeJev(), claude_fake
    from .claude import ClaudeClient
    from .jev import JevClient
    jev = JevClient(require("TYPESAFE_API_KEY"), model=JEV_MODEL) if "enrich" in stages or "group" in stages else None
    needs_claude = bool({"verify", "group", "recommend"} & set(stages)) or translate or fallback
    claude_client = (ClaudeClient(require("ANTHROPIC_API_KEY"), model=CLAUDE_MODEL, effort=effort, max_tokens=max_tokens)
                     if needs_claude else None)
    return jev, claude_client


def git_commit():
    try:
        out = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
        dirty = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "--", "pipeline"],
                               capture_output=True, text=True).stdout.strip()
        return out.stdout.strip() + ("+uncommitted-pipeline-changes" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def cmd_run(args):
    run_dir = Path(args.run_dir).resolve()
    input_csv = Path(args.input).resolve()
    stages = tuple(s.strip() for s in args.stages.split(",")) if args.stages else STAGES
    unknown = set(stages) - set(STAGES)
    if unknown:
        raise SystemExit(f"unknown stages: {sorted(unknown)}")
    from . import rubric
    rubric.use_variant(args.rubric)
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = read_json(run_dir / "run_manifest.json", {})
    # A run directory is tied to its input by content (SHA-256), not by folder name.
    from .store import sha256_file
    input_sha = sha256_file(input_csv)
    if manifest and manifest.get("input_sha256", input_sha) != input_sha:
        raise SystemExit(f"{run_dir} belongs to a different input ({manifest.get('input')}); use a new --run-dir")
    if manifest and manifest.get("input") != str(input_csv):
        manifest.setdefault("input_moves", []).append({"from": manifest.get("input"), "to": str(input_csv)})
    manifest["input_sha256"] = input_sha
    invocation = time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    manifest.setdefault("run_id", run_dir.name + "-" + uuid.uuid4().hex[:8])
    manifest.update({"input": str(input_csv), "budget_group": args.budget_group, "budget_usd": args.budget_usd,
                     "verify_n": args.verify_n, "fake": args.offline_fake, "stages": list(stages),
                     "workers": args.workers, "rps": args.rps, "max_minutes": args.max_minutes,
                     "exclude_golden_ids_from": args.exclude_golden, "translate": args.translate,
                     "rubric_variant": args.rubric, "fallback": args.fallback,
                     "scope_sample": args.scope_sample, "scope_include_duplicates": args.scope_include_duplicates,
                     "fallback_threshold": args.fallback_threshold, "fallback_max_fraction": args.fallback_max_fraction,
                     "claude_effort": args.claude_effort, "claude_max_tokens": args.claude_max_tokens})
    manifest.setdefault("invocations", []).append({"id": invocation, "code_version": git_commit(),
                                                  "argv": sys.argv[1:], "started": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
    write_json(run_dir / "run_manifest.json", manifest)

    if CLAUDE_MODEL not in MODEL_ALLOWLIST["claude"] or JEV_MODEL not in MODEL_ALLOWLIST["jev"]:
        raise SystemExit("configured model is not on the allowlist (config.MODEL_ALLOWLIST)")
    jev, claude_client = make_clients(args.offline_fake, stages, args.translate, args.fallback != "off",
                                      args.claude_effort, args.claude_max_tokens)
    budget = Budget(args.budget_group, args.budget_usd, run_dir.name,
                    ledger_dir=(run_dir / "budgets") if args.offline_fake else REPO / "budgets")
    calls = CallLog(run_dir / "calls.jsonl", run_id=manifest["run_id"], invocation=invocation,
                    worker_limit=args.workers)
    runlog = RunLog(run_dir, invocation)
    runlog.event("invocation_start", argv=sys.argv[1:], budget=budget.summary())
    code = None
    try:
        code = _run_stages(args, stages, run_dir, input_csv, jev, claude_client, budget, calls, runlog, manifest)
        return code
    finally:
        runlog.event("invocation_end", exit_code=code, budget=budget.summary())
        calls.close()
        budget.close()
        runlog.close()


def _run_stages(args, stages, run_dir, input_csv, jev, claude_client, budget, calls, runlog, manifest):
    try:
        return _stages(args, stages, run_dir, input_csv, jev, claude_client, budget, calls, runlog, manifest)
    except (BudgetExceeded, AuthFailure) as e:
        # Account or spend stops in any stage end the invocation cleanly; every saved handoff is kept,
        # and rerunning the same command resumes without repeating completed work.
        kind = "spending cap" if isinstance(e, BudgetExceeded) else "provider account (key or credits)"
        runlog.event("stopped", reason=kind, detail=str(e)[:300])
        log(f"stopped: {kind}: {e}. Progress is saved; fix the cause and rerun the same command to resume. "
            f"Budget {budget.summary()}")
        return STOP_EXIT


def _stages(args, stages, run_dir, input_csv, jev, claude_client, budget, calls, runlog, manifest):
    dispatch_kw = {"workers": args.workers, "rps": args.rps}
    exclude = golden.load_ids(args.exclude_golden)
    log(f"run: {run_dir.name}; stages {','.join(stages)}; budget {budget.summary()}")

    with runlog.stage("ingest"):
        ingest.run(input_csv, run_dir, log=log)
        if args.scope_sample:
            from . import scope as scope_mod
            existing = scope_mod.load(run_dir)
            wanted = {"sample_size": args.scope_sample, "include_duplicates": args.scope_include_duplicates}
            if existing and {k: existing["settings"][k] for k in wanted} != wanted:
                raise SystemExit(f"{run_dir} already has scope {existing['settings']}; use a new --run-dir")
            sc = scope_mod.build(run_dir, args.scope_sample, args.scope_include_duplicates)
            log(f"scope: {scope_mod.describe(sc)}; {len(sc['representative']):,} distinct texts to classify")
        elif (run_dir / "ingest" / "scope.json").exists():
            raise SystemExit(f"{run_dir} was started with a sample scope; pass the same --scope-sample to resume")
    texts = {u["unit"]: u["text"] for u in ingest.load_units(run_dir)}

    with StopFlag(max_minutes=args.max_minutes) as stop:
        if "enrich" in stages:
            with runlog.stage("enrich") as st:
                translator = claude_client if args.translate else None
                fb = ({"client": claude_client, "mode": args.fallback, "threshold": args.fallback_threshold,
                       "max_fraction": args.fallback_max_fraction, "workers": args.workers}
                      if args.fallback != "off" else None)
                reason = enrich.run(run_dir, jev, budget, calls, stop, max_new=args.stop_after_units,
                                    accept_gate=args.accept_early_gate, translator=translator, fallback_cfg=fb,
                                    log=log, **dispatch_kw)
                if reason == "incomplete" and stop.reason is None:
                    log("enrich: one more pass over units whose transient errors exhausted their retries")
                    reason = enrich.run(run_dir, jev, budget, calls, stop, accept_gate=args.accept_early_gate,
                                        translator=translator, fallback_cfg=fb, log=log, **dispatch_kw)
                st["stop_reason"] = reason
            if reason not in (None, "incomplete"):
                log(f"stopped: {reason}. Progress is saved. Rerun the same command to resume. Budget {budget.summary()}")
                return STOP_EXIT
            if reason == "incomplete":
                log("enrich: some units still failed; they are exported as quarantined with reasons and attempts")
        if "verify" in stages:
            with runlog.stage("verify"):
                extra = tuple(g.strip() for g in args.verify_extra_groups.split(",")) if args.verify_extra_groups else ()
                verify.run(run_dir, claude_client, budget, calls, texts, args.verify_n, jev.model,
                           exclude_ids=exclude, extra_groups=extra, log=log)
        if "group" in stages:
            with runlog.stage("group") as st:
                reason = group.run(run_dir, claude_client, jev, budget, calls, stop, texts, exclude_ids=exclude,
                                   log=log, **dispatch_kw)
                st["stop_reason"] = reason
            if reason:
                log(f"stopped during grouping: {reason}. Rerun the same command to resume.")
                return STOP_EXIT

    jev_model = jev.model if jev else JEV_MODEL
    final = records.build(run_dir, jev_model)
    claims, errors, ranking = [], [], None
    if "rank" in stages:
        with runlog.stage("rank"):
            ranking = rank.run(run_dir, final, log=log)
    if "recommend" in stages:
        ranking = ranking or rank.load_computed(run_dir)
        with runlog.stage("recommend") as st:
            _, issues = group.load_assignments(run_dir)
            claims, errors = memo.run(run_dir, claude_client, budget, calls, ranking, issues["issues"], final,
                                      exclude_ids=exclude, log=log)
            st["memo_check_errors"] = len(errors)
        if errors:
            log(f"memo: number check still failing after retries ({len(errors)} errors); see memo/check.json")
    calls.flush()
    summary = summarize(run_dir, final, budget.summary(),
                        {"budget_group": args.budget_group, "budget_usd": args.budget_usd,
                         "early_gate_fraction": "0.10", "max_minutes": args.max_minutes,
                         "workers": args.workers, "rps": args.rps})
    log(f"done. records {summary['records']['by_status']}; list-price cost ${summary['total_cost_usd_list_price']}")
    if args.grading_dir and "recommend" in stages:
        export.run(run_dir, Path(args.grading_dir).resolve(), final, claims, allow_fake=args.allow_fake, log=log,
                   results_dir=Path(args.results_dir).resolve() if args.results_dir else None)
    return 0


def jev_model_for(run_dir):
    return "fake-jev-0" if read_json(run_dir / "run_manifest.json", {}).get("fake") else JEV_MODEL


def cmd_export(args):
    run_dir = Path(args.run_dir).resolve()
    final = records.build(run_dir, jev_model_for(run_dir))
    rank.run(run_dir, final, log=log)
    cited = set(read_json(run_dir / "memo" / "check.json")["cited"])
    claims = [c for c in read_json(run_dir / "memo" / "memo_inputs.json")["claims"] if c["claim_id"] in cited]
    export.run(run_dir, Path(args.grading_dir).resolve(), final, claims, allow_fake=args.allow_fake, log=log,
               results_dir=Path(args.results_dir).resolve() if args.results_dir else None)
    return 0


def cmd_rerank(args):
    """No model calls: recompute the baseline ranking from saved records + membership and diff it."""
    if args.grading_dir:
        folder = Path(args.grading_dir).resolve()
        recomputed = rank.rerank_from_grading(folder)
        saved = (folder / "ranking.csv").read_text(encoding="utf-8")
    else:
        run_dir = Path(args.run_dir).resolve()
        final = records.build(run_dir, jev_model_for(run_dir))
        members = [(r["issue_id"], r["review_id"], r["severity"]) for r in final
                   if r["status"] == "completed" and r["intent"] in ("complaint", "cancellation")]
        recomputed = rank.to_csv(rank.RANK_FIELDS, rank.compute(members)[1])
        saved = (run_dir / "rank" / "ranking.csv").read_text(encoding="utf-8")
    if args.out:
        Path(args.out).write_text(recomputed, encoding="utf-8")
    same = recomputed == saved
    print({"identical_to_saved_ranking": same, "issues": recomputed.count("\n") - 1,
           "sha256": rank.sha256_text(recomputed)})
    return 0 if same else 1


def cmd_check(args):
    grading = Path(args.grading_dir).resolve()
    out = Path(args.out_dir).resolve()
    if out == grading or grading in out.parents:
        raise SystemExit("--out-dir must be outside the grading folder")
    out.mkdir(parents=True, exist_ok=True)
    ref = out / "local-reference.json"
    report = out / "self-check.json"
    py = sys.executable
    if not ref.exists() or args.rebuild_reference:
        subprocess.run([py, str(VENDOR_CHECKER), "reference", "--full", args.input, "--analysis", args.input,
                        "--out", str(ref)], check=True)
    cmd = [py, str(VENDOR_CHECKER), "check", "--reference", str(ref), "--submission", str(grading), "--out", str(report)]
    if args.gold:
        cmd[4:4] = ["--gold", args.gold]
    subprocess.run(cmd, check=True)
    result = read_json(report)
    print({"status": result["status"], "issue_counts": result["issue_counts"], "coverage": result["coverage"],
           "reported_calls": result["reported_calls"], "reported_input_tokens": result["reported_input_tokens"],
           "reported_output_tokens": result["reported_output_tokens"],
           "working_coverage_point_candidate": result["working_coverage_point_candidate"]})
    return 0 if result["status"] == "pass" else 1


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m pipeline", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("keys")
    p = sub.add_parser("run")
    p.add_argument("--input", required=True, help="input CSV path")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--budget-group", required=True, help="ledger shared across runs, e.g. dev or full")
    p.add_argument("--budget-usd", required=True, type=float, help="hard cap for the budget group")
    p.add_argument("--verify-n", type=int, default=1000, help="declared random verification sample size")
    p.add_argument("--verify-extra-groups", help="also verify every unit in these language groups, as a separate "
                   "stratum (e.g. non_english_latin,non_latin_script for the 10k language comparison)")
    p.add_argument("--scope-sample", type=int, help="classify a seeded random sample of this many review IDs "
                   "(all rows are still ingested; the rest are exported as quarantined out of scope)")
    p.add_argument("--scope-include-duplicates", action="store_true",
                   help="also complete every exact-duplicate copy of a sampled text (reuse, no extra model cost)")
    p.add_argument("--stages", help=f"comma list, default all: {','.join(STAGES)}")
    p.add_argument("--exclude-golden", help="golden_50 CSV: its review IDs (only) are kept out of prompt examples")
    p.add_argument("--stop-after-units", type=int, help="send at most N new enrichment requests, then stop (resume demo)")
    p.add_argument("--rubric", default="full", choices=["full", "compact"],
                   help="Jev question wording: full (original) or compact (same rules, fewer tokens)")
    p.add_argument("--fallback", default="off", choices=["off", "standard", "batch"],
                   help="Claude re-labels low-confidence Jev texts blind: standard API or Message Batches API (50%% price)")
    p.add_argument("--fallback-threshold", type=float, default=0.5,
                   help="fallback when min(topic, intent, severity confidence) is below this")
    p.add_argument("--fallback-max-fraction", type=float, default=0.2,
                   help="declared cap: at most this fraction of distinct texts go to the Claude fallback")
    p.add_argument("--translate", action="store_true",
                   help="translate non-English texts with Claude before Jev (part of label_config; off by default)")
    p.add_argument("--max-minutes", type=float, help="time cap: stop dispatching after this many minutes, save progress")
    p.add_argument("--accept-early-gate", action="store_true", help="continue past a failed 10%% cost gate")
    p.add_argument("--grading-dir", help="export the grading folder here when the run finishes")
    p.add_argument("--results-dir", help="export the human-readable results folder here")
    p.add_argument("--workers", type=int, default=1,
                   help="concurrent requests (start at 1, then 2; raise only within measured capacity)")
    p.add_argument("--rps", type=float, default=30, help="global request-rate limit shared by all workers")
    p.add_argument("--claude-effort", default="medium", choices=["low", "medium", "high"],
                   help="reasoning effort for every Claude role (part of each Claude config tag)")
    p.add_argument("--claude-max-tokens", type=int, default=16000, help="output-token cap per Claude request")
    p.add_argument("--offline-fake", action="store_true", help="TESTS ONLY: fake providers, no network, no spend")
    p.add_argument("--allow-fake", action="store_true", help="TESTS ONLY: allow exporting fake records")
    p = sub.add_parser("rerank")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--grading-dir", help="recompute from grading/records.jsonl.gz + membership.csv")
    g.add_argument("--run-dir", help="recompute from a run directory's saved stage outputs")
    p.add_argument("--out", help="also write the recomputed ranking.csv here")
    p = sub.add_parser("export")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--grading-dir", required=True)
    p.add_argument("--results-dir")
    p.add_argument("--allow-fake", action="store_true")
    p = sub.add_parser("check")
    p.add_argument("--input", required=True)
    p.add_argument("--grading-dir", required=True)
    p.add_argument("--out-dir", required=True, help="where local-reference.json and self-check.json go (not the grading dir)")
    p.add_argument("--gold")
    p.add_argument("--rebuild-reference", action="store_true")
    p = sub.add_parser("golden-input")
    p.add_argument("--golden", required=True)
    p.add_argument("--out", required=True)
    p = sub.add_parser("check-golden", help="validate your hand-labelled golden CSV (no model calls)")
    p.add_argument("--golden", default=str(REPO / "evals" / "golden" / "golden_50_human_labels.csv"))
    p.add_argument("--source", help="the course golden_50_to_label.csv, to confirm source columns are unchanged")
    p.add_argument("--out", default=str(REPO / "evals" / "golden" / "label_check.json"))
    p = sub.add_parser("score-golden")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--golden", required=True, help="your hand-labelled golden CSV")
    p.add_argument("--adjudication", help="post-hoc label decisions (evals/golden/adjudication.json); reported separately")
    p.add_argument("--out-dir", default=str(REPO / "evals" / "golden"))
    p = sub.add_parser("golden-head-to-head", help="Claude labels the stripped golden texts blind; Jev vs Claude vs human")
    p.add_argument("--golden-run", default=str(REPO / "runs" / "golden"))
    p.add_argument("--golden", default=str(REPO / "evals" / "golden" / "golden_50_human_labels.csv"))
    p.add_argument("--out-dir", default=str(REPO / "evals" / "golden"))
    p.add_argument("--budget-usd", type=float, default=2)
    p = sub.add_parser("effort-test", help="Claude reasoning effort low vs medium on saved dev/golden inputs (eval)")
    p.add_argument("--dev-run", default=str(REPO / "runs" / "dev500"))
    p.add_argument("--golden-run", default=str(REPO / "runs" / "golden"))
    p.add_argument("--golden", default=str(REPO / "evals" / "golden" / "golden_50_human_labels.csv"))
    p.add_argument("--threshold", type=float, default=0.5)
    p.add_argument("--out-dir", default=str(REPO / "evals" / "effort_test"))
    p.add_argument("--candidate", help="compare this fallback model against the saved Sonnet 5 medium results")
    p.add_argument("--candidate-effort", default="none", help="'none' = no extended thinking (Haiku 4.5)")
    p.add_argument("--budget-group", default="dev")
    p.add_argument("--budget-usd", type=float, default=10)
    p = sub.add_parser("subset", help="rows of a CSV in given language groups (for the translation test)")
    p.add_argument("--input", required=True)
    p.add_argument("--groups", default="non_english_latin,non_latin_script")
    p.add_argument("--out", required=True)
    p = sub.add_parser("compare-translation", aliases=["compare-variant"],
                       help="baseline vs variant (translated or compact) Jev labels against the same blind verifier")
    p.add_argument("--baseline-run", required=True)
    p.add_argument("--translated-run", required=True)
    p.add_argument("--out", default=str(REPO / "evals" / "translation_test.json"))
    from . import costcalc
    costcalc.add_parser(sub)
    p = sub.add_parser("db-setup", help="create dashboard tables and a SELECT-only role (DATABASE_URL in .env)")
    p.add_argument("--rotate", action="store_true", help="issue a new read-only password")
    p = sub.add_parser("publish", help="load a finished run's saved outputs into the dashboard database")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--label", required=True)
    p.add_argument("--scope", required=True)
    p.add_argument("--input", help="the run's input CSV (default: the path in run_manifest.json)")
    p.add_argument("--current", action="store_true", help="make this the run the dashboard shows by default")
    p = sub.add_parser("eval-injection")
    p.add_argument("--budget-usd", type=float, default=0.25)
    args = parser.parse_args(argv)
    if args.command == "keys":
        print(key_status())
        return 0
    if args.command == "golden-input":
        print("wrote", golden.strip_labels(args.golden, args.out))
        return 0
    if args.command in ("db-setup", "publish"):
        from . import publish
        return publish.db_setup(args, log) if args.command == "db-setup" else publish.publish(args, log)
    if args.command == "cost":
        from . import costcalc
        return costcalc.run(args, log)
    handlers = {"run": cmd_run, "rerank": cmd_rerank, "export": cmd_export, "check": cmd_check}
    if args.command in handlers:
        return handlers[args.command](args)
    from . import evals
    if args.command == "eval-injection":
        return evals.run_injection(args, log)
    if args.command == "score-golden":
        return evals.score_golden(args, log)
    if args.command == "check-golden":
        return evals.check_golden(args, log)
    if args.command == "golden-head-to-head":
        return evals.golden_head_to_head(args, log)
    if args.command == "effort-test":
        return evals.effort_test(args, log)
    if args.command == "subset":
        return evals.write_subset(args, log)
    if args.command in ("compare-translation", "compare-variant"):
        return evals.compare_translation(args, log)
    return 2
