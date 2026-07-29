"use client";

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { CalendarDays, Download, List, Map as MapIcon } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { ArticleCard } from "@/components/article-card";
import { CategoryChipRow } from "@/components/filters/category-chip-row";
import { EventsCalendar } from "@/components/events-calendar";
import { AirlineLogo } from "@/components/airline-logo";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api";
import { airlineTabs } from "@/lib/nav";
import { CATEGORIES, EVENT_REGIONS } from "@/lib/taxonomy";
import type { ArticleListOut, ArticleOut } from "@/lib/types";
import { cn } from "@/lib/utils";

// echarts + the world outline are only needed once the map is opened.
const RegionMap = dynamic(
  () => import("@/components/region-map").then((m) => m.RegionMap),
  { ssr: false, loading: () => <Skeleton className="h-[320px] w-full rounded-xl" /> },
);

// The user's named main rivals -- TK is the home carrier, not a rival.
const RIVALS = airlineTabs.filter((a) => a.code !== "TK");
const TK = airlineTabs.find((a) => a.code === "TK")!;

// Filter-row summary for the two aggregate chips.
const AIRLINE_FILTER_LABEL: Record<string, string> = {
  RIVALS: "9 ana rakibin tümü",
  ALL: "haberde geçen tüm havayolları",
};

// Only recent articles -- keeps the browser focused on "what's current"
// rather than the entire archive, per the freshness feedback on this page.
const DAYS_WINDOW = 30;
const PAGE_LIMIT = 30;

