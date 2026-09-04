"use client";

import { ChevronDown, Clock, TriangleAlert, type LucideIcon } from "lucide-react";
import { CircleAlert, Info } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { Collapse } from "@/components/ui/collapse";
import { formatRelativeTr } from "@/lib/format";
import { severityStyle } from "@/lib/signals";
import type { SignalOut, SignalSeverity } from "@/lib/types";
import { cn } from "@/lib/utils";

/** The two streams whose rows are alerts: the unacknowledged campaign inbox
 * and the Risk Radarı's high-severity clusters.
 *
 * A Set rather than a filter written inline, and exported, because the test
 * that matters is the one that pins WHICH streams these are: too wide and this
 * band reprints the signal board two sections above it, too narrow and an
 * alert stream silently stops being counted. */
export const ALERT_STREAMS = new Set(["campaign_alerts", "risk"]);

/** Three, down from ten. The section sits at the very bottom of the page and
 * opens closed; a reader who expands it wants the top of the list, and the
 * full list is one click away on /sinyaller, /kampanyalar and /risk-radari. */
const ROW_LIMIT = 3;

/** The three bands the closed band counts, worst first.
 *
 * `low` and `unknown` rows are still merged, still ordered and still reachable
 * in the open list -- they are simply not counted in a strip whose job is "is
 * there something to react to". The colours come from `severityStyle`, the
 * app's one severity->hue mapping (lib/signals.ts), rather than a second table
 * here: this band and a card on /sinyaller must not draw the same word in two
 * different colours.
 */
const BANDS: { severity: SignalSeverity; label: string; icon: LucideIcon }[] = [
  { severity: "critical", label: "KRİTİK", icon: TriangleAlert },
  { severity: "high", label: "YÜKSEK", icon: CircleAlert },
  { severity: "medium", label: "ORTA", icon: Info },
];

const BAND_ICON: Record<string, LucideIcon> = Object.fromEntries(
  BANDS.map((band) => [band.severity, band.icon]),
);

/**
 * ALERT MERKEZİ -- the page's last section, a 44px band that opens on demand.
 *
 * It was a full-height panel in the upper half of the page. The owner's order
 * puts alerts at the BOTTOM, which is right: an alert centre near the top
 * competes for attention with the market state a reader came for, and on a
 * local database with no recent campaign alerts it competed while empty.
 *
 * The closed band still prints its counts, including zeroes. "0 KRİTİK · 0
 * YÜKSEK · 0 ORTA" is information -- it says the streams answered and had
 * nothing -- and it is a different statement from the section being absent,
 * which would say nothing at all. So this component never falls silent over a
 * zero: a measured nothing gets said.
 *
 * THAT SENTENCE IS ONLY TRUE IF THE STREAMS ANSWERED, and that is now settled
 * one level up. This component used to fetch `/campaign-alerts` and
 * `/risks?days=14` itself and had to carry three failure branches for the four
 * states two independent fetches can be in; worse, it then merged and RE-SORTED
 * what came back under a priority ladder of its own. /sinyaller sorted the same
 * rows with the backend's ladder, so the two surfaces published two different
 * "top four" out of one set of facts, and the risk half was cut to four here
 * and eight there.
 *
 * Both are gone. `/signals` is read once, on the server (app/page.tsx), and
 * arrives here already merged and already ordered by
 * `signals_service.sort_signals` -- severity first, recency second, one
 * implementation. If that read fails, app/page.tsx does not render this
 * section AT ALL: sections 8 and 9 have no other source, so both give way to
 * the single SIGNALS failure line printed two sections higher, in Rekabet --
 * three identical warnings twenty pixels apart stop being read as one. So the
 * band's zeroes are always a measurement; an outage is never dressed as one.
 * (This used to claim the failure line was printed in place of this section.
 * It is not, and a reader trusting that would have gone looking for a warning
 * where the page prints nothing.)
 *
 * THE RISK HALF CAN BE A FLOOR. `/risks` caps how many articles one rollup
 * clusters, and when that cap bites every risk count in this band -- and in
 * /sinyaller's tally -- counts only the newest slice of the risk window.
 * `riskTruncated` is that flag, carried through `/signals` (see
 * SignalsOut.risk_truncated); when it is set the band says so in words rather
 * than printing a floor as the total.
 */
