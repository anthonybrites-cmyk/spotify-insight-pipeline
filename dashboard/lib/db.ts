import "server-only";
import { neon } from "@neondatabase/serverless";

// The backend connects with a SELECT-only Postgres role (see db/schema.sql and `python -m pipeline db-setup`).
// The connection string lives only in the server environment, never in browser code.
const url = process.env.DASHBOARD_DATABASE_URL;

export const sql = url ? neon(url) : null;

export function requireDb() {
  if (!sql) throw new Error("DASHBOARD_DATABASE_URL is not configured on the server");
  return sql;
}