// "28 Temmuz 2026" -- one formatter for the whole list, same reasoning as
// ArticleCard's PUBLISHED_FORMAT.
const DAY_HEADER_FORMAT = new Intl.DateTimeFormat("tr-TR", {
  day: "numeric",
  month: "long",
  year: "numeric",
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

  // Opening filters can come from the URL, so Know How's "Gelir Yönetimi
  // haberleri" link lands on the paper already filtered and a filtered view is
  // shareable. Read once, as the initial state: after that the chips own the
  // filters, and re-reading the URL would fight them.
  const searchParams = useSearchParams();
  const initial = useMemo(() => {
    const wanted = searchParams.get("category");
    return {
      // An unknown slug would filter to nothing and look broken; fall back.
      category: CATEGORIES.some((c) => c.slug === wanted) ? wanted! : CATEGORIES[0].slug,
      subcategory: searchParams.get("subcategory"),
      region: searchParams.get("region"),
      airline: searchParams.get("airline"),
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- deliberately the first URL only
  }, []);

  const [categorySlug, setCategorySlug] = useState(initial.category); // Gelir Yönetimi default
  const [subcategorySlug, setSubcategorySlug] = useState<string | null>(initial.subcategory);
  const [regionSlug, setRegionSlug] = useState<string | null>(initial.region);
  // An IATA code, or the aggregate values "RIVALS" / "ALL" the API understands.
  const [airlineCode, setAirlineCode] = useState<string | null>(initial.airline);
  const [eventView, setEventView] = useState<"news" | "calendar">("news");
  const [showMap, setShowMap] = useState(false);

  const [items, setItems] = useState<ArticleOut[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true); // first page (filter change)
  const [loadingMore, setLoadingMore] = useState(false); // subsequent pages
  const [error, setError] = useState<string | null>(null);

  const [counts, setCounts] = useState<Record<string, number>>({});

  const category = CATEGORIES.find((c) => c.slug === categorySlug) ?? CATEGORIES[0];

  function selectCategory(slug: string) {
    setCategorySlug(slug);
    setSubcategorySlug(null);
    // Region and rival filters deliberately survive a category switch: "show me
    // everything about Emirates" should stay pinned while browsing categories.
    setOffset(0);
  }

  // Tab badges: one grouped request, refreshed when the window is entered.
  useEffect(() => {
    const controller = new AbortController();
    apiFetch<Record<string, number>>(`/articles/counts?days=${DAYS_WINDOW}`, {
      cache: "default",
      signal: controller.signal,
    })
      .then(setCounts)
      .catch(() => {
        /* badges are decorative -- a failure here must not break the list */
      });
    return () => controller.abort();
  }, []);

  // Article list. offset===0 replaces (a filter changed); offset>0 appends
  // ("Daha fazla yükle"). Both live in one effect so they can't race.
  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const params = new URLSearchParams({
      category: categorySlug,
      days: String(DAYS_WINDOW),
      limit: String(PAGE_LIMIT),
      offset: String(offset),
    });
    if (subcategorySlug) params.set("subcategory", subcategorySlug);
    if (regionSlug) params.set("region", regionSlug);
    if (airlineCode) params.set("airline", airlineCode);

    const isFirstPage = offset === 0;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch driven by filter/offset change; the loading flag must flip synchronously with the dependency change
    if (isFirstPage) setLoading(true);
    else setLoadingMore(true);

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
        setItems((prev) => (isFirstPage ? data.items : [...prev, ...data.items]));
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
        setLoadingMore(false);
      });
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [categorySlug, subcategorySlug, regionSlug, airlineCode, offset]);

  const today = new Date().toISOString().slice(0, 10);
  const hasMore = items.length < total;
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
          <p className="text-sm text-muted-foreground">
            Kategoriye göre doğrulanmış, güncel havacılık haberleri.
          </p>
        </div>
        <Link
          href={`/newspaper/${today}`}
          className="flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-accent"
        >
          <Download className="size-3.5" />
          Günün Gazetesi
        </Link>
      </div>

      {/* Sticky category bar -- horizontally scrollable on mobile, blurred so
          content reads through it while scrolling. */}
      <div className="sticky top-0 z-20 -mx-2 border-b border-border bg-background/80 px-2 pb-3 pt-2 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        {/* Gelir Yönetimi is pinned first and keeps its amber identity even
            when inactive -- see CategoryChipRow, shared with Öneriler. */}
        <CategoryChipRow
          value={categorySlug}
          onChange={(slug) => selectCategory(slug ?? CATEGORIES[0].slug)}
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
      {category.subcategories.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          <button
            onClick={() => {
              setSubcategorySlug(null);
              setOffset(0);
            }}
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
                setSubcategorySlug(s.slug);
                setOffset(0);
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
            setRegionSlug(null);
            setOffset(0);
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
              setRegionSlug(regionSlug === r.slug ? null : r.slug);
              setOffset(0);
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
            setRegionSlug(slug);
            setOffset(0);
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
                setAirlineCode(active ? null : value);
                setOffset(0);
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
                setAirlineCode(active ? null : a.code);
                setOffset(0);
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
                    "sticky top-[3.25rem] z-10 -mx-2 flex items-center gap-2 bg-background/85 px-2 py-1.5 text-xs font-semibold uppercase tracking-wider backdrop-blur supports-[backdrop-filter]:bg-background/60",
                    isToday ? "text-signal" : "text-muted-foreground",
                  )}
                >
                  {/* A short approach-light bar leading into the date, amber
                      for today the way a threshold light is. */}
                  <span aria-hidden className="hairline-glow w-6 shrink-0" />
                  {group.label}
                  <span className="font-normal normal-case tracking-normal text-muted-foreground">
                    {group.articles.length} haber
                  </span>
                </motion.h2>
                <div className="flex flex-col divide-y divide-border rounded-xl border border-border bg-card">
                  <AnimatePresence initial={false}>
                    {group.articles.map((article, index) => (
                      <motion.div
                        key={article.id}
                        initial={reduceMotion ? false : { opacity: 0, y: 8 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{
                          duration: reduceMotion ? 0 : 0.18,
                          // Cap the stagger at 8 items (~160ms). It used to cap
                          // at PAGE_LIMIT, so the last row of a 30-item page
                          // only finished animating ~800ms after the data had
                          // arrived -- the single most visible part of "the
                          // buttons feel slow".
                          delay: reduceMotion ? 0 : Math.min(index + groupIndex, 8) * 0.02,
                        }}
                      >
                        <ArticleCard article={article} />
                      </motion.div>
                    ))}
                  </AnimatePresence>
                </div>
              </section>
              );
            })}
          </div>

          {hasMore && (
            <div className="flex justify-center">
              <button
                onClick={() => setOffset(items.length)}
                disabled={loadingMore}
                className="rounded-md border border-border px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-accent disabled:opacity-60"
              >
                {loadingMore ? "Yükleniyor…" : `Daha fazla yükle (${total - items.length})`}
              </button>
            </div>
          )}
        </>
      ) : (
        <div className="rounded-lg border border-dashed border-border p-10 text-center">
          <p className="text-sm font-medium text-foreground">Bu filtreyle haber bulunamadı</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Son {DAYS_WINDOW} günde bu kategoride yayımlanmış haber yok. Başka bir kategori
            veya alt başlık deneyin.
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
    <div className="flex flex-col divide-y divide-border rounded-xl border border-border bg-card">
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="flex flex-col gap-2 p-4">
          <div className="flex items-center gap-2">
            <Skeleton className="h-4 w-20 rounded-full" />
            <Skeleton className="h-4 w-16 rounded-full" />
            <Skeleton className="h-4 w-24 rounded-full" />
          </div>
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-5/6" />
        </div>
      ))}
    </div>
  );
}