export function AlertCenter({
  signals,
  riskTruncated = false,
  riskScannedArticles = null,
}: {
  signals: SignalOut[];
  /** The risk rollup behind these rows hit its scan cap, so the risk share of
   * the counts below is a floor. Defaults to `false` because that is what an
   * older payload without the field means -- an uncapped rollup -- not because
   * silence is safe. */
  riskTruncated?: boolean;
  /** How many articles that rollup did read, so the disclosure can name a
   * number. `null` when the response did not say -- the sentence then drops
   * the figure instead of inventing one. */
  riskScannedArticles?: number | null;
}) {
  const [open, setOpen] = useState(false);

  // NOT re-sorted. `filter` preserves order, and the order is the backend's --
  // the same one /sinyaller lists these rows in. A `.sort()` here would be a
  // second opinion about which alert is the most important one on the page.
  const merged = useMemo(
    () => signals.filter((row) => ALERT_STREAMS.has(row.stream)),
    [signals],
  );

  /** Counted over EVERYTHING the two streams contributed, not over the three
   * rows the open panel shows. A band that said "2 kritik" because it had
   * truncated to three rows would be a band nobody could reconcile with
   * /sinyaller. */
  const counts = useMemo(() => {
    const tally: Record<string, number> = {};
    for (const row of merged) tally[row.severity] = (tally[row.severity] ?? 0) + 1;
    return tally;
  }, [merged]);

  const rows = merged.slice(0, ROW_LIMIT);

  // Exactly one row may flash, exactly once: the top CRITICAL. Since the list
  // arrives worst-first, that is the first row if it is critical at all.
  // `animate-pulse-once` does not loop and is off under reduced motion; a list
  // where several rows pulsed would be a notification tray, which this is not.
  const flashId = merged.find((row) => row.severity === "critical")?.id ?? null;

  /** Said only when the cap actually bit. A line that is always on screen is
   * furniture, and on an ordinary day these counts really are complete. */
  const riskFloorNote = !riskTruncated
    ? null
    : riskScannedArticles && riskScannedArticles > 0
      ? `Risk taraması pencerenin en yeni ${riskScannedArticles.toLocaleString(
          "tr-TR",
        )} haberinde durdu; yukarıdaki risk sayıları taban değerdir — hepsi bu kadar değil.`
      : "Risk taraması pencerenin tamamına ulaşamadı; yukarıdaki risk sayıları taban değerdir — hepsi bu kadar değil.";

  return (
    <div className="flex flex-col gap-1.5 rounded-lg border border-border bg-card/60 px-3 py-2">
      <div className="flex h-7 flex-wrap items-center gap-x-3 gap-y-1">
        <TriangleAlert
          className={cn(
            "size-3.5 shrink-0",
            (counts.critical ?? 0) > 0 ? "text-critical" : "text-muted-foreground",
          )}
          aria-hidden
        />
        <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
          {BANDS.map(({ severity, label }) => (
            <span
              key={severity}
              className={cn(
                "flex items-center gap-1 text-[11px] tabular-nums",
                (counts[severity] ?? 0) > 0
                  ? severityStyle(severity).text
                  : "text-muted-foreground",
              )}
            >
              <span
                aria-hidden
                className={cn("size-1.5 rounded-full", severityStyle(severity).dot)}
              />
              {counts[severity] ?? 0} {label}
            </span>
          ))}
        </span>

        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          disabled={rows.length === 0}
          className="rounded border border-border px-2 py-0.5 text-[10px] font-medium text-muted-foreground transition-colors hover:bg-accent disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
        >
          {open ? "Daralt" : "Genişlet"}
          <ChevronDown
            className={cn("ml-1 inline size-3 transition-transform", open && "rotate-180")}
            aria-hidden
          />
        </button>

        <span className="ml-auto flex gap-3 text-[10px]">
          {/* Sinyaller first: it is the surface that owns the full, filterable
              list these rows are a head of. The other two are the pages each
              stream's rows drill down into. */}
          <Link
            href="/sinyaller"
            className="rounded text-muted-foreground underline-offset-2 hover:text-primary hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          >
            Sinyaller →
          </Link>
          <Link
            href="/kampanyalar"
            className="rounded text-muted-foreground underline-offset-2 hover:text-primary hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          >
            Kampanyalar →
          </Link>
          <Link
            href="/risk-radari"
            className="rounded text-muted-foreground underline-offset-2 hover:text-primary hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          >
            Risk →
          </Link>
        </span>
      </div>

      {riskFloorNote && (
        <p className="text-[10px] text-muted-foreground">{riskFloorNote}</p>
      )}

      <Collapse open={open && rows.length > 0}>
        <ul className="flex flex-col gap-0.5 pt-1">
          {rows.map((row) => {
            const Icon = BAND_ICON[row.severity] ?? Info;
            const style = severityStyle(row.severity);
            const body = (
              <>
                <Icon className={cn("size-3 shrink-0", style.text)} aria-hidden />
                <span className="sr-only">{row.severity_label_tr} öncelikli:</span>
                <span className="min-w-0 flex-1 truncate font-medium text-foreground">
                  {row.title_tr}
                </span>
                <span className="hidden shrink-0 text-[10px] text-muted-foreground lg:inline">
                  {row.type_label_tr}
                </span>
                <span className="flex shrink-0 items-center gap-1 text-[10px] tabular-nums text-muted-foreground">
                  <Clock className="size-2.5" aria-hidden />
                  {/* Never defaulted to "now": an undated alert says so. */}
                  {row.detected_at ? formatRelativeTr(row.detected_at) : "—"}
                </span>
              </>
            );
            const className = cn(
              "flex h-7 items-center gap-2 rounded px-2 text-xs",
              row.id === flashId && "edge-lit animate-pulse-once",
            );

            // `href` is the stream's own drill-down, published by the backend
            // beside the row -- never a target this component picks. A stream
            // that has no deeper page says so with `null`, and the row is then
            // text rather than a link that goes nowhere.
            return (
              <li key={row.id}>
                {row.href ? (
                  <Link
                    href={row.href}
                    style={{ "--glow-color": "var(--critical)" } as React.CSSProperties}
                    className={cn(
                      className,
                      "transition-colors hover:bg-accent/50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
                    )}
                  >
                    {body}
                  </Link>
                ) : (
                  <div
                    style={{ "--glow-color": "var(--critical)" } as React.CSSProperties}
                    className={className}
                  >
                    {body}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      </Collapse>
    </div>
  );
}
