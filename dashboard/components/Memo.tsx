"use client";
import Link from "next/link";
import type { ReactNode } from "react";
import { withRun } from "@/lib/useApi";

export type Claim = { claim_id: string; issue_id: string; metric: string; value: string; issue_name?: string };
export type Fact = { fact_id: string; meaning: string; value: string };

const TOKEN = /(\[(?:C|F)\d{2}\]|\*\*[^*]+\*\*|`[^`]+`|\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b|\b(?:access|usability|playback|downloads|catalog|billing|support|other)\.[a-z0-9_]+\b)/g;

/** Renders the saved memo markdown, turning claim IDs, fact IDs, issue IDs and review IDs into evidence links. */
export function Memo({ markdown, claims, facts, run, issueIds }: {
  markdown: string; claims: Claim[]; facts: Fact[]; run: string | null; issueIds: Set<string>;
}) {
  const claimMap = new Map(claims.map((c) => [c.claim_id, c]));
  const factMap = new Map(facts.map((f) => [f.fact_id, f]));

  const inline = (text: string, keyBase: string): ReactNode[] =>
    text.split(TOKEN).filter(Boolean).map((part, i) => {
      const key = `${keyBase}-${i}`;
      const cm = part.match(/^\[((?:C|F)\d{2})\]$/);
      if (cm) {
        const id = cm[1];
        const c = claimMap.get(id);
        if (c) return (
          <Link key={key} href={withRun(`/issues/${c.issue_id}`, run)} className="chip num link" title={`${c.issue_id} ${c.metric} = ${c.value}`}>
            {id}
          </Link>);
        const f = factMap.get(id);
        return <span key={key} className="chip num" title={f ? `${f.meaning} = ${f.value}` : "unknown"}>{id}</span>;
      }
      if (part.startsWith("**")) return <strong key={key}>{part.slice(2, -2)}</strong>;
      if (part.startsWith("`")) {
        const inner = part.slice(1, -1);
        return issueIds.has(inner)
          ? <Link key={key} href={withRun(`/issues/${inner}`, run)} className="link"><code>{inner}</code></Link>
          : <code key={key}>{inner}</code>;
      }
      if (/^[0-9a-f]{8}-/.test(part)) return <Link key={key} href={withRun(`/reviews/${part}`, run)} className="link num">{part.slice(0, 8)}…</Link>;
      if (issueIds.has(part)) return <Link key={key} href={withRun(`/issues/${part}`, run)} className="link"><code>{part}</code></Link>;
      return <span key={key}>{part}</span>;
    });

  const blocks = markdown.split(/\n\s*\n/);
  return (
    <div className="flex flex-col gap-3 leading-relaxed">
      {blocks.map((block, b) => {
        const lines = block.split("\n").filter((l) => l.trim());
        if (!lines.length) return null;
        if (lines[0].startsWith("#")) {
          const level = lines[0].match(/^#+/)![0].length;
          const text = lines[0].replace(/^#+\s*/, "");
          const rest = lines.slice(1).join(" ");
          return (
            <div key={b}>
              {level <= 1 ? <h2 className="text-xl font-semibold">{inline(text, `h${b}`)}</h2>
                          : <h3 className="text-lg font-semibold mt-2">{inline(text, `h${b}`)}</h3>}
              {rest && <p className="mt-2">{inline(rest, `p${b}`)}</p>}
            </div>);
        }
        if (lines.every((l) => /^\s*([-*]|\d+\.)\s+/.test(l))) {
          const ordered = /^\s*\d+\./.test(lines[0]);
          const items = lines.map((l, i) => <li key={i}>{inline(l.replace(/^\s*([-*]|\d+\.)\s+/, ""), `li${b}-${i}`)}</li>);
          return ordered ? <ol key={b} className="list-decimal pl-6 flex flex-col gap-1">{items}</ol>
                         : <ul key={b} className="list-disc pl-6 flex flex-col gap-1">{items}</ul>;
        }
        return <p key={b}>{inline(lines.join(" "), `p${b}`)}</p>;
      })}
    </div>
  );
}
