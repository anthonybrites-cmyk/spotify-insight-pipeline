"use client";
import Link from "next/link";
import { withRun } from "@/lib/useApi";

export type IssueRow = { rank: number; issue_id: string; topic: string; name: string; complaint_count: number;
  severity_sum: number; mean_severity: string; priority_score: number; definition?: string };

export function IssueTable({ rows, run, showDefinition = false }: { rows: IssueRow[]; run: string | null; showDefinition?: boolean }) {
  const fmt = (n: number) => Number(n).toLocaleString("en-US");
  return (
    <div className="overflow-x-auto">
      <table className="data text-sm">
        <thead>
          <tr><th className="n">Rank</th><th>Issue</th><th>Topic</th><th className="n">Complaints</th>
            <th className="n">Severity sum</th><th className="n">Mean severity</th><th className="n">Priority score</th></tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.issue_id}>
              <td className="n">{r.rank}</td>
              <td>
                <Link href={withRun(`/issues/${r.issue_id}`, run)} className="link">{r.name}</Link>
                <div className="muted text-xs"><code>{r.issue_id}</code></div>
                {showDefinition && r.definition && <div className="secondary text-xs mt-1">{r.definition}</div>}
              </td>
              <td>{r.topic}</td>
              <td className="n">{fmt(r.complaint_count)}</td>
              <td className="n">{fmt(r.severity_sum)}</td>
              <td className="n">{r.mean_severity}</td>
              <td className="n font-semibold">{fmt(r.priority_score)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted text-xs mt-2">Priority score = complaint count × mean severity = severity sum. Ties break by issue ID.</p>
    </div>
  );
}
