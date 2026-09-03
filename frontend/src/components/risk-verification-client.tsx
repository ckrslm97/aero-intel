"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useCallback, useMemo, useState } from "react";

import { DataSourceError, LastUpdatedStamp, StaleDataBanner } from "@/components/data-source-error";
import { RiskFunnel } from "@/components/risk/risk-funnel";
import { RiskRejectionsTable } from "@/components/risk/risk-rejections-table";
import { Skeleton } from "@/components/ui/skeleton";
import { useDataSource } from "@/hooks/use-data-source";
import { apiFetch } from "@/lib/api";
import { rejectionFilterOptions } from "@/lib/risk";
import type { RiskQualityOut, RiskRejection } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Mirrors DAY_WINDOWS in risk-radar-client.tsx and DEFAULT_WINDOW_DAYS in
 * backend/app/api/v1/risks.py. The funnel has to be readable against the same
 * window the radar is showing, or the two pages describe different days and
 * neither reconciles. */
const DAY_WINDOWS = [5, 7, 14, 30, 90] as const;
const DEFAULT_DAYS = 5;

/** How many rejected rows to fetch. The API caps at 200 per reason; this is
 * the screen's own working size -- enough to scan a window's rejections, small
 * enough that the table stays a table. */
const ROW_LIMIT = 100;

const chip = (active: boolean) =>
  cn(
    "flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
    active
      ? "bg-primary/12 text-primary ring-1 ring-primary/40 dark:glow-soft"
      : "border border-border text-muted-foreground hover:bg-accent",
  );

/** Risk Radarı → Veri doğrulama.
 *
 * ITS OWN ROUTE, deliberately, rather than a panel on the radar. The radar's
 * job is "what is happening now" and it is read by someone deciding something;
 * this page's job is "do I believe the radar", and it is read by someone
 * debugging it. Folding a nine-stage funnel and an eight-column rejection
 * table into the operational page would cost every reader attention to serve
 * the few who came to audit -- and the audit view needs the whole width.
 *
 * Two sources, two failures. The funnel and the rejection list are separate
 * fetches so one failing thins the page by a section rather than blanking it
 * (Faz 12's per-source contract), and because the rejection list re-fetches on
 * every filter change while the funnel does not.
 *
 * NOTHING HERE IS A CONTROL. Every endpoint behind this screen is a GET; there
 * is no "mark this rejection as wrong" button and adding one would be a write
 * on a surface pinned as read-only (backend test_faz7_surface_stays_read_only).
 * The output of this page is a code change, not a database edit.
 */
