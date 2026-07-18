"use client";

import ReactECharts from "echarts-for-react";
import { ExternalLink, Lightbulb } from "lucide-react";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api";
import { getCategory } from "@/lib/taxonomy";
import { worldRegions } from "@/lib/nav";

interface InsightsOut {
  volume_by_week: { weeks: string[]; series: Record<string, number[]> };
  airline_momentum: {
    code: string;
    name: string;
    current: number;
    previous: number;
    delta: number;
  }[];
  new_route_signals: { region: string | null; count: number }[];
  sentiment_by_category: {
    category: string;
    positive: number;
    neutral: number;
    negative: number;
  }[];
  top_stories: { id: string; headline: string; url: string; sources: number; category: string }[];
  digest: { date: string; body: string; provider: string } | null;
}

// Chart-local 4-slot categorical theme, validated with the dataviz palette
// checker for both surfaces (lightness band, chroma, CVD ≥8, normal-vision
// ≥15, contrast ≥3:1 -- ALL PASS). Deliberately NOT the category badge tints:
// those were tuned as badges and fail adjacent-series separation as lines.
const CHART_THEME = {
  light: ["#2a78d6", "#eb6834", "#199e70", "#a63d7a"],
  dark: ["#3987e5", "#d95926", "#1baf7a", "#c757a0"],
};

const REGION_NAME: Record<string, string> = Object.fromEntries(
  worldRegions.map((r) => [r.slug, r.name]),
);

