"""Load a finished run's saved outputs into Postgres for the deployed dashboard (no model calls).

  python -m pipeline db-setup                      create tables and a SELECT-only role for the dashboard
  python -m pipeline publish --run-dir runs/X --label "..." --scope "..." [--current]

DATABASE_URL (owner) is read from .env. db-setup writes DASHBOARD_DATABASE_URL (read-only) into .env
without printing it; the deployed backend uses only that read-only URL.
"""

import csv
import json
import os
import secrets
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .config import JEV_MODEL, REPO
from .envfile import load_env
from .store import read_json, read_jsonl

SCHEMA = REPO / "db" / "schema.sql"
READER = "dashboard_reader"


def connect():
    import psycopg
    load_env()
    for line in (REPO / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("DATABASE_URL="):
            os.environ.setdefault("DATABASE_URL", line.split("=", 1)[1].strip().strip('"').strip("'"))
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is not set: paste the Neon connection string into .env (git-ignored)")
    return psycopg.connect(url)


def db_setup(args, log):
    with connect() as conn:
        conn.execute(SCHEMA.read_text(encoding="utf-8"))
        exists = conn.execute("select 1 from pg_roles where rolname = %s", (READER,)).fetchone()
        env_path = REPO / ".env"
        has_url = "DASHBOARD_DATABASE_URL=" in env_path.read_text(encoding="utf-8")
        if not exists or not has_url or args.rotate:
            password = secrets.token_urlsafe(24)  # generated here, written to .env, never printed
            verb = "alter" if exists else "create"
            conn.execute(f"{verb} role {READER} with login password '{password}'")
            parts = urlsplit(os.environ["DATABASE_URL"])
            host = parts.netloc.split("@", 1)[1]
            reader_url = urlunsplit((parts.scheme, f"{READER}:{password}@{host}", parts.path, parts.query, ""))
            lines = [l for l in env_path.read_text(encoding="utf-8").splitlines()
                     if not l.startswith("DASHBOARD_DATABASE_URL=")]
            env_path.write_text("\n".join(lines + [f"DASHBOARD_DATABASE_URL={reader_url}"]) + "\n", encoding="utf-8")
            log(f"db-setup: {verb}d read-only role {READER}; wrote DASHBOARD_DATABASE_URL to .env (not printed)")
        db = conn.execute("select current_database()").fetchone()[0]
        conn.execute(f"grant connect on database {db} to {READER}")
        conn.execute(f"grant usage on schema public to {READER}")
        conn.execute(f"grant select on all tables in schema public to {READER}")
        conn.execute(f"alter default privileges in schema public grant select on tables to {READER}")
        conn.commit()
    log("db-setup: schema applied; dashboard role has SELECT only")
    return 0


def publish(args, log):
    from .enrich import current_config, final_results
    from .records import build
    run_dir = Path(args.run_dir).resolve()
    manifest = read_json(run_dir / "run_manifest.json")
    summary = read_json(run_dir / "run_summary.json")
    ingest = read_json(run_dir / "ingest" / "summary.json")
    records = build(run_dir, JEV_MODEL)
    config = current_config(run_dir, JEV_MODEL)
    final = final_results(run_dir, config)
    unit_of = {s["review_id"]: s["unit"] for s in read_jsonl(run_dir / "ingest" / "sources.jsonl")}
    source = {}
    input_csv = Path(args.input or manifest["input"])
    if not input_csv.exists():
        raise SystemExit(f"input CSV {input_csv} not found; pass --input")
    from .checker import csv_rows
    wanted = {r["review_id"] for r in records}
    for row in csv_rows(input_csv):
        if row["review_id"] in wanted:
            source[row["review_id"]] = row
    issues = read_json(run_dir / "group" / "issues.json")["issues"]
    with (run_dir / "rank" / "ranking.csv").open(encoding="utf-8", newline="") as f:
        ranking = {r["issue_id"]: r for r in csv.DictReader(f)}
    memo_inputs = read_json(run_dir / "memo" / "memo_inputs.json")
    check = read_json(run_dir / "memo" / "check.json")
    cited = set(check["cited"])
    claims = [c for c in memo_inputs["claims"] if c["claim_id"] in cited]
    memo_md = (run_dir / "memo" / "memo.md").read_text(encoding="utf-8")
    verify = read_json(run_dir / "verify" / "report.json")

    completed = [r for r in records if r["status"] == "completed"]
    topic = defaultdict(Counter)
    for r in completed:
        t = topic[r["topic"]]
        t["reviews"] += 1
        if r["intent"] in ("complaint", "cancellation"):
            t["complaints"] += 1
            t["severity_sum"] += r["severity"]
        t["cancellations"] += r["intent"] == "cancellation"
    run_id = manifest["run_id"]
    usage = summary["usage_by_role_model"]
    models = sorted({k.split("|", 1)[1] for k in usage})
    with connect() as conn:
        conn.execute(SCHEMA.read_text(encoding="utf-8"))
        conn.execute("delete from runs where run_id = %s", (run_id,))
        conn.execute(
            """insert into runs (run_id, label, scope, input_file, input_sha256, source_rows, completed, quarantined,
               quarantine_reasons, cache_reuse, needs_review, decided_by, api_cost_usd, label_config, models,
               verification) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (run_id, args.label, args.scope, input_csv.name, ingest["input_sha256"], len(records), len(completed),
             len(records) - len(completed), json.dumps(summary["records"]["quarantine_reasons"]),
             summary["records"]["completed_via_cache_reuse"], sum(1 for r in completed if r["needs_review"]),
             json.dumps(Counter(v.get("decided_by", "jev") for v in final.values())),
             Decimal(summary["total_cost_usd_list_price"]), config, json.dumps(models),
             json.dumps({"headline": verify.get("headline"), "strata": verify.get("strata")})))
        with conn.cursor() as cur:
            with cur.copy("""copy reviews (run_id, review_id, source_sha256, status, reason, topic, intent, severity,
                              sentiment, needs_review, issue_id, evidence_quote, entities, decided_by,
                              cache_source_id, review_text, review_rating, review_timestamp, app_version)
                              from stdin""") as copy:
                for r in records:
                    s = source[r["review_id"]]
                    fr = final.get(unit_of.get(r["review_id"]), {})
                    done = r["status"] == "completed"
                    copy.write_row((run_id, r["review_id"], r["source_sha256"], r["status"], r.get("reason"),
                                    r.get("topic"), r.get("intent"), r.get("severity"), r.get("sentiment"),
                                    r.get("needs_review"), r.get("issue_id"), r.get("evidence_quote"),
                                    json.dumps(r.get("entities", [])) if done else None,
                                    fr.get("decided_by") if done else None, r.get("cache_source_id"),
                                    s["review_text"], s["review_rating"], s["review_timestamp"], s["app_version"]))
            for iid, meta in issues.items():
                rk = ranking.get(iid, {})
                cur.execute("""insert into issues (run_id, issue_id, topic, name, definition, rank, complaint_count,
                               severity_sum, mean_severity, priority_score) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                            (run_id, iid, meta["topic"], meta["name"], meta["definition"],
                             int(rk["rank"]) if rk else None, int(rk.get("complaint_count", 0)),
                             int(rk.get("severity_sum", 0)), rk.get("mean_severity"), int(rk.get("priority_score", 0))))
            for t, c in topic.items():
                cur.execute("insert into topic_metrics values (%s,%s,%s,%s,%s,%s)",
                            (run_id, t, c["reviews"], c["complaints"], c["cancellations"], c["severity_sum"]))
            for c in claims:
                cur.execute("insert into claims values (%s,%s,%s,%s,%s)",
                            (run_id, c["claim_id"], c["issue_id"], c["metric"], c["value"]))
            for fid, (meaning, value) in memo_inputs["facts"].items():
                cur.execute("insert into facts values (%s,%s,%s,%s)", (run_id, fid, meaning, value))
            memo_calls = [k for k in usage if k.startswith("memo|")]
            cur.execute("insert into recommendations values (%s,%s,%s,%s,%s,%s,%s)",
                        (run_id, memo_md, memo_calls[0].split("|", 1)[1] if memo_calls else "unknown",
                         check["memo_label_config"], check["passed"], json.dumps(check["errors"]),
                         json.dumps(memo_inputs["examples"])))
        if args.current:
            conn.execute("update runs set is_current = (run_id = %s)", (run_id,))
        conn.commit()
        n = conn.execute("select count(*) from reviews where run_id = %s", (run_id,)).fetchone()[0]
    log(f"publish: {run_id} ({args.label}): {n} reviews, {len(issues)} issues, {len(claims)} claims"
        f"{' (current)' if args.current else ''}")
    return 0