export function RiskVerificationClient() {
  const [days, setDays] = useState<number>(DEFAULT_DAYS);
  const [reason, setReason] = useState<string | null>(null);

  const quality = useDataSource<RiskQualityOut>(
    (signal) =>
      apiFetch<RiskQualityOut>(`/risks/quality?days=${days}`, { cache: "default", signal }),
    [days],
  );

  const rejected = useDataSource<RiskRejection[]>(
    (signal) =>
      apiFetch<RiskRejection[]>(
        `/risks/rejected?days=${days}&limit=${ROW_LIMIT}${reason ? `&reason=${reason}` : ""}`,
        { cache: "default", signal },
      ),
    [days, reason],
  );

  const data = quality.data;
  const options = useMemo(() => (data ? rejectionFilterOptions(data) : []), [data]);
  const rows = rejected.data ?? [];

  const shownOf = useMemo(() => {
    if (!data) return null;
    if (reason) return data.rejected_counts[reason] ?? 0;
    // The unfiltered table cannot show `outside_window`: that bucket is the
    // archive, and the API counts it rather than listing it. Saying "N / M"
    // against a total the table can never reach would look like a bug.
    return Object.entries(data.rejected_counts)
      .filter(([slug]) => slug !== "outside_window")
      .reduce((sum, [, count]) => sum + count, 0);
  }, [data, reason]);

  const selectReason = useCallback((next: string | null) => setReason(next), []);

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex min-w-0 flex-col gap-1">
            <Link
              href="/risk-radari"
              className="flex w-fit items-center gap-1 text-[11px] font-medium text-muted-foreground underline-offset-2 hover:text-foreground hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
            >
              <ArrowLeft className="size-3" aria-hidden />
              Risk Radarı
            </Link>
            <h1 className="text-2xl font-semibold tracking-tight">Veri doğrulama</h1>
            <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground">
              Radarın gösterdiği sinyaller kaç haberden geriye kaldı, ve elenenler
              hangi kural yüzünden elendi. Bu ekran &ldquo;neden bu haber
              görünmüyor&rdquo; ve &ldquo;neden bu haber görünüyor&rdquo;
              sorularını cevaplamak içindir.
            </p>
          </div>
          <div className="flex shrink-0 flex-col items-end gap-1">
            <LastUpdatedStamp
              date={data ? new Date(data.generated_at) : quality.lastUpdated}
            />
            <button
              type="button"
              onClick={() => {
                quality.retry();
                rejected.retry();
              }}
              className="text-[11px] font-medium text-muted-foreground underline-offset-2 hover:text-foreground hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
            >
              Yenile
            </button>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Dönem
          </span>
          {DAY_WINDOWS.map((window) => (
            <button
              key={window}
              type="button"
              onClick={() => setDays(window)}
              aria-pressed={days === window}
              className={chip(days === window)}
            >
              {window}g
            </button>
          ))}
        </div>

        {/* The sentence the whole screen is built to make defensible. Three of
            the four gates publish rows nobody measured, and a funnel that did
            not say so would read as far stronger evidence than it is. */}
        {data && (
          <p className="text-[11px] leading-relaxed text-muted-foreground">
            Kapılar ölçülmemiş satırları ELER DEĞİL YAYINLAR: bu pencerede
            havacılık kapısını <span className="tabular-nums">{data.aviation_unscored}</span>,
            konum kapısını <span className="tabular-nums">{data.location_unscored}</span>,
            güven kapısını <span className="tabular-nums">{data.confidence_unscored}</span> satır
            ölçülmediği için geçti. Bu sayılar düştükçe kapılar gerçekten devreye
            girmiş olur.
          </p>
        )}
      </header>

      {(quality.stale || rejected.stale) && (
        <StaleDataBanner onRetry={quality.retry} lastUpdated={quality.lastUpdated} />
      )}

      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold">Huni</h2>
        {quality.error && !data ? (
          <DataSourceError onRetry={quality.retry} lastUpdated={quality.lastUpdated} />
        ) : !data ? (
          <Skeleton className="h-80 w-full rounded-xl" />
        ) : (
          <RiskFunnel
            stages={data.stages}
            activeReason={reason}
            onSelectReason={selectReason}
          />
        )}
      </section>

      <section className="flex flex-col gap-2">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-sm font-semibold">Reddedilen adaylar</h2>
          {shownOf !== null && (
            <span className="text-[11px] tabular-nums text-muted-foreground">
              {rows.length} / {shownOf}
            </span>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            onClick={() => setReason(null)}
            aria-pressed={reason === null}
            className={chip(reason === null)}
          >
            Tümü
          </button>
          {options.map((option) => (
            <button
              key={option.reason}
              type="button"
              onClick={() => setReason(reason === option.reason ? null : option.reason)}
              aria-pressed={reason === option.reason}
              title={option.reason}
              className={chip(reason === option.reason)}
            >
              {option.label}
              <span className="ml-0.5 tabular-nums opacity-70">{option.count}</span>
            </button>
          ))}
        </div>

        {rejected.error && rejected.data === null ? (
          <DataSourceError onRetry={rejected.retry} lastUpdated={rejected.lastUpdated} />
        ) : !rejected.loaded ? (
          <Skeleton className="h-64 w-full rounded-xl" />
        ) : rows.length === 0 ? (
          <p className="rounded-lg border border-dashed border-border px-3 py-6 text-center text-xs text-muted-foreground">
            {reason === "outside_window"
              ? "Bu pencerenin dışında kalan risk adayı yok."
              : reason
                ? "Bu sebeple elenen aday yok."
                : "Bu pencerede hiçbir risk adayı elenmedi."}
          </p>
        ) : (
          <RiskRejectionsTable rows={rows} />
        )}

        <p className="text-[11px] leading-relaxed text-muted-foreground">
          Sebep sütunu adayı eleyen İLK kapıyı gösterir; satır başka kapılarda da
          elenecekse bunlar &ldquo;+&rdquo; ile listelenir.{" "}
          <span className="font-medium">Pencere dışında</span> kalan adaylar
          sayılır ama listelenmez — o kova arşivin tamamıdır; görmek için o
          filtreyi seçin, en yeniden başlayarak gösterilir.
        </p>
      </section>
    </div>
  );
}
