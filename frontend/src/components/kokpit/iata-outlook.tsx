import { ExternalLink, TriangleAlert } from "lucide-react";

import { AnnualTrendChart } from "@/components/kokpit/annual-trend-chart-lazy";
import { ANNUAL_KIND_LABELS_TR, ANNUAL_KIND_SUFFIX } from "@/lib/cockpit";
import { formatMonthTr } from "@/lib/format";
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

/** Short month + year of an IATA edition, e.g. "Ara 2025". Pinned: an edition
 * published at 23:00Z on 30 November is a December edition in Istanbul and a
 * November one in London, and which month IATA published in is not a fact
 * about where the reader is sitting. */
function editionLabel(iso: string): string {
  return formatMonthTr(iso) ?? "—";
}

/**
 * "REVİZYON · NET KÂR  −18,0 mlr $ · aşağı revize" -- one tile per profit line
 * whose previous edition is on record.
 *
 * IATA revises its own forecasts between editions, and the revision is very
 * often the story: the 2026 net-profit line went from $41bn to $23bn between
 * December 2025 and June 2026. A panel showing only the current number prints
 * the conclusion and drops the news.
 *
 * Deliberately NOT a `Delta`: a Delta means a market moved, and this is one
 * publisher changing its mind about the same year. Colouring it green or red
 * would say something happened in the world.
 *
 * THREE states, not two. `previous_value` can equal `value`, and the earlier
 * draft's `revision < 0 ? "aşağı" : "yukarı"` therefore printed "0 milyar $ ·
 * yukarı revize" for a figure IATA had reprinted unchanged -- a direction
 * claimed for a number that did not move.
 *
 * (The arithmetic and wording are rescued from `iata-indicator-table.tsx`,
 * which was dead code -- nothing imported it -- and which this file replaces.)
 */
