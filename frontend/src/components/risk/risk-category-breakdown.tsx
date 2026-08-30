"use client";

import { FALLBACK_TYPE_ICON, TYPE_META } from "@/components/risk/risk-meta";
import { riskTypeBreakdown } from "@/lib/risk";
import type { RiskCountry } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Which kinds of risk the current view is made of.
 *
 * Horizontal bars and not a pie, for the usual reason plus one specific to this
 * page: a pie asks "what share of the whole", and the whole here is a filtered
 * slice of a news feed rather than a population -- a 40% wedge would invite a
 * reading ("40% of world risk is wildfire") the data cannot support. Bars with
 * the count written out ask the answerable question instead: which type has the
 * most signals right now, and how many.
 *
 * The high-severity segment is drawn inside each bar rather than as a second
 * bar: it is a subset, and two bars side by side would read as two independent
 * quantities.
 *
 * Counts come from the VISIBLE set, not from the payload's window-wide
 * `type_counts` -- a breakdown that disagrees with the list above it is the one
 * thing a breakdown must never do.
 */
export function RiskCategoryBreakdown({
  countries,
  selectedType,
  onSelectType,
}: {
  countries: RiskCountry[];
  selectedType: string | null;
  onSelectType: (type: string | null) => void;
}) {
  const rows = riskTypeBreakdown(countries);
  if (rows.length === 0) return null;

  const max = Math.max(...rows.map((row) => row.count));

  return (
    <section className="flex flex-col gap-3 rounded-xl border border-border bg-card bg-card-sheen p-4 shadow-elev-1">
      <div className="flex flex-col gap-1">
        <h2 className="text-sm font-semibold">Tür dağılımı</h2>
        <p className="text-[11px] leading-relaxed text-muted-foreground">
          Görünürdeki sinyaller; koyu bölüm yüksek şiddetli olanlar. Filtrelerle
          birlikte değişir.
        </p>
      </div>

      <ul className="flex flex-col gap-2">
        {rows.map((row) => {
          const Icon = TYPE_META[row.type]?.icon ?? FALLBACK_TYPE_ICON;
          const active = selectedType === row.type;
          return (
            <li key={row.type}>
              <button
                type="button"
                onClick={() => onSelectType(active ? null : row.type)}
                aria-pressed={active}
                className={cn(
                  "flex w-full flex-col gap-1 rounded-lg border px-2 py-1.5 text-left transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
                  active
                    ? "border-primary/40 bg-primary/5"
                    : "border-transparent hover:border-border hover:bg-accent/50",
                )}
              >
                <span className="flex items-center gap-2">
                  <Icon className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                  <span className="min-w-0 flex-1 truncate text-xs font-medium">{row.label}</span>
                  <span className="shrink-0 font-mono text-[11px] tabular-nums text-muted-foreground">
                    {row.count}
                    {row.high > 0 && (
                      <span className="ml-1 text-critical">{row.high}Y</span>
                    )}
                  </span>
                </span>
                <span
                  aria-hidden
                  className="flex h-1.5 overflow-hidden rounded-full bg-muted"
                  style={{ width: `${(row.count / max) * 100}%`, minWidth: "6%" }}
                >
                  <span
                    className="bg-critical"
                    style={{ width: `${(row.high / row.count) * 100}%` }}
                  />
                  <span className="flex-1 bg-muted-foreground/40" />
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
