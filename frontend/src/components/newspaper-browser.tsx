"use client";

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import {
  Archive as ArchiveIcon,
  CalendarDays,
  Download,
  List,
  Map as MapIcon,
} from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { ArticleCard } from "@/components/article-card";
import { CategoryChipRow } from "@/components/filters/category-chip-row";
import { EventsCalendar } from "@/components/events-calendar";
import { AirlineLogo } from "@/components/airline-logo";
import { BreakingStrip } from "@/components/gazete/breaking-strip";
import { EventRadarStrip } from "@/components/gazete/event-radar-strip";
import { HighlightsRow } from "@/components/gazete/highlights-row";
import { SourceFilterRow } from "@/components/gazete/source-filter-row";
import { Pagination } from "@/components/pagination";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api";
import {
  applyWindowParams,
  DEFAULT_CATEGORY,
  type GazeteFilters,
  hasNarrowingFilters,
  parseFilters,
  serializeFilters,
  TIER_FILTERS,
  WINDOW_OPTIONS,
  windowOption,
} from "@/lib/gazete";
import { airlineTabs } from "@/lib/nav";
import {
  EVENT_REGIONS,
  NEWSPAPER_CATEGORIES,
  NEWSPAPER_CATEGORY_SLUGS,
  NEWSPAPER_EXCLUDED_CATEGORY_SLUGS,
} from "@/lib/taxonomy";
import { RIVAL_CODES } from "@/lib/taxonomy.gen";
import type { ArticleListOut, ArticleOut, CountryOut } from "@/lib/types";
import { cn } from "@/lib/utils";

// echarts + the world outline are only needed once the map is opened.
const RegionMap = dynamic(
  () => import("@/components/region-map").then((m) => m.RegionMap),
  { ssr: false, loading: () => <Skeleton className="h-[320px] w-full rounded-xl" /> },
);

// The user's named main rivals, taken from the backend's own list rather than
// from "every branded carrier except TK": the "Ana Rakipler" chip below sends
// airline=RIVALS, which the API expands to exactly RIVAL_CODES. Deriving the
// chip row by subtraction meant that branding a carrier the desk does not
// consider a rival (SQ) silently added a rival chip the aggregate would not
// have matched.
const RIVALS = airlineTabs.filter((a) => (RIVAL_CODES as readonly string[]).includes(a.code));
const TK = airlineTabs.find((a) => a.code === "TK")!;

// Filter-row summary for the two aggregate chips. The count is derived for the
// same reason the row is: a hand-written "9" is a caption that goes stale.
const AIRLINE_FILTER_LABEL: Record<string, string> = {
  RIVALS: `${RIVAL_CODES.length} ana rakibin tümü`,
  ALL: "haberde geçen tüm havayolları",
};

const PAGE_LIMIT = 30;

/** "Fewer, more critical stories": a floor on the FOCUS-WEIGHTED importance
 * score -- `importance_score + FOCUS_BONUS[category]`, applied server-side (see
 * backend/app/repositories/article_repository.py `_focus_weighted_importance`).
 * The bonus table is the one the daily edition's front page already ranks by
 * (backend/app/taxonomy.py): Gelir Yönetimi +0.30, Ağ & Rota +0.18, Finans
 * +0.10, Etkinlik +0.08, everything else +0.
 *
 * The weighting is the whole point, because raw importance is
 * `confidence * 0.7 + min(corroborating, 5) * 0.06` -- it measures how widely
 * SYNDICATED a story is, not how much an RM desk needs it. Measured over 30
 * days of translated articles (n=4205 from the live API), a flat floor on the
 * raw column inverted the desk's priority:
 *
 *   category            before   flat 0.47   weighted 0.47
 *   Gelir Yönetimi         471    71  (15%)   471  (100%)
 *   Etkinlik                83    29  (35%)    82   (99%)
 *   Finans                 368   104  (28%)   368  (100%)
 *   Filo                  1072   562  (52%)   562   (52%)
 *   Genel                  602   321  (53%)   321   (53%)
 *   Havalimanı             407   104  (26%)   104   (26%)
 *   total                 3003  1191 (40%)   1908   (64%)
 *
 * A Boeing order runs on ten wires; a rival's fare move runs on one. The flat
 * cut kept the former and deleted the latter -- 85% of Gelir Yönetimi, the
 * desk's first priority. Weighting leaves the zero-bonus categories cut exactly
 * as before (Filo and Genel roughly halved, which is what the simplification
 * was for) and stops culling the two beats the paper exists for.
 *
 * The value stayed 0.47; only the predicate changed. Do not read that as a
 * free parameter -- the threshold is effectively a STEP function, because
 * importance_score takes just 24 distinct values across the corpus and 71% of
 * it sits inside 0.455-0.490, a band narrower than the smallest bonus. Every
 * threshold in 0.470-0.476 gives the identical result above; the next rung up
 * is 0.478-0.487 (total 1266, 42%), which cuts harder but collapses Havalimanı
 * to 28 stories in 30 days (~1/day) and Genel to 78 -- too thin to be a tab.
 * Below 0.470 the filter stops doing anything (0.466 keeps 87%); at 0.490
 * Havalimanı drops to 3. There is nothing in between to tune, so pick a rung,
 * not a number. Both rungs sit in gaps between stored values, so neither is
 * exposed to float-comparison edge cases. */
