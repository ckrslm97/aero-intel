"use client";

import ReactECharts from "echarts-for-react";
import { AnimatePresence, useReducedMotion } from "framer-motion";
import { ExternalLink, Lightbulb } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { AirlineLogo } from "@/components/airline-logo";
import { MotionItem, MotionList } from "@/components/motion/motion-list";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api";
import {
  baseOption,
  categoryAxis,
  useChartTheme,
  valueAxis,
} from "@/lib/chart-theme";
import { getCategory } from "@/lib/taxonomy";
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
}

const REGION_NAME: Record<string, string> = Object.fromEntries(
  worldRegions.map((r) => [r.slug, r.name]),
);

const AIRLINE_COLOR: Record<string, string> = Object.fromEntries(
  airlineTabs.map((a) => [a.code, a.color]),
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
      ? "bg-primary/12 text-primary ring-1 ring-primary/40 dark:glow"
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
  const { good, critical, ink, surface, neutral: neutralBar } = theme;

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
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-72 w-full rounded-xl" />
          ))}
        </div>
        <Skeleton className="h-72 w-full rounded-xl" />
      </div>
    );
  }

  const movers = [...data.airline_momentum].reverse(); // biggest at top after axis inversion
  const momentumOption = {
    ...base,
    tooltip: {
      ...base.tooltip,
      trigger: "item",
      formatter: (p: { dataIndex: number }) => {
        const m = movers[p.dataIndex];
        return `${m.name}<br/>Son 7 gün: ${m.current} haber · Önceki: ${m.previous}`;
      },
    },
    xAxis: { ...valueAxis(theme), type: "value" },
    yAxis: {
      ...categoryAxis(theme),
      type: "category",
      data: movers.map((m) => `${m.name}`),
    },
    series: [
      {
        type: "bar",
        barMaxWidth: 14,
        data: movers.map((m) => ({
          value: m.delta,
          itemStyle: {
            color: m.delta >= 0 ? good : critical,
            borderRadius: m.delta >= 0 ? [0, 4, 4, 0] : [4, 0, 0, 4],
          },
        })),
        label: {
          show: true,
          position: "outside",
          color: ink,
          fontSize: 11,
          formatter: (p: { value: number }) => (p.value > 0 ? `+${p.value}` : `${p.value}`),
        },
      },
    ],
  };

  const sentimentCats = data.sentiment_by_category.slice(0, 6);
  const sentimentOption = {
    ...base,
    tooltip: { ...base.tooltip, trigger: "axis" },
    legend: { top: 0, textStyle: { color: ink, fontSize: 11 } },
    xAxis: { ...valueAxis(theme), type: "value" },
    yAxis: {
      ...categoryAxis(theme),
      type: "category",
      data: sentimentCats.map((s) => getCategory(s.category).label).reverse(),
    },
    series: (
      [
        ["Olumlu", "positive", good],
        ["Nötr", "neutral", neutralBar],
        ["Olumsuz", "negative", critical],
      ] as const
    ).map(([name, key, color]) => ({
      name,
      type: "bar",
      stack: "sentiment",
      barMaxWidth: 14,
      data: sentimentCats.map((s) => s[key]).reverse(),
      // 2px surface gap between stacked segments, per the mark spec.
      itemStyle: { color, borderColor: surface, borderWidth: 1 },
    })),
  };

  // NEW: where the route news is coming from. Straight off new_route_signals'
  // region + count -- no extra aggregation.
  const regionSlices = data.new_route_signals
    .map((s) => ({
      name: s.region ? (REGION_NAME[s.region] ?? s.region) : "Bölge belirtilmemiş",
      value: s.count,
    }))
    .filter((s) => s.value > 0);

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

  // NEW: absolute mention volume behind the momentum delta -- the delta chart
  // says "who moved", this says "off what base".
  const volumeAirlines = [...data.airline_momentum]
    .sort((a, b) => b.current - a.current)
    .slice(0, 8);

  const volumeOption = {
    ...base,
    tooltip: { ...base.tooltip, trigger: "axis", axisPointer: { type: "shadow" } },
    legend: {
      top: 0,
      icon: "roundRect",
      itemWidth: 10,
      itemHeight: 10,
      textStyle: { color: ink, fontSize: 11 },
    },
    xAxis: {
      ...categoryAxis(theme),
      type: "category",
      data: volumeAirlines.map((m) => m.code),
    },
    yAxis: { ...valueAxis(theme), type: "value" },
    series: [
      {
        name: "Önceki 7 gün",
        type: "bar",
        barMaxWidth: 16,
        data: volumeAirlines.map((m) => m.previous),
        itemStyle: { color: neutralBar, borderRadius: [3, 3, 0, 0] },
      },
      {
        name: "Son 7 gün",
        type: "bar",
        barMaxWidth: 16,
        // Carrier livery where we know it, otherwise the app's own series
        // ramp cycled per carrier -- previously every unknown carrier
        // collapsed onto one hardcoded blue.
        data: volumeAirlines.map((m, i) => ({
          value: m.current,
          itemStyle: {
            color: AIRLINE_COLOR[m.code] ?? theme.series[i % theme.series.length],
            borderRadius: [3, 3, 0, 0],
          },
        })),
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

      <MotionList className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <MotionItem className={litCard} style={glow("var(--chart-1)")}>
          <h2 className="mb-2 text-sm font-semibold">
            Havayolu momentumu{" "}
            <span className="font-normal text-muted-foreground">
              (son 7 gün vs önceki 7 gün, haber sayısı farkı)
            </span>
          </h2>
          <ReactECharts
            option={momentumOption}
            style={{ height: 280 }}
            opts={{ renderer: "svg" }}
            notMerge
          />
        </MotionItem>

        <MotionItem className={litCard} style={glow("var(--good)")}>
          <h2 className="mb-2 text-sm font-semibold">
            Duygu dengesi <span className="font-normal text-muted-foreground">(son 30 gün)</span>
          </h2>
          <ReactECharts
            option={sentimentOption}
            style={{ height: 280 }}
            opts={{ renderer: "svg" }}
            notMerge
          />
        </MotionItem>

        <MotionItem className={litCard} style={glow("var(--chart-4)")}>
          <h2 className="mb-2 text-sm font-semibold">
            Haber hacmi{" "}
            <span className="font-normal text-muted-foreground">
              (taşıyıcı bazında, son 7 gün vs önceki 7 gün)
            </span>
          </h2>
          {volumeAirlines.length > 0 ? (
            <ReactECharts
              option={volumeOption}
              style={{ height: 280 }}
              opts={{ renderer: "svg" }}
              notMerge
            />
          ) : (
            <p className="py-24 text-center text-sm text-muted-foreground">
              Bu dönemde taşıyıcı bazında haber sayılmadı.
            </p>
          )}
        </MotionItem>

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
          <MotionList className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <AnimatePresence mode="popLayout" initial={false}>
              {visibleSignals.map((signal) => (
                <MotionItem
                  key={signal.id}
                  lift={!reduceMotion}
                  exit="exit"
                  className="flex flex-col gap-2 rounded-lg border border-border bg-card p-4"
                >
                  <h3 className="text-sm font-medium leading-snug">
                    <span className="line-clamp-2">{signal.headline}</span>
                  </h3>
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="rounded-full bg-secondary px-2 py-0.5 text-[10px] font-medium text-secondary-foreground">
                      {signal.region
                        ? (REGION_NAME[signal.region] ?? signal.region)
                        : "Bölge belirtilmemiş"}
                    </span>
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
                  <div className="mt-auto flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-muted-foreground">
                    <span className="font-medium">{signal.source_name}</span>
                    {formatSignalDate(signal.published_at) && (
                      <span>· {formatSignalDate(signal.published_at)}</span>
                    )}
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
