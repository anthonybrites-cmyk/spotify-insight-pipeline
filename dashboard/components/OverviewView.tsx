"use client";
import Link from "next/link";
import { useApi, withRun } from "@/lib/useApi";
import { ErrorBox, Loading } from "./Status";
import { TopicBars, type TopicRow } from "./TopicBars";
import { IssueTable, type IssueRow } from "./IssueTable";
import { RunPicker } from "./RunPicker";

type Overview = {
  run: { run_id: string; label: string; scope: string; source_rows: number; completed: number; quarantined: number;
    quarantine_reasons: Record<string, number>; cache_reuse: number; needs_review: number; api_cost_usd: string;
    decided_by: Record<string, number>; models: string[]; label_config: string; published_at: string;
    verification: { strata?: Record<string, { n: number; topic_agreement: number; intent_agreement: number; severity_exact_agreement: number }> } };
  topics: TopicRow[]; topIssues: IssueRow[]; recommendation: { memo_markdown: string; model: string; check_passed: boolean } | null;
};

const fmt = (n: number) => Number(n).toLocaleString("en-US");
const pct = (a: number, b: number) => (b ? `${((100 * a) / b).toFixed(1)}%` : "–");

function Tile({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="card p-4">
      <div className="text-sm secondary">{label}</div>
      <div className="text-2xl font-semibold mt-1">{value}</div>
      {note && <div className="text-xs muted mt-1">{note}</div>}
    </div>
  );
}

function recommendationSection(md: string) {
  const m = md.split(/\n(?=##\s)/).find((s) => /^##\s*Recommendation/i.test(s.trim()));
  return (m ?? md).replace(/^##\s*Recommendation\s*/i, "").replace(/\[(?:C|F)\d{2}\]/g, "").replace(/\*\*/g, "").replace(/`/g, "").trim();
}

export function OverviewView() {
  const { data, error, loading, run } = useApi<Overview>("/api/overview");
  if (loading) return <Loading />;
  if (error || !data) return <ErrorBox message={error ?? "no data"} />;
  const r = data.run;
  const random = r.verification?.strata?.["random:all"] ?? r.verification?.strata?.["all"];
  const fallback = r.decided_by?.claude_fallback ?? 0;
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Where should next quarter&apos;s product effort go?</h1>
          <p className="secondary mt-1">{r.label} · {r.scope} · published {new Date(r.published_at).toLocaleDateString()}</p>
        </div>
        <RunPicker />
      </div>

      {data.recommendation && (
        <section className="card p-5">
          <div className="text-sm secondary">AI recommendation ({data.recommendation.model}, from the saved metrics)</div>
          <p className="mt-2 text-lg leading-relaxed">{recommendationSection(data.recommendation.memo_markdown)}</p>
          <Link href={withRun("/recommendation", run)} className="link text-sm mt-3 inline-block">
            Read the full recommendation with its cited numbers and evidence →
          </Link>
        </section>
      )}

      <section className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))" }}>
        <Tile label="Completed classifications" value={fmt(r.completed)} note={`${pct(r.completed, r.source_rows)} of ${fmt(r.source_rows)} source rows`} />
        <Tile label="Quarantined" value={fmt(r.quarantined)} note={Object.entries(r.quarantine_reasons ?? {}).map(([k, v]) => `${k}: ${fmt(v)}`).join(" · ") || "none"} />
        <Tile label="Exact-duplicate reuse" value={fmt(r.cache_reuse)} note="records labelled from an identical text" />
        <Tile label="Needs review" value={fmt(r.needs_review)} note={`${pct(r.needs_review, r.completed)} of completed`} />
        <Tile label="Claude fallback decided" value={fmt(fallback)} note="low-confidence Jev labels re-labelled" />
        {random && <Tile label="Verifier topic agreement" value={`${(100 * random.topic_agreement).toFixed(1)}%`} note={`declared random sample of ${random.n}; agreement is not accuracy`} />}
        <Tile label="API cost (estimate)" value={`$${Number(r.api_cost_usd).toFixed(2)}`} note="provider tokens × list prices" />
      </section>

      <section className="card p-5">
        <TopicBars rows={data.topics} />
      </section>

      <section className="card p-5">
        <div className="flex items-baseline justify-between mb-3">
          <h2 className="font-semibold">Top 10 issues (baseline ranking)</h2>
          <Link href={withRun("/issues", run)} className="link text-sm">Full ranking →</Link>
        </div>
        <IssueTable rows={data.topIssues} run={run} />
      </section>
    </div>
  );
}