const MIN_IMPORTANCE = 0.47;

/** Appended to every Gazete query: the tab row's allow-list hides these four
 * categories, and this keeps their articles out of the list (and out of the
 * badge counts) rather than letting them resurface under Genel. Query-time
 * only -- nothing stops being ingested or classified. */
function appendGazeteFilters(params: URLSearchParams): URLSearchParams {
  // Repeated keys, one per value -- the same shape FastAPI parses into a list
  // that recommendations-client.tsx uses for its multi-select filters.
  NEWSPAPER_EXCLUDED_CATEGORY_SLUGS.forEach((slug) =>
    params.append("exclude_categories", slug),
  );
  params.set("min_importance", String(MIN_IMPORTANCE));
  return params;
}

// "28 Temmuz 2026" -- one formatter for the whole list, same reasoning as
// ArticleCard's PUBLISHED_FORMAT.
const DAY_HEADER_FORMAT = new Intl.DateTimeFormat("tr-TR", {
  day: "numeric",
  month: "long",
  year: "numeric",
});

const LAST_UPDATED_FORMAT = new Intl.DateTimeFormat("tr-TR", {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});

interface DayGroup {
  /** ISO calendar day, or null for the trailing "Tarihsiz" bucket. */
  key: string | null;
  label: string;
  articles: ArticleOut[];
}

/** Group an already date-sorted list (the API returns published_at desc) into
 * calendar days, preserving order. Undated stories fall into one trailing
 * bucket rather than being silently dropped or dated to today. */
function groupByDay(items: ArticleOut[]): DayGroup[] {
  const groups: DayGroup[] = [];
  const undated: ArticleOut[] = [];
  const byKey = new Map<string, DayGroup>();

  for (const article of items) {
    if (!article.published_at) {
      undated.push(article);
      continue;
    }
    const published = new Date(article.published_at);
    if (Number.isNaN(published.getTime())) {
      undated.push(article);
      continue;
    }
    // Local calendar day, so a reader in Istanbul sees Istanbul's dates.
    const key = `${published.getFullYear()}-${published.getMonth()}-${published.getDate()}`;
    const existing = byKey.get(key);
    if (existing) {
      existing.articles.push(article);
    } else {
      const group: DayGroup = {
        key,
        label: DAY_HEADER_FORMAT.format(published),
        articles: [article],
      };
      byKey.set(key, group);
      groups.push(group);
    }
  }

  if (undated.length > 0) {
    groups.push({ key: null, label: "Tarihsiz", articles: undated });
  }
  return groups;
}

