"use client";
import { useApi } from "@/lib/useApi";
import { ErrorBox, Loading } from "./Status";
import { IssueTable, type IssueRow } from "./IssueTable";
import { RunPicker } from "./RunPicker";

export function IssuesView() {
  const { data, error, loading, run } = useApi<{ issues: IssueRow[] }>("/api/issues");
  if (loading) return <Loading />;
  if (error || !data) return <ErrorBox message={error ?? "no data"} />;
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="text-2xl font-semibold">Issue ranking ({data.issues.length} issues)</h1>
        <RunPicker />
      </div>
      <section className="card p-5"><IssueTable rows={data.issues} run={run} showDefinition /></section>
    </div>
  );
}
