"use client";

import { Search, X } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo, useState } from "react";

import { DataSourceError, LastUpdatedStamp, StaleDataBanner } from "@/components/data-source-error";
import { MotionList } from "@/components/motion/motion-list";
import { RiskCategoryBreakdown } from "@/components/risk/risk-category-breakdown";
import { CountrySection } from "@/components/risk/risk-country-section";
import { RiskDetailDrawer } from "@/components/risk/risk-detail-drawer";
import {
  CoverageBadge,
  FAMILY_META,
  TYPE_META,
  TYPE_ORDER,
} from "@/components/risk/risk-meta";
import { RiskTrendChart } from "@/components/risk/risk-trend-chart-lazy";
import { severityMeta } from "@/components/risk/severity-pill";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useDataSource } from "@/hooks/use-data-source";
import { apiFetch } from "@/lib/api";
import { relativeTimeTr } from "@/lib/campaigns";
import { worldRegions } from "@/lib/nav";
import {
  EMPTY_RISK_FILTERS,
  filterRiskCountries,
  liveFeedItems,
  UNKNOWN_COUNTRY,
  type RiskFilters,
} from "@/lib/risk";
import type { RiskCountry, RiskItem, RiskRadarOut, RiskTrendOut } from "@/lib/types";
import { cn } from "@/lib/utils";

// echarts only needed once the map renders -- Faz 14, same pattern as
// newspaper-browser.tsx's RegionMap.
const RiskMap = dynamic(
  () => import("@/components/risk-map").then((m) => m.RiskMap),
  {
    ssr: false,
    loading: () => <Skeleton className="h-[280px] w-full rounded-xl sm:h-[420px]" />,
  },
);

/** The windows the days chips offer.
 *
 * 5 days is the floor and the default, down from a 7-day floor and a 14-day
 * default. A risk radar's subject is what is happening now, and a fortnight is
 * not now: at 14 days the page routinely opened on a story whose newest telling
 * was a week old, drawn at the same weight as one from this morning.
 *
 * The old floor's reasoning -- that a short window looks empty because the
 * clock is short rather than because the world is quiet -- still stands, and is
 * why the floor is five days rather than 24 hours. Five is the shortest window
 * that spans a full ingest weekend.
 *
 * The longer windows are all still selectable: the shorter default is a
 * statement about what the page opens on, not a claim that the older window is
 * useless. Mirrors DEFAULT_WINDOW_DAYS in backend app/api/v1/risks.py -- the
 * two are the same decision and must not drift.
 *
 * 30 is what the trend chart draws regardless of the list's window, so the
 * shape below never changes shape just because someone narrowed the list. */
const DAY_WINDOWS = [5, 7, 14, 30, 90] as const;
const DEFAULT_DAYS = 5;
const TREND_DAYS = 30;

/** The lit-chip pattern shared with Gazete/Hub/Öneriler. Note there is
 * no REGION_GLOW anywhere on this page: the chrome stays neutral so the only
 * saturated things on screen are the few item cards that earn it. */
const chip = (active: boolean) =>
  cn(
    "flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
    active
      ? "bg-primary/12 text-primary ring-1 ring-primary/40 dark:glow-soft"
      : "border border-border text-muted-foreground hover:bg-accent",
  );

