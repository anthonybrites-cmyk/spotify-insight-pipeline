import { handle, json } from "@/lib/api";
import { requireDb } from "@/lib/db";

export async function GET() {
  return handle(async () => {
    const sql = requireDb();
    const runs = await sql`select run_id, label, scope, source_rows, completed, is_current, published_at
                           from runs order by is_current desc, published_at desc`;
    return json({ runs });
  });
}
