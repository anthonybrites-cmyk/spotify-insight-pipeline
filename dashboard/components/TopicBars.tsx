"use client";
import { useState } from "react";

export type TopicRow = { topic: string; reviews: number; complaints: number; cancellations: number; severity_sum: number };

/** One series (complaint + cancellation reviews per topic) as horizontal bars; value at the tip; hover tooltip.
 *  Severity sums live in the table below, never on a second axis. */
export function TopicBars({ rows }: { rows: TopicRow[] }) {
  const [hover, setHover] = useState<string | null>(null);
  const max = Math.max(1, ...rows.map((r) => r.complaints));
  const fmt = (n: number) => n.toLocaleString("en-US");
  return (
    <figure>
      <figcaption className="font-semibold mb-3">Complaint and cancellation-intent reviews by topic</figcaption>
      <div role="list" className="flex flex-col" style={{ gap: 2 }}>
        {rows.map((r) => {
          const pct = (r.complaints / max) * 100;
          return (
            <div key={r.topic} role="listitem" className="relative grid items-center"
                 style={{ gridTemplateColumns: "6.5rem 1fr", minHeight: 28 }}
                 onMouseEnter={() => setHover(r.topic)} onMouseLeave={() => setHover(null)}
                 onFocus={() => setHover(r.topic)} onBlur={() => setHover(null)} tabIndex={0}
                 aria-label={`${r.topic}: ${fmt(r.complaints)} complaints, severity sum ${fmt(r.severity_sum)}`}>
              <span className="text-sm secondary">{r.topic}</span>
              <div className="flex items-center gap-2" style={{ minHeight: 28 }}>
                <div style={{ width: `${pct}%`, minWidth: r.complaints ? 3 : 0, height: 20,
                              background: "var(--series-1)", borderRadius: "0 4px 4px 0",
                              opacity: hover && hover !== r.topic ? 0.55 : 1 }} />
                <span className="text-sm num">{fmt(r.complaints)}</span>
              </div>
              {hover === r.topic && (
                <div className="card absolute z-10 px-3 py-2 text-sm shadow-sm" style={{ left: "7rem", top: 26 }}>
                  <div className="font-semibold">{r.topic}</div>
                  <div className="num">Complaints + cancellations: {fmt(r.complaints)}</div>
                  <div className="num">of which cancellation intent: {fmt(r.cancellations)}</div>
                  <div className="num">Severity sum: {fmt(r.severity_sum)}</div>
                  <div className="num">All classified reviews: {fmt(r.reviews)}</div>
                </div>
              )}
            </div>
          );
        })}
      </div>
      <details className="mt-3 text-sm">
        <summary className="secondary cursor-pointer">Table view</summary>
        <table className="data mt-2">
          <thead><tr><th>Topic</th><th className="n">Reviews</th><th className="n">Complaints</th><th className="n">Cancellation intent</th><th className="n">Severity sum</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.topic}><td>{r.topic}</td><td className="n">{fmt(r.reviews)}</td><td className="n">{fmt(r.complaints)}</td>
                <td className="n">{fmt(r.cancellations)}</td><td className="n">{fmt(r.severity_sum)}</td></tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}
