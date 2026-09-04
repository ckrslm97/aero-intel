"use client";

import { Activity } from "lucide-react";
import { useCallback, useMemo } from "react";

import { DataSourceError, LastUpdatedStamp, StaleDataBanner } from "@/components/data-source-error";
import { MotionItem, MotionList } from "@/components/motion/motion-list";
import { SignalCard } from "@/components/sinyaller/signal-card";
import { Skeleton } from "@/components/ui/skeleton";
import { useDataSource } from "@/hooks/use-data-source";
import { useUrlState } from "@/hooks/use-url-state";
import { apiFetch } from "@/lib/api";
import {
  countBy,
  filterSignals,
  KIND_ORDER,
  parseSignalFilters,
  SEVERITY_ORDER,
  severityStyle,
  signalFiltersToSearchParams,
  type SignalFilters,
} from "@/lib/signals";
import type { SignalKind, SignalSeverity, SignalsOut } from "@/lib/types";
import { cn } from "@/lib/utils";

/** "SİNYALLER" -- the early-warning centre.
 *
 * One list, two filter axes, no grouping. Grouping by stream was the obvious
 * alternative and was dropped: a reader opens this page to find out what needs
 * a reaction, and seven headed blocks would make them scan all seven to answer
 * a question the severity sort answers in one glance. The stream a row came
 * from is still on the card (its type label and its source line), and the
 * per-stream tally under the header says what each one contributed -- including
 * the ones that contributed nothing.
 *
 * The composition, the severity mapping and the sort all live server-side (see
 * backend/app/services/signals_service.py). This component filters and draws;
 * it does not re-rank, because a second ordering would be a second chance to
 * disagree with the one the API published.
 */
export function SignalsClient() {
  const fetcher = useCallback(
    (signal: AbortSignal) =>
      apiFetch<SignalsOut>("/signals", { cache: "default", signal }),
    [],
  );
  const { data, error, loaded, lastUpdated, pending, stale, retry } = useDataSource(fetcher, []);

  // Both chips are URL-owned. This page's whole output is "look at this" --
  // a severity chip that evaporates on reload cannot be sent to the person who
  // has to act on it. Same parse/serialise shape as Kampanyalar.
  const { params, replaceParams } = useUrlState();
  const filters = useMemo(() => parseSignalFilters(params), [params]);
  const setFilters = useCallback(
    (next: SignalFilters) => {
      replaceParams(signalFiltersToSearchParams(next, params));
    },
    [params, replaceParams],
  );

  const signals = useMemo(() => data?.signals ?? [], [data]);
  const visible = useMemo(() => filterSignals(signals, filters), [signals, filters]);
  const kindCounts = useMemo(() => countBy(signals, "kind", filters), [signals, filters]);
  const severityCounts = useMemo(
    () => countBy(signals, "severity", filters),
    [signals, filters],
  );

  if (!loaded) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-20 w-full rounded-xl" />
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {Array.from({ length: 6 }).map((_, index) => (
            <Skeleton key={index} className="h-36 w-full rounded-xl" />
          ))}
        </div>
      </div>
    );
  }

  if (error && !data) {
    return <DataSourceError onRetry={retry} lastUpdated={lastUpdated} pending={pending} />;
  }
  if (!data) return null;

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-1">
        <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
          <Activity className="size-6 text-signal" aria-hidden />
          Sinyaller
        </h1>
        <p className="text-sm text-muted-foreground">
          Erken uyarı merkezi: Kokpit sinyal panosu, kampanya uyarıları, Risk Radarı,
          rakip ve stratejik olaylar, ağ sinyalleri ve haber momentumu tek listede —
          şiddete, sonra tazeliğe göre sıralı.
        </p>
        <p className="text-[11px] leading-relaxed text-muted-foreground">
          Bu sayfa hiçbir şey tespit etmez; var olan akışları tek biçimde gösterir. Her
          kartın şiddeti, o sinyali üreten akışın kendi bandıdır — kartın “şiddet
          gerekçesi” notu hangisi olduğunu söyler. Ücret değişimi ya da faiz gibi
          akışlar burada yoktur, çünkü bu sistemde o veriler yok.
        </p>
      </header>

      {stale && <StaleDataBanner onRetry={retry} lastUpdated={lastUpdated} pending={pending} />}

      {/* Stream tally. Every contributing stream is listed whether or not it
          produced anything -- the same structural no-filler rule the Biz
          sections use.

          THE EMPTY STATE IS ON SCREEN, NOT IN A TOOLTIP. This block used to
          claim in a comment that a reader could tell "nothing happened" from
          "it broke", and then draw the quiet streams as a dim `0`: the only
          thing separating that from any other zero was a `title` attribute,
          which a skimming reader never opens and a touch reader cannot reach.
          So a stream that measured nothing now says "sinyal yok" in words.

          It says "sinyal yok" and NOT "okunamadı" because that is what the
          field means: `available` is the server's `bool(count)` -- whether the
          stream produced rows -- not whether it could be read
          (backend/app/services/signals_service.py:506, pinned by
          test_every_stream_is_listed_even_when_it_produced_nothing). A stream
          cannot fail on its own here: `unified_signals` composes all seven in
          one request, so an unreadable stream is an unreadable RESPONSE, and
          that is the DataSourceError / StaleDataBanner branch above -- where
          it can be said once, about the whole band, truthfully. Printing
          "okunamadı" on a chip that means "zero" would be this round's own
          sin, mirrored: an outage invented out of a measurement. */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 rounded-xl border border-border bg-card p-3 text-[11px]">
        {/* The window belongs to the streams it governs, not to the tally.
            `days` is the news lookback for the EVENT-derived streams only --
            the risk rollup keeps its own 14-day window and the campaign alert
            inbox has none at all (backend/app/api/v1/signals.py). "N sinyal ·
            30 gün" read as one window over all seven and was never true. */}
        <span className="font-semibold uppercase tracking-wider text-muted-foreground">
          {data.total} sinyal · olay akışları {data.days} gün
        </span>
        {data.streams.map((stream) => (
          <span
            key={stream.key}
            className={cn(
              "flex items-center gap-1 tabular-nums",
              stream.available ? "text-foreground" : "text-muted-foreground",
            )}
          >
            {stream.label_tr}
            {stream.available ? (
              <span className="font-semibold">{stream.count}</span>
            ) : (
              <span
                title={stream.empty_message ?? undefined}
                className="rounded-full border border-dashed border-border px-1.5 font-medium"
              >
                sinyal yok
              </span>
            )}
          </span>
        ))}
      </div>

      {/* The risk half of that tally can be a floor: /risks caps how many
          articles one rollup clusters, and when the cap bites the risk stream
          counted only the newest slice of its window. The flag rides on this
          same response (SignalsOut.risk_truncated) precisely so this page does
          not have to call /risks to find out. Printed only when it bit. */}
      {data.risk_truncated && (
        <p className="text-[11px] text-muted-foreground">
          {data.risk_scanned_articles > 0
            ? `Risk taraması pencerenin en yeni ${data.risk_scanned_articles.toLocaleString(
                "tr-TR",
              )} haberinde durdu; Risk Radarı sayıları taban değerdir — hepsi bu kadar değil.`
            : "Risk taraması pencerenin tamamına ulaşamadı; Risk Radarı sayıları taban değerdir — hepsi bu kadar değil."}
        </p>
      )}

      <div className="flex flex-col gap-2">
        <ChipRow
          label="Tür"
          values={KIND_ORDER}
          labels={Object.fromEntries(
            signals.map((signal) => [signal.kind, signal.kind_label_tr]),
          )}
          counts={kindCounts}
          active={filters.kind}
          onChange={(kind) => setFilters({ ...filters, kind: kind as SignalKind | null })}
        />
        <ChipRow
          label="Şiddet"
          values={SEVERITY_ORDER}
          labels={Object.fromEntries(
            signals.map((signal) => [signal.severity, signal.severity_label_tr]),
          )}
          counts={severityCounts}
          active={filters.severity}
          onChange={(severity) =>
            setFilters({ ...filters, severity: severity as SignalSeverity | null })
          }
          dotFor={(value) => severityStyle(value).dot}
        />
      </div>

      {visible.length === 0 ? (
        <p className="rounded-xl border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
          {signals.length === 0
            ? "Şu anda hiçbir akışta sinyal yok."
            : "Bu filtreyle sinyal yok. Başka bir tür ya da şiddet deneyin."}
        </p>
      ) : (
        <MotionList className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {visible.map((signal) => (
            <MotionItem key={signal.id} variant="scalePop" className="h-full">
              <SignalCard signal={signal} />
            </MotionItem>
          ))}
        </MotionList>
      )}

      <LastUpdatedStamp date={lastUpdated} />
    </div>
  );
}

