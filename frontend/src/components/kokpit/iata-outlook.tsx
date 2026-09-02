import { ExternalLink } from "lucide-react";

import { AnnualTrendChart } from "@/components/kokpit/annual-trend-chart-lazy";
import type { AnnualSeries, IataIndicatorOut } from "@/lib/types";
import { cn } from "@/lib/utils";

const METRIC_LABEL_TR: Record<string, string> = {
  net_profit: "Net kâr",
  ebit: "EBIT",
};

/** The two profit lines the outlook panel carries, in reading order. */
const METRICS = ["net_profit", "ebit"] as const;

function trNumber(value: number): string {
  return value.toLocaleString("tr-TR");
}

/** Short month + year of an IATA edition, e.g. "Ara 2025". */
function editionLabel(iso: string): string {
  return new Date(iso).toLocaleDateString("tr-TR", { month: "short", year: "numeric" });
}

/**
 * "Ara-25 baskısı: 41,0 ▼" -- one muted line under the current figure,
 * rendered only where the previous edition's number is on record.
 *
 * IATA revises its own forecasts between editions, and the revision is very
 * often the story: the 2026 net-profit line went from $41bn to $23bn between
 * December 2025 and June 2026. A card showing only the current number prints
 * the conclusion and drops the news.
 *
 * Deliberately plain text rather than a delta pill: this is not a market
 * moving, it is one publisher changing its mind, and it must not read like the
 * former. (Rescued verbatim from `iata-indicator-table.tsx`, which was dead
 * code -- nothing imported it -- and which this component replaces.)
 */
function RevisionNote({ row }: { row: IataIndicatorOut }) {
  if (row.previous_value === null || row.previous_publication_date === null) return null;

  const revisedDown = row.value < row.previous_value;
  const unchanged = row.value === row.previous_value;
  const arrow = unchanged ? "→" : revisedDown ? "▼" : "▲";
  const arrowLabel = unchanged
    ? "değişmedi"
    : revisedDown
      ? "aşağı revize edildi"
      : "yukarı revize edildi";

  const body = (
    <>
      <span aria-label={arrowLabel} title={arrowLabel}>
        {arrow}
      </span>{" "}
      {editionLabel(row.previous_publication_date)} baskısı: {trNumber(row.previous_value)}
    </>
  );

  return (
    <p className="text-[10px] leading-relaxed text-muted-foreground">
      {row.previous_source_url ? (
        <a
          href={row.previous_source_url}
          target="_blank"
          rel="noopener noreferrer"
          className="rounded underline-offset-2 hover:text-primary hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
        >
          {body}
        </a>
      ) : (
        body
      )}
    </p>
  );
}

function MetricTile({ row }: { row: IataIndicatorOut }) {
  return (
    <div className="flex flex-col gap-0.5 rounded-lg border border-border bg-card/60 px-3 py-2">
      <div className="flex items-baseline gap-1.5">
        <span className="min-w-0 flex-1 truncate text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          {METRIC_LABEL_TR[row.metric] ?? row.metric}
        </span>
        <span className="shrink-0 rounded-full bg-muted px-1.5 py-px text-[10px] text-muted-foreground">
          {row.period_label_tr}
        </span>
        <a
          href={row.source_url}
          target="_blank"
          rel="noopener noreferrer"
          aria-label={`${METRIC_LABEL_TR[row.metric] ?? row.metric} kaynağına git`}
          className="shrink-0 rounded text-muted-foreground hover:text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
        >
          <ExternalLink className="size-3" />
        </a>
      </div>
      <span
        className="font-mono text-[13px] tabular-nums"
        title={row.interpretation_tr ?? undefined}
      >
        {trNumber(row.value)}{" "}
        <span className="text-[10px] font-sans text-muted-foreground">{row.unit}</span>
      </span>
      <RevisionNote row={row} />
    </div>
  );
}

/**
 * IATA GÖRÜNÜMÜ -- one trend chart and the profit lines beside it.
 *
 * There is no regional selector. `iata_indicators.region` is NULL on all eight
 * rows in the table and `curated_seed.py` never sets it, so a
 * GLOBAL/EUROPE/ASIA-PACIFIC switch would offer five choices that return
 * nothing. An empty selector does not communicate "we have no regional data";
 * it communicates "this product is broken". The section byline states the
 * limitation in words instead.
 */
export function IataOutlook({
  series,
  indicators,
}: {
  series: AnnualSeries[];
  indicators: IataIndicatorOut[];
}) {
  const byMetric = new Map(indicators.map((row) => [row.metric, row]));
  const tiles = METRICS.map((metric) => byMetric.get(metric)).filter(
    (row): row is IataIndicatorOut => row !== undefined,
  );

  const netProfit = byMetric.get("net_profit");
  const revision =
    netProfit && netProfit.previous_value !== null
      ? netProfit.value - netProfit.previous_value
      : null;

  const hasChart = series.length > 0;

  return (
    <div className="grid grid-cols-1 gap-3 xl:grid-cols-12">
      <div className={cn("xl:col-span-8", tiles.length === 0 && "xl:col-span-12")}>
        {hasChart ? (
          <div
            style={{ "--glow-color": "var(--chart-2)" } as React.CSSProperties}
            className="rounded-xl border-gradient p-3 shadow-elev-1"
          >
            <AnnualTrendChart series={series} />
          </div>
        ) : (
          <p className="flex h-[240px] items-center justify-center rounded-lg border border-dashed border-border p-4 text-center text-xs text-muted-foreground">
            IATA gelir serisi yüklenmedi.
          </p>
        )}
      </div>

      {tiles.length > 0 && (
        <div className="flex flex-col gap-2 xl:col-span-4">
          {tiles.map((row) => (
            <MetricTile key={row.metric} row={row} />
          ))}
          {revision !== null && (
            <div className="flex flex-col gap-0.5 rounded-lg border border-border bg-card/60 px-3 py-2">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Revizyon (net kâr)
              </span>
              {/* Not a `Delta`: a Delta means a metric moved, and this is the
                  same publisher printing a different number for the same year.
                  Colouring it green or red would say a market did something.

                  THREE states, not two. `revision !== null` admits zero, and
                  the old `revision < 0 ? "aşağı" : "yukarı"` therefore printed
                  "0 milyar $ · yukarı revize" for a figure IATA had reprinted
                  unchanged -- a direction claimed for a number that did not
                  move. `RevisionNote` a few lines up already handled the same
                  case correctly; this tile now says the same word it does. */}
              <span className="font-mono text-[13px] tabular-nums">
                {revision > 0 ? "+" : ""}
                {trNumber(Number(revision.toFixed(1)))}{" "}
                <span className="font-sans text-[10px] text-muted-foreground">
                  {netProfit?.unit} ·{" "}
                  {revision === 0 ? "değişmedi" : revision < 0 ? "aşağı revize" : "yukarı revize"}
                </span>
              </span>
            </div>
          )}
        </div>
      )}

      {tiles.length === 0 && (
        <p className="rounded-lg border border-dashed border-border p-4 text-center text-xs text-muted-foreground xl:col-span-12">
          Kâr göstergeleri henüz seed edilmedi.
        </p>
      )}
    </div>
  );
}
