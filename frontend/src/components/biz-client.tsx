"use client";

import {
  ExternalLink,
  Frown,
  Meh,
  MessageSquareQuote,
  Smile,
  Sparkles,
  Star,
} from "lucide-react";
import { useEffect, useState } from "react";

import { ArticleCard } from "@/components/article-card";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api";
import type { ArticleListOut, ArticleOut } from "@/lib/types";
import { cn } from "@/lib/utils";

const THY_RED = "#c70a20";

interface TkQuote {
  excerpt: string;
  original: string | null;
  url: string;
  source_name: string;
  review_date: string | null;
  rating: number | null;
  sentiment: string;
  route: string | null;
  author: string | null;
  themes: string[];
}

interface TkTheme {
  slug: string;
  label: string;
  count: number;
  positive: number;
  negative: number;
  quote: TkQuote | null;
}

interface TkOut {
  review_count: number;
  rating: { average: number | null; count: number };
  sentiment: { positive: number; neutral: number; negative: number };
  themes: TkTheme[];
  sources: { name: string; count: number }[];
  quotes: TkQuote[];
  digest: { date: string; body: string; provider: string } | null;
}

const SENTIMENT_META = {
  positive: { label: "Olumlu", icon: Smile },
  neutral: { label: "Nötr", icon: Meh },
  negative: { label: "Olumsuz", icon: Frown },
} as const;

