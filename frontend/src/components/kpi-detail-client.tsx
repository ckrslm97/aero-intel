"use client";

import { ArrowDownRight, ArrowUpRight, CircleDashed, Download, ExternalLink, Minus } from "lucide-react";
import { useCallback, useState } from "react";

import { KpiDetailChart } from "@/components/charts/kpi-detail-chart";
import {
  DataSourceError,
  InlineSourceError,
  StaleDataBanner,
} from "@/components/data-source-error";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useDataSource } from "@/hooks/use-data-source";
import { API_BASE_URL, ApiError, apiFetch } from "@/lib/api";
import {
  DISPLAY_TIME_ZONE_TR,
  formatMetricValue,
  formatShortDateTr,
  formatStampTr,
  kpiDeltaLabel,
} from "@/lib/format";
import { KPI_ICONS } from "@/lib/kpi-icons";
import type { KpiDetailOut, KpiPeriod } from "@/lib/types";
import { cn } from "@/lib/utils";

const PERIODS: { value: KpiPeriod; label: string }[] = [
  { value: "1w", label: "1W" },
  { value: "1m", label: "1M" },
  { value: "3m", label: "3M" },
  { value: "6m", label: "6M" },
  { value: "1y", label: "12M" },
];

/** What one request to `/kpis/{key}` can settle into.
 *
 * A 404 IS AN ANSWER, NOT A FAILURE. The endpoint raises it for a metric this
 * system does not track ("Unknown KPI") and for one with no observations
 * recorded yet -- both in `get_kpi_detail`, backend/app/api/v1/kpis.py, cited
 * by name rather than by line so the reference cannot drift off the raises it
 * describes. Both are statements about what has been measured, and neither is
 * a reason to tell the reader the server might be down. It is caught in the fetcher and carried through as data so the
 * error branch below is left holding only real transport failures. */
type KpiDetailResult =
  | { detail: KpiDetailOut; missing: false }
  | { detail: null; missing: true };

