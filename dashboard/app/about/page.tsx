export default function Page() {
  return (
    <div className="flex flex-col gap-4 max-w-3xl leading-relaxed">
      <h1 className="text-2xl font-semibold">Method &amp; data</h1>
      <p>This dashboard shows saved results from the Spotify review-analysis pipeline. The pipeline is in{" "}
        <a className="link" href="https://github.com/anthonybrites-cmyk/spotify-insight-pipeline">the GitHub repository</a>.</p>
      <ol className="list-decimal pl-6 flex flex-col gap-1">
        <li><strong>Ingest (code):</strong> every row is hashed, empty texts are quarantined, and identical texts are classified once.</li>
        <li><strong>Enrich:</strong> Jev (<code>jev-1.13.0</code>) picks topic, intent, severity and sentiment. Low-confidence texts are re-labelled blind by <code>claude-sonnet-5</code> under a declared 20% cap. Evidence quotes are exact substrings cut by code.</li>
        <li><strong>Verify:</strong> Claude blind-labels a declared random sample, and code compares the results.</li>
        <li><strong>Group:</strong> Claude proposes subtopics from a sample of complaint quotes, and Jev assigns each complaint to one issue.</li>
        <li><strong>Rank (code):</strong> priority = complaint count × mean severity = severity sum.</li>
        <li><strong>Recommend:</strong> Claude writes the memo from the aggregates only. Code checks every number, ID and quote.</li>
      </ol>
      <p><strong>Architecture of this site:</strong> the pipeline publishes a finished run into Neon Postgres (<code>python -m pipeline publish</code>). This app&apos;s API routes (<code>/api/*</code>) read it with a SELECT-only role and serve JSON to these pages. Viewing the dashboard never calls a model.</p>
      <p><strong>Limits:</strong> these are self-selected, historical Play Store reviews. There is no revenue, plan or confirmed-churn data, and cancellation intent is not churn. Verifier agreement is between two models, not accuracy.</p>
    </div>
  );
}
