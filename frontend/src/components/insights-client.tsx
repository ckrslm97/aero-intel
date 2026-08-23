"use client";

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { ChevronDown, CircleDashed, ExternalLink, Lightbulb, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { AirlineLogo } from "@/components/airline-logo";
import { MotionItem, MotionList, MotionRail } from "@/components/motion/motion-list";
import { RouteSignalMap } from "@/components/route-signal-map";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api";
import { useChartTheme } from "@/lib/chart-theme";
import { collapseSection, reduceVariants, useMeasuredHeight } from "@/lib/motion";
import { airlineTabs, worldRegions } from "@/lib/nav";
import type { InsightsOut, RouteSignalArticle } from "@/lib/types";
import { cn } from "@/lib/utils";

/** One route signal, flattened out of its region group so the whole set can be
 * filtered and re-grouped as a single list. */
interface FlatSignal extends RouteSignalArticle {
  region: string | null;
}

/** A ledger section: every signal naming one carrier. A story naming two
 * carriers is filed under both -- that is what the story is about, and picking
 * one would silently drop the other from its own section. Section counts
 * therefore sum to more than the signal total. */
interface CarrierGroup {
  /** null is the "no carrier named" group, not a carrier. */
  code: string | null;
  name: string;
  /** The section's approach light and its cards' edge light. */
  color: string;
  signals: FlatSignal[];
}

const REGION_NAME: Record<string, string> = Object.fromEntries(
  worldRegions.map((r) => [r.slug, r.name]),
);

const AIRLINE_NAME: Record<string, string> = Object.fromEntries(
  airlineTabs.map((a) => [a.code, a.name]),
);

const AIRLINE_COLOR: Record<string, string> = Object.fromEntries(
  airlineTabs.map((a) => [a.code, a.color]),
);

/** The deliberately no-identity gray, for the group that has no identity to
 * show and for the residue. */
const NO_IDENTITY = "var(--category-general)";

function formatSignalDate(iso: string | null): string | null {
  if (!iso) return null;
  return new Date(iso).toLocaleDateString("tr-TR", { day: "numeric", month: "short" });
}

/** The lit-chip pattern shared with Gazete/Öneriler: a selected filter burns
 * in its own color with a ring and (in dark mode) a glow, instead of a flat
 * primary fill. */
const chip = (active: boolean) =>
  cn(
    "rounded-full px-2.5 py-1 text-xs font-medium transition-colors",
    active
      ? "bg-primary/12 text-primary ring-1 ring-primary/40 dark:glow-soft"
      : "border border-border text-muted-foreground hover:bg-accent",
  );

export function InsightsClient() {
  const theme = useChartTheme();
  const reduceMotion = useReducedMotion();

  const [data, setData] = useState<InsightsOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Signal filters. Deliberately client-side: /insights returns the whole
  // (already capped) signal set in one payload, so filtering in memory is
  // exact -- no backend query params, no second round trip. There is no
  // Kategori row here because every route signal is network/new_route by
  // construction (see backend/app/services/insights_service.py), so a
  // category filter would have exactly one non-empty value.
  const [signalRegion, setSignalRegion] = useState<string | null>(null);
  // Shared with the map's carrier chip row: one selection, two affordances.
  // Picking a carrier there draws its arcs *and* narrows the ledger, which is
  // the same thing the ledger's own Havayolu row does.
  const [signalAirline, setSignalAirline] = useState<string | null>(null);
  // Set by clicking a marker on the map.
  const [signalCity, setSignalCity] = useState<string | null>(null);
  const [residueOpen, setResidueOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    apiFetch<InsightsOut>("/insights", { cache: "default" })
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch(() => {
        if (!cancelled) setError("İçgörüler yüklenemedi. Sunucu çalışıyor mu?");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const flatSignals = useMemo<FlatSignal[]>(
    () =>
      (data?.new_route_signals ?? []).flatMap((group) =>
        group.articles.map((article) => ({ ...article, region: group.region })),
      ),
    [data],
  );

  const visibleSignals = useMemo(
    () =>
      flatSignals.filter((signal) => {
        if (signalRegion && signal.region !== signalRegion) return false;
        if (signalAirline && !signal.airlines.includes(signalAirline)) return false;
        if (signalCity && !signal.airports.some((a) => a.city === signalCity)) return false;
        return true;
      }),
    [flatSignals, signalRegion, signalAirline, signalCity],
  );

  /* --- the ledger's two halves -------------------------------------------
   * A signal that named no airport the reference table knows is not a carrier
   * story we can place -- it has no city, so it is on no map and in no
   * geography. Those go to the residue below, whole, rather than being spread
   * thinly through the carrier sections where they would read as placed.
   */
  const placedSignals = useMemo(
    () => visibleSignals.filter((s) => s.airports.length > 0),
    [visibleSignals],
  );
  const residueSignals = useMemo(
    () => visibleSignals.filter((s) => s.airports.length === 0),
    [visibleSignals],
  );

  const carrierGroups = useMemo<CarrierGroup[]>(() => {
    const byCarrier = new Map<string | null, FlatSignal[]>();
    for (const signal of placedSignals) {
      if (signal.airlines.length === 0) {
        byCarrier.set(null, [...(byCarrier.get(null) ?? []), signal]);
        continue;
      }
      for (const code of signal.airlines) {
        byCarrier.set(code, [...(byCarrier.get(code) ?? []), signal]);
      }
    }

    // Carriers outside the ten watched tabs have no brand hex on file. They
    // still get an identity light rather than the no-identity gray -- gray is
    // reserved for "we know nothing here", and we do know the carrier -- so
    // they cycle the validated series hues instead of borrowing a brand color
    // that isn't theirs.
    let fallbackIndex = 0;
    const groups: CarrierGroup[] = [];
    for (const [code, signals] of byCarrier) {
      if (code === null) continue;
      groups.push({
        code,
        name: AIRLINE_NAME[code] ?? code,
        color: AIRLINE_COLOR[code] ?? theme.series[fallbackIndex++ % theme.series.length],
        signals,
      });
    }
    groups.sort((a, b) => b.signals.length - a.signals.length || a.name.localeCompare(b.name, "tr"));

    // Under a carrier filter the ledger shows that carrier's section only. The
    // co-mentioned carriers' sections would all still be non-empty -- a story
    // filed under two carriers is filed under both -- but "Havayolu: TK" and a
    // page still headed by four other carriers reads as a filter that failed,
    // not as a filter that told the truth about co-mentions.
    if (signalAirline) return groups.filter((g) => g.code === signalAirline);

    // "No carrier named" is an absence, not a carrier -- it wears the gray and
    // is pinned last regardless of how many signals it holds.
    const unnamed = byCarrier.get(null);
    if (unnamed?.length) {
      groups.push({
        code: null,
        name: "Taşıyıcı belirtilmemiş",
        color: NO_IDENTITY,
        signals: unnamed,
      });
    }
    return groups;
  }, [placedSignals, signalAirline, theme.series]);

  /* --- the stat strip ---------------------------------------------------- */
  const stats = useMemo(() => {
    const carriers = new Set<string>();
    const cities = new Set<string>();
    let unresolved = 0;
    for (const signal of flatSignals) {
      for (const code of signal.airlines) carriers.add(code);
      for (const airport of signal.airports) cities.add(airport.city);
      if (signal.airports.length === 0) unresolved += 1;
    }
    return {
      total: flatSignals.length,
      carriers: carriers.size,
      cities: cities.size,
      unresolved,
    };
  }, [flatSignals]);

  // Only offer chips that can actually match something -- an empty filter row
  // that returns "0 sonuç" for eight of nine regions is noise.
  const regionsWithSignals = useMemo(() => {
    const counts = new Map<string, number>();
    for (const signal of flatSignals) {
      if (!signal.region) continue;
      counts.set(signal.region, (counts.get(signal.region) ?? 0) + 1);
    }
    return worldRegions
      .filter((r) => counts.has(r.slug))
      .map((r) => ({ ...r, count: counts.get(r.slug)! }));
  }, [flatSignals]);

  const airlinesWithSignals = useMemo(() => {
    const seen = new Set<string>();
    for (const signal of flatSignals) {
      for (const code of signal.airlines) seen.add(code);
    }
    return airlineTabs.filter((a) => seen.has(a.code));
  }, [flatSignals]);

  if (error) {
    return (
      <p className="rounded-lg border border-dashed border-border p-6 text-sm text-muted-foreground">
        {error}
      </p>
    );
  }
  if (!data) {
    return (
      <div className="flex flex-col gap-6">
        <Skeleton className="h-28 w-full rounded-xl" />
        <Skeleton className="h-24 w-full rounded-xl" />
        <Skeleton className="h-96 w-full rounded-xl" />
        <Skeleton className="h-72 w-full rounded-xl" />
      </div>
    );
  }

  // These panels are plain divs rather than <Card>, so they take the Task 4
  // base coat (elevation + sheen + shadow transition) explicitly.
  const chartCard =
    "rounded-xl border border-border bg-card bg-card-sheen p-5 shadow-elev-1 transition-shadow duration-300";

  /** Each card carries its lead color as its edge light. */
  const glow = (token: string) => ({ "--glow-color": token }) as React.CSSProperties;

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">İçgörüler</h1>
        <p className="text-sm leading-relaxed text-muted-foreground">
          Haber arşivinden otomatik çıkarılan örüntüler — her sayı veritabanındaki
          satırlara kadar izlenebilir.
        </p>
      </div>

      {data.digest && (
        <div
          style={glow("var(--category-revenue-management)")}
          className="border-gradient flex flex-col gap-2 rounded-xl p-5 shadow-elev-1"
        >
          <div className="flex items-center gap-2">
            <Lightbulb className="size-4 text-category-revenue-management" />
            <h2 className="text-sm font-semibold">Günün Örüntüsü</h2>
            <span className="rounded-full bg-secondary px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-secondary-foreground">
              {data.digest.provider === "openai_compat" ? "AI özeti" : "otomatik özet"}
            </span>
            <span className="text-[10px] text-muted-foreground">{data.digest.date}</span>
          </div>
          <p className="text-sm leading-relaxed text-muted-foreground">{data.digest.body}</p>
        </div>
      )}

      {/* The month in four numbers. The last one is a confession, not a KPI --
          see StatTile. */}
      <MotionList className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatTile label="Toplam sinyal" value={stats.total} />
        <StatTile label="Taşıyıcı" value={stats.carriers} />
        <StatTile label="Şehir" value={stats.cities} />
        <StatTile label="Çözümlenemedi" value={stats.unresolved} muted />
      </MotionList>

      <div className={cn(chartCard, "flex flex-col gap-4")}>
        <h2 className="text-sm font-semibold">
          Yeni hat sinyalleri nereye iniyor?{" "}
          <span className="font-normal text-muted-foreground">(son 30 gün)</span>
        </h2>
        <RouteSignalMap
          signals={flatSignals}
          carrier={signalAirline}
          onCarrierChange={setSignalAirline}
          city={signalCity}
          onCityChange={setSignalCity}
        />
      </div>

      <div className={cn(chartCard, "flex flex-col gap-4")}>
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-sm font-semibold">
            Yeni hat sinyalleri{" "}
            <span className="font-normal text-muted-foreground">
              (taşıyıcıya göre, son 30 gün, kaynakçalı)
            </span>
          </h2>
          <span className="text-xs tabular-nums text-muted-foreground">
            {visibleSignals.length} / {flatSignals.length} sinyal
          </span>
        </div>

        {flatSignals.length > 0 && (
          <div className="flex flex-col gap-2 rounded-lg border border-border bg-background/50 p-4">
            <SignalFilterRow label="Bölge">
              <button
                type="button"
                onClick={() => setSignalRegion(null)}
                className={chip(!signalRegion)}
              >
                Tümü
              </button>
              {regionsWithSignals.map((r) => (
                <button
                  key={r.slug}
                  type="button"
                  onClick={() => setSignalRegion(signalRegion === r.slug ? null : r.slug)}
                  className={chip(signalRegion === r.slug)}
                >
                  {r.name}
                  <span className="ml-1 tabular-nums opacity-70">{r.count}</span>
                </button>
              ))}
            </SignalFilterRow>

            {airlinesWithSignals.length > 0 && (
              <SignalFilterRow label="Havayolu">
                <button
                  type="button"
                  onClick={() => setSignalAirline(null)}
                  className={chip(!signalAirline)}
                >
                  Tümü
                </button>
                {airlinesWithSignals.map((a) => (
                  <button
                    key={a.code}
                    type="button"
                    title={a.name}
                    onClick={() => setSignalAirline(signalAirline === a.code ? null : a.code)}
                    className={cn(
                      chip(signalAirline === a.code),
                      "flex items-center gap-1 tabular-nums",
                    )}
                  >
                    <span
                      className={cn(
                        "flex size-4 items-center justify-center overflow-hidden rounded-[3px]",
                        signalAirline === a.code && "bg-white/85",
                      )}
                    >
                      <AirlineLogo code={a.code} name={a.name} className="size-4" />
                    </span>
                    {a.code}
                  </button>
                ))}
              </SignalFilterRow>
            )}

            {/* The map's click has no chip row of its own, so it gets a
                dismissible one here -- a filter the user cannot see they set
                is a bug report waiting to happen. */}
            {signalCity && (
              <SignalFilterRow label="Şehir">
                <button
                  type="button"
                  onClick={() => setSignalCity(null)}
                  className={cn(chip(true), "flex items-center gap-1")}
                >
                  {signalCity}
                  <X className="size-3" />
                </button>
              </SignalFilterRow>
            )}
          </div>
        )}

        {visibleSignals.length === 0 ? (
          <p className="py-16 text-center text-sm text-muted-foreground">
            {flatSignals.length === 0
              ? "Son 30 günde yeni hat duyurusu yakalanmadı."
              : "Bu filtrelerle sinyal yok. Bölge, taşıyıcı ya da şehir seçimini kaldırın."}
          </p>
        ) : (
          <div className="flex flex-col gap-8">
            {carrierGroups.map((group) => (
              <section key={group.code ?? "__none__"} className="flex flex-col gap-3">
                <div className="flex flex-col gap-2">
                  <div className="flex items-center gap-2">
                    {group.code ? (
                      <AirlineLogo
                        code={group.code}
                        name={group.name}
                        className="size-5 shrink-0 rounded-[3px]"
                      />
                    ) : (
                      <CircleDashed className="size-5 shrink-0 text-muted-foreground" />
                    )}
                    <h3
                      className={cn(
                        "text-sm font-semibold",
                        group.code === null && "text-muted-foreground",
                      )}
                    >
                      {group.name}
                    </h3>
                    <span className="text-xs tabular-nums text-muted-foreground">
                      {group.signals.length} sinyal
                    </span>
                  </div>
                  {/* Each carrier section underlined by its own approach light. */}
                  <MotionRail style={glow(group.color)} />
                </div>

                <MotionList className="grid grid-cols-1 gap-6 md:grid-cols-2">
                  <AnimatePresence mode="popLayout" initial={false}>
                    {group.signals.map((signal) => (
                      <SignalCard
                        key={`${group.code ?? "none"}-${signal.id}`}
                        signal={signal}
                        color={group.color}
                      />
                    ))}
                  </AnimatePresence>
                </MotionList>
              </section>
            ))}

            {/* --- the residue -------------------------------------------
                Collapsed, never hidden. A signal we could not place is the
                one thing this page must not quietly drop: a residue nobody
                can see is a residue nobody fixes. */}
            {residueSignals.length > 0 && (
              <section className="flex flex-col gap-3 border-t border-dashed border-border pt-6">
                <button
                  type="button"
                  onClick={() => setResidueOpen((open) => !open)}
                  className="flex w-fit items-center gap-2 text-sm font-medium text-muted-foreground hover:text-foreground"
                >
                  <CircleDashed className="size-4 shrink-0" />
                  Çözümlenemeyen sinyaller ({residueSignals.length})
                  <ChevronDown
                    className={cn(
                      "size-3.5 transition-transform motion-reduce:transition-none",
                      residueOpen && "rotate-180",
                    )}
                  />
                </button>
                <p className="text-xs text-muted-foreground">
                  Bu haberlerde tanınan bir havalimanı geçmiyor; koordinatları olmadığı için
                  haritada yer almıyorlar. Sayı düştükçe harita doğrulaşır.
                </p>
                <Expandable open={residueOpen} reduceMotion={reduceMotion}>
                  <MotionList className="grid grid-cols-1 gap-6 pt-3 md:grid-cols-2">
                    {residueSignals.map((signal) => (
                      <SignalCard key={signal.id} signal={signal} color={NO_IDENTITY} />
                    ))}
                  </MotionList>
                </Expandable>
              </section>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/** One number from the month. `muted` renders the value in the secondary ink:
 * "Çözümlenemedi" counts what the pipeline failed to resolve, and a confession
 * typeset like an achievement is a lie told in CSS. */
function StatTile({
  label,
  value,
  muted = false,
}: {
  label: string;
  value: number;
  muted?: boolean;
}) {
  return (
    <MotionItem
      variant="scalePop"
      className="rounded-xl border border-border bg-card bg-card-sheen p-4 shadow-elev-1"
    >
      <p className="text-xs text-muted-foreground">{label}</p>
      <p
        className={cn(
          "mt-1 text-2xl font-semibold tabular-nums",
          muted && "text-muted-foreground",
        )}
      >
        {value}
      </p>
    </MotionItem>
  );
}

/** A signal, lit in the color of whatever section holds it. */
function SignalCard({ signal, color }: { signal: FlatSignal; color: string }) {
  return (
    <MotionItem
      // No `lift`: the hover lift is the CSS `hover:-translate-y-1` below, the
      // same one Gazete's tiles use. Keeping both would compose Framer's
      // inline transform with the class's separate `translate` property into a
      // doubled jump.
      exit="exit"
      style={{ "--glow-color": color } as React.CSSProperties}
      className={cn(
        "edge-lit flex flex-col gap-2.5 rounded-xl border bg-card p-5 transition-all duration-200",
        "hover:glow-edge hover:-translate-y-1 motion-reduce:transform-none motion-reduce:transition-none",
      )}
    >
      {/* Region identity moved to this badge when the carrier took the edge
          light -- the card still says which part of the world it is about. */}
      <div className="flex items-center gap-2">
        <span className="rounded-full bg-secondary px-2 py-0.5 text-[10px] font-medium text-secondary-foreground">
          {signal.region ? (REGION_NAME[signal.region] ?? signal.region) : "Bölge belirtilmemiş"}
        </span>
        {formatSignalDate(signal.published_at) && (
          <span className="ml-auto text-[10px] tabular-nums text-muted-foreground">
            {formatSignalDate(signal.published_at)}
          </span>
        )}
      </div>

      <h3 className="text-sm font-medium leading-snug">
        <span className="line-clamp-2">{signal.headline}</span>
      </h3>

      {signal.airlines.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          {signal.airlines.map((code) => (
            <span
              key={code}
              title={AIRLINE_NAME[code] ?? code}
              className="flex items-center gap-1 rounded-full border border-border px-1.5 py-0.5 text-[10px] font-semibold tabular-nums"
            >
              <AirlineLogo code={code} name={AIRLINE_NAME[code]} className="size-3.5" />
              {code}
            </span>
          ))}
        </div>
      )}

      {/* The bottom rung of the spine: which airports, by name, this signal
          actually resolved to. */}
      {signal.airports.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          {signal.airports.map((airport) => (
            <span
              key={airport.code}
              title={airport.name}
              className="rounded-full border border-border px-1.5 py-0.5 font-mono text-[10px]"
            >
              {airport.code} · {airport.city}
            </span>
          ))}
        </div>
      )}

      {/* mt-auto bottom-aligns the footer across a row of cards with unequal
          headline lengths. */}
      <div className="mt-auto flex items-center gap-2 pt-1.5 text-[11px] text-muted-foreground">
        <span className="font-medium">{signal.source_name}</span>
        <a
          href={signal.url}
          target="_blank"
          rel="noopener noreferrer"
          className="ml-auto flex items-center gap-1 font-medium text-primary hover:underline"
        >
          Kaynak
          <ExternalLink className="size-3" />
        </a>
      </div>
    </MotionItem>
  );
}

/** Animated-height reveal, the same one the hub panels use: the wrapper
 * animates to a measured pixel height rather than to `"auto"`, which cannot be
 * composited. */
function Expandable({
  open,
  reduceMotion,
  children,
}: {
  open: boolean;
  reduceMotion: boolean | null;
  children: React.ReactNode;
}) {
  const [contentRef, measuredHeight] = useMeasuredHeight<HTMLDivElement>();
  const variants = collapseSection(measuredHeight);

  return (
    <AnimatePresence initial={false}>
      {open && (
        <motion.div
          variants={reduceMotion ? reduceVariants(variants) : variants}
          initial="hidden"
          animate="show"
          exit="exit"
          className="overflow-hidden"
        >
          <div ref={contentRef}>{children}</div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

function SignalFilterRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="w-16 shrink-0 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      {children}
    </div>
  );
}