export function InsightsClient() {
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === "dark";

  const [data, setData] = useState<InsightsOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiFetch<InsightsOut>("/insights")
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

  const palette = isDark ? CHART_THEME.dark : CHART_THEME.light;
  const good = "#0ca30c";
  const critical = isDark ? "#e66767" : "#d03b3b";
  const gridline = isDark ? "#2c2c2a" : "#e1e0d9";
  const ink = isDark ? "#c3c2b7" : "#52514e";
  const surface = isDark ? "#1a1a19" : "#fcfcfb";
  const neutralBar = isDark ? "#4a4a47" : "#c8c7c0";

  const base = {
    grid: { left: 8, right: 24, top: 28, bottom: 8, containLabel: true },
    tooltip: {
      backgroundColor: surface,
      borderColor: gridline,
      textStyle: { color: isDark ? "#ffffff" : "#0b0b0b", fontSize: 12 },
    },
    textStyle: { fontFamily: "inherit" },
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
      <div className="flex flex-col gap-4">
        <Skeleton className="h-28 w-full rounded-xl" />
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-72 w-full rounded-xl" />
          ))}
        </div>
      </div>
    );
  }

  // Top 4 categories only: the validated theme has 4 slots, and a 6-line
  // spaghetti chart reads worse than a focused one. Assignment is by fixed
  // volume order at render, stable across theme flips.
  const volumeCategories = Object.keys(data.volume_by_week.series).slice(0, 4);
  const weekLabels = data.volume_by_week.weeks.map((w) =>
    new Date(w + "T12:00:00Z").toLocaleDateString("tr-TR", { day: "numeric", month: "short" }),
  );

  const volumeOption = {
    ...base,
    tooltip: { ...base.tooltip, trigger: "axis" },
    legend: {
      top: 0,
      textStyle: { color: ink, fontSize: 11 },
      data: volumeCategories.map((slug) => getCategory(slug).label),
    },
    xAxis: {
      type: "category",
      data: weekLabels,
      boundaryGap: false,
      axisLine: { lineStyle: { color: gridline } },
      axisTick: { show: false },
      axisLabel: { color: ink, fontSize: 11 },
    },
    yAxis: {
      type: "value",
      splitLine: { lineStyle: { color: gridline } },
      axisLabel: { color: ink, fontSize: 11 },
    },
    series: volumeCategories.map((slug, i) => ({
      name: getCategory(slug).label,
      type: "line",
      data: data.volume_by_week.series[slug],
      lineStyle: { width: 2, color: palette[i] },
      itemStyle: { color: palette[i], borderColor: surface, borderWidth: 2 },
      symbol: "circle",
      symbolSize: 8,
      showSymbol: false,
      emphasis: { focus: "series" },
    })),
  };

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
    xAxis: {
      type: "value",
      splitLine: { lineStyle: { color: gridline } },
      axisLabel: { color: ink, fontSize: 11 },
    },
    yAxis: {
      type: "category",
      data: movers.map((m) => `${m.name}`),
      axisLine: { lineStyle: { color: gridline } },
      axisTick: { show: false },
      axisLabel: { color: ink, fontSize: 11 },
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

  const routeRegions = data.new_route_signals.map((s) =>
    s.region ? (REGION_NAME[s.region] ?? s.region) : "Belirsiz",
  );
  const routesOption = {
    ...base,
    tooltip: { ...base.tooltip, trigger: "item" },
    xAxis: {
      type: "category",
      data: routeRegions,
      axisLine: { lineStyle: { color: gridline } },
      axisTick: { show: false },
      axisLabel: { color: ink, fontSize: 11, interval: 0, rotate: 20 },
    },
    yAxis: {
      type: "value",
      splitLine: { lineStyle: { color: gridline } },
      axisLabel: { color: ink, fontSize: 11 },
    },
    series: [
      {
        type: "bar",
        barMaxWidth: 28,
        data: data.new_route_signals.map((s) => s.count),
        itemStyle: { color: palette[0], borderRadius: [4, 4, 0, 0] },
        label: { show: true, position: "top", color: ink, fontSize: 11 },
      },
    ],
  };

  const sentimentCats = data.sentiment_by_category.slice(0, 6);
  const sentimentOption = {
    ...base,
    tooltip: { ...base.tooltip, trigger: "axis" },
    legend: { top: 0, textStyle: { color: ink, fontSize: 11 } },
    xAxis: {
      type: "value",
      splitLine: { lineStyle: { color: gridline } },
      axisLabel: { color: ink, fontSize: 11 },
    },
    yAxis: {
      type: "category",
      data: sentimentCats.map((s) => getCategory(s.category).label).reverse(),
      axisLine: { lineStyle: { color: gridline } },
      axisTick: { show: false },
      axisLabel: { color: ink, fontSize: 11 },
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

  const chartCard = "rounded-xl border border-border bg-card p-4";

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">İçgörüler</h1>
        <p className="text-sm text-muted-foreground">
          Haber arşivinden otomatik çıkarılan örüntüler — her sayı veritabanındaki
          satırlara kadar izlenebilir.
        </p>
      </div>

      {data.digest && (
        <div className="flex flex-col gap-2 rounded-xl border border-border bg-card p-4">
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

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className={chartCard}>
          <h2 className="mb-2 text-sm font-semibold">Haftalık haber hacmi (ilk 4 kategori)</h2>
          <ReactECharts option={volumeOption} style={{ height: 280 }} opts={{ renderer: "svg" }} notMerge />
        </div>
        <div className={chartCard}>
          <h2 className="mb-2 text-sm font-semibold">
            Havayolu momentumu <span className="font-normal text-muted-foreground">(son 7 gün vs önceki 7 gün, haber sayısı farkı)</span>
          </h2>
          <ReactECharts option={momentumOption} style={{ height: 280 }} opts={{ renderer: "svg" }} notMerge />
        </div>
        <div className={chartCard}>
          <h2 className="mb-2 text-sm font-semibold">Yeni hat sinyalleri <span className="font-normal text-muted-foreground">(son 30 gün, bölgeye göre)</span></h2>
          {data.new_route_signals.length === 0 ? (
            <p className="py-16 text-center text-sm text-muted-foreground">
              Son 30 günde yeni hat duyurusu yakalanmadı.
            </p>
          ) : (
            <ReactECharts option={routesOption} style={{ height: 280 }} opts={{ renderer: "svg" }} notMerge />
          )}
        </div>
        <div className={chartCard}>
          <h2 className="mb-2 text-sm font-semibold">Duygu dengesi <span className="font-normal text-muted-foreground">(son 30 gün)</span></h2>
          <ReactECharts option={sentimentOption} style={{ height: 280 }} opts={{ renderer: "svg" }} notMerge />
        </div>
      </div>

      <div className="flex flex-col gap-2 rounded-xl border border-border bg-card p-4">
        <h2 className="text-sm font-semibold">En çok doğrulanan haberler <span className="font-normal text-muted-foreground">(son 14 gün)</span></h2>
        {data.top_stories.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            Son iki haftada birden fazla bağımsız kaynakla doğrulanan haber yok.
          </p>
        ) : (
          <ul className="flex flex-col divide-y divide-border">
            {data.top_stories.map((story) => (
              <li key={story.id}>
                <a
                  href={story.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="group flex items-center justify-between gap-3 py-2.5"
                >
                  <span className="text-sm text-card-foreground group-hover:text-primary">
                    {story.headline}
                  </span>
                  <span className="flex shrink-0 items-center gap-2 text-xs text-muted-foreground">
                    {story.sources} kaynak
                    <ExternalLink className="size-3.5 opacity-0 transition-opacity group-hover:opacity-100" />
                  </span>
                </a>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
