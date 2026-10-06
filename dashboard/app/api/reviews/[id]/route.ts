import type { NextRequest } from "next/server";
import { BadRequest, handle, json, resolveRun, validReviewId } from "@/lib/api";
import { requireDb } from "@/lib/db";

export async function GET(req: NextRequest, ctx: RouteContext<"/api/reviews/[id]">) {
  return handle(async () => {
    const sql = requireDb();
    const reviewId = validReviewId((await ctx.params).id);
    const runId = await resolveRun(req.nextUrl.searchParams.get("run"));
    const [[review], [run]] = await sql.transaction([
      sql`select r.*, i.name as issue_name, i.rank as issue_rank from reviews r
          left join issues i on i.run_id = r.run_id and i.issue_id = r.issue_id
          where r.run_id = ${runId} and r.review_id = ${reviewId}`,
      sql`select label_config from runs where run_id = ${runId}`,
    ]);
    if (!review) throw new BadRequest("review not in this run");
    return json({ runId, review, labelConfig: run.label_config });
  });
}
