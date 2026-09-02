"use client";

import { Archive as ArchiveIcon, Download, Map as MapIcon, SlidersHorizontal } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { AirlineLogo } from "@/components/airline-logo";
import { CategoryChipRow } from "@/components/filters/category-chip-row";
import { EventDetailDrawer } from "@/components/gazete/event-detail-drawer";
import { EventRadarStrip } from "@/components/gazete/event-radar-strip";
import { EventTimeline } from "@/components/gazete/event-timeline";
import { NewsSection } from "@/components/gazete/news-section";
import { TodayIntelligence } from "@/components/gazete/today-intelligence";
import { Collapse } from "@/components/ui/collapse";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api";
import {
  type GazeteFilters,
  parseFilters,
  serializeFilters,
  WINDOW_OPTIONS,
} from "@/lib/gazete";
import { airlineTabs } from "@/lib/nav";
import { EVENT_REGIONS, getCategory, NEWSPAPER_CATEGORY_SLUGS } from "@/lib/taxonomy";
import { RIVAL_CODES } from "@/lib/taxonomy.gen";
import type { CountryOut, EventOut } from "@/lib/types";
import { cn } from "@/lib/utils";

// The user's named main rivals, taken from the backend's own list rather than
// from "every branded carrier except TK": the "Ana Rakipler" chip sends
// airline=RIVALS, which the API expands to exactly RIVAL_CODES.
const RIVALS = airlineTabs.filter((a) => (RIVAL_CODES as readonly string[]).includes(a.code));
const TK = airlineTabs.find((a) => a.code === "TK")!;

// echarts + the world outline are only needed once the map is opened -- and it
// now lives two clicks in (the filter panel, then this toggle), so the chunk is
// never on the paper's first-paint path.
const RegionMap = dynamic(
  () => import("@/components/region-map").then((m) => m.RegionMap),
  { ssr: false, loading: () => <Skeleton className="h-[320px] w-full rounded-xl" /> },
);

const AIRLINE_FILTER_LABEL: Record<string, string> = {
  RIVALS: `${RIVAL_CODES.length} ana rakibin tümü`,
  ALL: "haberde geçen tüm havayolları",
};

/** The two beats that print news cards, in the owner's priority order.
 *
 * `events`, the paper's third category, has no card list of its own: the
 * Event Radar and the Event Timeline below are its section, and they are built
 * on the CURATED calendar (backend/app/models/event.py) rather than on
 * whatever the wire happened to file under "Etkinlik". A hand-checked date and
 * a demand read beat a news story about a fair every time.
 */
const NEWS_SECTION_SLUGS: readonly string[] = ["revenue_management", "airport"];

/** "Global Aviation Intelligence" -- the paper.
 *
 * FIVE BLOCKS, IN THIS ORDER, and the order is the argument: a standfirst,
 * then the two beats that move fares, then what is coming. Nothing else. What
 * used to be here and is not any more:
 *
 *   * a "Son Dakika" strip and a "Bugünün Öne Çıkanları" grid. Both were
 *     top-N queries over the same list they sat above, so the paper's first
 *     screen printed its best stories twice and then a third time. The
 *     sections themselves are now the critical selection (see
 *     backend/app/services/critical_selection.py), which is what those strips
 *     were approximating client-side.
 *   * the source-authority chips and the named-outlet row that PR #60 added.
 *     They asked a newsroom's question; this page answers a desk's.
 *   * pagination. Sections are capped and the archive is one click away, so
 *     there is no page 4 of a filtered list to land on and find empty.
 *
 * Filter state is URL-owned and read every render, so a filtered view is
 * shareable and the back button walks the filters rather than leaving the
 * page (Next's useSearchParams re-renders on popstate; there is no listener to
 * get wrong).
 */
