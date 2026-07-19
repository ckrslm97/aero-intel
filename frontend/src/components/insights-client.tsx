"use client";

import ReactECharts from "echarts-for-react";
import { ExternalLink, Lightbulb } from "lucide-react";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api";
import { getCategory } from "@/lib/taxonomy";
import { worldRegions } from "@/lib/nav";

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

const REGION_NAME: Record<string, string> = Object.fromEntries(
  worldRegions.map((r) => [r.slug, r.name]),
);

function formatSignalDate(iso: string | null): string | null {
  if (!iso) return null;
  return new Date(iso).toLocaleDateString("tr-TR", { day: "numeric", month: "short" });
}

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

  // Remaining-chart colors, validated with the dataviz palette checker for
  // both surfaces -- do not restyle.
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
          {Array.from({ length: 2 }).map((_, i) => (
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
          <h2 className="mb-2 text-sm font-semibold">
            Havayolu momentumu <span className="font-normal text-muted-foreground">(son 7 gün vs önceki 7 gün, haber sayısı farkı)</span>
          </h2>
          <ReactECharts option={momentumOption} style={{ height: 280 }} opts={{ renderer: "svg" }} notMerge />
        </div>
        <div className={chartCard}>
          <h2 className="mb-2 text-sm font-semibold">Duygu dengesi <span className="font-normal text-muted-foreground">(son 30 gün)</span></h2>
          <ReactECharts option={sentimentOption} style={{ height: 280 }} opts={{ renderer: "svg" }} notMerge />
        </div>
      </div>

      <div className={chartCard}>
        <h2 className="mb-2 text-sm font-semibold">
          Yeni hat sinyalleri <span className="font-normal text-muted-foreground">(son 30 gün, kaynakçalı)</span>
        </h2>
        {data.new_route_signals.length === 0 ? (
          <p className="py-16 text-center text-sm text-muted-foreground">
            Son 30 günde yeni hat duyurusu yakalanmadı.
          </p>
        ) : (
          <div className="flex flex-col gap-4">
            {data.new_route_signals.map((signal) => (
              <div key={signal.region ?? "unspecified"} className="flex flex-col gap-1">
                <div className="flex items-center gap-2">
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    {signal.region
                      ? (REGION_NAME[signal.region] ?? signal.region)
                      : "Bölge belirtilmemiş"}
                  </h3>
                  <span className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-semibold tabular-nums text-muted-foreground">
                    {signal.count}
                  </span>
                </div>
                <ul className="flex flex-col divide-y divide-border">
                  {signal.articles.map((article) => (
                    <li key={article.id}>
                      <a
                        href={article.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="group flex flex-col gap-1 py-2.5"
                      >
                        <span className="flex items-start gap-1.5 text-sm font-medium text-card-foreground group-hover:text-primary">
                          <span className="line-clamp-2">{article.headline}</span>
                          <ExternalLink className="mt-1 size-3.5 shrink-0 opacity-0 transition-opacity group-hover:opacity-100" />
                        </span>
                        <span className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
                          <span className="font-medium">{article.source_name}</span>
                          {formatSignalDate(article.published_at) && (
                            <span>· {formatSignalDate(article.published_at)}</span>
                          )}
                          {article.airlines.map((code) => (
                            <span
                              key={code}
                              className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-semibold tabular-nums"
                            >
                              {code}
                            </span>
                          ))}
                        </span>
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
