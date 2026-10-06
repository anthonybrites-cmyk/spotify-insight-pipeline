import "server-only";
import { connection } from "next/server";
import { requireDb } from "./db";

// Input validation for every query parameter the API accepts.
const RUN_ID = /^[A-Za-z0-9._-]{1,80}$/;
const ISSUE_ID = /^[a-z]+\.[a-z0-9_]{1,60}$/;
const REVIEW_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

export class BadRequest extends Error {}

export function validRunParam(value: string | null): string | null {
  if (value === null || value === "") return null;
  if (!RUN_ID.test(value)) throw new BadRequest("invalid run id");
  return value;
}

export function validIssueId(value: string): string {
  if (!ISSUE_ID.test(value)) throw new BadRequest("invalid issue id");
  return value;
}

export function validReviewId(value: string): string {
  if (!REVIEW_ID.test(value)) throw new BadRequest("invalid review id");
  return value;
}

/** The requested run, or the run marked current. */
export async function resolveRun(runParam: string | null): Promise<string> {
  const sql = requireDb();
  const run = validRunParam(runParam);
  const rows = run
    ? await sql`select run_id from runs where run_id = ${run}`
    : await sql`select run_id from runs order by is_current desc, published_at desc limit 1`;
  if (rows.length === 0) throw new BadRequest(run ? "unknown run" : "no published runs");
  return rows[0].run_id as string;
}

export function json(data: unknown, status = 200) {
  // Saved results change only when a run is republished: let the CDN cache briefly.
  return Response.json(data, {
    status,
    headers: { "Cache-Control": "public, s-maxage=60, stale-while-revalidate=300" },
  });
}

export async function handle(fn: () => Promise<Response>): Promise<Response> {
  // Always answer at request time from the database; never prerender an API response at build.
  await connection();
  return fn().catch((e: unknown) => {
    if (e instanceof BadRequest) return Response.json({ error: e.message }, { status: 400 });
    console.error(e);
    return Response.json({ error: "server error" }, { status: 500 });
  });
}
