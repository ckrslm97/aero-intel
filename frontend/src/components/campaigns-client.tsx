"use client";

import {
  CalendarRange,
  ChevronLeft,
  ChevronRight,
  Download,
  ExternalLink,
  Megaphone,
  SlidersHorizontal,
  Table2,
} from "lucide-react";
import { useCallback, useMemo, useRef, useState } from "react";

import { AirlineLogo } from "@/components/airline-logo";
import { CampaignAlertStrip } from "@/components/campaign-alert-strip";
import { CampaignAnalystTable } from "@/components/campaign-analyst-table";
import {
  CampaignClusterMarker,
  NewCampaignBadge,
} from "@/components/campaign-cluster-marker";
import { CampaignDrawer } from "@/components/campaign-drawer";
import {
  DataSourceError,
  LastUpdatedStamp,
  StaleDataBanner,
} from "@/components/data-source-error";
import { Pagination } from "@/components/pagination";
import { Skeleton } from "@/components/ui/skeleton";
import { useDataSource } from "@/hooks/use-data-source";
import { API_BASE_URL, apiFetch } from "@/lib/api";
import {
  campaignFacetCounts,
  campaignQueryString,
  campaignStatusStyle,
  confidenceBandLabel,
  EMPTY_CAMPAIGN_FILTERS,
  filterCampaigns,
  groupDatelessCampaigns,
  hasActiveCampaignFilter,
  reviewRequiredCount,
  type CampaignFilters,
} from "@/lib/campaigns";
import { airlineTabs, worldRegions } from "@/lib/nav";
import {
  CAMPAIGN_STATUSES,
  CAMPAIGN_TYPE_LABELS_TR,
  CAMPAIGN_TYPES,
  type CampaignType,
} from "@/lib/taxonomy.gen";
import type { PromotionNewCountOut, PromotionOut } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Two weeks behind, six ahead. Behind, because a sale that ended last week is
 * still the thing a desk is reacting to this week; ahead, because six weeks is
 * as far as anyone actually publishes a sale window. */
const WEEKS_BACK = 2;
const WEEKS_FORWARD = 6;
const WEEKS = WEEKS_BACK + WEEKS_FORWARD;
const DAY_COUNT = WEEKS * 7;
/** How far the steppers will walk, in weeks either side of today. Past this
 * the grid is empty in both directions and stepping is just a treadmill. */
const WEEK_HORIZON = 26;
/** How long an open-ended campaign's bar runs past today before fading out.
 * It is a fade, not a claim -- see `placeBar`. */
const OPEN_ENDED_RUNOUT = 7;
/** Days a bar needs to span before its title fits inside it. Below this the
 * name is in the `title` attribute and the drawer, not painted at 10px into a
 * two-day sliver. */
const LABEL_MIN_SPAN = 7;
/** Campaigns in the "Kampanya akışı" list below the timeline. */
const FLOW_LIMIT = 12;
/** Label rail width. Matches the grid template below; the two must agree,
 * because the week-line and today overlays are inset by exactly this. */
const LABEL_WIDTH = 176;
/** Rows per page in the analyst table. Twenty-five is what fits a laptop
 * screen without the header scrolling out of sight. */
const PAGE_SIZE = 25;

const MS_DAY = 86_400_000;

const BRAND: Record<string, { name: string; color: string }> = Object.fromEntries(
  airlineTabs.map((a) => [a.code, { name: a.name, color: a.color }]),
);

const DETECTED_FORMAT = new Intl.DateTimeFormat("tr-TR", {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});

/** Days since the epoch. Every position on this grid is integer day
 * arithmetic -- no Date objects are compared, so no reader's timezone can
 * shift a campaign onto the wrong column. */
function epochDay(y: number, m: number, d: number): number {
  return Math.floor(Date.UTC(y, m, d) / MS_DAY);
}

/** "2026-05-02" or "2026-05-02T09:00:00Z" -> day number. */
function parseDay(iso: string): number {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  if (!y || !m || !d) return Number.NaN;
  return epochDay(y, m - 1, d);
}

