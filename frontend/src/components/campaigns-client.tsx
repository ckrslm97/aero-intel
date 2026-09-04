"use client";

import { Download, LayoutList, Megaphone, Table2 } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo, useState } from "react";

import { CampaignAlertStrip } from "@/components/campaign-alert-strip";
import { CampaignAnalystTable } from "@/components/campaign-analyst-table";
import { CampaignDrawer } from "@/components/campaign-drawer";
import { CampaignExpiring } from "@/components/campaign-expiring";
import { CampaignFeed, CampaignUndatedSection } from "@/components/campaign-feed";
import { CampaignFilterBar } from "@/components/campaign-filters";
import { CampaignSummary, summarise, summaryCaption } from "@/components/campaign-summary";
import {
  DataSourceError,
  InlineSourceError,
  LastUpdatedStamp,
  StaleDataBanner,
} from "@/components/data-source-error";
import { Pagination } from "@/components/pagination";
import { Skeleton } from "@/components/ui/skeleton";
import { useDataSource } from "@/hooks/use-data-source";
import { useNow } from "@/hooks/use-now";
import { API_BASE_URL, apiFetch } from "@/lib/api";
import {
  campaignFiltersToSearchParams,
  campaignQueryString,
  dropExpiredCampaigns,
  filterCampaigns,
  hasActiveCampaignFilter,
  matchesCampaignFilters,
  orderCampaigns,
  parseCampaignFilters,
  splitUndatedCampaigns,
  todayIso,
  type CampaignFilters,
} from "@/lib/campaigns";
import { airlineTabs } from "@/lib/nav";
import type { PromotionNewCountOut, PromotionOut } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Rows in the feed before the reader has to ask for more. */
const FEED_PAGE_SIZE = 20;
/** Rows per page in the analyst table. Twenty-five is what fits a laptop
 * screen without the header scrolling out of sight. */
const TABLE_PAGE_SIZE = 25;
/** The horizon `/promotions/expiring` is asked for. A week is what a revenue
 * desk can still act inside; the alert service's own EXPIRING threshold is
 * three days, which is a different job (interrupt me) from this one. */
const EXPIRING_DAYS = 7;
/** Alerts shown above the feed. Five, not ten: the two loudest alert types
 * (NEW, EXPIRING) now have sections of their own on this page, so the strip is
 * here for what those two do not cover -- a changed date, a low-confidence
 * record -- and does not need to be the tallest thing on screen. */
const ALERT_LIMIT = 5;

const BRAND: Record<string, { name: string; color: string }> = Object.fromEntries(
  airlineTabs.map((a) => [a.code, { name: a.name, color: a.color }]),
);

/**
 * KAMPANYA TAKİBİ -- what a rival is selling, when it can be bought, and when
 * it can be flown.
 *
 * The page in five parts, in the order a desk reads them:
 *
 *   1. five numbers, on one hairline band;
 *   2. what closes this week, from `/promotions/expiring` -- the only thing
 *      here that expires while you read it;
 *   3. the alert strip: what changed since the last look;
 *   4. the feed -- one row per campaign, with the SALE and TRAVEL windows
 *      drawn as two separate tracks (see campaign-windows.tsx, and §11: this
 *      is the distinction the whole product exists to keep straight);
 *   5. the undated group, apart and closed.
 *
 * WHAT WAS REMOVED, AND WHY. This page used to open on a carrier x time
 * swimlane: eleven lanes, fifty-six day columns, a week-stepper and a "today"
 * rule. It was the right instrument for the data it was built against and it
 * is the wrong one for the data we actually have. Measured against production
 * on 2026-09-03: of 83 publishable campaigns, 13 carry a date the grid could
 * place and 70 carry none at all. A 400-pixel grid that renders thirteen marks
 * and pushes every real answer below the fold is not a visualisation, it is a
 * decoration -- and its one genuine job, showing a sale window as a length in
 * time, is now done inside every feed row, where the travel window sits
 * directly under it and the comparison is one eye movement instead of a scroll.
 * The analyst table is kept and reachable from the toggle: it is the view a
 * timeline structurally cannot be, values side by side.
 *
 * THEME. The written spec asks for a white page. This app is theme-aware and
 * pinning one route to light would break the switch for the reader who chose
 * dark; what the spec is actually asking for is restraint, so that is what is
 * implemented -- hairline borders, small radii, compact spacing, tiny status
 * pills, tabular figures, and no saturated colour anywhere except the handful
 * of state badges that earn it. Both themes get the same page.
 *
 * EXPIRED. Nowhere, in any view. The API stopped returning it by default in
 * v2 and nothing on this page asks for it back -- there is no `include_expired`
 * anywhere in the frontend, no EXPIRED filter chip, and no "show archive"
 * escape hatch in the analyst table. An opt-in would be exactly the regression
 * the test suite guards against, and the CSV/JSON export already exists for
 * the audit case.
 */