export function KpiDetailClient({ metricKey }: { metricKey: string }) {
  const [period, setPeriod] = useState<KpiPeriod>("1m");

  const fetcher = useCallback(
    async (signal: AbortSignal): Promise<KpiDetailResult> => {
      try {
        return {
          detail: await apiFetch<KpiDetailOut>(`/kpis/${metricKey}?period=${period}`, {
            signal,
          }),
          missing: false,
        };
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) {
          return { detail: null, missing: true };
        }
        throw error;
      }
    },
    [metricKey, period],
  );
  const source = useDataSource(fetcher, [metricKey, period]);
  const result = source.data;
  const fresh = result?.detail ?? null;

  /** The last payload read successfully FOR THIS METRIC, whatever period it
   * carried.
   *
   * ONLY THE PERIOD-INDEPENDENT HALF IS EVER DRAWN FROM IT. The endpoint's
   * `period` argument selects `history` and nothing else -- the value, the
   * delta, the timestamp, the source and the corroborations are the metric's
   * latest reading either way (see get_kpi_detail). So a failed 12M click has
   * no business demolishing a loaded page: the figures at the top were read
   * and are still true, and only the trend and the table are about the window
   * that failed. This page used to fall to one grey paragraph, with no retry,
   * on exactly that click.
   *
   * Adjusted during render rather than in an effect -- React's own documented
   * "store a previous value" pattern, the same one SearchClient uses for its
   * input box. An effect would paint one frame of the collapsed page first,
   * which is the frame this exists to prevent. */
  const [kept, setKept] = useState<{ key: string; detail: KpiDetailOut } | null>(null);
  if (fresh && kept?.detail !== fresh) setKept({ key: metricKey, detail: fresh });

  const detail = fresh ?? (kept?.key === metricKey ? kept.detail : null);
  /** The trend and the data table belong to the SELECTED PERIOD, so they read
   * `fresh` and never `kept`: a 12M heading over 1M points would be the exact
   * mislabelling the fx forecast chart was fixed for. */
  const historyFailed = source.error !== null && fresh === null && !result?.missing;
  const historyPending = source.pending && fresh === null;

  // A metric with nothing recorded, said as the measurement it is. There is no
  // retry here on purpose: asking again cannot make an unrecorded observation
  // exist, and a retry button would suggest it might.
  if (result?.missing) {
    return (
      <div className="flex flex-col gap-2 rounded-lg border border-dashed border-border p-6">
        <p className="text-sm font-medium text-foreground">Bu metrik için ölçüm yok</p>
        <p className="text-sm text-muted-foreground">
          <span className="font-mono">{metricKey}</span> için bu sistemde kayıtlı bir
          gözlem bulunmuyor — adres izlenmeyen bir metriği gösteriyor ya da bu metriğin
          ilk ölçümü henüz alınmadı.
        </p>
      </div>
    );
  }

  if (!detail) {
    // The two remaining branches, which used to be one grey sentence apiece:
    // nothing read yet and on its way, versus a source that answered with a
    // failure and can be asked again.
    return source.error ? (
      <DataSourceError
        onRetry={source.retry}
        lastUpdated={source.lastUpdated}
        pending={source.pending}
      />
    ) : (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-24 w-full rounded-xl" />
        <Skeleton className="h-40 w-full rounded-xl" />
        <Skeleton className="h-56 w-full rounded-xl" />
      </div>
    );
  }

  // Exactly one of the two is a number -- points for a metric already
  // denominated in points, percent for everything else. See KpiOut in
  // lib/types.ts on why the payload never offers both.
  const delta = detail.delta_pct ?? detail.delta_points;
  // `kpiDeltaLabel`, which folds "pick the non-null one" and "draw it the way
  // every other delta in this app is drawn" (ui/delta.tsx) into the single
  // helper KpiOut's contract note points at. This page had its own
  // `formatDelta` printing "+4.2%" -- an English decimal point, and the
  // percent sign on the wrong side of the number -- for the same move Kokpit's
  // KUR cell printed as "+%4,2".
  const deltaLabel = kpiDeltaLabel(detail.delta_pct, detail.delta_points);
  const isFlat = (delta ?? 0) === 0;
  const isPositive = (delta ?? 0) >= 0;
  const isGoodDirection = isPositive === detail.up_is_good;
  const deltaColor = isFlat ? "text-muted-foreground" : isGoodDirection ? "text-good" : "text-critical";
  const Icon = KPI_ICONS[detail.metric_key] ?? CircleDashed;
  // `fresh`, not `detail`: the table lists the SELECTED period's observations,
  // and the kept payload's rows belong to whichever period was last read.
  const historyNewestFirst = [...(fresh?.history ?? [])].sort(
    (a, b) => new Date(b.as_of).getTime() - new Date(a.as_of).getTime(),
  );

  return (
    <div className="flex flex-col gap-6">
      {/* The demotion the whole rewrite is for: a failed refresh is a banner
          over a page that still stands, not a replacement for it. `lastUpdated`
          is this metric's own last successful read -- never another metric's,
          because `useDataSource` tags every settled record with the selection
          that produced it. */}
      {(source.stale || historyFailed) && (
        <StaleDataBanner
          onRetry={source.retry}
          lastUpdated={source.lastUpdated}
          pending={source.pending}
        />
      )}

      <div className="flex flex-col gap-1">
        <div className="flex items-center gap-2">
          <span className="flex size-11 shrink-0 items-center justify-center rounded-md bg-accent text-accent-foreground">
            <Icon className="size-6" />
          </span>
          <h1 className="text-2xl font-semibold tracking-tight">{detail.label}</h1>
          {detail.is_estimate && (
            <span
              title="Lisanslı veri kaynağı henüz bağlanmadı -- tahmini değer"
              className="rounded-full bg-secondary px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-secondary-foreground"
            >
              tahmini
            </span>
          )}
        </div>
        <p className="text-sm text-muted-foreground">
          Kaynak:{" "}
          {detail.source_url ? (
            <a
              href={detail.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 font-medium text-primary hover:underline"
            >
              {detail.source}
              <ExternalLink className="size-3" />
            </a>
          ) : (
            <span className="font-medium">{detail.source}</span>
          )}
        </p>
      </div>

      <div className="flex flex-wrap items-end justify-between gap-6 rounded-xl border border-border bg-card p-5">
        <div className="flex flex-col gap-1">
          <div className="flex items-baseline gap-1.5">
            {/* The page's own precision rule used to be compact notation,
                which quotes a currency cross to one decimal: /kpi/fx_eur_usd
                printed "1,1" for the reading Kokpit prints as "1,0850". The
                rule now lives in lib/format.ts and every surface reads it. */}
            <span className="text-4xl font-semibold tracking-tight">
              {formatMetricValue(detail.value, detail.unit, detail.metric_key)}
            </span>
            {detail.unit && <span className="text-base text-muted-foreground">{detail.unit}</span>}
          </div>
          {/* What period the number describes. A 2026 full-year FORECAST drawn
              with nothing but a value and a timestamp reads as a measurement
              taken at that timestamp, which is what this page did to
              /kpi/load_factor. */}
          {detail.period_label && (
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              {detail.period_label}
            </p>
          )}
          {deltaLabel !== null && (
            <div className="flex items-center gap-1 text-sm">
              {isFlat ? (
                <Minus className="size-4 text-muted-foreground" />
              ) : isPositive ? (
                <ArrowUpRight className={cn("size-4", deltaColor)} />
              ) : (
                <ArrowDownRight className={cn("size-4", deltaColor)} />
              )}
              <span className={cn("font-medium", deltaColor)}>{deltaLabel}</span>
              {/* Server-sent: this used to be a hardcoded "önceki ölçüme göre"
                  printed over year-on-year comparisons too. */}
              {detail.comparison_label && (
                <span className="text-muted-foreground">{detail.comparison_label}</span>
              )}
            </div>
          )}
          {/* The zone is PINNED and then stated. Formatted with no `timeZone`,
              this stamp read three hours apart from the same reading on
              /gazete, because one surface was rendered on a UTC node and the
              other in the reader's browser -- and "itibarıyla" over a time
              whose clock is unnamed is a measurement a reader cannot place. */}
          <p className="text-xs text-muted-foreground">
            {formatStampTr(detail.as_of) ?? "Tarih bilinmiyor"} {DISPLAY_TIME_ZONE_TR} itibarıyla
          </p>
        </div>

        {detail.corroborations.length > 0 && (
          <div className="flex flex-col gap-1.5 text-sm">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Çapraz doğrulama kaynakları ({DISPLAY_TIME_ZONE_TR})
            </p>
            {detail.corroborations.map((c) => (
              <div key={c.source} className="flex items-center gap-2">
                {/* The verdict is the backend's, not this component's. The
                    0.5% rule used to live here as a bare comparison, which put
                    the one claim this block makes in the layer that draws it
                    -- and left `diff_pct: null` (a comparison that could not be
                    made at all) reading as the strongest possible agreement. */}
                <Badge
                  variant="outline"
                  className="text-[10px]"
                  title={
                    c.incomparable_reason === "as_of_too_far_apart"
                      ? "İki ölçümün zamanı birbirinden çok uzak -- karşılaştırma yapılmadı."
                      : undefined
                  }
                >
                  {c.diff_pct !== null && c.verdict === "diverges"
                    ? `Δ %${c.diff_pct.toFixed(2)}`
                    : c.verdict_label_tr}
                </Badge>
                {c.source_url ? (
                  <a
                    href={c.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-primary hover:underline"
                  >
                    {c.source}
                  </a>
                ) : (
                  <span>{c.source}</span>
                )}
                <span className="text-muted-foreground">
                  {formatMetricValue(c.value, detail.unit, detail.metric_key)} {detail.unit}
                </span>
                {/* The second reading's own timestamp. Without it a refused
                    comparison ("Karşılaştırılamaz") is unanswerable. */}
                <span className="text-xs text-muted-foreground">
                  {formatShortDateTr(c.as_of) ?? "—"}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="flex flex-col gap-3 rounded-xl border border-border bg-card p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Trend
          </h2>
          {/* Period labels (1W/1M/3M/6M/12M) are left as international finance
              abbreviations -- they're standard in Turkish business dashboards too. */}
          <div className="flex gap-1 rounded-lg border border-border p-0.5">
            {PERIODS.map((p) => (
              <button
                key={p.value}
                onClick={() => setPeriod(p.value)}
                className={cn(
                  "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                  period === p.value
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
                )}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>

        {/* Three branches, and only the last of them is allowed to say the
            archive is thin: "henüz yeterli geçmiş veri kaydedilmedi" is a
            claim about the database, and it used to be the sentence a reader
            got when the request for this window never came back. */}
        {historyPending ? (
          <Skeleton className="h-56 w-full rounded-lg" />
        ) : historyFailed ? (
          <InlineSourceError
            message="Bu dönemin geçmişi okunamadı; kayıtlı veri olmadığı anlamına gelmez."
            onRetry={source.retry}
            pending={source.pending}
          />
        ) : fresh && fresh.history.length > 1 ? (
          <KpiDetailChart
            history={fresh.history}
            period={fresh.period}
            unit={fresh.unit}
            metricKey={fresh.metric_key}
          />
        ) : (
          <p className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
            Bu dönem için henüz yeterli geçmiş veri kaydedilmedi.
          </p>
        )}

        {/* Three provenances, not two: jet fuel's chart is Brent's real closes
            plus a stated crack spread, and the boolean above could only call
            that "the source's own archive" -- asserting a published jet-fuel
            history that exists nowhere. The sentence is written where the
            derivation is known. It describes the series drawn above it, so it
            appears only when one was. */}
        {fresh && (
          <p className="text-xs text-muted-foreground">{fresh.history_provenance_tr}</p>
        )}
      </div>

      <div className="flex flex-col gap-3 rounded-xl border border-border bg-card p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Veri Tablosu
          </h2>
          <a
            href={`${API_BASE_URL}/kpis/${metricKey}/observations.csv`}
            className="flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-foreground hover:bg-accent"
          >
            <Download className="size-3.5" />
            CSV İndir
          </a>
        </div>

        {historyPending ? (
          <Skeleton className="h-40 w-full rounded-lg" />
        ) : historyFailed ? (
          <InlineSourceError
            message="Bu dönemin gözlem tablosu okunamadı."
            onRetry={source.retry}
            pending={source.pending}
          />
        ) : historyNewestFirst.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  {/* One zone, named once, for the whole column. */}
                  <th className="px-2 py-2 font-semibold">Tarih ({DISPLAY_TIME_ZONE_TR})</th>
                  <th className="px-2 py-2 font-semibold">Değer</th>
                  <th className="px-2 py-2 font-semibold">Kaynak</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {historyNewestFirst.map((point) => (
                  <tr key={point.as_of}>
                    <td className="px-2 py-2 text-muted-foreground">
                      {formatStampTr(point.as_of) ?? "—"}
                    </td>
                    <td className="px-2 py-2 font-medium">
                      {formatMetricValue(point.value, detail.unit, detail.metric_key)}
                      {detail.unit && (
                        <span className="ml-1 font-normal text-muted-foreground">
                          {detail.unit}
                        </span>
                      )}
                    </td>
                    <td className="px-2 py-2">
                      {detail.source_url ? (
                        <a
                          href={detail.source_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 text-primary hover:underline"
                        >
                          {detail.source}
                          <ExternalLink className="size-3" />
                        </a>
                      ) : (
                        <span className="text-muted-foreground">{detail.source}</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
            Bu dönem için henüz kayıtlı gözlem yok.
          </p>
        )}
      </div>
    </div>
  );
}