function labelFor(day: number): string {
  return new Date(day * MS_DAY).toLocaleDateString("tr-TR", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
}

type Status = "live" | "upcoming" | "expired";

/** What a campaign becomes on the grid. The shapes are the states the data can
 * actually be in, not visual variants of one thing:
 *   bar     -- both sale dates known;
 *   open    -- a start but no published end, so the bar fades out;
 *   point   -- no start date at all, so there is nothing to draw a bar *along*
 *              and the only honest mark is where we first saw it;
 *   cluster -- several points that would land on the same day in the same
 *              lane. One day is one column, and a column holds one mark. */
type Placement =
  | { kind: "bar" | "open"; promo: PromotionOut; start: number; end: number; status: Status }
  | { kind: "point"; promo: PromotionOut; at: number; status: Status }
  | { kind: "cluster"; key: string; day: string; items: PromotionOut[]; at: number };

/** Which side of a mark the "Yeni" badge hangs off. Right by default; left for
 * the last few columns, where the timeline card's `overflow-hidden` would cut
 * a right-hand badge in half. */
function badgeSideFor(lastColumn: number): "after" | "before" {
  return lastColumn >= DAY_COUNT - 3 ? "before" : "after";
}

/** The column a placement starts in, whatever its shape. */
function placementStart(placement: Placement): number {
  if (placement.kind === "point" || placement.kind === "cluster") return placement.at;
  return placement.start;
}

/** Deliberately NOT `promo.status` from the API.
 *
 * These bars draw the SALE window and nothing else, so their three states are
 * about that window alone. The API's five-state status also answers "is the
 * travel benefit still live" (BOOKING_CLOSED_TRAVEL_ACTIVE), which has no bar
 * to be drawn on this grid -- painting it as "live" would show a closed sale
 * as buyable. The analyst table renders the full five states instead, which is
 * exactly the division of labour the view toggle exists for. */
function statusOf(promo: PromotionOut, today: number): Status {
  const start = promo.sale_starts ? parseDay(promo.sale_starts) : null;
  const end = promo.sale_ends ? parseDay(promo.sale_ends) : null;
  if (end !== null && end < today) return "expired";
  if (start !== null && start > today) return "upcoming";
  // Either the sale is genuinely running, or no start date was published --
  // in which case it has been announced and not yet withdrawn, which is as
  // close to "live" as the source lets us get.
  return "live";
}

/** Place one campaign inside the visible window, or return null when it falls
 * entirely outside it. */
function place(promo: PromotionOut, windowStart: number, today: number): Placement | null {
  const last = DAY_COUNT - 1;
  const status = statusOf(promo, today);
  const clamp = (day: number) => Math.min(Math.max(day - windowStart, 0), last);

  if (!promo.sale_starts) {
    const detected = parseDay(promo.detected_at);
    if (Number.isNaN(detected)) return null;
    const idx = detected - windowStart;
    if (idx < 0 || idx > last) return null;
    return { kind: "point", promo, at: idx, status };
  }

  const start = parseDay(promo.sale_starts);
  if (Number.isNaN(start)) return null;

  if (!promo.sale_ends) {
    // Runs to a week past today and then fades. The fade is the point: the bar
    // has to end somewhere on a finite grid, and a hard edge at an arbitrary
    // day would look exactly like a published end date.
    const end = Math.max(start, Math.min(today + OPEN_ENDED_RUNOUT, windowStart + last));
    if (end < windowStart || start > windowStart + last) return null;
    return { kind: "open", promo, start: clamp(start), end: clamp(end), status };
  }

  const end = parseDay(promo.sale_ends);
  if (Number.isNaN(end)) return null;
  if (end < windowStart || start > windowStart + last) return null;
  return { kind: "bar", promo, start: clamp(start), end: clamp(end), status };
}

const chipClass = (active: boolean) =>
  cn(
    "flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium transition-colors",
    active
      ? "bg-primary/12 text-primary ring-1 ring-primary/40 dark:glow-soft"
      : "border border-border text-muted-foreground hover:bg-accent",
  );

/** The rival campaign page.
 *
 * Two views over one fetch. The timeline is a carrier x time swimlane built out
 * of DOM and CSS grid rather than a chart library: every bar is a link into a
 * drawer, carries a `title`, an `aria-label` and a "Yeni" badge, and has to
 * survive three different missing-data shapes -- a canvas renderer would draw
 * rectangles and leave the keyboard, the screen reader and the badge anchoring
 * to be rebuilt on top. The analyst table is the same rows as values side by
 * side, for the comparison a timeline structurally cannot make.
 *
 * The window is fetched once (eight weeks, no server-side paging) and every
 * filter is applied in memory -- the Risk Radarı pattern, for the same reason:
 * the payload is already small, so narrowing it locally is exact and costs no
 * round trip. The export links carry the same filters to the API, because an
 * export must be able to exceed what the page is holding.
 *
 * Colour discipline on the timeline: fill is the carrier's own brand hex and
 * light is the status. There is never a second hue -- a red bar here means
 * Emirates or Turkish, never "urgent". The table is where semantic colour is
 * allowed, and there it is always paired with an icon and a word.
 */
export function CampaignsClient() {
  const [view, setView] = useState<"timeline" | "table">("timeline");
  const [weekOffset, setWeekOffset] = useState(0);
  const [filters, setFiltersState] = useState<CampaignFilters>(EMPTY_CAMPAIGN_FILTERS);
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<PromotionOut | null>(null);
  const [highlighted, setHighlighted] = useState<string | null>(null);

  const laneRefs = useRef(new Map<string, HTMLDivElement>());
  const highlightTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Read once per mount: every column index on the grid is measured from this,
  // so it has to be stable across renders.
  const [today] = useState(() => {
    const now = new Date();
    return epochDay(now.getFullYear(), now.getMonth(), now.getDate());
  });
  // Mondays: Turkish weeks start there, and anchoring the window to a week
  // boundary is what makes the week rules land on the tick labels.
  const thisMonday = today - ((new Date(today * MS_DAY).getUTCDay() + 6) % 7);
  const windowStart = thisMonday + (weekOffset - WEEKS_BACK) * 7;
  const windowEnd = windowStart + DAY_COUNT - 1;

  const fromIso = new Date(windowStart * MS_DAY).toISOString().slice(0, 10);
  const toIso = new Date(windowEnd * MS_DAY).toISOString().slice(0, 10);

  const fetcher = useCallback(
    async (signal: AbortSignal) => {
      const [rows, fresh] = await Promise.all([
        apiFetch<PromotionOut[]>(`/promotions?date_from=${fromIso}&date_to=${toIso}`, {
          cache: "default",
          signal,
        }),
        // The banner is a bonus, not a dependency: a failing count must not
        // take the campaigns down with it.
        apiFetch<PromotionNewCountOut>("/promotions/new-count", {
          cache: "default",
          signal,
        }).catch(() => null),
      ]);
      return { rows, fresh };
    },
    [fromIso, toIso],
  );
  const { data, error, loaded, lastUpdated, stale, retry } = useDataSource(fetcher, [
    fromIso,
    toIso,
  ]);

  const promotions = data?.rows ?? null;
  const newCount = data?.fresh ?? null;

  /** Any filter change resets to page 1. Doing it in the setter rather than in
   * an effect keeps the two state updates in one commit -- an effect would
   * render page 5 of a two-page result first. */
  const setFilters = useCallback((next: CampaignFilters) => {
    setFiltersState(next);
    setPage(1);
  }, []);
  const toggleFilter = useCallback(
    <K extends keyof CampaignFilters>(key: K, value: CampaignFilters[K]) => {
      setFiltersState((current) => ({
        ...current,
        [key]: current[key] === value ? EMPTY_CAMPAIGN_FILTERS[key] : value,
      }));
      setPage(1);
    },
    [],
  );

  const filtered = useMemo(
    () => filterCampaigns(promotions ?? [], filters),
    [promotions, filters],
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

  /** One entry per carrier that actually has something in this window. A
   * carrier with nothing to show gets no lane at all -- ten mostly-empty rows
   * would read as "we have no data" rather than "they ran no campaigns", and
   * the footer says the second thing in words. */
  const lanes = useMemo(() => {
    const byCarrier = new Map<string, Placement[]>();
    const push = (code: string, placed: Placement) => {
      const bucket = byCarrier.get(code);
      if (bucket) bucket.push(placed);
      else byCarrier.set(code, [placed]);
    };

    // Dateless campaigns are bucketed by (carrier, detection day) BEFORE they
    // are placed, because that bucket is exactly one column of this grid and a
    // column can hold one mark. Bars and open bars go through `place`
    // untouched -- see groupDatelessCampaigns.
    const { dated, singles, clusters } = groupDatelessCampaigns(filtered);
    for (const promo of [...dated, ...singles]) {
      const placed = place(promo, windowStart, today);
      if (!placed) continue;
      push(promo.airline_code, placed);
    }
    for (const cluster of clusters) {
      // Every item shares the day, so the whole cluster is inside the window
      // or outside it together.
      const at = parseDay(cluster.day) - windowStart;
      if (Number.isNaN(at) || at < 0 || at >= DAY_COUNT) continue;
      push(cluster.airlineCode, {
        kind: "cluster",
        key: cluster.key,
        day: cluster.day,
        items: cluster.items,
        at,
      });
    }

    return [...byCarrier.entries()]
      .map(([code, items]) => ({
        code,
        name: BRAND[code]?.name ?? code,
        color: BRAND[code]?.color ?? "var(--primary)",
        // Sorted by start so CSS grid's auto-placement packs overlapping
        // campaigns into stacked rows instead of interleaving them.
        items: items.sort((a, b) => placementStart(a) - placementStart(b)),
      }))
      // TK first, always: this is a Turkish Airlines desk's page, and its own
      // lane is the baseline every rival lane is read against.
      .sort((a, b) => {
        if (a.code === "TK") return -1;
        if (b.code === "TK") return 1;
        return b.items.length - a.items.length;
      });
  }, [filtered, windowStart, today]);

  const litCodes = new Set(lanes.map((l) => l.code));
  const darkCarriers = airlineTabs.filter((a) => !litCodes.has(a.code));

  const flow = useMemo(
    () =>
      filtered
        .slice()
        .sort(
          (a, b) => new Date(b.detected_at).getTime() - new Date(a.detected_at).getTime(),
        )
        .slice(0, FLOW_LIMIT),
    [filtered],
  );

  const freshCodes = useMemo(
    () => (newCount?.airline_codes ?? []).filter((code) => BRAND[code]),
    [newCount],
  );

  // Facet counts are computed against every OTHER active filter, so a chip's
  // number is what clicking it would actually give you.
  const airlineCounts = useMemo(
    () => campaignFacetCounts(promotions ?? [], filters, "airline"),
    [promotions, filters],
  );
  const typeCounts = useMemo(
    () => campaignFacetCounts(promotions ?? [], filters, "campaignType"),
    [promotions, filters],
  );
  const statusCounts = useMemo(
    () => campaignFacetCounts(promotions ?? [], filters, "status"),
    [promotions, filters],
  );
  const regionCounts = useMemo(
    () => campaignFacetCounts(promotions ?? [], filters, "region"),
    [promotions, filters],
  );
  const bandCounts = useMemo(
    () => campaignFacetCounts(promotions ?? [], filters, "band"),
    [promotions, filters],
  );
  const reviewCount = useMemo(
    () => reviewRequiredCount(promotions ?? [], filters),
    [promotions, filters],
  );

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const currentPage = Math.min(page, totalPages);
  const pageRows = filtered.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);

  const exportQuery = campaignQueryString(filters, { from: fromIso, to: toIso });
  const exportHref = (format: "csv" | "json") =>
    `${API_BASE_URL}/promotions/export?format=${format}${exportQuery ? `&${exportQuery}` : ""}`;

  const todayIdx = today - windowStart;
  const todayInWindow = todayIdx >= 0 && todayIdx < DAY_COUNT;

  const focusCarrier = (code: string) => {
    const lane = laneRefs.current.get(code);
    lane?.scrollIntoView({ block: "center", behavior: "smooth" });
    setHighlighted(code);
    if (highlightTimer.current) clearTimeout(highlightTimer.current);
    // A one-shot ring, not a pulsing one: it says "here", then stops.
    highlightTimer.current = setTimeout(() => setHighlighted(null), 2400);
  };

  const navButton =
    "inline-flex size-8 items-center justify-center rounded-lg border border-border text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:pointer-events-none disabled:opacity-40";

  const weekTicks = Array.from({ length: WEEKS }, (_, i) => windowStart + i * 7);

  const availableTypes = CAMPAIGN_TYPES.filter((type) => (typeCounts[type] ?? 0) > 0);
  const availableStatuses = CAMPAIGN_STATUSES.filter(
    (status) => (statusCounts[status] ?? 0) > 0,
  );
  const availableRegions = worldRegions.filter((r) => (regionCounts[r.slug] ?? 0) > 0);
  const availableCarriers = airlineTabs.filter((a) => (airlineCounts[a.code] ?? 0) > 0);
  const availableBands = ["high", "medium"].filter((band) => (bandCounts[band] ?? 0) > 0);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">Kampanya Takibi</h1>
        <p className="text-sm text-muted-foreground">
          Rakip havayollarının satış kampanyaları, taşıyıcı ve zaman ekseninde. Çubuklar
          biletin <span className="font-medium text-foreground">satın alınabildiği</span>{" "}
          dönemi gösterir; seyahat dönemi ayrıntıda yer alır. Kaynağın açıklamadığı bir
          tarih tahmin edilmez.
        </p>
      </div>

      {/* Renders nothing at all when the alerts endpoint is missing or down --
          see campaign-alert-strip.tsx. */}
      <CampaignAlertStrip />

      {!loaded ? (
        <Skeleton className="h-96 w-full rounded-xl" />
      ) : error && !promotions ? (
        <DataSourceError onRetry={retry} lastUpdated={lastUpdated} />
      ) : (
        <>
          {stale && <StaleDataBanner onRetry={retry} lastUpdated={lastUpdated} />}

          {newCount !== null && newCount.count > 0 && (
            <div
              style={
                {
                  "--glow-color": "var(--signal)",
                  "--gradient-surface": "var(--card)",
                } as React.CSSProperties
              }
              className="border-gradient flex flex-wrap items-center gap-3 rounded-xl p-4 shadow-elev-1"
            >
              <Megaphone className="size-5 shrink-0 text-signal" />
              <p className="text-sm">
                Son {newCount.window_hours} saatte{" "}
                <span className="font-bold tabular-nums text-signal">{newCount.count}</span>{" "}
                yeni kampanya yakalandı
              </p>
              {freshCodes.length > 0 && (
                <div className="flex flex-wrap items-center gap-1.5">
                  {freshCodes.map((code) => (
                    <button
                      key={code}
                      type="button"
                      onClick={() => focusCarrier(code)}
                      title={`${BRAND[code].name} kampanyasına git`}
                      className="flex items-center gap-1.5 rounded-full border border-border px-2 py-1 text-[11px] font-medium transition-colors hover:bg-accent"
                    >
                      <AirlineLogo code={code} name={BRAND[code].name} className="size-4" />
                      <span className="tabular-nums">{code}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* --- filters + view toggle + export ------------------------- */}
          <div className="flex flex-col gap-2 rounded-lg border border-border bg-background/50 p-4">
            <div className="flex flex-wrap items-center gap-2">
              <SlidersHorizontal className="size-4 text-muted-foreground" />
              <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                Filtreler
              </span>
              <span className="text-xs tabular-nums text-muted-foreground">
                {filtered.length} / {promotions?.length ?? 0} kampanya
              </span>
              {hasActiveCampaignFilter(filters) && (
                <button
                  type="button"
                  onClick={() => setFilters(EMPTY_CAMPAIGN_FILTERS)}
                  className="text-xs font-medium text-primary hover:underline"
                >
                  Filtreleri temizle
                </button>
              )}

              <div className="ml-auto flex items-center gap-1.5">
                <div
                  role="group"
                  aria-label="Görünüm"
                  className="flex items-center rounded-lg border border-border p-0.5"
                >
                  <ViewButton
                    active={view === "timeline"}
                    onClick={() => setView("timeline")}
                    icon={CalendarRange}
                    label="Zaman çizelgesi"
                  />
                  <ViewButton
                    active={view === "table"}
                    onClick={() => setView("table")}
                    icon={Table2}
                    label="Analist tablosu"
                  />
                </div>
                <a
                  href={exportHref("csv")}
                  className="flex items-center gap-1 rounded-lg border border-border px-2.5 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                  title="Görünen filtrelerle CSV indir (en fazla 2000 satır)"
                >
                  <Download className="size-3.5" />
                  CSV
                </a>
                <a
                  href={exportHref("json")}
                  className="flex items-center gap-1 rounded-lg border border-border px-2.5 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                  title="Görünen filtrelerle JSON indir (en fazla 2000 satır)"
                >
                  <Download className="size-3.5" />
                  JSON
                </a>
              </div>
            </div>

            {availableCarriers.length > 0 && (
              <FilterRow label="Taşıyıcı">
                <button
                  type="button"
                  onClick={() => setFilters({ ...filters, airline: null })}
                  className={chipClass(!filters.airline)}
                >
                  Tümü
                </button>
                {availableCarriers.map((carrier) => (
                  <button
                    key={carrier.code}
                    type="button"
                    onClick={() => toggleFilter("airline", carrier.code)}
                    className={chipClass(filters.airline === carrier.code)}
                    title={carrier.name}
                  >
                    <AirlineLogo
                      code={carrier.code}
                      name={carrier.name}
                      className="size-3.5"
                    />
                    {carrier.code}
                    <span className="ml-0.5 tabular-nums opacity-70">
                      {airlineCounts[carrier.code]}
                    </span>
                  </button>
                ))}
              </FilterRow>
            )}

            {availableStatuses.length > 0 && (
              <FilterRow label="Durum">
                <button
                  type="button"
                  onClick={() => setFilters({ ...filters, status: null })}
                  className={chipClass(!filters.status)}
                >
                  Tümü
                </button>
                {availableStatuses.map((status) => (
                  <button
                    key={status}
                    type="button"
                    onClick={() => toggleFilter("status", status)}
                    className={chipClass(filters.status === status)}
                  >
                    {campaignStatusStyle(status).short}
                    <span className="ml-0.5 tabular-nums opacity-70">
                      {statusCounts[status]}
                    </span>
                  </button>
                ))}
              </FilterRow>
            )}

            {availableTypes.length > 0 && (
              <FilterRow label="Tür">
                <button
                  type="button"
                  onClick={() => setFilters({ ...filters, campaignType: null })}
                  className={chipClass(!filters.campaignType)}
                >
                  Tümü
                </button>
                {availableTypes.map((type) => (
                  <button
                    key={type}
                    type="button"
                    onClick={() => toggleFilter("campaignType", type)}
                    className={chipClass(filters.campaignType === type)}
                  >
                    {CAMPAIGN_TYPE_LABELS_TR[type as CampaignType]}
                    <span className="ml-0.5 tabular-nums opacity-70">{typeCounts[type]}</span>
                  </button>
                ))}
              </FilterRow>
            )}

            {availableRegions.length > 0 && (
              <FilterRow label="Bölge">
                <button
                  type="button"
                  onClick={() => setFilters({ ...filters, region: null })}
                  className={chipClass(!filters.region)}
                >
                  Tümü
                </button>
                {availableRegions.map((region) => (
                  <button
                    key={region.slug}
                    type="button"
                    onClick={() => toggleFilter("region", region.slug)}
                    className={chipClass(filters.region === region.slug)}
                  >
                    {region.name}
                    <span className="ml-0.5 tabular-nums opacity-70">
                      {regionCounts[region.slug]}
                    </span>
                  </button>
                ))}
              </FilterRow>
            )}

            {(availableBands.length > 0 || reviewCount > 0) && (
              <FilterRow label="Güven">
                <button
                  type="button"
                  onClick={() => setFilters({ ...filters, band: null })}
                  className={chipClass(!filters.band)}
                >
                  Tümü
                </button>
                {availableBands.map((band) => (
                  <button
                    key={band}
                    type="button"
                    onClick={() => toggleFilter("band", band)}
                    className={chipClass(filters.band === band)}
                  >
                    {confidenceBandLabel(band)}
                    <span className="ml-0.5 tabular-nums opacity-70">{bandCounts[band]}</span>
                  </button>
                ))}
                {reviewCount > 0 && (
                  <button
                    type="button"
                    aria-pressed={filters.reviewOnly}
                    onClick={() =>
                      setFilters({ ...filters, reviewOnly: !filters.reviewOnly })
                    }
                    className={cn(
                      chipClass(filters.reviewOnly),
                      !filters.reviewOnly && "border-warning/40 text-warning",
                    )}
                    title="Güven eşiğinin altında kalan, insan incelemesi bekleyen kayıtlar"
                  >
                    İnceleme gerekli
                    <span className="ml-0.5 tabular-nums opacity-70">{reviewCount}</span>
                  </button>
                )}
              </FilterRow>
            )}
          </div>

          {filtered.length === 0 ? (
            <div className="rounded-xl border border-dashed border-border p-10 text-center">
              <Megaphone className="mx-auto mb-3 size-6 text-muted-foreground" />
              <p className="text-sm font-medium">
                {hasActiveCampaignFilter(filters)
                  ? "Bu filtrelerle kampanya yok."
                  : "Bu dönemde kayıtlı kampanya yok."}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                {hasActiveCampaignFilter(filters)
                  ? "Filtreleri gevşetin ya da temizleyin."
                  : "Sekiz haftalık pencerede hiçbir taşıyıcının kampanyası bulunmuyor. Oklarla başka bir döneme bakabilirsiniz."}
              </p>
            </div>
          ) : view === "table" ? (
            <div className="flex flex-col gap-3">
              <CampaignAnalystTable rows={pageRows} onSelect={setSelected} />
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-xs tabular-nums text-muted-foreground">
                  {(currentPage - 1) * PAGE_SIZE + 1}–
                  {Math.min(currentPage * PAGE_SIZE, filtered.length)} / {filtered.length}
                </span>
                <Pagination
                  page={currentPage}
                  totalPages={totalPages}
                  onPageChange={setPage}
                />
              </div>
            </div>
          ) : (
            <>
              {/* The swimlane is a desktop instrument: 56 columns cannot be read
                  on a phone, so below md the campaign flow below is the page. */}
              <div className="hidden flex-col gap-3 md:flex">
                <div className="flex flex-wrap items-center gap-3">
                  <h2 className="text-xl font-semibold tracking-tight tabular-nums sm:text-2xl">
                    {labelFor(windowStart)} – {labelFor(windowEnd)}
                  </h2>
                  <div className="ml-auto flex items-center gap-1">
                    <button
                      type="button"
                      aria-label="Önceki hafta"
                      onClick={() => setWeekOffset((w) => w - 1)}
                      disabled={weekOffset <= -WEEK_HORIZON}
                      className={navButton}
                    >
                      <ChevronLeft className="size-4" />
                    </button>
                    <button
                      type="button"
                      aria-label="Sonraki hafta"
                      onClick={() => setWeekOffset((w) => w + 1)}
                      disabled={weekOffset >= WEEK_HORIZON}
                      className={navButton}
                    >
                      <ChevronRight className="size-4" />
                    </button>
                    <button
                      type="button"
                      onClick={() => setWeekOffset(0)}
                      className="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                    >
                      Bugün
                    </button>
                  </div>
                </div>

                <div className="overflow-hidden rounded-xl border border-border bg-card bg-card-sheen shadow-elev-1">
                  <div
                    className="grid border-b border-border bg-muted/40"
                    style={{ gridTemplateColumns: `${LABEL_WIDTH}px 1fr` }}
                  >
                    <div />
                    <div
                      className="grid"
                      style={{ gridTemplateColumns: `repeat(${WEEKS}, minmax(0,1fr))` }}
                    >
                      {weekTicks.map((day) => (
                        <span
                          key={day}
                          className="py-2 pl-2 text-[11px] uppercase tracking-wide text-muted-foreground tabular-nums"
                        >
                          {labelFor(day)}
                        </span>
                      ))}
                    </div>
                  </div>

                  <div className="relative">
                    {/* One painted background for all 8 week rules, rather than
                        56 (or even 8) bordered divs: the boundaries are chrome,
                        and chrome should not cost DOM nodes per lane. */}
                    <span
                      aria-hidden
                      className="pointer-events-none absolute inset-y-0 right-0 z-0"
                      style={{
                        left: LABEL_WIDTH,
                        backgroundImage:
                          "repeating-linear-gradient(to right, var(--border) 0 1px, transparent 1px, transparent calc(100% / 8))",
                      }}
                    />

                    <div
                      className="relative z-10 grid"
                      style={{ gridTemplateColumns: `${LABEL_WIDTH}px 1fr` }}
                    >
                      {lanes.map((lane, index) => (
                        <Lane
                          key={lane.code}
                          lane={lane}
                          isLast={index === lanes.length - 1}
                          highlighted={highlighted === lane.code}
                          isNew={isNew}
                          onSelect={setSelected}
                          registerRef={(node) => {
                            if (node) laneRefs.current.set(lane.code, node);
                            else laneRefs.current.delete(lane.code);
                          }}
                        />
                      ))}
                    </div>

                    {/* Static, and above the bars: it is the one line on the
                        grid that is not a campaign, so it must not be mistaken
                        for one or hidden behind one. */}
                    {todayInWindow && (
                      <div
                        aria-hidden
                        className="pointer-events-none absolute inset-y-0 right-0 z-20"
                        style={{ left: LABEL_WIDTH }}
                      >
                        <div
                          className="absolute inset-y-0 w-px bg-signal/70"
                          style={{ left: `${((todayIdx + 0.5) / DAY_COUNT) * 100}%` }}
                        >
                          <span className="absolute -top-0.5 left-1 whitespace-nowrap text-[10px] font-medium text-signal">
                            Bugün
                          </span>
                        </div>
                      </div>
                    )}
                  </div>
                </div>

                <Legend />

                {darkCarriers.length > 0 && (
                  <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                    <span>Bu dönemde kampanyası olmayan:</span>
                    {darkCarriers.map((carrier) => (
                      <span
                        key={carrier.code}
                        title={carrier.name}
                        className="flex items-center gap-1 rounded-full border border-border px-1.5 py-0.5"
                      >
                        <AirlineLogo
                          code={carrier.code}
                          name={carrier.name}
                          className="size-3.5 opacity-70"
                        />
                        <span className="tabular-nums">{carrier.code}</span>
                      </span>
                    ))}
                  </div>
                )}
              </div>

              <div className="flex flex-col gap-3">
                <h2 className="text-lg font-semibold tracking-tight">Kampanya akışı</h2>
                <div className="grid gap-3 sm:grid-cols-2">
                  {flow.map((promo) => (
                    <FlowCard
                      key={promo.id}
                      promo={promo}
                      isNew={isNew(promo)}
                      onSelect={() => setSelected(promo)}
                    />
                  ))}
                </div>
              </div>
            </>
          )}

          <LastUpdatedStamp date={lastUpdated} />
        </>
      )}

      <CampaignDrawer
        promotion={selected}
        brandHex={selected ? (BRAND[selected.airline_code]?.color ?? "var(--primary)") : "var(--primary)"}
        onClose={() => setSelected(null)}
      />
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
  icon: typeof CalendarRange;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
        active
          ? "bg-primary/12 text-primary"
          : "text-muted-foreground hover:bg-accent hover:text-foreground",
      )}
    >
      <Icon className="size-3.5" />
      {label}
    </button>
  );
}

function FilterRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="w-16 shrink-0 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      {children}
    </div>
  );
}

function Legend() {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-[11px] text-muted-foreground">
      <span className="font-semibold uppercase tracking-wide">Okuma</span>
      <span className="flex items-center gap-1.5">
        <span
          className="size-3 rounded-[3px] bg-foreground"
          style={{ "--glow-color": "var(--foreground)" } as React.CSSProperties}
        />
        Canlı — satış sürüyor
      </span>
      <span className="flex items-center gap-1.5">
        <span className="size-3 rounded-[3px] border border-foreground bg-foreground/15" />
        Yaklaşan — henüz başlamadı
      </span>
      <span className="flex items-center gap-1.5">
        <span className="size-3 rounded-[3px] bg-foreground opacity-40" />
        Sona erdi
      </span>
      <span className="flex items-center gap-1.5">
        <span className="rounded-full bg-signal px-1.5 py-px text-[9px] font-bold uppercase text-white">
          Yeni
        </span>
        Son 48 saatte ilk kez görüldü
      </span>
      <span className="flex items-center gap-1.5">
        <span className="size-3 rotate-45 rounded-[2px] bg-foreground" />
        Tarihi açıklanmayan kampanya, tespit gününde
      </span>
      <span className="flex items-center gap-1.5">
        <span className="flex items-center gap-1 rounded-full border border-border bg-card px-1.5 py-0.5">
          <span className="size-2.5 rotate-45 rounded-[2px] bg-foreground" />
          <span className="text-[10px] font-bold leading-none tabular-nums">3</span>
        </span>
        Aynı gün açıklanan birden çok tarihsiz kampanya — listeyi açmak için tıklayın
      </span>
      <span>Renk taşıyıcının kendi markasıdır; durumu ışık anlatır.</span>
    </div>
  );
}

function Lane({
  lane,
  isLast,
  highlighted,
  isNew,
  onSelect,
  registerRef,
}: {
  lane: { code: string; name: string; color: string; items: Placement[] };
  isLast: boolean;
  highlighted: boolean;
  isNew: (promo: PromotionOut) => boolean;
  onSelect: (promo: PromotionOut) => void;
  registerRef: (node: HTMLDivElement | null) => void;
}) {
  const edge = cn("min-h-10 border-b border-border/60", isLast && "border-b-0");

  return (
    <>
      <div
        ref={registerRef}
        className={cn(
          edge,
          "sticky left-0 z-10 flex items-center gap-2 bg-card px-3 transition-shadow duration-300",
          highlighted && "ring-2 ring-inset ring-signal",
        )}
      >
        <AirlineLogo code={lane.code} name={lane.name} className="size-5" />
        <span className="text-xs font-semibold tabular-nums">{lane.code}</span>
        <span className="hidden truncate text-[11px] text-muted-foreground lg:block">
          {lane.name}
        </span>
      </div>

      <div
        className={cn(edge, "relative items-center gap-y-1 py-1")}
        style={{
          display: "grid",
          gridTemplateColumns: `repeat(${DAY_COUNT}, minmax(0,1fr))`,
        }}
      >
        {lane.items.map((item) =>
          item.kind === "cluster" ? (
            <CampaignClusterMarker
              key={item.key}
              items={item.items}
              day={item.day}
              airlineCode={lane.code}
              airlineName={lane.name}
              color={lane.color}
              gridColumn={`${item.at + 1} / ${item.at + 2}`}
              badgeSide={badgeSideFor(item.at)}
              isNew={isNew}
              onSelect={onSelect}
            />
          ) : item.kind === "point" ? (
            <PointMarker
              key={item.promo.id}
              item={item}
              color={lane.color}
              fresh={isNew(item.promo)}
              onSelect={onSelect}
            />
          ) : (
            <Bar
              key={item.promo.id}
              item={item}
              color={lane.color}
              fresh={isNew(item.promo)}
              onSelect={onSelect}
            />
          ),
        )}
      </div>
    </>
  );
}

function Bar({
  item,
  color,
  fresh,
  onSelect,
}: {
  item: Extract<Placement, { kind: "bar" | "open" }>;
  color: string;
  fresh: boolean;
  onSelect: (promo: PromotionOut) => void;
}) {
  const { promo, status, start, end } = item;
  const span = end - start + 1;
  const open = item.kind === "open";

  // Fill is the carrier. Light is the status. Nothing here introduces a hue
  // the carrier does not already own.
  const style: React.CSSProperties = {
    gridColumn: `${start + 1} / ${end + 2}`,
    "--glow-color": color,
  } as React.CSSProperties;

  if (open) {
    // The bar dissolves rather than ending: there is no published end date, so
    // there is no edge to draw. Squared off on the right for the same reason --
    // a rounded cap is a terminus.
    style.background = `linear-gradient(90deg, ${color} 0%, ${color} 65%, transparent 100%)`;
  } else if (status === "upcoming") {
    style.backgroundColor = `${color}26`;
    style.borderColor = color;
  } else {
    style.backgroundColor = color;
  }

  const label = [
    promo.airline_name,
    promo.title_tr,
    status === "live" ? "satış sürüyor" : status === "upcoming" ? "henüz başlamadı" : "sona erdi",
    promo.sale_range_tr,
    open ? "bitiş tarihi açıklanmadı" : null,
    fresh ? "yeni" : null,
  ]
    .filter(Boolean)
    .join(", ");

  return (
    <button
      type="button"
      title={promo.title_tr}
      aria-label={label}
      onClick={() => onSelect(promo)}
      style={style}
      className={cn(
        // NOT `truncate`: that put `overflow-hidden` on the button, which
        // clipped its own "Yeni" badge back inside the bar and onto the title.
        // The title span below truncates itself instead, which is the only
        // thing that ever needed clipping.
        "relative flex h-6 items-center self-center rounded-md px-2 text-left text-[10px] font-medium transition-all duration-200 hover:-translate-y-0.5 hover:glow-soft motion-reduce:transform-none motion-reduce:transition-none",
        open && "rounded-l-md rounded-r-none",
        status === "upcoming" && !open && "border",
        status === "expired" && !open && "opacity-40",
        // Resting light is the status; a fresh campaign is simply turned up
        // one notch, and the pulse fires once on mount and never again.
        (status === "live" || open) && (fresh ? "glow animate-pulse-once" : "glow-soft"),
      )}
    >
      {span >= LABEL_MIN_SPAN && (
        <span
          className={cn(
            "min-w-0 truncate",
            // White survives PC's yellow and EY's gold; a 15% wash does not
            // survive white, so an outlined upcoming bar keeps body text.
            status === "upcoming" && !open
              ? "text-foreground/90"
              : "text-white/95 [text-shadow:0_1px_2px_rgba(0,0,0,0.45)]",
          )}
        >
          {promo.title_tr}
        </span>
      )}
      {fresh && <NewCampaignBadge side={badgeSideFor(end)} />}
    </button>
  );
}

/** A campaign whose start date nobody published. There is no window to draw,
 * so it is marked at the only day we can stand behind -- the day we saw it --
 * and shaped differently from every bar so it is never read as a one-day sale.
 *
 * Only when it is alone on its day in its lane. Two or more become one
 * `CampaignClusterMarker`, because the column they share can hold one mark. */
function PointMarker({
  item,
  color,
  fresh,
  onSelect,
}: {
  item: Extract<Placement, { kind: "point" }>;
  color: string;
  fresh: boolean;
  onSelect: (promo: PromotionOut) => void;
}) {
  const { promo } = item;
  return (
    <button
      type="button"
      title={promo.title_tr}
      aria-label={`${promo.airline_name}, ${promo.title_tr}, satış tarihi açıklanmadı, ${DETECTED_FORMAT.format(new Date(promo.detected_at))} tarihinde tespit edildi`}
      onClick={() => onSelect(promo)}
      style={
        { gridColumn: `${item.at + 1} / ${item.at + 2}`, "--glow-color": color } as React.CSSProperties
      }
      className="relative flex h-6 items-center justify-center self-center transition-transform duration-200 hover:-translate-y-0.5 motion-reduce:transform-none motion-reduce:transition-none"
    >
      <span
        className={cn("size-3 rotate-45 rounded-[2px]", fresh && "glow animate-pulse-once")}
        style={{ backgroundColor: color }}
      />
      {fresh && <NewCampaignBadge side={badgeSideFor(item.at)} />}
    </button>
  );
}

/** The campaign flow. On desktop it is the reading order after the timeline;
 * below md, where 56 columns cannot be rendered honestly, it IS the page. */
function FlowCard({
  promo,
  isNew,
  onSelect,
}: {
  promo: PromotionOut;
  isNew: boolean;
  onSelect: () => void;
}) {
  const brand = BRAND[promo.airline_code];
  return (
    <button
      type="button"
      onClick={onSelect}
      style={{ "--glow-color": brand?.color ?? "var(--primary)" } as React.CSSProperties}
      className="edge-lit group relative flex flex-col gap-2 rounded-xl border bg-card p-4 text-left transition-all duration-200 hover:-translate-y-0.5 hover:glow-edge motion-reduce:transform-none motion-reduce:transition-none"
    >
      <div className="flex flex-wrap items-center gap-2">
        <AirlineLogo
          code={promo.airline_code}
          name={brand?.name ?? promo.airline_name}
          className="size-5"
        />
        <span className="text-xs font-semibold tabular-nums">{promo.airline_code}</span>
        <span className="text-[11px] text-muted-foreground">{promo.source_name}</span>
        {isNew && (
          <span className="rounded-full bg-signal px-1.5 py-px text-[9px] font-bold uppercase text-white">
            Yeni
          </span>
        )}
        {promo.discount_pct !== null && (
          <span className="ml-auto text-sm font-bold tabular-nums">
            %{promo.discount_pct}
          </span>
        )}
      </div>
      <span className="font-medium leading-snug text-card-foreground group-hover:text-primary">
        {promo.title_tr}
      </span>
      <span className="text-[11px] text-muted-foreground tabular-nums">
        Satış: {promo.sale_range_tr}
      </span>
      <span className="flex items-center gap-1 text-[11px] text-muted-foreground">
        <ExternalLink className="size-3" />
        {DETECTED_FORMAT.format(new Date(promo.detected_at))} tarihinde tespit edildi
      </span>
    </button>
  );
}
