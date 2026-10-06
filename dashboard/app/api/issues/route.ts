import type { NextRequest } from "next/server";
import { handle, json, resolveRun } from "@/lib/api";
import { requireDb } from "@/lib/db";

export async function GET(req: NextRequest) {
  return handle(async () => {
    const sql = requireDb();
    const runId = await resolveRun(req.nextUrl.searchParams.get("run"));
    const issues = await sql`select rank, issue_id, topic, name, definition, complaint_count, severity_sum,
                                    mean_severity, priority_score
                             from issues where run_id = ${runId} and rank is not null order by rank`;
    return json({ runId, issues });
  });
}
