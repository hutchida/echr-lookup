import type { BarRow } from "../_lib/format";
import { formatCount } from "../_lib/format";

/** Plain HTML/CSS horizontal bars. The count and share are always printed, so the bar is never the only signal. */
export function BarList({ title, rows, testId }: { title: string; rows: BarRow[]; testId?: string }) {
  return (
    <div data-testid={testId}>
      <h3 className="mb-2 text-sm font-medium text-stone-700">{title}</h3>
      {rows.length === 0 ? (
        <p className="text-sm text-stone-500">No data.</p>
      ) : (
        <ul className="space-y-1">
          {rows.map((row) => (
            <li key={row.label} className="grid grid-cols-[8rem_1fr_6rem] items-center gap-2 text-sm">
              <span className="truncate" title={row.label}>
                {row.label}
              </span>
              <span className="h-3 rounded-sm bg-stone-100" aria-hidden="true">
                <span className="block h-3 rounded-sm bg-stone-600" style={{ width: `${row.width}%` }} />
              </span>
              <span className="text-right tabular-nums text-stone-700">
                {formatCount(row.count)} <span className="text-stone-400">({row.share})</span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
