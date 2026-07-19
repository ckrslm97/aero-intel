"use client";

import { Download, Newspaper } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { ArticleCard } from "@/components/article-card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { API_BASE_URL, apiFetch } from "@/lib/api";
import type { ArticleListOut, ArticleOut, EditionSummaryOut } from "@/lib/types";
import { cn } from "@/lib/utils";

const DAYS = 7;

/** UTC day keys, newest first -- articles are timestamped UTC, so the strip
 * must be built on UTC dates or the last day goes missing every evening in
 * any timezone east of Greenwich. */
function lastDays(): string[] {
  const out: string[] = [];
  const now = Date.now();
  for (let i = 0; i < DAYS; i += 1) {
    out.push(new Date(now - i * 86_400_000).toISOString().slice(0, 10));
  }
  return out;
}

function dayLabel(iso: string): { weekday: string; date: string } {
  const d = new Date(iso + "T12:00:00Z");
  return {
    weekday: d.toLocaleDateString("tr-TR", { weekday: "short" }),
    date: d.toLocaleDateString("tr-TR", { day: "numeric", month: "short" }),
  };
}

export function ArchiveClient() {
  const days = lastDays();
  const [counts, setCounts] = useState<Record<string, number> | null>(null);
  const [selected, setSelected] = useState(days[0]);
  const [items, setItems] = useState<ArticleOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editions, setEditions] = useState<EditionSummaryOut[]>([]);

  useEffect(() => {
    let cancelled = false;
    apiFetch<Record<string, number>>(`/articles/daily-counts?days=${DAYS}`, {
      cache: "default",
    })
      .then((data) => {
        if (cancelled) return;
        setCounts(data);
        // If today is still empty, open the archive on the newest day that
        // actually has news instead of an empty list.
        setSelected((current) => {
          if ((data[current] ?? 0) > 0) return current;
          return days.find((d) => (data[d] ?? 0) > 0) ?? current;
        });
      })
      .catch(() => {
        if (!cancelled) setCounts({});
      });
    apiFetch<EditionSummaryOut[]>("/editions", { cache: "default" })
      .then((data) => {
        if (!cancelled) setEditions(data);
      })
      .catch(() => {
        /* the edition list is a bonus section -- don't break the page */
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- days is derived from the clock, stable for the page's lifetime
  }, []);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch driven by day selection; the loading flag must flip with it
    setLoading(true);
    apiFetch<ArticleListOut>(`/articles?date=${selected}&limit=100`, {
      cache: "default",
      signal: controller.signal,
    })
      .then((data) => {
        if (cancelled) return;
        setItems(data.items);
        setError(null);
      })
      .catch((error: unknown) => {
        if (cancelled || (error as Error)?.name === "AbortError") return;
        setError("Haberler yüklenemedi. Sunucu çalışıyor mu?");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [selected]);

  const edition = editions.find((e) => e.edition_date === selected);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">Arşiv</h1>
        <p className="text-sm text-muted-foreground">
          Son {DAYS} günde toplanan haberler — gün seçin.
        </p>
      </div>

      {/* Date strip */}
      <div className="flex gap-2 overflow-x-auto pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {days.map((iso) => {
          const { weekday, date } = dayLabel(iso);
          const count = counts?.[iso] ?? 0;
          const active = iso === selected;
          return (
            <button
              key={iso}
              onClick={() => setSelected(iso)}
              className={cn(
                "flex min-w-[76px] shrink-0 flex-col items-center gap-0.5 rounded-lg border px-3 py-2 transition-colors",
                active
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border text-foreground hover:bg-accent",
              )}
            >
              <span
                className={cn(
                  "text-[10px] font-medium uppercase tracking-wide",
                  active ? "text-primary-foreground/80" : "text-muted-foreground",
                )}
              >
                {weekday}
              </span>
              <span className="text-sm font-semibold">{date}</span>
              <span
                className={cn(
                  "rounded-full px-1.5 text-[10px] font-semibold tabular-nums",
                  active
                    ? "bg-primary-foreground/20"
                    : counts === null
                      ? "text-transparent"
                      : "bg-muted text-muted-foreground",
                )}
              >
                {counts === null ? "…" : count}
              </span>
            </button>
          );
        })}
      </div>

      {/* Selected day's edition, when one was assembled */}
      {edition && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-card p-3">
          <Link
            href={`/newspaper/${edition.edition_date}`}
            className="flex min-w-0 items-center gap-2 text-sm font-medium hover:text-primary"
          >
            <Newspaper className="size-4 shrink-0 text-muted-foreground" />
            <span className="truncate">Günün Gazetesi: {edition.headline}</span>
            <Badge variant="secondary" className="shrink-0 text-[10px] uppercase">
              {edition.story_count} haber
            </Badge>
          </Link>
          {edition.pdf_available && (
            <a
              href={`${API_BASE_URL}/editions/${edition.edition_date}/pdf`}
              className="flex shrink-0 items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs font-medium hover:bg-accent"
            >
              <Download className="size-3.5" />
              PDF
            </a>
          )}
        </div>
      )}

      {/* The day's collected articles */}
      {error ? (
        <p className="rounded-lg border border-dashed border-border p-6 text-sm text-muted-foreground">
          {error}
        </p>
      ) : loading && items.length === 0 ? (
        <div className="flex flex-col divide-y divide-border rounded-xl border border-border bg-card">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="flex flex-col gap-2 p-4">
              <Skeleton className="h-4 w-24 rounded-full" />
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="h-3 w-full" />
            </div>
          ))}
        </div>
      ) : items.length > 0 ? (
        <div className="flex flex-col divide-y divide-border rounded-xl border border-border bg-card">
          {items.map((article) => (
            <ArticleCard key={article.id} article={article} />
          ))}
        </div>
      ) : (
        <div className="rounded-lg border border-dashed border-border p-10 text-center">
          <p className="text-sm font-medium text-foreground">Bu günde haber toplanmamış</p>
          <p className="mt-1 text-sm text-muted-foreground">Başka bir gün seçin.</p>
        </div>
      )}

      {/* Full edition archive (PDF list) -- carried over from the old page */}
      {editions.length > 0 && (
        <div className="flex flex-col gap-2">
          <h2 className="text-sm font-semibold">Günlük Sayılar</h2>
          <ul className="flex flex-col divide-y divide-border rounded-xl border border-border bg-card">
            {editions.map((e) => (
              <li key={e.id} className="flex items-center justify-between gap-4 p-3">
                <Link
                  href={`/newspaper/${e.edition_date}`}
                  className="flex min-w-0 flex-1 flex-col gap-0.5 hover:text-primary"
                >
                  <span className="text-xs font-medium text-muted-foreground">
                    {new Date(e.edition_date + "T12:00:00Z").toLocaleDateString("tr-TR", {
                      weekday: "short",
                      year: "numeric",
                      month: "short",
                      day: "numeric",
                    })}
                  </span>
                  <span className="truncate text-sm font-medium text-card-foreground">
                    {e.headline}
                  </span>
                </Link>
                {e.pdf_available && (
                  <a
                    href={`${API_BASE_URL}/editions/${e.edition_date}/pdf`}
                    title="PDF İndir"
                    className="flex shrink-0 items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs font-medium hover:bg-accent"
                  >
                    <Download className="size-3.5" />
                  </a>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
