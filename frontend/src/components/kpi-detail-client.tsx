"use client";

import { ArrowDownRight, ArrowUpRight, CircleDashed, Download, ExternalLink, Minus } from "lucide-react";
import { useEffect, useState } from "react";

import { KpiDetailChart } from "@/components/charts/kpi-detail-chart";
import { Badge } from "@/components/ui/badge";
import { API_BASE_URL, apiFetch } from "@/lib/api";
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

export function KpiDetailClient({ metricKey }: { metricKey: string }) {
  const [period, setPeriod] = useState<KpiPeriod>("1m");
  const [detail, setDetail] = useState<KpiDetailOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- data fetch driven by metricKey/period; loading must flip synchronously with the dependency change
    setLoading(true);
    apiFetch<KpiDetailOut>(`/kpis/${metricKey}?period=${period}`)
      .then((data) => {
        if (!cancelled) {
          setDetail(data);
          setError(null);
        }
      })
      .catch(() => {
        if (!cancelled) setError("Bu KPI yüklenemedi. Sunucu çalışıyor mu?");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [metricKey, period]);

  if (error) {
    return (
      <p className="rounded-lg border border-dashed border-border p-6 text-sm text-muted-foreground">
        {error}
      </p>
    );
  }

  if (!detail && loading) {
    return <p className="text-sm text-muted-foreground">Yükleniyor…</p>;
  }

  if (!detail) return null;

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
  const historyNewestFirst = [...detail.history].sort(
    (a, b) => new Date(b.as_of).getTime() - new Date(a.as_of).getTime(),
  );

  return (
    <div className="flex flex-col gap-6">
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

        {detail.history.length > 1 ? (
          <KpiDetailChart
            history={detail.history}
            period={detail.period}
            unit={detail.unit}
            metricKey={detail.metric_key}
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
            derivation is known. */}
        <p className="text-xs text-muted-foreground">{detail.history_provenance_tr}</p>
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

        {historyNewestFirst.length > 0 ? (
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