export function RiskRadarClient() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  // ?days and ?country stay URL-owned for their whole life: those two are what
  // makes a view worth sending to someone ("Yunanistan, son 30 gün"). The rest
  // of the filters are chip-owned -- putting seven params in the bar would make
  // every chip click a history entry and the back button useless.
  const daysParam = Number(searchParams.get("days"));
  const days = DAY_WINDOWS.includes(daysParam as (typeof DAY_WINDOWS)[number])
    ? daysParam
    : DEFAULT_DAYS;
  const country = searchParams.get("country");

  const setUrlState = useCallback(
    (next: { days?: number; country?: string | null }) => {
      const params = new URLSearchParams(searchParams.toString());
      if (next.days !== undefined) {
        if (next.days === DEFAULT_DAYS) params.delete("days");
        else params.set("days", String(next.days));
      }
      if (next.country !== undefined) {
        if (next.country === null) params.delete("country");
        else params.set("country", next.country);
      }
      router.replace(params.size ? `${pathname}?${params.toString()}` : pathname, {
        scroll: false,
      });
    },
    [pathname, router, searchParams],
  );

  const setCountry = useCallback(
    (value: string | null) => setUrlState({ country: value }),
    [setUrlState],
  );

  /** The audit view, opened on the SAME window this page is showing.
   *
   * The link used to be bare. The funnel then opened on its own 5-day default
   * and the reader compared a 30-day radar against a 5-day audit -- two
   * different sets of days under one question ("do I believe what I just
   * looked at"), with nothing on either screen saying they were different.
   * risk-verification-client.tsx's own docstring forbids exactly this.
   *
   * `country` rides along too. The audit endpoints cannot narrow by country --
   * `/risks/quality` and `/risks/rejected` take days and reason only -- so it
   * is carried as memory rather than as a filter: the audit says out loud that
   * it is not narrowed, and its way back returns the reader to the country
   * they were looking at instead of dropping them on an unfiltered radar. */
  const verificationHref = useMemo(() => {
    const params = new URLSearchParams();
    if (days !== DEFAULT_DAYS) params.set("days", String(days));
    if (country) params.set("country", country);
    return params.size
      ? `/risk-radari/dogrulama?${params.toString()}`
      : "/risk-radari/dogrulama";
  }, [days, country]);

  const radar = useDataSource<RiskRadarOut>(
    (signal) => apiFetch<RiskRadarOut>(`/risks?days=${days}`, { cache: "default", signal }),
    [days],
  );
  // The trend is its own source: a 30-day aggregate failing must thin the page
  // by one section, never blank the radar above it. Faz 12's contract, applied
  // per section rather than per page.
  const trend = useDataSource<RiskTrendOut>(
    (signal) =>
      apiFetch<RiskTrendOut>(`/risks/trend?days=${TREND_DAYS}`, { cache: "default", signal }),
    [],
  );

  const [family, setFamily] = useState<string | null>(null);
  const [type, setType] = useState<string | null>(null);
  const [severity, setSeverity] = useState<string | null>(null);
  const [region, setRegion] = useState<string | null>(null);
  const [onlyNew, setOnlyNew] = useState(false);
  const [onlyUpdated, setOnlyUpdated] = useState(false);
  const [search, setSearch] = useState("");

  const [selected, setSelected] = useState<RiskItem | null>(null);

  const data = radar.data;

  const filters: RiskFilters = useMemo(
    () => ({
      ...EMPTY_RISK_FILTERS,
      family,
      type,
      severity,
      region,
      country,
      onlyNew,
      onlyUpdated,
      search,
    }),
    [family, type, severity, region, country, onlyNew, onlyUpdated, search],
  );

  // Filtering is client-side on purpose: /risks returns the whole (already
  // small) classified set for the window in one payload, so narrowing it in
  // memory is exact and costs no round trip. The per-country score and severity
  // counts are recomputed for the FILTERED view inside filterRiskCountries --
  // a ranking that ignored the active filters would contradict the list.
  const visible = useMemo<RiskCountry[]>(
    () => (data ? filterRiskCountries(data.countries, filters) : []),
    [data, filters],
  );

  const stats = useMemo(() => {
    let total = 0;
    let high = 0;
    let fresh = 0;
    let updated = 0;
    for (const group of visible) {
      total += group.count;
      high += group.severity_counts.high;
      for (const item of group.items) {
        if (item.is_fresh) fresh += 1;
        if (item.is_updated) updated += 1;
      }
    }
    const placedCountries = visible.filter((g) => g.country !== UNKNOWN_COUNTRY).length;
    return { total, high, fresh, updated, countries: placedCountries };
  }, [visible]);

  const feed = useMemo(() => liveFeedItems(visible), [visible]);

  // Only offer chips that can match something.
  const availableTypes = useMemo(() => {
    if (!data) return [];
    return TYPE_ORDER.filter(
      (slug) => (data.type_counts[slug] ?? 0) > 0 && (!family || TYPE_META[slug].family === family),
    );
  }, [data, family]);

  const availableRegions = useMemo(() => {
    if (!data) return [];
    const seen = new Set<string>();
    for (const group of data.countries) {
      for (const item of group.items) if (item.region) seen.add(item.region);
    }
    return worldRegions.filter((r) => seen.has(r.slug));
  }, [data]);

  const availableSeverities = useMemo(() => {
    if (!data) return [];
    const seen = new Set<string>();
    for (const group of data.countries) {
      for (const item of group.items) seen.add(item.severity);
    }
    return ["high", "medium", "low"].filter((s) => seen.has(s));
  }, [data]);

  const anyFilterActive =
    family !== null ||
    type !== null ||
    severity !== null ||
    region !== null ||
    country !== null ||
    onlyNew ||
    onlyUpdated ||
    search.trim() !== "";

  function clearFilters() {
    setFamily(null);
    setType(null);
    setSeverity(null);
    setRegion(null);
    setOnlyNew(false);
    setOnlyUpdated(false);
    setSearch("");
    setCountry(null);
  }

  const generatedAt = data ? new Date(data.generated_at) : radar.lastUpdated;

  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-col gap-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex min-w-0 flex-col gap-1">
            <h1 className="text-2xl font-semibold tracking-tight">Risk Radarı</h1>
            <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground">
              Haber akışından sınıflandırılmış doğal afet ve çatışma sinyalleri; her
              sinyalin arkasındaki kaynaklarla birlikte.
            </p>
          </div>
          <div className="flex shrink-0 flex-col items-end gap-1">
            <LastUpdatedStamp date={generatedAt} />
            <span className="flex items-center gap-2">
              {/* The audit view lives on its own route and is reached from
                  here rather than rendered here: this page is read by someone
                  deciding something, and a nine-stage funnel plus an
                  eight-column rejection table would cost every reader
                  attention to serve the few who came to check the pipeline.
                  One quiet link is the whole footprint it gets. */}
              <Link
                href={verificationHref}
                className="text-[11px] font-medium text-muted-foreground underline-offset-2 hover:text-foreground hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
              >
                Veri doğrulama
              </Link>
              <button
                type="button"
                onClick={radar.retry}
                className="text-[11px] font-medium text-muted-foreground underline-offset-2 hover:text-foreground hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
              >
                Yenile
              </button>
            </span>
          </div>
        </div>

        {data && data.total > 0 && (
          <div className="flex flex-wrap gap-x-4 gap-y-1.5 rounded-lg border border-border bg-background/50 px-3 py-2">
            <Kpi label="Aktif sinyal" value={stats.total} suffix={`/ ${data.total}`} />
            <Kpi label="Yüksek şiddet" value={stats.high} tone={stats.high > 0 ? "critical" : undefined} />
            <Kpi label="Ülke" value={stats.countries} />
            <Kpi label="Son 24s yeni" value={stats.fresh} />
            <Kpi label="Güncellenen" value={stats.updated} />
          </div>
        )}

        {/* Stating plainly what this is NOT is the strongest anti-alarmism move
            available, and it belongs above the fold rather than in a footnote. */}
        <p className="text-[11px] leading-relaxed text-muted-foreground">
          Operasyonel farkındalık için; resmî uyarı sistemi değildir. Zaman
          bilgileri haberlerin yayın anlarıdır, olayların gerçekleşme anı değildir.
          {/* Said out loud rather than left as a silent gap between "kaç haber
              sınıflandı" and "kaç sinyal görüyorum". A list that quietly drops
              rows is a list whose counts nobody can reconcile. */}
          {data && data.suppressed_low_confidence > 0 && (
            <>
              {" "}
              Tek kaynaklı ve güven eşiğinin altında kalan{" "}
              <span className="tabular-nums">{data.suppressed_low_confidence}</span> sinyal
              bu listede gösterilmiyor.
            </>
          )}
        </p>
      </header>

      {radar.stale && (
        <StaleDataBanner
          onRetry={radar.retry}
          lastUpdated={radar.lastUpdated}
          pending={radar.pending}
        />
      )}

      {radar.error && !data ? (
        <DataSourceError
          onRetry={radar.retry}
          lastUpdated={radar.lastUpdated}
          pending={radar.pending}
        />
      ) : !data ? (
        <div className="flex flex-col gap-6">
          <Skeleton className="h-20 w-full rounded-xl" />
          <Skeleton className="h-[280px] w-full rounded-xl sm:h-[420px]" />
          <Skeleton className="h-64 w-full rounded-xl" />
        </div>
      ) : (
        <>
          <div className="flex flex-col gap-3 rounded-lg border border-border bg-background/50 p-3">
            <div className="flex flex-wrap items-center gap-1.5">
              <FilterLabel>Dönem</FilterLabel>
              {DAY_WINDOWS.map((window) => (
                <button
                  key={window}
                  type="button"
                  onClick={() => setUrlState({ days: window })}
                  aria-pressed={days === window}
                  className={chip(days === window)}
                >
                  {window}g
                </button>
              ))}

              <span className="ml-auto flex items-center gap-1.5">
                <label className="relative flex items-center">
                  <Search
                    className="pointer-events-none absolute left-2 size-3.5 text-muted-foreground"
                    aria-hidden
                  />
                  <Input
                    type="search"
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                    placeholder="Başlık, ülke, kaynak ara"
                    aria-label="Sinyallerde ara"
                    className="w-48 pl-7 text-xs"
                  />
                </label>
                {anyFilterActive && (
                  <button
                    type="button"
                    onClick={clearFilters}
                    className="flex items-center gap-1 rounded-full border border-border px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
                  >
                    <X className="size-3" aria-hidden />
                    Filtreleri temizle
                  </button>
                )}
              </span>
            </div>

            <div className="flex flex-wrap items-center gap-1.5">
              <FilterLabel>Aile</FilterLabel>
              <button
                type="button"
                onClick={() => {
                  setFamily(null);
                  setType(null);
                }}
                className={chip(!family)}
              >
                Tümü
              </button>
              {Object.entries(FAMILY_META).map(([slug, label]) => (
                <button
                  key={slug}
                  type="button"
                  onClick={() => {
                    const next = family === slug ? null : slug;
                    setFamily(next);
                    // A type chip from the other family would silently return
                    // zero rows; clear it rather than show an empty page.
                    if (next && type && TYPE_META[type]?.family !== next) setType(null);
                  }}
                  className={chip(family === slug)}
                >
                  {label}
                  <span className="ml-0.5 tabular-nums opacity-70">
                    {data.family_counts[slug] ?? 0}
                  </span>
                </button>
              ))}

              <span className="mx-1 h-4 w-px bg-border" aria-hidden />

              <FilterLabel>Akış</FilterLabel>
              <button
                type="button"
                onClick={() => setOnlyNew((value) => !value)}
                aria-pressed={onlyNew}
                title="İlk haberi son 24 saat içinde yayımlanan sinyaller"
                className={chip(onlyNew)}
              >
                Yeni
              </button>
              <button
                type="button"
                onClick={() => setOnlyUpdated((value) => !value)}
                aria-pressed={onlyUpdated}
                title="Daha eski olaylar; son 24 saatte yeni haber eklenmiş"
                className={chip(onlyUpdated)}
              >
                Güncellendi
              </button>
            </div>

            {availableTypes.length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5">
                <FilterLabel>Tür</FilterLabel>
                <button type="button" onClick={() => setType(null)} className={chip(!type)}>
                  Tümü
                </button>
                {availableTypes.map((slug) => {
                  const meta = TYPE_META[slug];
                  const Icon = meta.icon;
                  return (
                    <button
                      key={slug}
                      type="button"
                      onClick={() => setType(type === slug ? null : slug)}
                      className={chip(type === slug)}
                    >
                      <Icon className="size-3.5" aria-hidden />
                      {meta.label}
                      <span className="ml-0.5 tabular-nums opacity-70">
                        {data.type_counts[slug] ?? 0}
                      </span>
                    </button>
                  );
                })}
              </div>
            )}

            {(availableSeverities.length > 0 || availableRegions.length > 0) && (
              <div className="flex flex-wrap items-center gap-1.5">
                <FilterLabel>Şiddet</FilterLabel>
                <button type="button" onClick={() => setSeverity(null)} className={chip(!severity)}>
                  Tümü
                </button>
                {availableSeverities.map((slug) => {
                  const meta = severityMeta(slug);
                  const Icon = meta.icon;
                  return (
                    <button
                      key={slug}
                      type="button"
                      onClick={() => setSeverity(severity === slug ? null : slug)}
                      className={chip(severity === slug)}
                    >
                      <Icon className="size-3.5" aria-hidden />
                      {meta.label}
                    </button>
                  );
                })}

                {availableRegions.length > 0 && (
                  <>
                    <span className="mx-1 h-4 w-px bg-border" aria-hidden />
                    <FilterLabel>Bölge</FilterLabel>
                    <button
                      type="button"
                      onClick={() => setRegion(null)}
                      className={chip(!region)}
                    >
                      Tümü
                    </button>
                    {availableRegions.map((r) => (
                      <button
                        key={r.slug}
                        type="button"
                        onClick={() => setRegion(region === r.slug ? null : r.slug)}
                        className={chip(region === r.slug)}
                      >
                        {r.name}
                      </button>
                    ))}
                  </>
                )}
              </div>
            )}

            {country && (
              <div className="flex flex-wrap items-center gap-1.5">
                <FilterLabel>Ülke</FilterLabel>
                <button type="button" onClick={() => setCountry(null)} className={chip(true)}>
                  {country}
                  <X className="size-3" aria-hidden />
                </button>
              </div>
            )}
          </div>

          {data.total === 0 ? (
            <EmptyRadar days={days} />
          ) : (
            <div className="flex flex-col gap-8">
              <RiskMap
                countries={visible}
                selectedCountry={country}
                onSelectCountry={setCountry}
                onOpenItem={setSelected}
              />

              <div className="flex flex-col gap-6 xl:flex-row-reverse xl:items-start">
                <div className="flex flex-col gap-6 xl:w-72 xl:shrink-0">
                  <HotSpots countries={visible} selected={country} onSelect={setCountry} />
                  <LiveFeed rows={feed} onSelect={setSelected} />
                </div>

                <div className="flex min-w-0 flex-1 flex-col gap-4">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <h2 className="text-sm font-semibold">
                      Sınıflandırılan olaylar{" "}
                      <span className="font-normal text-muted-foreground">
                        (son {data.days} gün)
                      </span>
                    </h2>
                    <span className="text-xs tabular-nums text-muted-foreground">
                      {stats.total} / {data.total} sinyal
                    </span>
                  </div>

                  {visible.length === 0 ? (
                    <p className="rounded-lg border border-dashed border-border py-16 text-center text-sm text-muted-foreground">
                      Bu filtrelerle sinyal yok. Arama, tür, şiddet veya bölge
                      seçimini kaldırın.
                    </p>
                  ) : (
                    // No AnimatePresence around these sections. It was here to
                    // animate a country out when a filter removed it, and in
                    // this stack (framer-motion 12 + React 19, `popLayout`)
                    // the exit never resolved: filtered-out sections stayed in
                    // the DOM permanently, so narrowing to one wildfire still
                    // showed twelve country headings. A filter that visibly
                    // does not filter is a far worse failure than a section
                    // that disappears without a fade, and the entrance stagger
                    // -- which does work -- is kept.
                    <MotionList className="flex flex-col gap-8">
                      {visible.map((group) => (
                        <CountrySection
                          key={group.country}
                          group={group}
                          // The window the DATA covers, not the chip that is
                          // lit: those differ for a moment while a new window
                          // loads, and an age tag drawn against the wrong
                          // window is worse than one drawn a beat late.
                          windowDays={data.days}
                          onSelect={setSelected}
                        />
                      ))}
                    </MotionList>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Outside the empty branch on purpose. The trend draws a fixed
              window regardless of the list's, so on a quiet week "son 7 günde
              sinyal yok" plus "here is what the last stretch looked like" is a
              more useful answer than a bare empty box -- and it is the one
              section that still has something true to say when the radar is
              silent. The breakdown renders nothing of its own accord when
              there is nothing visible. */}
          <div className="grid gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
            <section className="flex flex-col gap-3 rounded-xl border border-border bg-card bg-card-sheen p-4 shadow-elev-1">
              <div className="flex flex-col gap-1">
                <h2 className="text-sm font-semibold">Yayın hacmi</h2>
                <p className="text-[11px] leading-relaxed text-muted-foreground">
                  Son {TREND_DAYS} günde günlük risk haberi sayısı — sayfanın dönem
                  seçiminden bağımsızdır, şekil karşılaştırılabilir kalsın diye.
                </p>
              </div>
              {trend.error && !trend.data ? (
                <DataSourceError
                  onRetry={trend.retry}
                  lastUpdated={trend.lastUpdated}
                  pending={trend.pending}
                />
              ) : trend.data ? (
                <RiskTrendChart trend={trend.data} />
              ) : (
                <Skeleton className="h-[280px] w-full rounded-xl" />
              )}
            </section>

            <RiskCategoryBreakdown
              countries={visible}
              selectedType={type}
              onSelectType={setType}
            />
          </div>
        </>
      )}

      <RiskDetailDrawer item={selected} onClose={() => setSelected(null)} />
    </div>
  );
}

