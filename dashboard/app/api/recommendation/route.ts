import type { NextRequest } from "next/server";
import { handle, json, resolveRun } from "@/lib/api";
import { requireDb } from "@/lib/db";

export async function GET(req: NextRequest) {
  return handle(async () => {
    const sql = requireDb();
    const runId = await resolveRun(req.nextUrl.searchParams.get("run"));
    const [rec, claims, facts, issues] = await sql.transaction([
      sql`select memo_markdown, model, label_config, check_passed, check_errors, evidence_pack
          from recommendations where run_id = ${runId}`,
      sql`select c.claim_id, c.issue_id, c.metric, c.value, i.name as issue_name from claims c
          left join issues i on i.run_id = c.run_id and i.issue_id = c.issue_id
          where c.run_id = ${runId} order by c.claim_id`,
      sql`select fact_id, meaning, value from facts where run_id = ${runId} order by fact_id`,
      sql`select issue_id, name, rank from issues where run_id = ${runId}`,
    ]);
    return json({ runId, recommendation: rec[0] ?? null, claims, facts, issues });
  });
}
