"use client";

import { Download, Newspaper, X } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { ArticleCard } from "@/components/article-card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useUrlState, writeParam } from "@/hooks/use-url-state";
import { API_BASE_URL, apiFetch } from "@/lib/api";
import { DISPLAY_TIME_ZONE, formatDayMonthTr } from "@/lib/format";
import { CATEGORY_BY_SLUG } from "@/lib/taxonomy";
import { CATEGORY_SLUGS } from "@/lib/taxonomy.gen";
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

const EDITION_DAY_FORMAT = new Intl.DateTimeFormat("tr-TR", {
  timeZone: DISPLAY_TIME_ZONE,
  weekday: "short",
  year: "numeric",
  month: "short",
  day: "numeric",
});

/** One published edition's day. Date-only, so it is anchored at midday UTC --
 * the /newspaper/[date] masthead this row links to reads the same day. */
function editionDayLabel(iso: string): string {
  const at = new Date(`${iso}T12:00:00Z`);
  return Number.isNaN(at.getTime()) ? iso : EDITION_DAY_FORMAT.format(at);
}

const WEEKDAY_FORMAT = new Intl.DateTimeFormat("tr-TR", {
  timeZone: DISPLAY_TIME_ZONE,
  weekday: "short",
});

/** The day-picker's two lines. Both pinned to the display zone, and both fed
 * the midday anchor `formatDayMonthTr` carries -- this used to open-code the
 * anchor and then format in the runtime's zone. */
function dayLabel(iso: string): { weekday: string; date: string } {
  const d = new Date(`${iso}T12:00:00Z`);
  return {
    weekday: WEEKDAY_FORMAT.format(d),
    date: formatDayMonthTr(iso) ?? iso,
  };
}

/** `?category=` off the address bar, or null.
 *
 * An unrecognised slug is dropped rather than passed through: `/articles`
 * would answer a made-up category with an empty list, and the page would then
 * show "bu günde haber toplanmamış" over an archive that is full. Same rule
 * `parseCampaignFilters` states for `?band=purple`. */
function readCategory(params: URLSearchParams): string | null {
  const value = params.get("category");
  return value && (CATEGORY_SLUGS as readonly string[]).includes(value) ? value : null;
}

/** `?date=` off the address bar, restricted to the days the strip actually
 * offers. A date outside the window has no chip to light and no counts to
 * check, so it falls back to the strip's own choice rather than rendering a
 * selected day the reader cannot see selected. */
function readDate(params: URLSearchParams, days: readonly string[]): string | null {
  const value = params.get("date");
  return value && days.includes(value) ? value : null;
}

/**
 * ARŞİV -- the archive's one job is to be the place a beat can be read whole.
 *
 * `?category` AND `?date` ARE BOTH URL-OWNED, and that is the point of this
 * screen. Gazete's "Arşivde tümü" link (components/gazete/news-section.tsx)
 * writes `?category=<beat>` and is this page's only deep-link path: the paper
 * prints the critical few and this is where the rest of that beat lives. The
 * link used to write a param nothing here read -- the reader got an unfiltered
 * single-day list with `category=` still in the address bar, which is worse
 * than no filter at all, because the URL said the filter had been applied.
 *
 * THE COUNTS AND THE JUMP MOVE WITH THE FILTER. `/articles/daily-counts` takes
 * the same `category`, so each day chip's badge counts the rows that day's
 * list will actually render, and the "today is empty, open on the newest day
 * that isn't" jump lands on the newest day with news IN THIS BEAT. Jumping on
 * an unfiltered tally would drop the reader on a day that has news but none of
 * the news they asked for -- an empty page reached by a rule they cannot see.
 */