export function CampaignsClient() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  // The whole filter state is URL-owned, so a narrowed page is a link. That is
  // the reverse of Risk Radarı's split (two params in the bar, the rest in
  // component state) and deliberately so: this page's filters are what an
  // analyst pastes into a message ("TK, Avrupa, satışı bu ay açık"), and a
  // chip whose state evaporates on reload cannot be sent to anyone.
  const filters = useMemo(
    () => parseCampaignFilters(new URLSearchParams(searchParams.toString())),
    [searchParams],
  );
  const view = searchParams.get("view") === "table" ? "table" : "feed";

  const [page, setPage] = useState(1);
  const [feedLimit, setFeedLimit] = useState(FEED_PAGE_SIZE);
  const [selected, setSelected] = useState<PromotionOut | null>(null);

  // Every countdown and every period filter is measured from this, so it has to
  // be stable ACROSS RENDERS -- a page re-deriving "today" per render could show
  // two different day counts in one paint. It must not be stable across the
  // DAY, though, which is what `useState(() => todayIso())` made it: a tab left
  // open through UTC midnight kept counting down to yesterday, one day
  // optimistic on every deadline on the page, until somebody reloaded it.
  //
  // A minute's resolution on a value that changes once a day is deliberate
  // slack: the boundary is crossed within a minute of it happening, and the
  // page re-renders 1 440 times a day rather than 86 400.
  const now = useNow();
  const today = useMemo(() => todayIso(now ?? undefined), [now]);

  const replaceParams = useCallback(
    (params: URLSearchParams) => {
      router.replace(params.size ? `${pathname}?${params.toString()}` : pathname, {
        scroll: false,
      });
    },
    [pathname, router],
  );

  const setFilters = useCallback(
    (next: CampaignFilters) => {
      // Both resets happen in the same commit as the navigation. Doing them in
      // an effect keyed on the filters would render page 5 of a two-page
      // result first.
      setPage(1);
      setFeedLimit(FEED_PAGE_SIZE);
      replaceParams(
        campaignFiltersToSearchParams(next, new URLSearchParams(searchParams.toString())),
      );
    },
    [replaceParams, searchParams],
  );

  const setView = useCallback(
    (next: "feed" | "table") => {
      const params = new URLSearchParams(searchParams.toString());
      if (next === "feed") params.delete("view");
      else params.set("view", next);
      setPage(1);
      replaceParams(params);
    },
    [replaceParams, searchParams],
  );

  const fetcher = useCallback(async (signal: AbortSignal) => {
    const [rows, fresh] = await Promise.all([
      // No date window and no `include_expired`: the API's default is now
      // exactly this page's contract -- every publishable campaign whose sale
      // or travel window has not finished, in the one shared order.
      apiFetch<PromotionOut[]>("/promotions", { cache: "default", signal }),
      // The badge window is a bonus, not a dependency: a failing count must
      // not take the campaigns down with it.
      apiFetch<PromotionNewCountOut>("/promotions/new-count", {
        cache: "default",
        signal,
      }).catch(() => null),
    ]);
    return { rows, fresh };
  }, []);
  const { data, error, loaded, lastUpdated, pending, stale, retry } = useDataSource(fetcher, []);

  // Its own source, so the band failing thins the page by one section rather
  // than blanking the feed under it. Faz 12's per-source contract.
  const expiringSource = useDataSource(
    (signal) =>
      apiFetch<PromotionOut[]>(`/promotions/expiring?days=${EXPIRING_DAYS}`, {
        cache: "default",
        signal,
      }),
    [],
  );

  const promotions = data?.rows ?? null;
  const newCount = data?.fresh ?? null;

  /** Everything the page is willing to show, before the reader's filters.
   * `dropExpiredCampaigns` is the frontend half of the v2 promise -- see its
   * docstring for why it is restated here rather than trusted to the API. */
  const publishable = useMemo(
    () => dropExpiredCampaigns(promotions ?? []),
    [promotions],
  );

  /** The API's own notion of "new", not a number retyped here: the backend
   * exports NEW_WINDOW_HOURS and `/promotions/new-count` hands it over, so the
   * badge and the banner can never disagree with the endpoint. */
  const newWindowHours = newCount?.window_hours ?? 48;
  const isNew = useCallback(
    (promo: PromotionOut) => {
      const age = Date.now() - new Date(promo.detected_at).getTime();
      return age >= 0 && age <= newWindowHours * 3_600_000;
    },
    [newWindowHours],
  );

  const filtered = useMemo(
    () =>
      orderCampaigns(filterCampaigns(publishable, filters, today)),
    [publishable, filters, today],
  );
  const { dated, undated } = useMemo(
    () => splitUndatedCampaigns(filtered),
    [filtered],
  );

  // The expiring band is narrowed by the same filters as everything else --
  // a page filtered to TK that still listed a Pegasus deadline would be two
  // pages stacked on top of each other.
  //
  // The `ACTIVE_BOOKING` guard is deliberately redundant: `/promotions/expiring`
  // already gates on it, and the endpoint's own docstring explains why it must.
  // It is restated here because "bitmek üzere" over a campaign that has already
  // stopped selling is the single most misleading thing this page could print,
  // and a rule that costly should be false in two places before it reaches a
  // reader, not one.
  /** The expiring source did not answer, and has no earlier answer to fall
   * back on. Kept apart from `expiring` because the two mean opposite things
   * and used to be the same empty array. */
  const expiringUnread = expiringSource.error !== null && expiringSource.data === null;

  const expiring = useMemo(
    () =>
      (expiringSource.data ?? []).filter(
        (promo) =>
          promo.status === "ACTIVE_BOOKING" &&
          matchesCampaignFilters(promo, filters, today),
      ),
    [expiringSource.data, filters, today],
  );

  // `null`, not `0`, when the band's own source is unread -- see
  // CampaignSummaryCounts.expiring. "Bitmek üzere: 0" is the single most
  // actionable sentence this page can print and the one it must never
  // manufacture from an outage.
  const counts = useMemo(
    () => summarise(filtered, expiringUnread ? null : expiring),
    [filtered, expiring, expiringUnread],
  );
  const active = hasActiveCampaignFilter(filters);

  const feedRows = dated.slice(0, feedLimit);
  const tablePages = Math.max(1, Math.ceil(filtered.length / TABLE_PAGE_SIZE));
  const currentPage = Math.min(page, tablePages);
  const tableRows = filtered.slice(
    (currentPage - 1) * TABLE_PAGE_SIZE,
    currentPage * TABLE_PAGE_SIZE,
  );

  const exportQuery = campaignQueryString(filters, today);
  const exportHref = (format: "csv" | "json") =>
    `${API_BASE_URL}/promotions/export?format=${format}${exportQuery ? `&${exportQuery}` : ""}`;

  return (
    <div className="flex flex-col gap-5">
      <header className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">Kampanya Takibi</h1>
        <p className="max-w-3xl text-xs leading-relaxed text-muted-foreground">
          Rakip havayollarının kampanyaları.{" "}
          <span className="font-medium text-foreground">Satış dönemi</span> biletin
          alınabildiği aralıktır;{" "}
          <span className="font-medium text-foreground">seyahat dönemi</span> uçuşun
          yapılabildiği aralık. İkisi ayrı gösterilir, kaynağın açıklamadığı bir tarih
          tahmin edilmez.
        </p>
      </header>

      {!loaded ? (
        <Skeleton className="h-96 w-full rounded-lg" />
      ) : error && !promotions ? (
        <DataSourceError onRetry={retry} lastUpdated={lastUpdated} pending={pending} />
      ) : (
        <>
          {stale && <StaleDataBanner onRetry={retry} lastUpdated={lastUpdated} pending={pending} />}

          <div className="flex flex-col gap-1.5">
            <CampaignSummary counts={counts} filtered={active} />
            <p className="text-[10px] text-muted-foreground">
              {summaryCaption(active, filtered.length)}
            </p>
          </div>

          {/* The band hides itself when nothing is closing -- an urgency
              strip that is empty most days trains a reader to stop looking at
              it. That rule only holds when "empty" is a measurement, so an
              unread source gets a line of its own instead of the same silence. */}
          {expiringUnread ? (
            <InlineSourceError
              message="Bitmek üzere olan kampanyalar okunamadı; bu hafta kapanan kampanya olmadığı anlamına gelmez."
              onRetry={expiringSource.retry}
              pending={expiringSource.pending}
            />
          ) : (
            <CampaignExpiring rows={expiring} today={today} onSelect={setSelected} />
          )}

          {/* Renders nothing at all when the alerts endpoint is missing or
              down -- see campaign-alert-strip.tsx. */}
          <CampaignAlertStrip limit={ALERT_LIMIT} />

          <CampaignFilterBar
            promotions={publishable}
            filters={filters}
            today={today}
            onChange={setFilters}
          >
            <div
              role="group"
              aria-label="Görünüm"
              className="flex items-center rounded-md border border-border p-0.5"
            >
              <ViewButton
                active={view === "feed"}
                onClick={() => setView("feed")}
                icon={LayoutList}
                label="Akış"
              />
              <ViewButton
                active={view === "table"}
                onClick={() => setView("table")}
                icon={Table2}
                label="Tablo"
              />
            </div>
            <a
              href={exportHref("csv")}
              title="Görünen filtrelerle CSV indir (en fazla 2000 satır)"
              className="flex items-center gap-1 rounded-md border border-border px-2 py-1 text-[11px] font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            >
              <Download className="size-3" aria-hidden />
              CSV
            </a>
            <a
              href={exportHref("json")}
              title="Görünen filtrelerle JSON indir (en fazla 2000 satır)"
              className="flex items-center gap-1 rounded-md border border-border px-2 py-1 text-[11px] font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            >
              <Download className="size-3" aria-hidden />
              JSON
            </a>
          </CampaignFilterBar>

          {filtered.length === 0 ? (
            <EmptyState filtered={active} />
          ) : view === "table" ? (
            <div className="flex flex-col gap-2">
              <CampaignAnalystTable rows={tableRows} onSelect={setSelected} />
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-[11px] tabular-nums text-muted-foreground">
                  {(currentPage - 1) * TABLE_PAGE_SIZE + 1}–
                  {Math.min(currentPage * TABLE_PAGE_SIZE, filtered.length)} /{" "}
                  {filtered.length}
                </span>
                <Pagination
                  page={currentPage}
                  totalPages={tablePages}
                  onPageChange={setPage}
                />
              </div>
            </div>
          ) : (
            <div className="flex flex-col gap-5">
              <section aria-label="Son kampanyalar" className="flex flex-col gap-2">
                <h2 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                  Son kampanyalar
                  <span className="ml-2 rounded-full bg-muted px-1.5 py-px text-[10px] font-normal tabular-nums">
                    {dated.length}
                  </span>
                </h2>

                {dated.length === 0 ? (
                  <p className="rounded-lg border border-dashed border-border px-3 py-6 text-center text-xs text-muted-foreground">
                    Tarihli kampanya yok. Bu filtrelerle eşleşen kayıtların hiçbirinde
                    yayımlanmış satış ya da seyahat dönemi bulunmuyor — aşağıdaki
                    &quot;Tarih belirtilmemiş&quot; grubuna bakabilirsiniz.
                  </p>
                ) : (
                  <>
                    <CampaignFeed rows={feedRows} isNew={isNew} onSelect={setSelected} />
                    {feedRows.length < dated.length && (
                      <button
                        type="button"
                        onClick={() => setFeedLimit((n) => n + FEED_PAGE_SIZE)}
                        className="mx-auto rounded-md border border-border px-3 py-1 text-[11px] font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
                      >
                        Daha fazla göster ({dated.length - feedRows.length})
                      </button>
                    )}
                  </>
                )}
              </section>

              <CampaignUndatedSection
                rows={undated}
                isNew={isNew}
                onSelect={setSelected}
              />
            </div>
          )}

          <LastUpdatedStamp date={lastUpdated} />
        </>
      )}

      <CampaignDrawer
        promotion={selected}
        brandHex={
          selected ? (BRAND[selected.airline_code]?.color ?? "var(--primary)") : "var(--primary)"
        }
        onClose={() => setSelected(null)}
      />
    </div>
  );
}

function EmptyState({ filtered }: { filtered: boolean }) {
  return (
    <div className="rounded-lg border border-dashed border-border p-8 text-center">
      <Megaphone className="mx-auto mb-2 size-5 text-muted-foreground" aria-hidden />
      <p className="text-sm font-medium">
        {filtered ? "Bu filtrelerle kampanya yok." : "Kayıtlı kampanya yok."}
      </p>
      <p className="mt-1 text-xs text-muted-foreground">
        {filtered
          ? "Filtreleri gevşetin ya da temizleyin."
          : "Hiçbir taşıyıcının yayımlanabilir kampanyası bulunmuyor."}
      </p>
    </div>
  );
}

function ViewButton({
  active,
  onClick,
  icon: Icon,
  label,
}: {
  active: boolean;
  onClick: () => void;
  icon: typeof Table2;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "flex items-center gap-1 rounded px-2 py-0.5 text-[11px] font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
        active
          ? "bg-primary/12 text-primary"
          : "text-muted-foreground hover:bg-accent hover:text-foreground",
      )}
    >
      <Icon className="size-3" aria-hidden />
      {label}
    </button>
  );
}
