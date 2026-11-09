import type { ReactNode } from "react";

export function Section({ id, testId, title, note, children }: { id: string; testId: string; title: string; note?: ReactNode; children: ReactNode }) {
  return (
    <section data-testid={testId} aria-labelledby={id} className="rounded-lg border border-stone-200 bg-white p-5">
      <h2 id={id} className="text-sm font-medium uppercase tracking-wide text-stone-500">
        {title}
      </h2>
      {note ? <p className="mt-1 text-sm text-stone-600">{note}</p> : null}
      <div className="mt-4">{children}</div>
    </section>
  );
}

export function SectionError({ what, error, status }: { what: string; error: string; status: number | null }) {
  return (
    <p role="alert" className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
      Could not load {what}
      {status !== null ? ` (HTTP ${status})` : ""}: {error}
    </p>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div>
      <dt className="text-xs text-stone-500">{label}</dt>
      <dd className="text-2xl font-semibold tabular-nums tracking-tight" title={hint}>
        {value}
      </dd>
    </div>
  );
}
