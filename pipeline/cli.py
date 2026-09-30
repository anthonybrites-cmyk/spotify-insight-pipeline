"""Command-line entry point: python -m pipeline <command> ...

  keys                 show whether each API key is present (never the value)
  run                  ingest -> enrich -> verify -> group -> rank -> recommend [-> export]
  export               rebuild the grading folder from a finished run directory
  check                run the course checker (profile, reference, check) against a grading folder
  eval-injection       live prompt-injection cases through the same Jev rubric (separate run dir)
  score-golden         compare a run's records with your hand-labelled golden_50 file
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

from . import enrich, export, group, ingest, memo, rank, records, verify
from .budget import Budget
from .config import CLAUDE_MODEL, JEV_MODEL, REPO, VENDOR_CHECKER
from .dispatch import StopFlag
from .envfile import key_status, require
from .store import JsonlAppender, read_json, write_json

STOP_EXIT = 3


def log(message):
    print(time.strftime("%H:%M:%S"), message, flush=True)


def make_clients(fake, need_claude=True):
    if fake:
        from .fakes import FakeClaude, FakeJev
        return FakeJev(), FakeClaude()
    from .claude import ClaudeClient
    from .jev import JevClient
    jev = JevClient(require("TYPESAFE_API_KEY"), model=JEV_MODEL)
    claude_client = ClaudeClient(require("ANTHROPIC_API_KEY"), model=CLAUDE_MODEL) if need_claude else None
    return jev, claude_client


def cmd_run(args):
    run_dir = Path(args.run_dir).resolve()
    input_csv = Path(args.input).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = read_json(run_dir / "run_manifest.json", {})
    if manifest and manifest.get("input") != str(input_csv):
        raise SystemExit(f"{run_dir} belongs to input {manifest['input']}; use a new --run-dir")
    manifest.update({"input": str(input_csv), "budget_group": args.budget_group, "budget_usd": args.budget_usd,
                     "verify_n": args.verify_n, "fake": args.offline_fake})
    write_json(run_dir / "run_manifest.json", manifest)

    jev, claude_client = make_clients(args.offline_fake)
    budget = Budget(args.budget_group, args.budget_usd, run_dir.name,
                    ledger_dir=(run_dir / "budgets") if args.offline_fake else REPO / "budgets")
    calls = JsonlAppender(run_dir / "calls.jsonl")
    try:
        return _run_stages(args, run_dir, input_csv, jev, claude_client, budget, calls)
    finally:
        calls.close()
        budget.close()


def _run_stages(args, run_dir, input_csv, jev, claude_client, budget, calls):
    dispatch_kw = {"workers": args.workers, "rps": args.rps}
    log(f"run: {run_dir.name}; budget {budget.summary()}")

    summary = ingest.run(input_csv, run_dir, log=log)
    texts = {u["unit"]: u["text"] for u in ingest.load_units(run_dir)}

    with StopFlag() as stop:
        reason = enrich.run(run_dir, jev, budget, calls, stop, max_new=args.stop_after_units,
                            accept_gate=args.accept_early_gate, log=log, **dispatch_kw)
        if reason == "incomplete" and stop.reason is None:
            log("enrich: retrying units that failed (one pass)")
            reason = enrich.run(run_dir, jev, budget, calls, stop, accept_gate=args.accept_early_gate,
                                log=log, **dispatch_kw)
        if reason not in (None, "incomplete"):
            log(f"stopped: {reason}. Progress is saved. Rerun the same command to resume. Budget {budget.summary()}")
            return STOP_EXIT
        if reason == "incomplete":
            log("enrich: some units still failed after retries; they will be exported as quarantined with reasons")

        verify.run(run_dir, claude_client, budget, calls, texts, args.verify_n, jev.model, log=log)
        reason = group.run(run_dir, claude_client, jev, budget, calls, stop, texts, log=log, **dispatch_kw)
        if reason:
            log(f"stopped during grouping: {reason}. Rerun the same command to resume.")
            return STOP_EXIT

    final = records.build(run_dir, jev.model)
    ranking = rank.run(run_dir, final, log=log)
    _, issues = group.load_assignments(run_dir)
    claims, errors = memo.run(run_dir, claude_client, budget, calls, ranking, issues["issues"], final, log=log)
    if errors:
        log(f"memo: number check still failing after retries ({len(errors)} errors); see memo/check.json")
    write_json(run_dir / "spend.json", budget.summary())
    log(f"done. Budget {budget.summary()}")
    if args.grading_dir:
        export.run(run_dir, Path(args.grading_dir).resolve(), final, claims, allow_fake=args.allow_fake, log=log)
    return 0


def cmd_export(args):
    run_dir = Path(args.run_dir).resolve()
    manifest = read_json(run_dir / "run_manifest.json")
    jev_model = "fake-jev-0" if manifest.get("fake") else JEV_MODEL
    final = records.build(run_dir, jev_model)
    ranking = rank.run(run_dir, final, log=log)
    claims = [c for c in read_json(run_dir / "memo" / "memo_inputs.json")["claims"]
              if c["claim_id"] in set(read_json(run_dir / "memo" / "check.json")["cited"])]
    export.run(run_dir, Path(args.grading_dir).resolve(), final, claims, allow_fake=args.allow_fake, log=log)
    return 0


def cmd_check(args):
    grading = Path(args.grading_dir).resolve()
    out = Path(args.out_dir).resolve()
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
           "reported_output_tokens": result["reported_output_tokens"]})
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
    p.add_argument("--verify-n", type=int, default=1000)
    p.add_argument("--stop-after-units", type=int, help="send at most N new enrichment requests, then stop (resume demo)")
    p.add_argument("--accept-early-gate", action="store_true", help="continue past a failed 10%% cost gate")
    p.add_argument("--grading-dir", help="export the grading folder here when the run finishes")
    p.add_argument("--workers", type=int, default=24)
    p.add_argument("--rps", type=float, default=30)
    p.add_argument("--offline-fake", action="store_true", help="TESTS ONLY: fake providers, no network, no spend")
    p.add_argument("--allow-fake", action="store_true", help="TESTS ONLY: allow exporting fake records")
    p = sub.add_parser("export")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--grading-dir", required=True)
    p.add_argument("--allow-fake", action="store_true")
    p = sub.add_parser("check")
    p.add_argument("--input", required=True)
    p.add_argument("--grading-dir", required=True)
    p.add_argument("--out-dir", required=True, help="where local-reference.json and self-check.json go (not the grading dir)")
    p.add_argument("--gold")
    p.add_argument("--rebuild-reference", action="store_true")
    p = sub.add_parser("eval-injection")
    p.add_argument("--budget-usd", type=float, default=0.25)
    p = sub.add_parser("score-golden")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--golden", required=True)
    args = parser.parse_args(argv)
    if args.command == "keys":
        print(key_status())
        return 0
    if args.command == "run":
        return cmd_run(args)
    if args.command == "export":
        return cmd_export(args)
    if args.command == "check":
        return cmd_check(args)
    if args.command == "eval-injection":
        from .evals import run_injection
        return run_injection(args, log)
    if args.command == "score-golden":
        from .evals import score_golden
        return score_golden(args, log)
    return 2
