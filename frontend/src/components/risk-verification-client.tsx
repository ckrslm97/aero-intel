"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo } from "react";

import { DataSourceError, LastUpdatedStamp, StaleDataBanner } from "@/components/data-source-error";
import { RiskFunnel } from "@/components/risk/risk-funnel";
import { RiskRejectionsTable } from "@/components/risk/risk-rejections-table";
import { FilterChip, FilterChipGroup } from "@/components/ui/filter-chip";
import { Skeleton } from "@/components/ui/skeleton";
import { useDataSource } from "@/hooks/use-data-source";
import { readNumber, useUrlState, writeParam } from "@/hooks/use-url-state";
import { apiFetch } from "@/lib/api";
import { rejectionFilterOptions } from "@/lib/risk";
import type { RiskQualityOut, RiskRejection } from "@/lib/types";

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
  // ?days IS READ FROM THE URL, and that is the point of the parameter.
  //
  // The window used to be component state seeded from DEFAULT_DAYS, so the
  // funnel opened on 5 days no matter what the radar had been showing. A
  // reader on a 30-day radar clicked "Veri doğrulama" and audited a different
  // fortnight than the one they had just read -- the exact drift this file's
  // docstring says must not happen, produced by the link that exists to
  // prevent it. The radar now writes the window into the link
  // (risk-radar-client.tsx) and this screen reads it.
  //
  // ?reason joins it because it is the other thing worth sending: "şu kural
  // bu pencerede N haber eledi, bak" is the sentence this page exists to
  // support.
  //
  // ?country is carried but NOT applied -- see `radarHref`.
  const { params, replaceParams } = useUrlState();
  const days = readNumber(params, "days", DAY_WINDOWS, DEFAULT_DAYS);
  const urlReason = params.get("reason");
  const country = params.get("country");

  const setUrlState = useCallback(
    (next: { days?: number; reason?: string | null }) => {
      const updated = new URLSearchParams(params.toString());
      if (next.days !== undefined) {
        writeParam(updated, "days", next.days === DEFAULT_DAYS ? null : String(next.days));
      }
      if (next.reason !== undefined) writeParam(updated, "reason", next.reason);
      replaceParams(updated);
    },
    [params, replaceParams],
  );

  const setDays = useCallback(
    (next: number) => setUrlState({ days: next }),
    [setUrlState],
  );

  /** Back to the radar, on the window and country the reader came from.
   *
   * Without the round trip the audit is a one-way door: you arrive from
   * "Yunanistan, son 30 gün", press the back link, and land on the default
   * radar -- so checking whether you believe a view costs you the view. */
  const radarHref = useMemo(() => {
    const back = new URLSearchParams();
    if (days !== DEFAULT_DAYS) back.set("days", String(days));
    if (country) back.set("country", country);
    return back.size ? `/risk-radari?${back.toString()}` : "/risk-radari";
  }, [days, country]);

  const quality = useDataSource<RiskQualityOut>(
    (signal) =>
      apiFetch<RiskQualityOut>(`/risks/quality?days=${days}`, { cache: "default", signal }),
    [days],
  );

  const data = quality.data;
  const options = useMemo(() => (data ? rejectionFilterOptions(data) : []), [data]);

  /** The reason actually applied. The set of rejection reasons is served, not
   * compiled in, so `?reason=` can only be checked once the funnel arrives --
   * before that it is passed through (the API answers an unknown one with an
   * empty list, which costs one request), and after that an unrecognised one
   * is dropped rather than left lighting no chip above an empty table. */
  const activeReason = useMemo(() => {
    if (!urlReason) return null;
    if (!data) return urlReason;
    return options.some((option) => option.reason === urlReason) ? urlReason : null;
  }, [urlReason, data, options]);

  // Dropping it from the request is only half the job: left in the address bar
  // it made the URL claim a filter the table was not applying. archive-client
  // names this exact failure -- "worse than no filter at all, because the URL
  // said the filter had been applied" -- and forwarding such a link passes the
  // claim on. So once the funnel has told us the reason is not one of ours, the
  // address bar loses it too, and the two say the same thing again.
  useEffect(() => {
    if (!urlReason || !data) return;
    if (activeReason === null) setUrlState({ reason: null });
  }, [urlReason, data, activeReason, setUrlState]);

  const rejected = useDataSource<RiskRejection[]>(
    (signal) =>
      apiFetch<RiskRejection[]>(
        `/risks/rejected?days=${days}&limit=${ROW_LIMIT}${activeReason ? `&reason=${activeReason}` : ""}`,
        { cache: "default", signal },
      ),
    [days, activeReason],
  );

  const rows = rejected.data ?? [];

  const shownOf = useMemo(() => {
    if (!data) return null;
    if (activeReason) return data.rejected_counts[activeReason] ?? 0;
    // The unfiltered table cannot show `outside_window`: that bucket is the
    // archive, and the API counts it rather than listing it. Saying "N / M"
    // against a total the table can never reach would look like a bug.
    return Object.entries(data.rejected_counts)
      .filter(([slug]) => slug !== "outside_window")
      .reduce((sum, [, count]) => sum + count, 0);
  }, [data, activeReason]);

  const selectReason = useCallback(
    (next: string | null) => setUrlState({ reason: next }),
    [setUrlState],
  );

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex min-w-0 flex-col gap-1">
            <Link
              href={radarHref}
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

        <FilterChipGroup label="Dönem">
          {DAY_WINDOWS.map((window) => (
            <FilterChip
              key={window}
              active={days === window}
              onClick={() => setDays(window)}
              // "30g" is unreadable out loud; the accessible name says the
              // whole thing while the chip keeps the two characters the row
              // has room for.
              label={`Son ${window} gün`}
            >
              {window}g
            </FilterChip>
          ))}
          {/* Said out loud rather than left to be discovered. The radar's
              country filter travels in the link so the way back restores it,
              but the audit endpoints take days and reason only -- a screen
              that quietly ignored a filter it is visibly carrying would be
              exactly the "iki ekran, iki farklı gün" problem in a new place. */}
          {country && (
            <span className="text-[11px] text-muted-foreground">
              Radar <span className="font-medium text-foreground">{country}</span> ile
              daraltılmıştı; bu ekran ülkeye göre daralmaz, huni pencerenin
              tamamını sayar.
            </span>
          )}
        </FilterChipGroup>

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

      {/* ONE BANNER PER SOURCE, EACH OVER THE SECTION IT IS ABOUT.
          The two used to share a single banner carrying the funnel's retry and
          the funnel's "son başarılı" time. When it was the TABLE that had
          failed, that banner printed a success time belonging to the other
          endpoint and its button re-fetched the source that was working --
          a stale badge vouching for a freshness nobody had measured. */}
      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold">Huni</h2>
        {quality.stale && (
          <StaleDataBanner
            onRetry={quality.retry}
            lastUpdated={quality.lastUpdated}
            pending={quality.pending}
          />
        )}
        {quality.error && !data ? (
          <DataSourceError
            onRetry={quality.retry}
            lastUpdated={quality.lastUpdated}
            pending={quality.pending}
          />
        ) : !data ? (
          <Skeleton className="h-80 w-full rounded-xl" />
        ) : (
          <RiskFunnel
            stages={data.stages}
            activeReason={activeReason}
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

        <FilterChipGroup label="Elenme nedeni">
          <FilterChip
            active={activeReason === null}
            onClick={() => selectReason(null)}
            label="Tüm elenme nedenleri"
          >
            Tümü
          </FilterChip>
          {options.map((option) => (
            <FilterChip
              key={option.reason}
              active={activeReason === option.reason}
              onClick={() =>
                selectReason(activeReason === option.reason ? null : option.reason)
              }
              title={option.reason}
            >
              {option.label}
              <span className="ml-0.5 tabular-nums opacity-70">{option.count}</span>
            </FilterChip>
          ))}
        </FilterChipGroup>

        {rejected.stale && (
          <StaleDataBanner
            onRetry={rejected.retry}
            lastUpdated={rejected.lastUpdated}
            pending={rejected.pending}
          />
        )}

        {rejected.error && rejected.data === null ? (
          <DataSourceError
            onRetry={rejected.retry}
            lastUpdated={rejected.lastUpdated}
            pending={rejected.pending}
          />
        ) : !rejected.loaded ? (
          <Skeleton className="h-64 w-full rounded-xl" />
        ) : rows.length === 0 ? (
          <p className="rounded-lg border border-dashed border-border px-3 py-6 text-center text-xs text-muted-foreground">
            {activeReason === "outside_window"
              ? "Bu pencerenin dışında kalan risk adayı yok."
              : activeReason
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