function RevisionTile({ row }: { row: IataIndicatorOut }) {
  if (row.previous_value === null || row.previous_publication_date === null) return null;

  const delta = row.value - row.previous_value;
  const word = delta === 0 ? "değişmedi" : delta < 0 ? "aşağı revize" : "yukarı revize";
  const previous = (
    <>
      {editionLabel(row.previous_publication_date)} baskısı: {trNumber(row.previous_value)}
    </>
  );

  return (
    <div className="flex flex-col gap-0.5 rounded-lg border border-border bg-card/60 px-3 py-2">
      <span className="truncate text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        Revizyon · {METRIC_LABEL_TR[row.metric] ?? row.metric}
      </span>
      <span className="font-mono text-[13px] tabular-nums">
        {delta > 0 ? "+" : ""}
        {trNumber(Number(delta.toFixed(1)))}{" "}
        <span className="font-sans text-[10px] text-muted-foreground">
          {row.unit} · {word}
        </span>
      </span>
      <p className="truncate text-[10px] text-muted-foreground">
        {row.previous_source_url ? (
          <a
            href={row.previous_source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="rounded underline-offset-2 hover:text-primary hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          >
            {previous}
          </a>
        ) : (
          previous
        )}
      </p>
    </div>
  );
}

/**
 * "NET KÂR  [2026T]  23 USD milyar · tahmin"
 *
 * THE BADGE CARRIES THE KIND, NOT JUST THE YEAR. IATA's 2026 profit lines are
 * FORECASTS, and this tile used to draw them in exactly the visual language it
 * draws a measured year in -- the word "tahmin" existed only inside
 * `interpretation_tr`, which is a hover title. Every other surface on this page
 * keeps the distinction in the open (YearDots' labels, Market Pulse's "IATA
 * 2026T" badge, both delta scopes), so on this one tile the ABSENCE of a
 * suffix read as a measurement.
 *
 * Three things say it, none of them hover-only: the page's own one-letter
 * suffix from `ANNUAL_KIND_SUFFIX` (a reader who learned "T = tahmin" in the
 * cell above must not meet a different letter here), the Turkish word from
 * `ANNUAL_KIND_LABELS_TR` beside the unit, and a dashed badge border -- the
 * app's existing idiom for "not a measurement".
 *
 * An `actual` row gets no word and no dash, which is the same rule the rest of
 * the page follows: the plain form is the measured one.
 */
function MetricTile({ row }: { row: IataIndicatorOut }) {
  const kindLabel = ANNUAL_KIND_LABELS_TR[row.kind];
  const isProjection = row.kind !== "actual";

  return (
    <div className="flex flex-col gap-0.5 rounded-lg border border-border bg-card/60 px-3 py-2">
      <div className="flex items-baseline gap-1.5">
        <span className="min-w-0 flex-1 truncate text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          {METRIC_LABEL_TR[row.metric] ?? row.metric}
        </span>
        <span
          title={`${row.period_label_tr} · ${kindLabel}`}
          className={cn(
            "shrink-0 rounded-full px-1.5 py-px text-[10px] text-muted-foreground",
            isProjection ? "border border-dashed border-border" : "bg-muted",
          )}
        >
          {row.period_label_tr}
          {ANNUAL_KIND_SUFFIX[row.kind]}
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
        <span className="text-[10px] font-sans text-muted-foreground">
          {row.unit}
          {isProjection && ` · ${kindLabel}`}
        </span>
      </span>
    </div>
  );
}

/**
 * IATA GÖRÜNÜMÜ -- one trend chart and up to four profit figures beside it.
 *
 * WHICH FOUR, AND WHY NOT THE OTHER FOUR
 * --------------------------------------
 * `/kokpit/iata?kind=forecast` carries five metrics. Three of them --
 * `load_factor`, `passenger_demand`, `rpk_growth` -- are already on this page
 * as Market Pulse's DOLULUK cell, the KPI strip's YOLCU card and Market
 * Pulse's TALEP delta respectively, to the decimal. Printing them again here
 * would be four tiles saying what three surfaces above already said.
 *
 * What is left is the two profit lines and their revisions, which appear
 * nowhere else: the levels say where the industry expects to land, the
 * revision tiles say how far IATA has moved since its previous edition, and
 * that movement is the single most decision-relevant thing in the report.
 *
 * A NET MARGIN TILE WAS CONSIDERED AND REJECTED. IATA quotes a 2026 net margin
 * of ~2%, but that is over TOTAL industry revenue including cargo, and the
 * only revenue series this system carries is passenger + ancillary. Dividing
 * net profit by it would produce a number that looks like IATA's and is not.
 *
 * There is no regional selector either. `iata_indicators.region` is NULL on
 * all rows and `curated_seed.py` never sets it, so a GLOBAL/EUROPE/ASIA switch
 * would offer five choices that all return nothing -- which reads as a broken
 * product, not as absent data. The section byline says it in words.
 *
 * TWO SOURCES, TWO UNAVAILABILITY FLAGS. `/kokpit/annual-series` and
 * `/kokpit/iata` fail independently, and each failure arrives here as the same
 * empty prop a genuinely empty database would produce. Without the flags this
 * panel answered an outage with "IATA gelir serisi yüklenmedi" and "Kâr
 * göstergeleri henüz seed edilmedi" -- statements about what has been SEEDED,
 * which a reader can act on and which are simply false when the request never
 * returned. Same shape as `KpiStrip`'s `unavailable` and `SectorBalance`'s
 * `reason`, for the same reason.
 */
export function IataOutlook({
  series,
  /** The annual-series endpoint did not answer, as opposed to answering with
   * an empty series. */
  seriesUnavailable = false,
  indicators,
  /** The indicators endpoint did not answer, as opposed to answering with no
   * profit rows. */
  indicatorsUnavailable = false,
}: {
  series: AnnualSeries[];
  seriesUnavailable?: boolean;
  indicators: IataIndicatorOut[];
  indicatorsUnavailable?: boolean;
}) {
  const byMetric = new Map(indicators.map((row) => [row.metric, row]));
  const levels = METRICS.map((metric) => byMetric.get(metric)).filter(
    (row): row is IataIndicatorOut => row !== undefined,
  );
  const revisions = levels.filter(
    (row) => row.previous_value !== null && row.previous_publication_date !== null,
  );
  const tileCount = levels.length + revisions.length;

  const hasChart = series.length > 0;

  return (
    <div className="grid grid-cols-1 gap-3 xl:grid-cols-12">
      <div className={cn("xl:col-span-8", tileCount === 0 && "xl:col-span-12")}>
        {hasChart ? (
          <div
            style={{ "--glow-color": "var(--chart-2)" } as React.CSSProperties}
            className="rounded-xl border-gradient p-3 shadow-elev-1"
          >
            <AnnualTrendChart series={series} />
          </div>
        ) : seriesUnavailable ? (
          <p className="flex h-[240px] flex-wrap items-center justify-center gap-1.5 rounded-lg border border-dashed border-warning/40 bg-warning/5 p-4 text-center text-xs text-warning">
            <TriangleAlert className="size-4 shrink-0" aria-hidden />
            IATA gelir serisi okunamadı; seri olmadığı anlamına gelmez.
          </p>
        ) : (
          <p className="flex h-[240px] items-center justify-center rounded-lg border border-dashed border-border p-4 text-center text-xs text-muted-foreground">
            IATA gelir serisi yüklenmedi.
          </p>
        )}
      </div>

      {tileCount > 0 && (
        // Two by two rather than a single stack: four tiles stacked ran past
        // the chart's 240px and made the section the tallest thing below the
        // fold for no gain.
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:col-span-4">
          {levels.map((row) => (
            <MetricTile key={row.metric} row={row} />
          ))}
          {revisions.map((row) => (
            <RevisionTile key={`revision-${row.metric}`} row={row} />
          ))}
        </div>
      )}

      {tileCount === 0 &&
        (indicatorsUnavailable ? (
          <p className="flex flex-wrap items-center gap-1.5 rounded-lg border border-dashed border-warning/40 bg-warning/5 px-3 py-2 text-xs text-warning xl:col-span-12">
            <TriangleAlert className="size-3.5 shrink-0" aria-hidden />
            Kâr göstergeleri okunamadı; seed edilmedikleri anlamına gelmez.
          </p>
        ) : (
          <p className="rounded-lg border border-dashed border-border px-3 py-2 text-xs text-muted-foreground xl:col-span-12">
            Kâr göstergeleri henüz seed edilmedi.
          </p>
        ))}
    </div>
  );
}