function formatDate(iso: string | null): string | null {
  if (!iso) return null;
  return new Date(iso + "T12:00:00Z").toLocaleDateString("tr-TR", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

export function BizClient() {
  const [data, setData] = useState<TkOut | null>(null);
  const [articles, setArticles] = useState<ArticleOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiFetch<TkOut>("/tk", { cache: "default" })
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch(() => {
        if (!cancelled) setError("TK masası yüklenemedi. Sunucu çalışıyor mu?");
      });
    apiFetch<ArticleListOut>("/articles?airline=TK&days=60&limit=10", { cache: "default" })
      .then((d) => {
        if (!cancelled) setArticles(d.items);
      })
      .catch(() => {
        if (!cancelled) setArticles([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

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
        <Skeleton className="h-24 w-full rounded-xl" />
        <div className="grid grid-cols-3 gap-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-24 w-full rounded-xl" />
          ))}
        </div>
        <Skeleton className="h-72 w-full rounded-xl" />
      </div>
    );
  }

  const { sentiment } = data;
  const sentimentTotal = sentiment.positive + sentiment.neutral + sentiment.negative;
  const positivePct = sentimentTotal
    ? Math.round((sentiment.positive / sentimentTotal) * 100)
    : 0;
  const maxThemeCount = Math.max(1, ...data.themes.map((t) => t.count));
  const card = "rounded-xl border border-border bg-card p-4";

  return (
    <div className="flex flex-col gap-6">
      {/* THY-identity hero */}
      <div
        className="flex flex-wrap items-center justify-between gap-4 rounded-xl p-5 text-white"
        style={{
          background: `radial-gradient(circle at 20% 0%, ${THY_RED}55 0%, #16161a 65%)`,
        }}
      >
        <div className="flex items-center gap-3">
          <span
            className="flex size-11 items-center justify-center rounded-full"
            style={{ backgroundColor: THY_RED }}
          >
            <Star className="size-6 fill-white text-white" />
          </span>
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">BİZ — Türk Hava Yolları</h1>
            <p className="text-sm text-white/70">
              Halka açık kaynaklardan toplanan yolcu yorumlarının analizi + TK haber akışı.
            </p>
          </div>
        </div>
        <p className="text-xs text-white/50">
          Kaynaklar:{" "}
          {data.sources.map((s) => `${s.name} (${s.count})`).join(" · ") || "henüz yok"}
        </p>
      </div>

      {/* Stat tiles */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div className={card}>
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Ortalama Puan
          </p>
          <p className="mt-1 text-3xl font-semibold tracking-tight">
            {data.rating.average ?? "—"}
            <span className="text-base font-normal text-muted-foreground"> / 10</span>
          </p>
          <p className="text-xs text-muted-foreground">{data.rating.count} puanlı yorum</p>
        </div>
        <div className={card}>
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Toplanan Yorum
          </p>
          <p className="mt-1 text-3xl font-semibold tracking-tight">{data.review_count}</p>
          <p className="text-xs text-muted-foreground">Skytrax · Reddit · App Store</p>
        </div>
        <div className={card}>
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Olumlu Oranı
          </p>
          <p className="mt-1 text-3xl font-semibold tracking-tight">%{positivePct}</p>
          {/* Sentiment split -- status colors with icon+label, never color alone */}
          <div className="mt-2 flex h-2 w-full gap-0.5 overflow-hidden rounded-full">
            <span
              className="bg-good"
              style={{ width: `${sentimentTotal ? (sentiment.positive / sentimentTotal) * 100 : 0}%` }}
            />
            <span
              className="bg-muted-foreground/40"
              style={{ width: `${sentimentTotal ? (sentiment.neutral / sentimentTotal) * 100 : 0}%` }}
            />
            <span
              className="bg-critical"
              style={{ width: `${sentimentTotal ? (sentiment.negative / sentimentTotal) * 100 : 0}%` }}
            />
          </div>
          <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-muted-foreground">
            {(Object.keys(SENTIMENT_META) as (keyof typeof SENTIMENT_META)[]).map((key) => {
              const Icon = SENTIMENT_META[key].icon;
              return (
                <span key={key} className="flex items-center gap-1">
                  <Icon className="size-3" />
                  {SENTIMENT_META[key].label} {sentiment[key]}
                </span>
              );
            })}
          </div>
        </div>
      </div>

      {/* AI synthesis */}
      {data.digest && (
        <div className={cn(card, "flex flex-col gap-2")}>
          <div className="flex items-center gap-2">
            <Sparkles className="size-4" style={{ color: THY_RED }} />
            <h2 className="text-sm font-semibold">Yorum Sentezi</h2>
            <span className="rounded-full bg-secondary px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-secondary-foreground">
              {data.digest.provider === "openai_compat" ? "AI özeti" : "otomatik özet"}
            </span>
            <span className="text-[10px] text-muted-foreground">{data.digest.date}</span>
          </div>
          <p className="whitespace-pre-line text-sm leading-relaxed text-muted-foreground">
            {data.digest.body}
          </p>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* Theme breakdown -- plain HTML bars, count = width, +/- split inside */}
        <div className={card}>
          <h2 className="mb-3 text-sm font-semibold">
            Temalar{" "}
            <span className="font-normal text-muted-foreground">(yorum sayısına göre)</span>
          </h2>
          {data.themes.length === 0 ? (
            <p className="py-10 text-center text-sm text-muted-foreground">
              Henüz tema verisi yok.
            </p>
          ) : (
            <ul className="flex flex-col gap-3">
              {data.themes.map((theme) => {
                const neutralCount = theme.count - theme.positive - theme.negative;
                return (
                  <li key={theme.slug} className="flex flex-col gap-1">
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="text-sm font-medium">{theme.label}</span>
                      <span className="text-xs tabular-nums text-muted-foreground">
                        {theme.count} yorum · {theme.positive}+ / {theme.negative}−
                      </span>
                    </div>
                    <div
                      className="flex h-2.5 gap-0.5 overflow-hidden rounded-full"
                      style={{ width: `${(theme.count / maxThemeCount) * 100}%`, minWidth: "10%" }}
                    >
                      {theme.positive > 0 && (
                        <span className="bg-good" style={{ flex: theme.positive }} />
                      )}
                      {neutralCount > 0 && (
                        <span className="bg-muted-foreground/40" style={{ flex: neutralCount }} />
                      )}
                      {theme.negative > 0 && (
                        <span className="bg-critical" style={{ flex: theme.negative }} />
                      )}
                    </div>
                    {theme.quote && (
                      <a
                        href={theme.quote.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="group mt-0.5 text-xs italic leading-relaxed text-muted-foreground hover:text-foreground"
                      >
                        “{theme.quote.excerpt}”{" "}
                        <span className="not-italic">
                          — {theme.quote.source_name}
                          <ExternalLink className="ml-0.5 inline size-3 opacity-0 transition-opacity group-hover:opacity-100" />
                        </span>
                      </a>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        {/* Recent quotes with citations */}
        <div className={card}>
          <h2 className="mb-3 text-sm font-semibold">
            Son Yorumlar{" "}
            <span className="font-normal text-muted-foreground">(kaynağa bağlantılı)</span>
          </h2>
          {data.quotes.length === 0 ? (
            <p className="py-10 text-center text-sm text-muted-foreground">
              Henüz yorum toplanmadı.
            </p>
          ) : (
            <ul className="flex max-h-[560px] flex-col divide-y divide-border overflow-y-auto">
              {data.quotes.map((quote) => {
                const meta =
                  SENTIMENT_META[quote.sentiment as keyof typeof SENTIMENT_META] ??
                  SENTIMENT_META.neutral;
                const Icon = meta.icon;
                return (
                  <li key={quote.url + quote.excerpt.slice(0, 24)} className="py-2.5">
                    <a
                      href={quote.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="group flex flex-col gap-1"
                    >
                      <span className="flex items-start gap-1.5 text-sm leading-relaxed">
                        <MessageSquareQuote className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
                        <span className="group-hover:text-primary">“{quote.excerpt}”</span>
                      </span>
                      <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5 pl-5 text-[11px] text-muted-foreground">
                        <span
                          className={cn(
                            "flex items-center gap-0.5 font-medium",
                            quote.sentiment === "positive" && "text-good",
                            quote.sentiment === "negative" && "text-critical",
                          )}
                        >
                          <Icon className="size-3" />
                          {meta.label}
                        </span>
                        {quote.rating !== null && <span>{quote.rating}/10</span>}
                        <span>{quote.source_name}</span>
                        {quote.route && <span>{quote.route}</span>}
                        {formatDate(quote.review_date) && (
                          <span>{formatDate(quote.review_date)}</span>
                        )}
                      </span>
                    </a>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>

      {/* TK news -- same endpoint and cards the newspaper uses */}
      <div className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold">
          TK Haberleri{" "}
          <span className="font-normal text-muted-foreground">(son 60 gün)</span>
        </h2>
        {articles === null ? (
          <Skeleton className="h-40 w-full rounded-xl" />
        ) : articles.length === 0 ? (
          <p className="rounded-lg border border-dashed border-border p-6 text-sm text-muted-foreground">
            Son 60 günde TK ile ilişkilendirilmiş haber yok.
          </p>
        ) : (
          <div className="flex flex-col divide-y divide-border rounded-xl border border-border bg-card">
            {articles.map((article) => (
              <ArticleCard key={article.id} article={article} />
            ))}
          </div>
        )}
      </div>

      <p className="text-[11px] leading-relaxed text-muted-foreground">
        Yorumlar halka açık sayfalardan kısa alıntılar hâlinde, kaynağa bağlantı verilerek
        derlenmiştir; dağılım bulunan yorumların gerçek dağılımıdır, seçilmiş bir denge
        değildir. Toplama tarihi: 19 Temmuz 2026.
      </p>
    </div>
  );
}
