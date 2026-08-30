"use client";

import { ArrowDownRight, ArrowUpRight, Fuel, Minus } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useCallback, useState } from "react";

import { DataSourceError } from "@/components/data-source-error";
import { Skeleton } from "@/components/ui/skeleton";
import { useDataSource } from "@/hooks/use-data-source";
import { apiFetch } from "@/lib/api";
import { signalLevelStyle } from "@/lib/cockpit";
import { formatRate, formatSignedPct } from "@/lib/format";
import type { CockpitSignal, KpiDetailOut, KpiOut, KpiPeriod } from "@/lib/types";
import { cn } from "@/lib/utils";

const KpiDetailChart = dynamic(
  () => import("@/components/charts/kpi-detail-chart").then((m) => m.KpiDetailChart),
  { ssr: false, loading: () => <Skeleton className="h-[200px] w-full rounded-lg" /> },
);

const PERIODS: { id: KpiPeriod; label: string }[] = [
  { id: "1m", label: "30 gün" },
  { id: "3m", label: "90 gün" },
];

const chip = (active: boolean) =>
  cn(
    "rounded-full px-2 py-0.5 text-[11px] font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
    active
      ? "bg-primary/12 text-primary ring-1 ring-primary/40"
      : "border border-border text-muted-foreground hover:bg-accent",
  );

function DeltaPill({ deltaPct }: { deltaPct: number | null }) {
  if (deltaPct === null) return null;
  const flat = deltaPct === 0;
  const up = deltaPct > 0;
  const Icon = flat ? Minus : up ? ArrowUpRight : ArrowDownRight;
  return (
    <span
      className={cn(
        "flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[11px] font-semibold tabular-nums",
        // Brent is a cost: up is bad. Same up_is_good semantics the KPI cards
        // use, restated here because this panel does not render a KpiCard.
        flat ? "bg-muted text-muted-foreground" : up ? "bg-critical/10 text-critical" : "bg-good/10 text-good",
      )}
    >
      <Icon className="size-3" aria-hidden />
      {formatSignedPct(deltaPct)}
    </span>
  );
}

/** "Yakıt & Enerji": Brent's real history, and the jet-fuel number derived
 * from it, with the derivation printed rather than implied.
 *
 * Two honesty requirements shape this panel:
 *
 * * Jet fuel is not a quote. It is Brent plus IATA's published crack-spread
 *   assumption, and the caption says exactly that on the same line as the
 *   number -- not in a tooltip, not in a footnote.
 * * The risk chip is NOT recomputed here. It is the same `fuel` signal the
 *   Sinyal Panosu renders, passed in from the same fetch, so the two cannot
 *   band the same Brent price differently.
 */
export function FuelEnergy({
  signal,
  fuelKpi,
}: {
  signal: CockpitSignal | null;
  /** The backend's own derived jet-fuel reading, so the crack spread is never
   * re-added in the browser. */
  fuelKpi: KpiOut | null;
}) {
  const [period, setPeriod] = useState<KpiPeriod>("1m");

  const fetcher = useCallback(
    (abort: AbortSignal) =>
      apiFetch<KpiDetailOut>(`/kpis/oil_price?period=${period}`, {
        cache: "default",
        signal: abort,
      }),
    [period],
  );
  const { data, error, loaded, retry, lastUpdated } = useDataSource(fetcher, [period]);
  const style = signalLevelStyle(signal?.level ?? "unknown");

  return (
    <div className="flex h-full flex-col gap-3 rounded-xl border border-border bg-card bg-card-sheen p-4 shadow-elev-1">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <Fuel className="size-4 text-chart-5" aria-hidden />
        <h3 className="text-sm font-semibold">Brent &amp; Jet Yakıtı</h3>
        {signal && (
          <span
            title={signal.method_tr}
            className={cn(
              "cursor-help rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
              style.pill,
            )}
          >
            Yakıt riski: {signal.level_label_tr}
          </span>
        )}
        <div className="ml-auto flex gap-1">
          {PERIODS.map((entry) => (
            <button
              key={entry.id}
              type="button"
              onClick={() => setPeriod(entry.id)}
              aria-pressed={period === entry.id}
              className={chip(period === entry.id)}
            >
              {entry.label}
            </button>
          ))}
        </div>
      </div>

      {!loaded ? (
        <Skeleton className="h-[240px] w-full rounded-lg" />
      ) : error && !data ? (
        <DataSourceError onRetry={retry} lastUpdated={lastUpdated} />
      ) : !data ? null : (
        <>
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="text-2xl font-semibold tabular-nums dark:text-glow">
              {formatRate(data.value)}
            </span>
            <span className="text-xs text-muted-foreground">{data.unit}</span>
            <DeltaPill deltaPct={data.delta_pct} />
            <Link
              href="/kpi/oil_price"
              className="ml-auto rounded text-[11px] text-muted-foreground underline-offset-2 hover:text-primary hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
            >
              Detay →
            </Link>
          </div>

          {data.history.length > 1 ? (
            <div className="[&_>div]:!h-[200px]">
              <KpiDetailChart history={data.history} period={data.period} unit={data.unit} />
            </div>
          ) : (
            <p className="rounded-lg border border-dashed border-border p-6 text-center text-xs text-muted-foreground">
              Bu dönem için geçmiş veri yok.
            </p>
          )}

          {/* The derived number, with its derivation on the same line. Never a
              jet-fuel index quote -- there is no licensed feed for one here.
              The VALUE is the backend's own fuel_price reading rather than
              `data.value + 57` computed in the browser: the crack spread is a
              constant kpi_service.py owns, and a second copy of it here would
              have been one more place to forget when IATA revises it (which is
              exactly how the history endpoint ended up stuck on a stale
              1.18x multiplier -- fixed in this same change). */}
          {fuelKpi && (
            <p className="rounded-lg bg-muted/50 px-3 py-2 text-[11px] leading-relaxed text-muted-foreground">
              <span className="font-semibold text-foreground">
                Jet yakıtı ≈ {formatRate(fuelKpi.value)} {fuelKpi.unit}
              </span>{" "}
              — tahmini: Brent + 57$ crack varsayımı (IATA Küresel Görünüm, Haziran 2026). Lisanslı
              bir jet yakıtı endeksi kotasyonu değildir.
            </p>
          )}

          <a
            href={data.source_url ?? undefined}
            target="_blank"
            rel="noopener noreferrer"
            className="w-fit rounded text-[11px] text-muted-foreground hover:text-primary hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          >
            {data.source}
            {data.history_is_external && " · geçmiş: Yahoo Finance kapanışları"}
          </a>
        </>
      )}
    </div>
  );
}