/** One filter axis. "Hepsi" plus every value the feed actually contains --
 * a chip for a value with no rows behind it is a control that can only ever
 * empty the page. */
function ChipRow({
  label,
  values,
  labels,
  counts,
  active,
  onChange,
  dotFor,
}: {
  label: string;
  values: readonly string[];
  labels: Record<string, string>;
  counts: Record<string, number>;
  active: string | null;
  onChange: (value: string | null) => void;
  dotFor?: (value: string) => string;
}) {
  const present = values.filter((value) => counts[value] || value === active);
  if (present.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      <Chip active={active === null} onClick={() => onChange(null)}>
        Hepsi
      </Chip>
      {present.map((value) => (
        <Chip
          key={value}
          active={active === value}
          onClick={() => onChange(active === value ? null : value)}
          // The label and the count are adjacent spans, so the derived
          // accessible name would run them together ("Rakip1").
          ariaLabel={`${labels[value] ?? value}, ${counts[value] ?? 0} sinyal`}
        >
          {dotFor && (
            <span aria-hidden className={cn("size-1.5 rounded-full", dotFor(value))} />
          )}
          {labels[value] ?? value}
          <span className="tabular-nums opacity-70">{counts[value] ?? 0}</span>
        </Chip>
      ))}
    </div>
  );
}

function Chip({
  active,
  onClick,
  ariaLabel,
  children,
}: {
  active: boolean;
  onClick: () => void;
  ariaLabel?: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      aria-label={ariaLabel}
      className={cn(
        "flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
        active
          ? "bg-primary text-primary-foreground"
          : "border border-border text-muted-foreground hover:bg-accent",
      )}
    >
      {children}
    </button>
  );
}