export function NewspaperBrowser() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const filters = useMemo(
    () => parseFilters(new URLSearchParams(searchParams.toString())),
    [searchParams],
  );
  const { category: categorySlug, subcategory: subcategorySlug, region: regionSlug } = filters;

  const [filtersOpen, setFiltersOpen] = useState(false);
  const [showMap, setShowMap] = useState(false);
  const [openEvent, setOpenEvent] = useState<EventOut | null>(null);
  const [countries, setCountries] = useState<CountryOut[]>([]);

  /** Apply a patch to the URL.
   *
   * `router.replace`, not push: a filter row is a control the reader adjusts,
   * often several times in a row, and pushing every chip press would make the
   * back button undo them one at a time instead of leaving the page.
   * `scroll: false` because Next's default scroll-to-top would yank the page
   * on every press.
   */
  function updateFilters(patch: Partial<GazeteFilters>) {
    const params = serializeFilters({ ...filters, ...patch });
    const href = params.size ? `${pathname}?${params.toString()}` : pathname;
    router.replace(href, { scroll: false });
  }

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

  // Only the countries the chosen region actually produced -- the endpoint
  // already carries each country's region, so this is a filter rather than a
  // second request per region.
  const countriesInRegion = useMemo(
    () => (regionSlug ? countries.filter((c) => c.region === regionSlug) : []),
    [countries, regionSlug],
  );

  // Which sub-filters are actually in force. Printed on the toggle so a reader
  // who collapsed the row can still see that the paper is narrowed -- an
  // invisible active filter is how a page ends up looking empty for no
  // visible reason.
  const activeExtras = [subcategorySlug, regionSlug, filters.country, filters.airline].filter(
    Boolean,
  ).length;

  const showEvents = categorySlug === null || categorySlug === "events";
  const visibleNewsSlugs = NEWS_SECTION_SLUGS.filter(
    (slug) => categorySlug === null || categorySlug === slug,
  );
  const subcategories = categorySlug ? getCategory(categorySlug).subcategories : [];

  return (
    <div className="flex flex-col gap-10">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl font-semibold tracking-tight sm:text-[28px]">
            Global Aviation Intelligence
          </h1>
          <p className="text-sm text-muted-foreground">
            Gelir yönetimi masası için seçilmiş kritik gelişmeler.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link
            href="/archive"
            className="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            <ArchiveIcon className="size-3.5" />
            Arşiv
          </Link>
          <Link
            href={`/newspaper/${new Date().toISOString().slice(0, 10)}`}
            className="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            <Download className="size-3.5" />
            Günün Gazetesi
          </Link>
        </div>
      </header>

      {/* ONE visible filter row, and the rest behind a toggle. The paper used
          to open on five rows of chips -- time, tier, outlet, subcategory,
          region, carrier -- before a single headline. A reader arriving at a
          newspaper is not there to configure a query. */}
      <div className="flex flex-col gap-3 border-y border-border py-3">
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
          <CategoryChipRow
            value={categorySlug}
            // Region, country and carrier survive a section switch -- "show me
            // everything about Emirates" should stay pinned while moving
            // between beats. The subcategory cannot: it belongs to the section
            // being left.
            onChange={(slug) => updateFilters({ category: slug, subcategory: null })}
            slugs={NEWSPAPER_CATEGORY_SLUGS}
            pinned="revenue_management"
            includeAll
            focusStyling
            layoutId="newspaperCategoryPill"
            className="min-w-0 flex-1"
          />

          <div className="flex flex-wrap items-center gap-1.5">
            {WINDOW_OPTIONS.map((option) => (
              <button
                key={option.id}
                onClick={() => updateFilters({ window: option.id })}
                className={cn(
                  "rounded-full px-2 py-1 text-[11px] font-medium tabular-nums transition-colors",
                  filters.window === option.id
                    ? "bg-secondary text-secondary-foreground"
                    : "text-muted-foreground hover:bg-accent",
                )}
              >
                {option.label}
              </button>
            ))}
            <button
              type="button"
              onClick={() => setFiltersOpen((open) => !open)}
              aria-expanded={filtersOpen}
              className={cn(
                "ml-1 flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors",
                filtersOpen || activeExtras > 0
                  ? "bg-secondary text-secondary-foreground"
                  : "text-muted-foreground hover:bg-accent",
              )}
            >
              <SlidersHorizontal className="size-3.5" aria-hidden />
              Filtreler
              {activeExtras > 0 && (
                <span className="tabular-nums text-primary">{activeExtras}</span>
              )}
            </button>
          </div>
        </div>

        <Collapse open={filtersOpen}>
          <div className="flex flex-col gap-2 pt-2">
            {subcategories.length > 0 && (
              <FilterRow label="Alt kategori">
                <Chip
                  label="Tümü"
                  active={!subcategorySlug}
                  onClick={() => updateFilters({ subcategory: null })}
                />
                {subcategories.map((s) => (
                  <Chip
                    key={s.slug}
                    label={s.label}
                    active={subcategorySlug === s.slug}
                    onClick={() =>
                      updateFilters({
                        subcategory: subcategorySlug === s.slug ? null : s.slug,
                      })
                    }
                  />
                ))}
              </FilterRow>
            )}

            <FilterRow label="Bölge">
              <Chip
                label="Tümü"
                active={!regionSlug}
                onClick={() => updateFilters({ region: null, country: null })}
              />
              {EVENT_REGIONS.map((r) => (
                <Chip
                  key={r.slug}
                  label={r.name}
                  active={regionSlug === r.slug}
                  // Switching region drops the country with it: a country
                  // picked from Avrupa makes no sense pinned under Asya.
                  onClick={() =>
                    updateFilters({
                      region: regionSlug === r.slug ? null : r.slug,
                      country: null,
                    })
                  }
                />
              ))}
              {/* Country, revealed by a region. A flat select of every country
                  in the archive is 60 options a reader scrolls; scoped to the
                  region they just chose it is the handful that region actually
                  produced. */}
              {regionSlug && countriesInRegion.length > 0 && (
                <label className="ml-1 flex items-center gap-1.5 text-xs text-muted-foreground">
                  <span className="sr-only">Ülke</span>
                  <select
                    value={filters.country ?? ""}
                    onChange={(event) =>
                      updateFilters({ country: event.target.value || null })
                    }
                    className="rounded-full border border-border bg-background px-2.5 py-1 text-[11px] font-medium text-foreground transition-colors hover:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
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
              {/* The same Bölge filter, drawn. A chip row is the control; the
                  map is for a reader who thinks in geography rather than in
                  region names. Off by default and two clicks in, so the paper
                  never opens on it. */}
              <button
                type="button"
                onClick={() => setShowMap((open) => !open)}
                aria-expanded={showMap}
                className={cn(
                  "ml-1 flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors",
                  showMap
                    ? "bg-secondary text-secondary-foreground"
                    : "text-muted-foreground hover:bg-accent",
                )}
              >
                <MapIcon className="size-3.5" aria-hidden />
                Harita
              </button>
            </FilterRow>

            {showMap && (
              <RegionMap
                value={regionSlug}
                onChange={(slug) => updateFilters({ region: slug, country: null })}
              />
            )}

            {/* Carrier filter -- entity-based, so a rival's fleet or finance
                news is caught too, not only stories filed under Rakip. */}
            <FilterRow label="Havayolu">
              {(
                [
                  ["RIVALS", "Ana Rakipler"],
                  ["ALL", "Tüm Taşıyıcılar"],
                ] as const
              ).map(([value, label]) => (
                <Chip
                  key={value}
                  label={label}
                  active={filters.airline === value}
                  onClick={() =>
                    updateFilters({ airline: filters.airline === value ? null : value })
                  }
                />
              ))}
              <span aria-hidden className="mx-0.5 h-4 w-px bg-border" />
              {[TK, ...RIVALS].map((a) => {
                const active = filters.airline === a.code;
                return (
                  <button
                    key={a.code}
                    title={a.name}
                    onClick={() => updateFilters({ airline: active ? null : a.code })}
                    style={active ? { backgroundColor: a.color, borderColor: a.color } : undefined}
                    className={cn(
                      "flex items-center gap-1 rounded-full border px-2 py-1 text-[11px] font-semibold tabular-nums transition-colors",
                      active ? "text-white" : "border-transparent text-muted-foreground hover:bg-accent",
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
              {filters.airline && (
                <span className="text-[11px] text-muted-foreground">
                  {AIRLINE_FILTER_LABEL[filters.airline] ??
                    airlineTabs.find((a) => a.code === filters.airline)?.name}
                </span>
              )}
            </FilterRow>
          </div>
        </Collapse>
      </div>

      {/* Two or three sentences about the day, or -- with no digest row in the
          database -- nothing at all. See the component: an empty box where the
          paper's first sentence belongs is worse than no box. */}
      <TodayIntelligence />

      {visibleNewsSlugs.map((slug) => (
        <NewsSection key={slug} categorySlug={slug} filters={filters} />
      ))}

      {showEvents && (
        <>
          <EventRadarStrip
            // The radar IS the subject of the Etkinlik view, so it opens
            // itself there -- see the component's docstring for how that
            // interacts with the reader's stored choice.
            autoExpand={categorySlug === "events"}
            onSelect={setOpenEvent}
          />
          <EventTimeline onSelect={setOpenEvent} />
        </>
      )}

      {/* One detail panel for both event blocks, owned here: two drawers over
          the same rows could disagree about what they show. */}
      <EventDetailDrawer event={openEvent} onClose={() => setOpenEvent(null)} />
    </div>
  );
}

function FilterRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="w-20 shrink-0 text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
        {label}
      </span>
      {children}
    </div>
  );
}

function Chip({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors",
        active
          ? "bg-secondary text-secondary-foreground"
          : "text-muted-foreground hover:bg-accent",
      )}
    >
      {label}
    </button>
  );
}