function FilterLabel({ children }: { children: React.ReactNode }) {
  return (
    <span className="w-12 shrink-0 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
      {children}
    </span>
  );
}

function Kpi({
  label,
  value,
  suffix,
  tone,
}: {
  label: string;
  value: number;
  suffix?: string;
  tone?: "critical";
}) {
  return (
    <span className="flex items-baseline gap-1.5">
      <span className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</span>
      <span
        className={cn(
          "text-sm font-semibold tabular-nums",
          tone === "critical" && "text-critical",
        )}
      >
        {value}
      </span>
      {suffix && (
        <span className="text-[11px] tabular-nums text-muted-foreground">{suffix}</span>
      )}
    </span>
  );
}

/** "Sıcak Noktalar": the worst-hit countries by the weighted score.
 *
 * The segmented micro-bar is followed by the counts as literal text ("3Y · 1O")
 * so the bar is never the only encoding of the split -- a reader who cannot
 * separate the segments still gets the numbers. */
function HotSpots({
  countries,
  selected,
  onSelect,
}: {
  countries: RiskCountry[];
  selected: string | null;
  onSelect: (country: string | null) => void;
}) {
  // Excluded outright rather than merely sorted last: a ranking of the
  // worst-hit countries has no row for "we could not tell which country".
  const top = countries.filter((c) => c.country !== UNKNOWN_COUNTRY).slice(0, 8);
  if (top.length === 0) return null;

  return (
    <section className="flex flex-col gap-3 rounded-xl border border-border bg-card bg-card-sheen p-4 shadow-elev-1">
      <div className="flex flex-col gap-1.5">
        <h2 className="text-sm font-semibold">Sıcak Noktalar</h2>
        <p className="text-[11px] leading-relaxed text-muted-foreground">
          Ağırlıklı puana göre: yüksek 3, orta 2, düşük 1.
        </p>
      </div>
      <ol className="flex flex-col gap-2.5">
        {top.map((group, index) => {
          const { high, medium, low } = group.severity_counts;
          const total = Math.max(1, high + medium + low);
          const parts: { key: string; n: number; className: string }[] = [
            { key: "high", n: high, className: "bg-critical" },
            { key: "medium", n: medium, className: "bg-warning" },
            { key: "low", n: low, className: "bg-muted-foreground/40" },
          ];
          const active = selected === group.country;
          return (
            <li key={group.country}>
              <button
                type="button"
                onClick={() => onSelect(active ? null : group.country)}
                aria-pressed={active}
                className={cn(
                  "flex w-full flex-col gap-1.5 rounded-lg border px-2.5 py-2 text-left transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
                  active
                    ? "border-primary/40 bg-primary/5"
                    : "border-transparent hover:border-border hover:bg-accent/50",
                )}
              >
                <div className="flex items-baseline gap-2">
                  <span className="w-5 shrink-0 font-mono text-[11px] tabular-nums text-muted-foreground">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-xs font-medium">
                    {group.country}
                  </span>
                  <span className="shrink-0 font-mono text-[11px] tabular-nums text-muted-foreground">
                    {group.score}
                  </span>
                </div>
                <div className="flex items-center gap-2 pl-7">
                  <div className="flex h-1.5 flex-1 gap-px overflow-hidden rounded-full">
                    {parts
                      .filter((p) => p.n > 0)
                      .map((p) => (
                        <span
                          key={p.key}
                          className={cn("rounded-full", p.className)}
                          style={{ width: `${(p.n / total) * 100}%` }}
                        />
                      ))}
                  </div>
                  {/* The bar is decorative; these counts are the real reading. */}
                  <span className="shrink-0 font-mono text-[10px] tabular-nums text-muted-foreground">
                    {[
                      high > 0 && `${high}Y`,
                      medium > 0 && `${medium}O`,
                      low > 0 && `${low}D`,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                </div>
              </button>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

/** "Canlı Akış": what is being written about right now.
 *
 * Ordered by `last_reported_at`, not by the primary article's own publication
 * time -- a three-day-old story that just got a fourth article IS the newest
 * thing in the feed, and ordering by the primary would bury it. The rail is
 * about coverage, which is the only "now" this data has. */
function LiveFeed({
  rows,
  onSelect,
}: {
  rows: { item: RiskItem; country: string }[];
  onSelect: (item: RiskItem) => void;
}) {
  if (rows.length === 0) return null;

  return (
    <section className="flex flex-col gap-3 rounded-xl border border-border bg-card bg-card-sheen p-4 shadow-elev-1">
      <div className="flex flex-col gap-1.5">
        <h2 className="text-sm font-semibold">Canlı Akış</h2>
        <p className="text-[11px] leading-relaxed text-muted-foreground">
          En son haber alınan sinyaller.
        </p>
      </div>
      <ul className="flex flex-col gap-1">
        {rows.map(({ item, country }) => {
          const at = item.last_reported_at ?? item.published_at;
          return (
            <li key={item.id}>
              <button
                type="button"
                onClick={() => onSelect(item)}
                className="flex w-full flex-col gap-1 rounded-lg border border-transparent px-2 py-1.5 text-left transition-colors hover:border-border hover:bg-accent/50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
              >
                <span className="flex flex-wrap items-center gap-1.5">
                  <span
                    aria-hidden
                    className={cn("size-2 rounded-full", severityMeta(item.severity).dotClassName)}
                  />
                  <span className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                    {severityMeta(item.severity).label}
                  </span>
                  <CoverageBadge item={item} />
                  {at && (
                    <span className="ml-auto text-[10px] tabular-nums text-muted-foreground">
                      {relativeTimeTr(at)}
                    </span>
                  )}
                </span>
                <span className="line-clamp-2 text-[11px] font-medium leading-snug">
                  {item.headline}
                </span>
                <span className="text-[10px] text-muted-foreground">{country}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** A quiet radar is a good outcome. This must read as "nothing happened",
 * never as "something is broken". */
function EmptyRadar({ days }: { days: number }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed border-border px-6 py-16 text-center">
      <p className="text-sm text-muted-foreground">
        Son {days} günde risk sinyali sınıflandırılmadı.
      </p>
      <p className="max-w-md text-xs leading-relaxed text-muted-foreground/80">
        Haber akışı taranıyor; doğal afet veya çatışma olarak sınıflanan bir haber
        bulunmadı. Daha geniş bir dönem seçmeyi deneyebilirsiniz.
      </p>
    </div>
  );
}
