"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { useApi, withRun } from "@/lib/useApi";
import { ErrorBox, Loading } from "./Status";

type Member = { review_id: string; severity: number; intent: string; sentiment: string; evidence_quote: string;
  decided_by: string; needs_review: boolean; review_timestamp: string };
type IssueResp = { issue: { issue_id: string; topic: string; name: string; definition: string; rank: number;
  complaint_count: number; severity_sum: number; mean_severity: string; priority_score: number };
  claims: { claim_id: string; metric: string; value: string }[]; members: Member[]; memberCount: number;
  page: number; pageSize: number; severity: { severity: number; n: number }[] };

export function IssueView() {
  const { id } = useParams<{ id: string }>();
  const [page, setPage] = useState(0);
  const { data, error, loading, run } = useApi<IssueResp>(`/api/issues/${id}?page=${page}`);
  if (loading && !data) return <Loading />;
  if (error || !data) return <ErrorBox message={error ?? "no data"} />;
  const i = data.issue;
  const pages = Math.ceil(data.memberCount / data.pageSize);
  return (
    <div className="flex flex-col gap-4">
      <Link href={withRun("/issues", run)} className="link text-sm">← Issue ranking</Link>
      <div>
        <h1 className="text-2xl font-semibold">{i.name}</h1>
        <p className="muted text-sm"><code>{i.issue_id}</code> · topic {i.topic} · rank {i.rank ?? "–"}</p>
        <p className="secondary mt-2">{i.definition}</p>
      </div>
      <section className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))" }}>
        {[["Complaints", i.complaint_count], ["Severity sum", i.severity_sum], ["Mean severity", i.mean_severity], ["Priority score", i.priority_score]]
          .map(([k, v]) => <div key={k as string} className="card p-4"><div className="text-sm secondary">{k}</div>
            <div className="text-2xl font-semibold">{typeof v === "number" ? v.toLocaleString("en-US") : v}</div></div>)}
      </section>
      {data.claims.length > 0 && (
        <p className="text-sm secondary">Cited in the recommendation as {data.claims.map((c) => `${c.claim_id} (${c.metric} = ${c.value})`).join(", ")}.</p>
      )}
      <p className="text-sm secondary">Severity mix: {data.severity.map((s) => `${s.n.toLocaleString("en-US")} at ${s.severity}`).join(" · ")}</p>
      <section className="card p-5">
        <h2 className="font-semibold mb-3">Member reviews ({data.memberCount.toLocaleString("en-US")}), most severe first</h2>
        <div className="overflow-x-auto">
          <table className="data text-sm">
            <thead><tr><th>Review</th><th>Evidence quote (exact source text)</th><th className="n">Severity</th><th>Intent</th><th>Decided by</th></tr></thead>
            <tbody>
              {data.members.map((m) => (
                <tr key={m.review_id}>
                  <td><Link href={withRun(`/reviews/${m.review_id}`, run)} className="link num">{m.review_id.slice(0, 8)}…</Link>
                    <div className="muted text-xs">{m.review_timestamp?.slice(0, 10)}</div></td>
                  <td>“{m.evidence_quote}”{m.needs_review && <span className="chip ml-2 text-xs">needs review</span>}</td>
                  <td className="n">{m.severity}</td><td>{m.intent}</td><td className="text-xs">{m.decided_by}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {pages > 1 && (
          <div className="flex items-center gap-3 mt-3 text-sm">
            <button className="link" disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))}>← Previous</button>
            <span className="muted">Page {page + 1} of {pages}</span>
            <button className="link" disabled={page + 1 >= pages} onClick={() => setPage((p) => p + 1)}>Next →</button>
          </div>
        )}
      </section>
    </div>
  );
}
