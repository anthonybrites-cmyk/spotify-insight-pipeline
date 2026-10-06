"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useApi, withRun } from "@/lib/useApi";
import { ErrorBox, Loading } from "./Status";

type Review = { review_id: string; source_sha256: string; status: string; reason: string | null; topic: string;
  intent: string; severity: number; sentiment: string; needs_review: boolean; issue_id: string | null; issue_name: string | null;
  issue_rank: number | null; evidence_quote: string; entities: string[]; decided_by: string; cache_source_id: string | null;
  review_text: string; review_rating: string; review_timestamp: string; app_version: string };

function Highlight({ text, quote }: { text: string; quote: string }) {
  const at = quote ? text.indexOf(quote) : -1;
  if (at < 0) return <>{text}</>;
  return <>{text.slice(0, at)}<mark style={{ background: "var(--chip)", color: "inherit" }}>{quote}</mark>{text.slice(at + quote.length)}</>;
}

export function ReviewView() {
  const { id } = useParams<{ id: string }>();
  const { data, error, loading, run } = useApi<{ review: Review; labelConfig: string }>(`/api/reviews/${id}`);
  if (loading) return <Loading />;
  if (error || !data) return <ErrorBox message={error ?? "no data"} />;
  const r = data.review;
  const rows: [string, React.ReactNode][] = [
    ["Status", r.status + (r.reason ? ` (${r.reason})` : "")], ["Topic", r.topic], ["Intent", r.intent],
    ["Severity", r.severity], ["Sentiment", r.sentiment], ["Needs review", r.needs_review ? "yes" : "no"],
    ["Entities", (r.entities ?? []).join(", ") || "–"],
    ["Issue", r.issue_id ? <Link href={withRun(`/issues/${r.issue_id}`, run)} className="link">{r.issue_name} (rank {r.issue_rank ?? "–"})</Link> : "– (not a complaint)"],
    ["Labelled by", r.decided_by], ["Reused from", r.cache_source_id ? <Link href={withRun(`/reviews/${r.cache_source_id}`, run)} className="link num">{r.cache_source_id}</Link> : "– (classified directly)"],
    ["Label config", <code key="c" className="text-xs break-all">{data.labelConfig}</code>],
    ["Source row hash", <code key="h" className="text-xs break-all">{r.source_sha256}</code>],
    ["Star rating (metadata, not used for labels)", r.review_rating], ["Date", r.review_timestamp], ["App version", r.app_version || "missing"],
  ];
  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold num">Review {r.review_id}</h1>
      <blockquote className="card p-5 text-lg leading-relaxed"><Highlight text={r.review_text} quote={r.evidence_quote} /></blockquote>
      <p className="text-sm muted">Highlighted: the evidence quote, an exact substring of the original text.</p>
      <section className="card p-5"><table className="data text-sm"><tbody>
        {rows.map(([k, v]) => <tr key={k}><th style={{ width: "16rem" }}>{k}</th><td>{v}</td></tr>)}
      </tbody></table></section>
    </div>
  );
}
