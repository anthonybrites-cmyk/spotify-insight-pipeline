"use client";
import Link from "next/link";
import { useApi, withRun } from "@/lib/useApi";
import { ErrorBox, Loading } from "./Status";
import { Memo, type Claim, type Fact } from "./Memo";
import { RunPicker } from "./RunPicker";

type Resp = { recommendation: { memo_markdown: string; model: string; label_config: string; check_passed: boolean;
  check_errors: string[]; evidence_pack: Record<string, { review_id: string; quote: string }[]> } | null;
  claims: Claim[]; facts: Fact[]; issues: { issue_id: string; name: string; rank: number | null }[] };

export function RecommendationView() {
  const { data, error, loading, run } = useApi<Resp>("/api/recommendation");
  if (loading) return <Loading />;
  if (error || !data) return <ErrorBox message={error ?? "no data"} />;
  if (!data.recommendation) return <ErrorBox message="no recommendation saved for this run" />;
  const rec = data.recommendation;
  const issueIds = new Set(data.issues.map((i) => i.issue_id));
  const names = new Map(data.issues.map((i) => [i.issue_id, i.name]));
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">AI recommendation</h1>
          <p className="secondary text-sm mt-1">Written by <code>{rec.model}</code> from the saved aggregates and a bounded evidence pack only.
            Code then checked every number, issue ID, review ID and quote: <strong>{rec.check_passed ? "passed" : "failed"}</strong>.</p>
        </div>
        <RunPicker />
      </div>
      <article className="card p-6"><Memo markdown={rec.memo_markdown} claims={data.claims} facts={data.facts} run={run} issueIds={issueIds} /></article>
      <section className="card p-5">
        <h2 className="font-semibold mb-2">Claims cited (recomputed by the course checker from records + membership)</h2>
        <table className="data text-sm"><thead><tr><th>Claim</th><th>Issue</th><th>Metric</th><th className="n">Value</th></tr></thead><tbody>
          {data.claims.map((c) => <tr key={c.claim_id}><td className="num">{c.claim_id}</td>
            <td><Link href={withRun(`/issues/${c.issue_id}`, run)} className="link">{c.issue_name ?? c.issue_id}</Link></td>
            <td>{c.metric}</td><td className="n">{c.value}</td></tr>)}
        </tbody></table>
      </section>
      <section className="card p-5">
        <h2 className="font-semibold mb-2">Other quantities (facts computed in code)</h2>
        <table className="data text-sm"><tbody>
          {data.facts.map((f) => <tr key={f.fact_id}><td className="num">{f.fact_id}</td><td>{f.meaning}</td><td className="n">{f.value}</td></tr>)}
        </tbody></table>
      </section>
      <section className="card p-5">
        <h2 className="font-semibold mb-2">Evidence pack given to the model</h2>
        {Object.entries(rec.evidence_pack).map(([iid, quotes]) => (
          <div key={iid} className="mb-3">
            <Link href={withRun(`/issues/${iid}`, run)} className="link font-medium">{names.get(iid) ?? iid}</Link>
            <ul className="list-disc pl-6 text-sm mt-1">
              {quotes.map((q) => <li key={q.review_id}>“{q.quote}” <Link href={withRun(`/reviews/${q.review_id}`, run)} className="link num">{q.review_id.slice(0, 8)}…</Link></li>)}
            </ul>
          </div>))}
      </section>
    </div>
  );
}
