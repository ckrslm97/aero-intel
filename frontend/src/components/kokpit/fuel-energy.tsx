"use client";

import { ArrowDownRight, ArrowUpRight, Fuel, Info, Minus } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useCallback, useState } from "react";

import { DataSourceError } from "@/components/data-source-error";
import { MotionItem, MotionList } from "@/components/motion/motion-list";
import { Skeleton } from "@/components/ui/skeleton";
import { useDataSource } from "@/hooks/use-data-source";
import { apiFetch } from "@/lib/api";
import { signalLevelStyle } from "@/lib/cockpit";
import { formatRate, formatSignedPct } from "@/lib/format";
import type {
  CockpitSignal,
  EnergyBoardOut,
  EnergyMetricOut,
  KpiDetailOut,
  KpiPeriod,
} from "@/lib/types";
import { cn } from "@/lib/utils";

const KpiDetailChart = dynamic(
  () => import("@/components/charts/kpi-detail-chart").then((m) => m.KpiDetailChart),
  { ssr: false, loading: () => <Skeleton className="h-[180px] w-full rounded-lg" /> },
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

/** A percent change, or an em dash. Never a zero standing in for "unknown". */
function Change({ value }: { value: number | null }) {
  if (value === null) {
    return (
      <span className="text-muted-foreground/60" title="Bu pencere için yeterli geçmiş yok">
        —
      </span>
    );
  }
  return (
    <span
      className={cn(
        "font-semibold tabular-nums",
        value === 0 ? "text-muted-foreground" : value > 0 ? "text-critical" : "text-good",
      )}
    >
      {formatSignedPct(value)}
    </span>
  );
}

/** One row of the indicator grid: the contract, its price, and the five
 * figures that ARE derivable from its own closes. */
function EnergyRow({ metric }: { metric: EnergyMetricOut }) {
  return (
    <MotionItem
      variant="scalePop"
      style={{ "--glow-color": "var(--chart-5)" } as React.CSSProperties}
      className="grid grid-cols-[minmax(6.5rem,1.2fr)_repeat(5,minmax(2.6rem,1fr))] items-baseline gap-x-2 gap-y-0.5 rounded-lg px-2 py-1.5 text-[11px] transition-colors hover:bg-accent/40"
    >
      <Link
        href={metric.href}
        title={metric.note_tr ?? metric.source}
        className="flex min-w-0 flex-col rounded focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
      >
        <span className="truncate font-medium">{metric.label_tr}</span>
        <span className="flex items-baseline gap-1">
          <span className="font-semibold tabular-nums dark:text-glow">
            {metric.value === null ? "—" : formatRate(metric.value)}
          </span>
          <span className="text-[9px] text-muted-foreground">{metric.unit}</span>
        </span>
      </Link>
      <span className="text-right">
        <Change value={metric.week_change_pct} />
      </span>
      <span className="text-right">
        <Change value={metric.month_change_pct} />
      </span>
      <span className="text-right">
        <Change value={metric.ytd_change_pct} />
      </span>
      <span className="text-right tabular-nums">
        {metric.percentile_1y === null ? (
          <span className="text-muted-foreground/60">—</span>
        ) : (
          // Neutral: a high percentile is a high cost base, but the fuel
          // SIGNAL tile is what bands that -- colouring it here would be a
          // second, unstated threshold.
          <span className="font-semibold">%{metric.percentile_1y.toFixed(0)}</span>
        )}
      </span>
      <span className="text-right tabular-nums">
        {metric.volatility_30d_pct === null ? (
          <span className="text-muted-foreground/60">—</span>
        ) : (
          <span className="font-semibold">%{metric.volatility_30d_pct.toFixed(0)}</span>
        )}
      </span>
    </MotionItem>
  );
}

function IndicatorGrid({ board }: { board: EnergyBoardOut }) {
  return (
    <div className="flex flex-col gap-1">
      <div className="grid grid-cols-[minmax(6.5rem,1.2fr)_repeat(5,minmax(2.6rem,1fr))] gap-x-2 px-2 text-[9px] font-semibold uppercase tracking-wider text-muted-foreground">
        <span>Kontrat</span>
        <span className="text-right">1 hf</span>
        <span className="text-right">1 ay</span>
        <span className="text-right">YBB</span>
        <span
          className="cursor-help text-right"
          title={board.percentile_method_tr}
        >
          1y dilim
        </span>
        <span
          className="cursor-help text-right"
          title={board.volatility_method_tr}
        >
          30g vol
        </span>
      </div>
      <MotionList className="flex flex-col">
        {board.metrics.map((metric) => (
          <EnergyRow key={metric.metric_key} metric={metric} />
        ))}
      </MotionList>
      <p className="flex items-start gap-1 px-2 text-[10px] leading-relaxed text-muted-foreground">
        <Info className="mt-px size-3 shrink-0" aria-hidden />
        <span>
          YBB = yılbaşından bugüne. Her yüzde, o kontratın kendi günlük kapanışları üzerinden
          hesaplanır; bir pencereyi taşıyacak veri yoksa “—” yazar, sıfır yazmaz. Arz, rafineri
          kapasitesi veya jeopolitik risk gibi bir “risk matrisi” burada yoktur — bu sistem fiyat
          serisi toplar, arz dengesi toplamaz.
        </span>
      </p>
    </div>
  );
}

/** "Yakıt & Enerji": Brent's real history, the jet-fuel number derived from
 * it, and the two other energy contracts this system now records -- each with
 * the indicators its own series actually supports.
 *
 * Three honesty requirements shape this panel:
 *
 * * Jet fuel is not a quote. It is Brent plus IATA's published crack-spread
 *   assumption, and the caption says exactly that on the same line as the
 *   number. Its PERCENTAGES are computed over the derived series, not copied
 *   from Brent's -- adding a constant does not preserve percent changes.
 * * The risk chip is NOT recomputed here. It is the same `fuel` signal the
 *   Sinyal Panosu renders, passed in from the same fetch, so the two cannot
 *   band the same Brent price differently.
 * * There is no supply/geopolitical risk matrix. Every row of one would have
 *   been invented; see the note the grid prints for itself.
 */
export function FuelEnergy({ signal }: { signal: CockpitSignal | null }) {
  const [period, setPeriod] = useState<KpiPeriod>("1m");

  const brentFetcher = useCallback(
    (abort: AbortSignal) =>
      apiFetch<KpiDetailOut>(`/kpis/oil_price?period=${period}`, {
        cache: "default",
        signal: abort,
      }),
    [period],
  );
  const { data, error, loaded, retry, lastUpdated } = useDataSource(brentFetcher, [period]);

  const energyFetcher = useCallback(
    (abort: AbortSignal) =>
      apiFetch<EnergyBoardOut>("/kokpit/energy", { cache: "default", signal: abort }),
    [],
  );
  const energy = useDataSource(energyFetcher, []);

  const style = signalLevelStyle(signal?.level ?? "unknown");

  return (
    <div className="flex h-full flex-col gap-3 rounded-xl border border-border bg-card bg-card-sheen p-4 shadow-elev-1">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <Fuel className="size-4 text-chart-5" aria-hidden />
        <h3 className="text-sm font-semibold">Enerji Kontratları</h3>
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
        <Skeleton className="h-[220px] w-full rounded-lg" />
      ) : error && !data ? (
        <DataSourceError onRetry={retry} lastUpdated={lastUpdated} />
      ) : !data ? null : (
        <>
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Brent
            </span>
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
            <div className="[&_>div]:!h-[180px]">
              <KpiDetailChart history={data.history} period={data.period} unit={data.unit} />
            </div>
          ) : (
            <p className="rounded-lg border border-dashed border-border p-6 text-center text-xs text-muted-foreground">
              Bu dönem için geçmiş veri yok.
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

      {/* The dense half: the four contracts and everything their own series
          supports. Fills what used to be empty space under the chart with
          real, re-runnable arithmetic instead of an invented risk matrix. */}
      <div className="mt-auto border-t border-border pt-2">
        {!energy.loaded ? (
          <Skeleton className="h-24 w-full rounded-lg" />
        ) : energy.error && !energy.data ? (
          <DataSourceError onRetry={energy.retry} lastUpdated={energy.lastUpdated} />
        ) : energy.data ? (
          <IndicatorGrid board={energy.data} />
        ) : null}
      </div>
    </div>
  );
}
