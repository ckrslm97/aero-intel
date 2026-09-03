"use client";

import { Merge } from "lucide-react";

import { Card } from "@/components/ui/card";
import { buildRiskFunnel } from "@/lib/risk";
import type { RiskFunnelStage } from "@/lib/types";
import { cn } from "@/lib/utils";

/** The funnel: nine stages from "every article we hold" to "signals on the
 * radar", with what left at each one.
 *
 * BARS SCALED TO THE FIRST STAGE, not to the previous one. Scaling each bar to
 * its predecessor makes every stage look like it kept most of what reached it,
 * and the one fact this screen exists to convey is that ~14.000 articles
 * become single-digit signals. The bar is the shape; the two numbers beside it
 * are the audit.
 *
 * THE LAST STAGE IS NOT A REJECTION and is drawn differently for it.
 * Clustering removes rows from the count and none of them from the radar --
 * three outlets covering one eruption become one card, and the other two are
 * inside it. Rendering that drop in the same red as "güven eşiğinin altında"
 * would tell an analyst their event was discarded when it is on the page under
 * another headline. `drop_kind` carries the distinction from the API and this
 * component is where it has to survive.
 */
export function RiskFunnel({
  stages,
  activeReason,
  onSelectReason,
}: {
  stages: readonly RiskFunnelStage[];
  /** The rejection currently filtering the table below, so the funnel and the
   * table cannot disagree about what is being looked at. */
  activeReason?: string | null;
  onSelectReason?: (reason: string | null) => void;
}) {
  const bars = buildRiskFunnel(stages);
  if (bars.length === 0) return null;

  return (
    <Card size="sm" className="gap-2 p-0">
      <ol className="divide-y divide-border/60">
        {bars.map((bar) => {
          const merged = bar.dropKind === "merged";
          // One chip per REASON, not per stage. The location gate drops rows
          // for two different reasons, and a single chip labelled with the
          // stage's whole count but filtering on only the first of them would
          // return a third of what its own label promised.
          const chips = onSelectReason ? bar.reasons.filter((r) => r.count > 0) : [];
          return (
            <li key={bar.key} className="px-3 py-2">
              <div className="flex items-baseline justify-between gap-3">
                <span className="truncate text-xs font-medium">{bar.label}</span>
                <span className="flex shrink-0 items-baseline gap-2 text-[11px]">
                  <span className="font-mono tabular-nums">
                    {bar.passed.toLocaleString("tr-TR")}
                  </span>
                  {bar.keptPct !== null && (
                    <span className="tabular-nums text-muted-foreground">
                      %{bar.keptPct.toFixed(bar.keptPct < 10 ? 1 : 0)}
                    </span>
                  )}
                </span>
              </div>

              <div
                className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-muted"
                role="presentation"
              >
                <div
                  className={cn(
                    "h-full rounded-full transition-[width] duration-500",
                    merged ? "bg-primary/70" : "bg-primary",
                  )}
                  style={{ width: `${bar.widthPct}%` }}
                />
              </div>

              {bar.dropped > 0 && (
                <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10px] leading-relaxed">
                  {merged ? (
                    <span className="inline-flex items-center gap-1 text-muted-foreground">
                      <Merge className="size-2.5" aria-hidden />
                      <span className="tabular-nums">{bar.dropped}</span> haber tek
                      sinyalde birleşti
                    </span>
                  ) : chips.length > 0 ? (
                    chips.map((chipReason) => {
                      const active = chipReason.reason === activeReason;
                      return (
                        <button
                          key={chipReason.reason}
                          type="button"
                          onClick={() =>
                            onSelectReason?.(active ? null : chipReason.reason)
                          }
                          aria-pressed={active}
                          className={cn(
                            "rounded-full border px-1.5 py-px font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
                            active
                              ? "border-primary/40 bg-primary/12 text-primary"
                              : "border-border text-muted-foreground hover:bg-accent",
                          )}
                        >
                          <span className="tabular-nums">{chipReason.count}</span> elendi
                          {` · ${chipReason.reason}`}
                        </button>
                      );
                    })
                  ) : (
                    <span className="text-muted-foreground">
                      <span className="tabular-nums">{bar.dropped}</span> ayrıldı
                    </span>
                  )}
                  {bar.note && <span className="text-muted-foreground">{bar.note}</span>}
                </div>
              )}
            </li>
          );
        })}
      </ol>
    </Card>
  );
}