export function NewspaperBrowser() {
  const reduceMotion = useReducedMotion();
  const router = useRouter();
  const pathname = usePathname();

  /** The URL is the filter state -- read every render, not once on mount.
   *
   * It used to be read exactly once, as the initial value of six useStates,
   * after which the chips owned the filters. That made a filtered view
   * reachable but not SHAREABLE (the address bar never moved), and it made the
   * back button walk out of the page instead of back through the filters --
   * only `?page=` was URL-owned, so browser history recorded paging and
   * nothing else.
   *
   * Now every chip writes to the URL and the URL drives the fetch, so a
   * shared link reproduces the view it was copied from and back/forward walk
   * the filter history for free (Next's useSearchParams re-renders on
   * popstate; there is no listener to get wrong).
   */
  const searchParams = useSearchParams();
  const filters = useMemo(
    () => parseFilters(new URLSearchParams(searchParams.toString())),
    [searchParams],
  );
  const {
    category: categorySlug,
    subcategory: subcategorySlug,
    region: regionSlug,
    country: countrySlug,
    airline: airlineCode,
    tier: tierId,
    source: sourceName,
    page,
  } = filters;
  const activeWindow = windowOption(filters.window);

  /** Apply a patch to the URL.
   *
   * `router.replace`, not push: a filter row is a control the reader adjusts,
   * often several times in a row, and pushing every chip press would make the
   * back button undo them one at a time instead of leaving the page. Paging
   * keeps `push` below, which is Faz 11's existing pagination contract.
   *
   * Any filter change resets to page 1 unless the patch says otherwise --
   * landing on page 4 of a result set that now has two pages is the classic
   * way a filtered list renders empty for no visible reason.
   */
  function updateFilters(patch: Partial<GazeteFilters>, { push = false } = {}) {
    const next: GazeteFilters = { ...filters, page: 1, ...patch };
    const params = serializeFilters(next);
    const href = params.size ? `${pathname}?${params.toString()}` : pathname;
    // scroll: false on both -- Next's default scroll-to-top on navigation
    // would yank the page every time a chip is pressed.
    if (push) router.push(href, { scroll: false });
    else router.replace(href, { scroll: false });
  }

  function setPage(next: number) {
    updateFilters({ page: Math.max(1, next) }, { push: true });
    window.scrollTo({ top: 0, behavior: reduceMotion ? "instant" : "smooth" });
  }

  const [eventView, setEventView] = useState<"news" | "calendar">("news");
  const [showMap, setShowMap] = useState(false);

  const [items, setItems] = useState<ArticleOut[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [counts, setCounts] = useState<Record<string, number>>({});
  const [countries, setCountries] = useState<CountryOut[]>([]);

  const category =
    NEWSPAPER_CATEGORIES.find((c) => c.slug === categorySlug) ?? NEWSPAPER_CATEGORIES[0];

  function selectCategory(slug: string) {
    // Region, country and rival filters deliberately survive a category
    // switch: "show me everything about Emirates" should stay pinned while
    // browsing categories. The subcategory cannot -- it belongs to the tab
    // being left.
    updateFilters({ category: slug, subcategory: null });
  }

  // Tab badges: one grouped request, re-made when the time window changes.
  // translated_only, the exclusions and the importance floor all mirror the
  // list query below, so a tab badge never promises stories the filtered list
  // will not render -- and now the window mirrors it too, so switching to
  // "6 saat" does not leave the tabs advertising a month of news.
  useEffect(() => {
    const controller = new AbortController();
    const countParams = appendGazeteFilters(
      applyWindowParams(new URLSearchParams({ translated_only: "true" }), activeWindow),
    );
    apiFetch<Record<string, number>>(`/articles/counts?${countParams.toString()}`, {
      cache: "default",
      signal: controller.signal,
    })
      .then(setCounts)
      .catch(() => {
        /* badges are decorative -- a failure here must not break the list */
      });
    return () => controller.abort();
  }, [activeWindow]);

  // The country picker's options. Counted server-side, busiest first, and only
  // countries with at least one article -- a dropdown of 51 gazetteer names
  // where 40 are empty teaches the reader not to trust the control.
  useEffect(() => {
    const controller = new AbortController();
    apiFetch<CountryOut[]>("/taxonomy/countries?days=90", {
      cache: "default",
      signal: controller.signal,
    })
      .then(setCountries)
      .catch(() => {
        /* no list -> no picker, rather than an empty one */
      });
    return () => controller.abort();
  }, []);

  // Article list. Every fetch replaces the page in place -- `page` (URL-owned,
  // see above) is the only thing that changes which slice comes back.
  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const params = new URLSearchParams({
      category: categorySlug,
      limit: String(PAGE_LIMIT),
      offset: String((page - 1) * PAGE_LIMIT),
      // Gazete only shows stories that actually have a Turkish translation --
      // an untranslated article falls back to its original-language headline
      // and reads as raw German/English mixed into a Turkish paper. Filtered
      // server-side so `total` / the page count stay in step with the list.
      translated_only: "true",
    });
    // hours OR days, never both: the API 422s on a request carrying two time
    // windows, so this helper deletes one as it writes the other.
    applyWindowParams(params, activeWindow);
    appendGazeteFilters(params);
    if (subcategorySlug) params.set("subcategory", subcategorySlug);
    if (regionSlug) params.set("region", regionSlug);
    if (countrySlug) params.set("country", countrySlug);
    if (airlineCode) params.set("airline", airlineCode);
    // Repeatable on the wire even though the row is single-select -- the API
    // unions repeated values, so the shape does not change if the row ever
    // becomes multi-select.
    if (sourceName) params.append("source", sourceName);
    if (tierId) {
      // One chip can stand for two tiers ("Resmî" = official + regulator);
      // repeated keys are what the API unions.
      TIER_FILTERS.find((filter) => filter.id === tierId)?.tiers.forEach((tier) =>
        params.append("tier", tier),
      );
    }

    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch driven by filter/page change; the loading flag must flip synchronously with the dependency change
    setLoading(true);

    // cache: "default" lets the browser reuse its own copy -- the API now sends
    // max-age, so returning to a filter you already viewed is instant instead
    // of a fresh round trip. The abort stops click-spam from leaving a queue of
    // abandoned requests ahead of the one the reader is actually waiting for.
    apiFetch<ArticleListOut>(`/articles?${params.toString()}`, {
      cache: "default",
      signal: controller.signal,
    })
      .then((data) => {
        if (cancelled) return;
        setItems(data.items);
        setTotal(data.total);
        setError(null);
      })
      .catch((error: unknown) => {
        if (cancelled || (error as Error)?.name === "AbortError") return;
        setError("Haberler yüklenemedi. Sunucu çalışıyor mu?");
      })
      .finally(() => {
        if (cancelled) return;
        setLoading(false);
      });
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [categorySlug, subcategorySlug, regionSlug, countrySlug, airlineCode, tierId, sourceName, activeWindow, page]);

  const today = new Date().toISOString().slice(0, 10);
  // "Son güncelleme": the newest thing this page actually has, taken from the
  // payload rather than from the clock. `new Date()` would tick along happily
  // while the API served a two-hour-old cache and the stamp would be a lie
  // about the data, not a statement about the fetch.
  const lastUpdated = useMemo(() => {
    const newest = items.reduce<number | null>((latest, article) => {
      const stamp = new Date(article.fetched_at).getTime();
      return Number.isNaN(stamp) ? latest : Math.max(latest ?? stamp, stamp);
    }, null);
    return newest === null ? null : new Date(newest);
  }, [items]);

  // The two summary strips describe the DEFAULT paper. A top-4 that ignored
  // the region chip the reader just pressed would be four unrelated stories
  // sitting above their filtered list, which reads as a bug rather than as a
  // summary -- so they step out of the way as soon as a filter narrows things.
  const showStrips = !hasNarrowingFilters(filters);

  // Only the countries the chosen region actually produced -- the endpoint
  // already carries each country's region, so this is a filter rather than a
  // second request per region.
  const countriesInRegion = useMemo(
    () => (regionSlug ? countries.filter((c) => c.region === regionSlug) : []),
    [countries, regionSlug],
  );
  const totalPages = Math.max(1, Math.ceil(total / PAGE_LIMIT));
  // Same local-calendar key `groupByDay` builds, so "today" can be picked out
  // of the date headers without re-parsing every article.
  const todayGroupKey = (() => {
    const now = new Date();
    return `${now.getFullYear()}-${now.getMonth()}-${now.getDate()}`;
  })();

  const dayGroups = useMemo(() => groupByDay(items), [items]);

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl font-semibold tracking-tight">Gazete</h1>
          <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted-foreground">
            Kategoriye göre doğrulanmış, güncel havacılık haberleri.
            {lastUpdated && (
              <span className="text-xs tabular-nums">
                · Son güncelleme {LAST_UPDATED_FORMAT.format(lastUpdated)}
              </span>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {/* Arşiv stays a real route (Faz 11: six-page nav) -- just off the
              primary sidebar, reached from here instead. */}
          <Link
            href="/archive"
            className="flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-accent"
          >
            <ArchiveIcon className="size-3.5" />
            Arşiv
          </Link>
          <Link
            href={`/newspaper/${today}`}
            className="flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-accent"
          >
            <Download className="size-3.5" />
            Günün Gazetesi
          </Link>
        </div>
      </div>

      {/* Sticky category bar -- horizontally scrollable on mobile, blurred so
          content reads through it while scrolling. */}
      <div className="sticky top-0 z-20 -mx-2 border-b border-border bg-background/80 px-2 pb-3 pt-2 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        {/* Six tabs, in the order the desk ranked them (see
            NEWSPAPER_CATEGORY_SLUGS) -- not the full taxonomy. Gelir Yönetimi
            leads and keeps its amber identity even when inactive; the row
            component itself is shared with Öneriler, which still shows all
            eleven. */}
        <CategoryChipRow
          value={categorySlug}
          onChange={(slug) => selectCategory(slug ?? DEFAULT_CATEGORY)}
          slugs={NEWSPAPER_CATEGORY_SLUGS}
          pinned="revenue_management"
          focusStyling
          counts={counts}
          layoutId="newspaperCategoryPill"
        />
      </div>

      {/* The old standalone Takvim page lives here now: Etkinlik gets a
          news/calendar view switch, everything else goes straight to news. */}
      {categorySlug === "events" && (
        <div className="flex items-center gap-1 self-start rounded-lg border border-border p-0.5">
          {(
            [
              ["news", "Haberler", List],
              ["calendar", "Takvim", CalendarDays],
            ] as const
          ).map(([view, label, Icon]) => (
            <button
              key={view}
              onClick={() => setEventView(view)}
              className={cn(
                "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                eventView === view
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-accent",
              )}
            >
              <Icon className="size-3.5" />
              {label}
            </button>
          ))}
        </div>
      )}

      {categorySlug === "events" && eventView === "calendar" ? (
        <EventsCalendar />
      ) : (
        <>
      {/* Time window. Sits above the other filter rows because it qualifies
          all of them: "Gelir Yönetimi, son 6 saat" is a different question
          from "Gelir Yönetimi, son 30 gün", and every count on the page moves
          with it. 30 gün stays the default, so a bookmarked link that predates
          this row shows exactly what it always did. */}
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Zaman
        </span>
        {WINDOW_OPTIONS.map((option) => (
          <button
            key={option.id}
            onClick={() => updateFilters({ window: option.id })}
            className={cn(
              "rounded-full px-2.5 py-1 text-xs font-medium tabular-nums transition-colors",
              filters.window === option.id
                ? "bg-primary text-primary-foreground"
                : "border border-border text-muted-foreground hover:bg-accent",
            )}
          >
            {option.label}
          </button>
        ))}

        <span aria-hidden className="mx-1 h-4 w-px bg-border" />

        {/* Source authority. Four chips over five tiers -- official and
            regulator share one, because "from the horse's mouth" is the
            distinction a reader filters on and "airline newsroom vs
            regulator" is not. */}
        {/* "Kaynak türü", not "Kaynak": the named-outlet row directly below is
            also a source filter, and two rows sharing one heading would read
            as one control that had somehow been split. */}
        <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Kaynak türü
        </span>
        {TIER_FILTERS.map((filter) => (
          <button
            key={filter.id}
            onClick={() =>
              updateFilters({ tier: tierId === filter.id ? null : filter.id })
            }
            className={cn(
              "rounded-full px-2.5 py-1 text-xs font-medium transition-colors",
              tierId === filter.id
                ? "bg-primary text-primary-foreground"
                : "border border-border text-muted-foreground hover:bg-accent",
            )}
          >
            {filter.label}
          </button>
        ))}
      </div>

      {/* Named outlets, under the tier chips because it is the finer cut of
          the same axis: a tier says how authoritative, a name says which
          newsroom. Its options are counted server-side over the window above
          -- see components/gazete/source-filter-row.tsx. */}
      <SourceFilterRow
        window={activeWindow}
        category={categorySlug}
        minImportance={MIN_IMPORTANCE}
        excludedCategories={NEWSPAPER_EXCLUDED_CATEGORY_SLUGS}
        value={sourceName}
        onChange={(next) => updateFilters({ source: next })}
      />

      {category.subcategories.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          <button
            onClick={() => updateFilters({ subcategory: null })}
            className={cn(
              "rounded-full px-3 py-1 text-xs font-medium transition-colors",
              !subcategorySlug
                ? "bg-primary text-primary-foreground"
                : "border border-border text-muted-foreground hover:bg-accent",
            )}
          >
            Tümü
          </button>
          {category.subcategories.map((s) => (
            <button
              key={s.slug}
              onClick={() => {
                updateFilters({ subcategory: s.slug });
              }}
              className={cn(
                "rounded-full px-3 py-1 text-xs font-medium transition-colors",
                subcategorySlug === s.slug
                  ? "bg-primary text-primary-foreground"
                  : "border border-border text-muted-foreground hover:bg-accent",
              )}
            >
              {s.label}
            </button>
          ))}
        </div>
      )}

      {/* Region filter -- available in every category (driven by the
          entity-derived enrichment.region), not just Etkinlik. */}
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Bölge
        </span>
        <button
          onClick={() => {
            updateFilters({ region: null, country: null });
          }}
          className={cn(
            "rounded-full px-2.5 py-1 text-xs font-medium transition-colors",
            !regionSlug
              ? "bg-primary text-primary-foreground"
              : "border border-border text-muted-foreground hover:bg-accent",
          )}
        >
          Tümü
        </button>
        {EVENT_REGIONS.map((r) => (
          <button
            key={r.slug}
            onClick={() => {
              // Switching region drops the country with it: a country
              // picked from Avrupa makes no sense pinned under Asya.
              updateFilters({
                region: regionSlug === r.slug ? null : r.slug,
                country: null,
              });
            }}
            className={cn(
              "rounded-full px-2.5 py-1 text-xs font-medium transition-colors",
              regionSlug === r.slug
                ? "bg-primary text-primary-foreground"
                : "border border-border text-muted-foreground hover:bg-accent",
            )}
          >
            {r.name}
          </button>
        ))}
        {/* Country, revealed by a region. A flat select of every country in
            the archive is 60 options a reader scrolls; scoped to the region
            they just chose it is the handful that region actually produced.
            With no region picked the picker stays out of the row entirely
            rather than offering the long list. */}
        {regionSlug && countriesInRegion.length > 0 && (
          <label className="ml-1 flex items-center gap-1.5 text-xs text-muted-foreground">
            <span className="sr-only">Ülke</span>
            <select
              value={countrySlug ?? ""}
              onChange={(event) =>
                updateFilters({ country: event.target.value || null })
              }
              className="rounded-full border border-border bg-background px-2.5 py-1 text-xs font-medium text-foreground transition-colors hover:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
            >
              <option value="">Tüm ülkeler</option>
              {countriesInRegion.map((country) => (
                <option key={country.name} value={country.name}>
                  {country.name} ({country.article_count})
                </option>
              ))}
            </select>
          </label>
        )}
        <button
          onClick={() => setShowMap((open) => !open)}
          className={cn(
            "ml-1 flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium transition-colors",
            showMap
              ? "bg-primary text-primary-foreground"
              : "border border-border text-muted-foreground hover:bg-accent",
          )}
        >
          <MapIcon className="size-3.5" />
          Harita
        </button>
      </div>

      {showMap && (
        <RegionMap
          value={regionSlug}
          onChange={(slug) => {
            updateFilters({ region: slug, country: null });
          }}
        />
      )}

      {/* Carrier filter -- entity-based, so a rival's fleet or finance news is
          caught too, not only stories filed under Rakip. "Ana Rakipler" is
          itself a button (all 9 rivals at once), "Tüm Taşıyıcılar" matches any
          airline mentioned in the news, TK sits first among the carriers in
          THY red, and each carrier chip wears its stylized tail fin. */}
      <div className="flex flex-wrap items-center gap-1.5">
        {(
          [
            ["RIVALS", "Ana Rakipler"],
            ["ALL", "Tüm Taşıyıcılar"],
          ] as const
        ).map(([value, label]) => {
          const active = airlineCode === value;
          return (
            <button
              key={value}
              onClick={() => {
                updateFilters({ airline: active ? null : value });
              }}
              className={cn(
                "rounded-full border px-3 py-1 text-xs font-semibold transition-colors",
                active
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border text-muted-foreground hover:bg-accent",
              )}
            >
              {label}
            </button>
          );
        })}
        <span aria-hidden className="mx-0.5 h-4 w-px bg-border" />
        {[TK, ...RIVALS].map((a) => {
          const active = airlineCode === a.code;
          return (
            <button
              key={a.code}
              title={a.name}
              onClick={() => {
                updateFilters({ airline: active ? null : a.code });
              }}
              style={active ? { backgroundColor: a.color, borderColor: a.color } : undefined}
              className={cn(
                "flex items-center gap-1 rounded-full border px-2 py-1 text-xs font-semibold tabular-nums transition-colors",
                active
                  ? "text-white"
                  : "border-border text-muted-foreground hover:bg-accent",
              )}
            >
              <span
                className={cn(
                  "flex size-4 items-center justify-center overflow-hidden rounded-[3px]",
                  active && "bg-white/85",
                )}
              >
                <AirlineLogo code={a.code} name={a.name} className="size-4" />
              </span>
              {a.code}
            </button>
          );
        })}
        {airlineCode && (
          <span className="text-xs text-muted-foreground">
            {AIRLINE_FILTER_LABEL[airlineCode] ??
              airlineTabs.find((a) => a.code === airlineCode)?.name}
          </span>
        )}
      </div>

      {/* The three summaries, in the order a reader scans them: what just
          happened, what matters most, what is coming. Each one hides itself
          entirely when it has nothing -- a heading over an empty grid is worse
          than no heading, and a permanent empty "Son Dakika" box teaches the
          reader to scroll past the place breaking news will appear. */}
      {showStrips && (
        <>
          <BreakingStrip
            category={categorySlug}
            minImportance={MIN_IMPORTANCE}
            excludedCategories={NEWSPAPER_EXCLUDED_CATEGORY_SLUGS}
          />
          <HighlightsRow
            category={categorySlug}
            excludedCategories={NEWSPAPER_EXCLUDED_CATEGORY_SLUGS}
          />
          <EventRadarStrip
            // Collapsed by default everywhere, but the Etkinlik tab is the one
            // place the radar IS the subject -- see the component's docstring
            // for the precedence between this and the reader's stored choice.
            autoExpand={categorySlug === "events"}
            onOpenCalendar={
              // The radar is a teaser for the calendar that already exists;
              // the link switches to it rather than duplicating it. Only
              // offered from the Etkinlik tab, where that toggle is on screen.
              categorySlug === "events" ? () => setEventView("calendar") : undefined
            }
          />
        </>
      )}

      {error ? (
        <p className="rounded-lg border border-dashed border-border p-6 text-sm text-muted-foreground">
          {error}
        </p>
      ) : loading && items.length === 0 ? (
        // Skeleton only on a cold start. Swapping a 30-row list for a 6-row
        // skeleton on every chip click collapsed the page and threw the scroll
        // position around; the list now stays put and is replaced in place.
        <ArticleListSkeleton />
      ) : items.length > 0 ? (
        <>
          {/* Date-sorted reading order: the backend already returns
              published_at desc, so grouping is a pure client-side pass over
              the list and re-runs whenever a page is appended. */}
          <div className={cn("flex flex-col gap-8 transition-opacity", loading && "opacity-60")}>
            {dayGroups.map((group, groupIndex) => {
              const isToday = group.key === todayGroupKey;
              return (
              <section key={group.key ?? "undated"} className="flex flex-col gap-3">
                <motion.h2
                  initial={reduceMotion ? false : { opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: reduceMotion ? 0 : 0.2 }}
                  style={
                    {
                      "--glow-color": isToday ? "var(--signal)" : "var(--primary)",
                    } as React.CSSProperties
                  }
                  className={cn(
                    "sticky top-[3.25rem] z-10 -mx-2 flex items-center gap-2 bg-background/85 px-2 py-2 text-lg font-bold backdrop-blur supports-[backdrop-filter]:bg-background/60",
                    isToday ? "text-signal" : "text-muted-foreground",
                  )}
                >
                  {/* A short approach-light bar leading into the date, amber
                      for today the way a threshold light is. */}
                  <span aria-hidden className="hairline-glow w-6 shrink-0" />
                  {group.label}
                  <span className="text-sm font-normal normal-case tracking-normal text-muted-foreground">
                    {group.articles.length} haber
                  </span>
                </motion.h2>
                {/* An apron of individually-lit tiles: the day is already
                    delimited by the sticky glowing date header above, so the
                    tiles need no shared container of their own. */}
                <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
                  <AnimatePresence initial={false}>
                    {group.articles.map((article, index) => (
                      <motion.div
                        key={article.id}
                        // Each wrapper is a direct grid child carrying its own
                        // initial/animate: variant propagation from a
                        // `display:contents` parent cannot be measured by
                        // Framer Motion and freezes the animation permanently.
                        className={cn("h-full", groupIndex === 0 && index === 0 && "sm:col-span-2")}
                        initial={reduceMotion ? false : { opacity: 0, y: 12, scale: 0.96 }}
                        animate={{ opacity: 1, y: 0, scale: 1 }}
                        transition={
                          reduceMotion
                            ? { duration: 0 }
                            : {
                                type: "spring",
                                stiffness: 320,
                                damping: 28,
                                mass: 0.9,
                                // Cap the stagger at 8 items. It used to cap at
                                // PAGE_LIMIT, so the last tile of a 30-item
                                // page only finished animating long after the
                                // data had arrived.
                                delay: Math.min(index + groupIndex, 8) * 0.03,
                              }
                        }
                      >
                        <ArticleCard article={article} variant="grid" />
                      </motion.div>
                    ))}
                  </AnimatePresence>
                </div>
              </section>
              );
            })}
          </div>

          <div className="flex justify-center">
            <Pagination page={page} totalPages={totalPages} onPageChange={setPage} />
          </div>
        </>
      ) : (
        <div className="rounded-lg border border-dashed border-border p-10 text-center">
          <p className="text-sm font-medium text-foreground">Bu filtreyle haber bulunamadı</p>
          <p className="mt-1 text-sm text-muted-foreground">
            {/* The window is a filter now, so the empty state names the one
                actually in force rather than a hard-coded 30. */}
            {activeWindow.unbounded
              ? "Tüm arşivde bu kategoride, seçili filtrelerle yayımlanmış haber yok."
              : `Seçili dönemde (${activeWindow.scopeLabel}) bu kategoride yayımlanmış haber yok.`}{" "}
            Başka bir filtre deneyin.
          </p>
        </div>
      )}
        </>
      )}
    </div>
  );
}

function ArticleListSkeleton() {
  return (
    <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: 6 }).map((_, i) => (
        <div
          key={i}
          className={cn(
            "flex flex-col gap-2 rounded-xl border border-border bg-card p-5",
            i === 0 && "sm:col-span-2",
          )}
        >
          <div className="flex items-center gap-2">
            <Skeleton className="h-4 w-20 rounded-full" />
            <Skeleton className="ml-auto h-3 w-8 rounded-full" />
          </div>
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-5/6" />
          <Skeleton className="mt-1.5 h-2.5 w-16" />
        </div>
      ))}
    </div>
  );
}
