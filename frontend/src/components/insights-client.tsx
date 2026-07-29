"use client";

import ReactECharts from "echarts-for-react";
import { AnimatePresence, useReducedMotion } from "framer-motion";
import { ExternalLink, Lightbulb } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { AirlineLogo } from "@/components/airline-logo";
import { MotionItem, MotionList } from "@/components/motion/motion-list";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api";
import { baseOption, useChartTheme } from "@/lib/chart-theme";
import { airlineTabs, worldRegions } from "@/lib/nav";
import { cn } from "@/lib/utils";

interface RouteSignalArticle {
  id: string;
  headline: string;
  url: string;
  source_name: string;
  published_at: string | null;
  airlines: string[];
}

interface InsightsOut {
  airline_momentum: {
    code: string;
    name: string;
    current: number;
    previous: number;
    delta: number;
  }[];
  new_route_signals: {
    region: string | null;
    count: number;
    articles: RouteSignalArticle[];
  }[];
  sentiment_by_category: {
    category: string;
    positive: number;
    neutral: number;
    negative: number;
  }[];
  digest: { date: string; body: string; provider: string } | null;
}

/** One route signal, flattened out of its region group so the list can be
 * filtered as a single set. */
interface FlatSignal extends RouteSignalArticle {
  region: string | null;
  /** Index of the source region group, so a card's edge light lands on the
   * same `theme.series` hue as its slice in the region donut above. */
  colorIndex: number;
}

const REGION_NAME: Record<string, string> = Object.fromEntries(
  worldRegions.map((r) => [r.slug, r.name]),
);

