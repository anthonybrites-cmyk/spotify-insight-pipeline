import type { NextRequest } from "next/server";
import { BadRequest, handle, json, resolveRun, validIssueId } from "@/lib/api";
import { requireDb } from "@/lib/db";

const PAGE_SIZE = 50;

export async function GET(req: NextRequest, ctx: RouteContext<"/api/issues/[id]">) {
  return handle(async () => {
    const sql = requireDb();
    const issueId = validIssueId((await ctx.params).id);
    const runId = await resolveRun(req.nextUrl.searchParams.get("run"));
    const page = Math.max(0, Math.min(10000, Number.parseInt(req.nextUrl.searchParams.get("page") ?? "0", 10) || 0));
    const [[issue], claims, members, [{ n }], severity] = await sql.transaction([
      sql`select * from issues where run_id = ${runId} and issue_id = ${issueId}`,
      sql`select claim_id, metric, value from claims where run_id = ${runId} and issue_id = ${issueId} order by claim_id`,
      sql`select review_id, severity, intent, sentiment, evidence_quote, decided_by, needs_review, review_timestamp
          from reviews where run_id = ${runId} and issue_id = ${issueId}
          order by severity desc, review_id limit ${PAGE_SIZE} offset ${page * PAGE_SIZE}`,
      sql`select count(*)::int as n from reviews where run_id = ${runId} and issue_id = ${issueId}`,
      sql`select severity, count(*)::int as n from reviews where run_id = ${runId} and issue_id = ${issueId}
          group by severity order by severity`,
    ]);
    if (!issue) throw new BadRequest("unknown issue for this run");
    return json({ runId, issue, claims, members, memberCount: n, page, pageSize: PAGE_SIZE, severity });
  });
}
