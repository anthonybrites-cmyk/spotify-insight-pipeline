"use client";
import { useRouter, usePathname } from "next/navigation";
import { useApi } from "@/lib/useApi";

type Run = { run_id: string; label: string; scope: string; is_current: boolean };

export function RunPicker() {
  const { data, run } = useApi<{ runs: Run[] }>("/api/runs");
  const router = useRouter();
  const pathname = usePathname();
  if (!data || data.runs.length < 2) return null;
  const current = run ?? data.runs.find((r) => r.is_current)?.run_id ?? data.runs[0].run_id;
  return (
    <label className="text-sm secondary flex items-center gap-2">
      Run
      <select className="card px-2 py-1" value={current}
              onChange={(e) => router.push(`${pathname}?run=${encodeURIComponent(e.target.value)}`)}>
        {data.runs.map((r) => <option key={r.run_id} value={r.run_id}>{r.label}{r.is_current ? " (current)" : ""}</option>)}
      </select>
    </label>
  );
}
