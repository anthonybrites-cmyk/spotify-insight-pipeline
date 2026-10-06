export function Loading() {
  return <p className="muted">Loading saved results…</p>;
}
export function ErrorBox({ message }: { message: string }) {
  return (
    <div className="card p-4" style={{ background: "var(--warn-bg)" }} role="alert">
      Could not load data: {message}
    </div>
  );
}
