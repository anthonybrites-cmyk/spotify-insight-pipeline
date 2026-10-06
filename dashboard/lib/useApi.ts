"use client";
import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

type Result<T> = { url: string; data?: T; error?: string };

/** Fetch JSON from this app's backend API, forwarding the optional ?run= selector. */
export function useApi<T>(path: string | null) {
  const params = useSearchParams();
  const run = params.get("run");
  const url = path ? (run ? `${path}${path.includes("?") ? "&" : "?"}run=${encodeURIComponent(run)}` : path) : null;
  const [result, setResult] = useState<Result<T> | null>(null);
  useEffect(() => {
    if (!url) return;
    let alive = true;
    fetch(url)
      .then(async (r) => {
        const body = await r.json();
        if (!r.ok) throw new Error(body.error ?? `HTTP ${r.status}`);
        return body as T;
      })
      .then((data) => alive && setResult({ url, data }))
      .catch((e: Error) => alive && setResult({ url, error: e.message }));
    return () => {
      alive = false;
    };
  }, [url]);
  // Loading until the response for the *current* URL arrives (older responses are ignored).
  const current = result && result.url === url ? result : null;
  return { data: current?.data, error: current?.error, loading: !current, run };
}

export function withRun(href: string, run: string | null) {
  return run ? `${href}${href.includes("?") ? "&" : "?"}run=${encodeURIComponent(run)}` : href;
}
