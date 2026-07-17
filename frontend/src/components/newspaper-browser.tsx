"use client";

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { Download } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { ArticleCard } from "@/components/article-card";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api";
import { CATEGORIES, EVENT_REGIONS } from "@/lib/taxonomy";
import type { ArticleListOut, ArticleOut } from "@/lib/types";
import { cn } from "@/lib/utils";

// Only recent articles -- keeps the browser focused on "what's current"
// rather than the entire archive, per the freshness feedback on this page.
const DAYS_WINDOW = 30;
const PAGE_LIMIT = 30;

export function NewspaperBrowser() {
  const reduceMotion = useReducedMotion();

  const [categorySlug, setCategorySlug] = useState(CATEGORIES[0].slug); // Gelir Yönetimi first
  const [subcategorySlug, setSubcategorySlug] = useState<string | null>(null);
  const [regionSlug, setRegionSlug] = useState<string | null>(null);

  const [items, setItems] = useState<ArticleOut[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true); // first page (filter change)
  const [loadingMore, setLoadingMore] = useState(false); // subsequent pages
  const [error, setError] = useState<string | null>(null);

  const [counts, setCounts] = useState<Record<string, number>>({});

  const category = CATEGORIES.find((c) => c.slug === categorySlug) ?? CATEGORIES[0];
  const isEvents = categorySlug === "events";

  function selectCategory(slug: string) {
    setCategorySlug(slug);
    // Etkinlik always starts on "Genel"; every other category starts on "Tümü".
    setSubcategorySlug(slug === "events" ? "general" : null);
    setRegionSlug(null);
    setOffset(0);
  }

  // Tab badges: one grouped request, refreshed when the window is entered.
  useEffect(() => {
    let cancelled = false;
    apiFetch<Record<string, number>>(`/articles/counts?days=${DAYS_WINDOW}`)
      .then((data) => {
        if (!cancelled) setCounts(data);
      })
      .catch(() => {
        /* badges are decorative -- a failure here must not break the list */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Article list. offset===0 replaces (a filter changed); offset>0 appends
  // ("Daha fazla yükle"). Both live in one effect so they can't race.
  useEffect(() => {
    let cancelled = false;
    const params = new URLSearchParams({
      category: categorySlug,
      days: String(DAYS_WINDOW),
      limit: String(PAGE_LIMIT),
      offset: String(offset),
    });
    if (subcategorySlug) params.set("subcategory", subcategorySlug);
    if (regionSlug) params.set("region", regionSlug);

    const isFirstPage = offset === 0;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch driven by filter/offset change; the loading flag must flip synchronously with the dependency change
    if (isFirstPage) setLoading(true);
    else setLoadingMore(true);

    apiFetch<ArticleListOut>(`/articles?${params.toString()}`)
      .then((data) => {
        if (cancelled) return;
        setItems((prev) => (isFirstPage ? data.items : [...prev, ...data.items]));
        setTotal(data.total);
        setError(null);
      })
      .catch(() => {
        if (!cancelled) setError("Haberler yüklenemedi. Sunucu çalışıyor mu?");
      })
      .finally(() => {
        if (cancelled) return;
        setLoading(false);
        setLoadingMore(false);
      });
    return () => {
      cancelled = true;
    };
  }, [categorySlug, subcategorySlug, regionSlug, offset]);

  const today = new Date().toISOString().slice(0, 10);
  const hasMore = items.length < total;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl font-semibold tracking-tight">Gazete</h1>
          <p className="text-sm text-muted-foreground">
            Kategoriye göre doğrulanmış, güncel havacılık haberleri.
          </p>
        </div>
        <Link
          href={`/newspaper/${today}`}
          className="flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-accent"
        >
          <Download className="size-3.5" />
          Günün Gazetesi
        </Link>
      </div>

      {/* Sticky category bar -- horizontally scrollable on mobile, blurred so
          content reads through it while scrolling. */}
      <div className="sticky top-0 z-10 -mx-2 border-b border-border bg-background/80 px-2 pb-3 pt-2 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="flex gap-1.5 overflow-x-auto pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          {CATEGORIES.map((c) => {
            const Icon = c.icon;
            const active = c.slug === categorySlug;
            const count = counts[c.slug];
            return (
              <button
                key={c.slug}
                onClick={() => selectCategory(c.slug)}
                className={cn(
                  "relative flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-semibold transition-colors",
                  active ? c.textClass : "text-muted-foreground hover:bg-accent",
                )}
              >
                {active && (
                  <motion.span
                    layoutId="activeCategoryPill"
                    className={cn("absolute inset-0 rounded-full", c.bgClass)}
                    transition={
                      reduceMotion
                        ? { duration: 0 }
                        : { type: "spring", stiffness: 500, damping: 34 }
                    }
                  />
                )}
                <Icon className="relative z-10 size-3.5" />
                <span className="relative z-10">{c.label}</span>
                {count ? (
                  <span
                    className={cn(
                      "relative z-10 rounded-full px-1.5 text-[10px] font-semibold tabular-nums",
                      active ? "bg-background/60" : "bg-muted text-muted-foreground",
                    )}
                  >
                    {count}
                  </span>
                ) : null}
              </button>
            );
          })}
        </div>
      </div>

      {isEvents ? (
        <div className="flex flex-wrap gap-1.5">
          <button
            onClick={() => {
              setSubcategorySlug("general");
              setRegionSlug(null);
              setOffset(0);
            }}
            className={cn(
              "rounded-full px-3 py-1 text-xs font-medium transition-colors",
              !regionSlug
                ? "bg-primary text-primary-foreground"
                : "border border-border text-muted-foreground hover:bg-accent",
            )}
          >
            Genel
          </button>
          {EVENT_REGIONS.map((r) => (
            <button
              key={r.slug}
              onClick={() => {
                setSubcategorySlug("regional");
                setRegionSlug(r.slug);
                setOffset(0);
              }}
              className={cn(
                "rounded-full px-3 py-1 text-xs font-medium transition-colors",
                regionSlug === r.slug
                  ? "bg-primary text-primary-foreground"
                  : "border border-border text-muted-foreground hover:bg-accent",
              )}
            >
              {r.name}
            </button>
          ))}
        </div>
      ) : (
        category.subcategories.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            <button
              onClick={() => {
                setSubcategorySlug(null);
                setOffset(0);
              }}
              className={cn(
                "rounded-full px-3 py-1 text-xs font-medium transition-colors",
                !subcategorySlug
                  ? "bg-primary text-primary-foreground"
                  : "border border-border text-muted-foreground hover:bg-accent",
              )}
            >
              Tümü
            </button>
            {category.subcategories.map((s) => (
              <button
                key={s.slug}
                onClick={() => {
                  setSubcategorySlug(s.slug);
                  setOffset(0);
                }}
                className={cn(
                  "rounded-full px-3 py-1 text-xs font-medium transition-colors",
                  subcategorySlug === s.slug
                    ? "bg-primary text-primary-foreground"
                    : "border border-border text-muted-foreground hover:bg-accent",
                )}
              >
                {s.label}
              </button>
            ))}
          </div>
        )
      )}

      {error ? (
        <p className="rounded-lg border border-dashed border-border p-6 text-sm text-muted-foreground">
          {error}
        </p>
      ) : loading ? (
        <ArticleListSkeleton />
      ) : items.length > 0 ? (
        <>
          <div className="flex flex-col divide-y divide-border rounded-xl border border-border bg-card">
            <AnimatePresence initial={false}>
              {items.map((article, index) => (
                <motion.div
                  key={article.id}
                  initial={reduceMotion ? false : { opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{
                    duration: reduceMotion ? 0 : 0.2,
                    // Stagger only the first page; appended pages animate at once.
                    delay: reduceMotion ? 0 : Math.min(index, PAGE_LIMIT) * 0.02,
                  }}
                >
                  <ArticleCard article={article} />
                </motion.div>
              ))}
            </AnimatePresence>
          </div>

          {hasMore && (
            <div className="flex justify-center">
              <button
                onClick={() => setOffset(items.length)}
                disabled={loadingMore}
                className="rounded-md border border-border px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-accent disabled:opacity-60"
              >
                {loadingMore ? "Yükleniyor…" : `Daha fazla yükle (${total - items.length})`}
              </button>
            </div>
          )}
        </>
      ) : (
        <div className="rounded-lg border border-dashed border-border p-10 text-center">
          <p className="text-sm font-medium text-foreground">Bu filtreyle haber bulunamadı</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Son {DAYS_WINDOW} günde bu kategoride yayımlanmış haber yok. Başka bir kategori
            veya alt başlık deneyin.
          </p>
        </div>
      )}
    </div>
  );
}

function ArticleListSkeleton() {
  return (
    <div className="flex flex-col divide-y divide-border rounded-xl border border-border bg-card">
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="flex flex-col gap-2 p-4">
          <div className="flex items-center gap-2">
            <Skeleton className="h-4 w-20 rounded-full" />
            <Skeleton className="h-4 w-16 rounded-full" />
            <Skeleton className="h-4 w-24 rounded-full" />
          </div>
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-5/6" />
        </div>
      ))}
    </div>
  );
}