const AIRLINE_NAME: Record<string, string> = Object.fromEntries(
  airlineTabs.map((a) => [a.code, a.name]),
);

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
  const [signalAirline, setSignalAirline] = useState<string | null>(null);

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
      (data?.new_route_signals ?? []).flatMap((group, groupIndex) =>
        group.articles.map((article) => ({
          ...article,
          region: group.region,
          // Same array, same order that drives regionOption's pie slices.
          colorIndex: groupIndex,
        })),
      ),
    [data],
  );

  const visibleSignals = useMemo(
    () =>
      flatSignals.filter((signal) => {
        if (signalRegion && signal.region !== signalRegion) return false;
        if (signalAirline && !signal.airlines.includes(signalAirline)) return false;
        return true;
      }),
    [flatSignals, signalRegion, signalAirline],
  );

  // Only offer chips that can actually match something -- an empty filter row
  // that returns "0 sonuç" for eight of nine regions is noise.
  const regionsWithSignals = useMemo(() => {
    const counts = new Map<string, number>();
    for (const signal of flatSignals) {
      if (!signal.region) continue;
      counts.set(signal.region, (counts.get(signal.region) ?? 0) + 1);
    }
    return worldRegions.filter((r) => counts.has(r.slug)).map((r) => ({ ...r, count: counts.get(r.slug)! }));
  }, [flatSignals]);

  const airlinesWithSignals = useMemo(() => {
    const seen = new Set<string>();
    for (const signal of flatSignals) {
      for (const code of signal.airlines) seen.add(code);
    }
    return airlineTabs.filter((a) => seen.has(a.code));
  }, [flatSignals]);

  // All chart colors now come from lib/chart-theme.ts -- one mirror of
  // globals.css instead of a ternary per file. The hues are the same
  // dataviz-validated ones; they are just no longer duplicated here.
  const { ink, surface } = theme;

  const base = {
    ...baseOption(theme, reduceMotion),
    grid: { left: 8, right: 24, top: 28, bottom: 8, containLabel: true },
  };

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
        {/* One chart card now, not four -- see the single-column MotionList. */}
        <Skeleton className="h-72 w-full rounded-xl" />
        <Skeleton className="h-72 w-full rounded-xl" />
      </div>
    );
  }

  // Where the route news is coming from. Straight off new_route_signals'
  // region + count -- no extra aggregation.
  const regionSlices = data.new_route_signals
    .map((s) => ({
      name: s.region ? (REGION_NAME[s.region] ?? s.region) : "Bölge belirtilmemiş",
      value: s.count,
    }))
    .filter((s) => s.value > 0);

  const totalSignals = regionSlices.reduce((sum, s) => sum + s.value, 0);

  const regionOption = {
    ...base,
    // Finally uses the app's own --chart-1..5 tokens: this pie was falling
    // through to ECharts' stock palette, the only chart in the app that was
    // not on the validated hues at all.
    color: theme.series,
    grid: undefined,
    tooltip: {
      ...base.tooltip,
      trigger: "item",
      formatter: (p: { name: string; value: number; percent: number }) =>
        `${p.name}<br/>${p.value} sinyal · %${p.percent}`,
    },
    legend: {
      type: "scroll",
      orient: "vertical",
      right: 0,
      top: "middle",
      textStyle: { color: ink, fontSize: 11 },
    },
    // The total, sitting in the ring's hole. `graphic` text rather than a
    // second (label-only) pie series, so nothing extra enters the chart's
    // tooltip/legend/hover surface.
    //
    // The two texts hang off a positioning group rather than carrying
    // `left`/`top` each. ECharts places a graphic element by its bounding
    // box's top-left corner, so a bare text at `left: "36%"` starts at the
    // pie's center and runs off to the right of it -- and the correction is
    // half the rendered text width, a pixel amount that a percentage nudge
    // can only match at one container width. A *group* with
    // `bounding: "raw"` is measured by its own origin instead of its
    // children, so `left`/`top` land that origin exactly on the pie's
    // center ["36%", "52%"], and the children (textAlign/textVerticalAlign
    // centered, offset only in px) stay centered at every width and for any
    // digit count.
    //
    // Only ever rendered alongside the ring itself: this option object is
    // consumed inside the `regionSlices.length > 0` branch below.
    graphic: {
      elements: [
        {
          type: "group",
          left: "36%",
          top: "52%",
          bounding: "raw",
          children: [
            {
              type: "text",
              x: 0,
              y: -8,
              style: {
                text: String(totalSignals),
                fontSize: 28,
                fontWeight: 700,
                fill: theme.inkStrong,
                textAlign: "center",
                textVerticalAlign: "middle",
              },
            },
            {
              type: "text",
              x: 0,
              y: 16,
              style: {
                text: "sinyal",
                fontSize: 11,
                fill: ink,
                textAlign: "center",
                textVerticalAlign: "middle",
              },
            },
          ],
        },
      ],
    },
    series: [
      {
        type: "pie",
        radius: ["48%", "72%"],
        center: ["36%", "52%"],
        avoidLabelOverlap: true,
        itemStyle: { borderColor: surface, borderWidth: 2 },
        label: { show: false },
        labelLine: { show: false },
        data: regionSlices,
      },
    ],
  };

  // These panels are plain divs rather than <Card>, so they take the Task 4
  // base coat (elevation + sheen + shadow transition) explicitly.
  const chartCard =
    "rounded-xl border border-border bg-card bg-card-sheen p-5 shadow-elev-1 transition-shadow duration-300";
  const litCard = cn(chartCard, "hover:glow");

  /** Each chart card carries its lead series color as its edge light. */
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

      <MotionList className="grid grid-cols-1 gap-6">
        <MotionItem className={litCard} style={glow("var(--chart-5)")}>
          <h2 className="mb-2 text-sm font-semibold">
            Yeni hat sinyallerinin dağılımı{" "}
            <span className="font-normal text-muted-foreground">(bölgeye göre, son 30 gün)</span>
          </h2>
          {regionSlices.length > 0 ? (
            <ReactECharts
              option={regionOption}
              style={{ height: 280 }}
              opts={{ renderer: "svg" }}
              notMerge
            />
          ) : (
            <p className="py-24 text-center text-sm text-muted-foreground">
              Son 30 günde yeni hat duyurusu yakalanmadı.
            </p>
          )}
        </MotionItem>
      </MotionList>

      <div className={cn(chartCard, "flex flex-col gap-4")}>
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-sm font-semibold">
            Yeni hat sinyalleri{" "}
            <span className="font-normal text-muted-foreground">(son 30 gün, kaynakçalı)</span>
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
                    className={cn(chip(signalAirline === a.code), "flex items-center gap-1 tabular-nums")}
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
          </div>
        )}

        {visibleSignals.length === 0 ? (
          <p className="py-16 text-center text-sm text-muted-foreground">
            {flatSignals.length === 0
              ? "Son 30 günde yeni hat duyurusu yakalanmadı."
              : "Bu filtrelerle sinyal yok. Bölge ya da taşıyıcı seçimini kaldırın."}
          </p>
        ) : (
          <MotionList className="grid grid-cols-1 gap-6 md:grid-cols-2">
            <AnimatePresence mode="popLayout" initial={false}>
              {visibleSignals.map((signal) => (
                // Same treatment as Gazete's grid tiles: lit at rest via
                // `edge-lit`, brightening into `glow-edge` on hover, wearing
                // its region's donut hue as --glow-color.
                <MotionItem
                  key={signal.id}
                  // No `lift`: the hover lift is now the CSS
                  // `hover:-translate-y-1` below, the same one Gazete's tiles
                  // use. Keeping both would compose Framer's inline
                  // `transform: translateY(-2px)` with the class's separate
                  // `translate` property into a doubled 6px jump.
                  exit="exit"
                  style={
                    {
                      "--glow-color": theme.series[signal.colorIndex % theme.series.length],
                    } as React.CSSProperties
                  }
                  className={cn(
                    "edge-lit flex flex-col gap-2.5 rounded-xl border bg-card p-5 transition-all duration-200",
                    "hover:glow-edge hover:-translate-y-1 motion-reduce:transform-none motion-reduce:transition-none",
                  )}
                >
                  {/* Region badge + right-aligned date, mirroring the article
                      tile's category-badge + time row. */}
                  <div className="flex items-center gap-2">
                    <span className="rounded-full bg-secondary px-2 py-0.5 text-[10px] font-medium text-secondary-foreground">
                      {signal.region
                        ? (REGION_NAME[signal.region] ?? signal.region)
                        : "Bölge belirtilmemiş"}
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

                  {/* mt-auto bottom-aligns the footer across a row of cards
                      with unequal headline lengths. */}
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
              ))}
            </AnimatePresence>
          </MotionList>
        )}
      </div>
    </div>
  );
}

function SignalFilterRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="w-16 shrink-0 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      {children}
    </div>
  );
}