export function ArchiveClient() {
  const { params, replaceParams } = useUrlState();
  // Derived from the clock once per mount: a strip that re-derived "today"
  // per render could disagree with itself across one paint.
  const days = useMemo(() => lastDays(), []);

  const category = readCategory(params);
  const urlDate = readDate(params, days);

  const [counts, setCounts] = useState<Record<string, number> | null>(null);
  /** Where the strip landed on its own, for as long as the URL names no day.
   * The URL always wins when it names one -- this is the fallback, not a
   * second source of truth. */
  const [fallbackDay, setFallbackDay] = useState(days[0]);
  const selected = urlDate ?? fallbackDay;

  const [items, setItems] = useState<ArticleOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editions, setEditions] = useState<EditionSummaryOut[]>([]);

  const setFilters = useCallback(
    (next: { category?: string | null; date?: string | null }) => {
      // Onto the current params, so an unrelated key someone linked with
      // survives -- the same base-preserving serialise `lib/campaigns.ts` does.
      const updated = new URLSearchParams(params.toString());
      if (next.category !== undefined) writeParam(updated, "category", next.category);
      // Clearing the day hands the choice back to the strip's own rule: stay
      // where you are while that day still has news in the beat now selected,
      // and jump to the newest day that does when it does not. Pinning the
      // old day instead would strand a reader on a day the new beat is empty
      // on; jumping unconditionally would move the page under someone who had
      // not asked it to.
      if (next.date !== undefined) writeParam(updated, "date", next.date);
      replaceParams(updated);
    },
    [params, replaceParams],
  );

  // The edition list is a bonus section and never narrows: an edition is the
  // whole day's paper, so filtering it by beat would print a headline whose
  // story the filtered page cannot show.
  useEffect(() => {
    let cancelled = false;
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
  }, []);

  // Counts re-fetch when the beat changes, because they are counts OF that
  // beat. `days` is derived from the clock once per mount and is stable.
  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const query = new URLSearchParams({ days: String(DAYS) });
    if (category) query.set("category", category);

    apiFetch<Record<string, number>>(`/articles/daily-counts?${query.toString()}`, {
      cache: "default",
      signal: controller.signal,
    })
      .then((data) => {
        if (cancelled) return;
        setCounts(data);
        // If the day in view is empty in this beat, open on the newest day
        // that isn't. Only the fallback moves: a day the reader put in the URL
        // is a day they asked for, and silently walking away from it would
        // make the address bar disagree with the page.
        setFallbackDay((current) =>
          (data[current] ?? 0) > 0
            ? current
            : (days.find((day) => (data[day] ?? 0) > 0) ?? current),
        );
      })
      .catch(() => {
        if (cancelled || controller.signal.aborted) return;
        setCounts({});
      });
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [category, days]);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const query = new URLSearchParams({ date: selected, limit: "100" });
    if (category) query.set("category", category);

    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch driven by day/beat selection; the loading flag must flip with it
    setLoading(true);
    apiFetch<ArticleListOut>(`/articles?${query.toString()}`, {
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
  }, [selected, category]);

  const edition = editions.find((e) => e.edition_date === selected);
  const categoryLabel = category ? (CATEGORY_BY_SLUG[category]?.label ?? category) : null;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">Arşiv</h1>
        <p className="text-sm text-muted-foreground">
          Son {DAYS} günde toplanan haberler — gün seçin.
        </p>
      </div>

      {/* The active beat, as a chip that can be taken off. A filter arriving
          from another page's link has no control of its own on screen, so
          without this the reader can see `category=` in the URL and has no way
          to clear it but by editing the URL. */}
      {categoryLabel && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Filtre
          </span>
          <button
            type="button"
            onClick={() => setFilters({ category: null, date: null })}
            aria-label={`${categoryLabel} filtresini kaldır`}
            className="flex items-center gap-1 rounded-full bg-primary/12 px-2.5 py-1 text-xs font-medium text-primary ring-1 ring-primary/40 transition-colors hover:bg-primary/20 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring dark:glow-soft"
          >
            {categoryLabel}
            <X className="size-3" aria-hidden />
          </button>
          <span className="text-[11px] text-muted-foreground">
            Gün sayıları da bu başlığa göre sayılıyor.
          </span>
        </div>
      )}

      {/* Date strip */}
      <div className="flex gap-2 overflow-x-auto pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {days.map((iso) => {
          const { weekday, date } = dayLabel(iso);
          const count = counts?.[iso] ?? 0;
          const active = iso === selected;
          return (
            <button
              key={iso}
              onClick={() => setFilters({ date: iso })}
              aria-pressed={active}
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
          <p className="text-sm font-medium text-foreground">
            {categoryLabel
              ? `Bu günde ${categoryLabel.toLocaleLowerCase("tr")} haberi toplanmamış`
              : "Bu günde haber toplanmamış"}
          </p>
          <p className="mt-1 text-sm text-muted-foreground">
            {categoryLabel
              ? "Başka bir gün seçin ya da filtreyi kaldırın."
              : "Başka bir gün seçin."}
          </p>
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
                    {editionDayLabel(e.edition_date)}
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
