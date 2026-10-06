import type { NextRequest } from "next/server";
import { handle, json, resolveRun } from "@/lib/api";
import { requireDb } from "@/lib/db";

export async function GET(req: NextRequest) {
  return handle(async () => {
    const sql = requireDb();
    const runId = await resolveRun(req.nextUrl.searchParams.get("run"));
    const [[run], topics, top, rec] = await sql.transaction([
      sql`select * from runs where run_id = ${runId}`,
      sql`select topic, reviews, complaints, cancellations, severity_sum from topic_metrics
          where run_id = ${runId} order by complaints desc, topic`,
      sql`select rank, issue_id, topic, name, complaint_count, severity_sum, mean_severity, priority_score
          from issues where run_id = ${runId} and rank is not null order by rank limit 10`,
      sql`select memo_markdown, model, check_passed from recommendations where run_id = ${runId}`,
    ]);
    return json({ run, topics, topIssues: top, recommendation: rec[0] ?? null });
  });
}
