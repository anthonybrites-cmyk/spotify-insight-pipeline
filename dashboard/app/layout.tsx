import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Spotify Review Insights",
  description: "Where should Spotify's next quarter of product effort go? Ranked issues, metrics and an AI recommendation, traceable to source reviews.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full flex flex-col font-sans">
        <header className="border-b" style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}>
          <nav className="mx-auto max-w-6xl px-4 py-3 flex flex-wrap items-center gap-x-6 gap-y-2">
            <Link href="/" className="font-semibold">Spotify Review Insights</Link>
            <Link href="/" className="secondary">Overview</Link>
            <Link href="/issues" className="secondary">Issue ranking</Link>
            <Link href="/recommendation" className="secondary">AI recommendation</Link>
            <Link href="/about" className="secondary">Method &amp; data</Link>
          </nav>
        </header>
        <main className="mx-auto w-full max-w-6xl px-4 py-6 flex-1">{children}</main>
        <footer className="mx-auto w-full max-w-6xl px-4 py-6 text-sm muted">
          Saved pipeline results served from Postgres by this app&apos;s API. Viewing this dashboard makes no model calls.
        </footer>
      </body>
    </html>
  );
}
