"use client";

import { useEffect, useMemo, useState } from "react";

import { ArticleCard } from "@/components/article-card";
import { InlineSourceError } from "@/components/data-source-error";
import { SectionHeader } from "@/components/kokpit/section-header";
import { MotionItem, MotionList } from "@/components/motion/motion-list";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api";
import {
  appendGazeteFilters,
  applyWindowParams,
  type GazeteFilters,
  windowOption,
} from "@/lib/gazete";
import { categoryVar, getCategory } from "@/lib/taxonomy";
import type { ArticleListOut, ArticleOut } from "@/lib/types";

/** Cards a section prints before it stops and points at the archive.
 *
 * The backend hands out at most 8 (Gelir Yönetimi) or 5 (Havalimanı) critical
 * stories per run with no carry-over, so over the paper's three-day default a
 * section usually has fewer than this and the cap never fires. It exists for
 * the reader who widens the window to 30 gün, where the honest answer is "here
 * are the first twelve, the rest is an archive" rather than four hundred
 * tiles. */
const SECTION_LIMIT = 12;

/** One beat of the paper: a heading, its count, and its cards.
 *
 * Each section issues its OWN query with an explicit `category=`. The paper
 * used to make one query under a tab row, which is why it needed
 * `exclude_categories` to keep the other eight beats out and a shared
 * pagination to walk what came back. Per-section queries make the exclusion
 * structural, make `total` a per-section number the heading can print
 * truthfully, and mean a quiet Havalimanı day cannot be papered over by a busy
 * Gelir Yönetimi one -- which is the same rule the backend's quota enforces
 * upstream (backend/app/services/critical_selection.py).
 *
 * A section that has nothing says so in one line. It does NOT hide itself: the
 * two news beats are the paper's masthead promise, and a section that vanishes
 * on a quiet day teaches the reader that the page is unreliable rather than
 * that the wire was quiet. (The event blocks below it do hide themselves --
 * they are additions, not the promise.)
 */
export function NewsSection({
  categorySlug,
  filters,
}: {
  categorySlug: string;
  filters: GazeteFilters;
}) {
  const category = getCategory(categorySlug);
  const [items, setItems] = useState<ArticleOut[]>([]);
  const [total, setTotal] = useState(0);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  /** Bumped by the retry, so the effect below re-runs the SAME query. */
  const [retryToken, setRetryToken] = useState(0);

  const activeWindow = windowOption(filters.window);
  const { subcategory, region, country, airline } = filters;

  const query = useMemo(() => {
    const params = new URLSearchParams({
      category: categorySlug,
      limit: String(SECTION_LIMIT),
    });
    applyWindowParams(params, activeWindow);
    appendGazeteFilters(params);
    if (subcategory) params.set("subcategory", subcategory);
    if (region) params.set("region", region);
    if (country) params.set("country", country);
    if (airline) params.set("airline", airline);
    return params.toString();
  }, [categorySlug, activeWindow, subcategory, region, country, airline]);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    // eslint-disable-next-line react-hooks/set-state-in-effect -- the fetch is driven by the filter change; the loading flag has to flip with the dependency, not a render later
    setState("loading");
    // cache: "default" lets the browser reuse its own copy -- the API sends
    // max-age, so returning to a filter already viewed is instant. The abort
    // stops chip-spam from queueing abandoned requests ahead of the one the
    // reader is waiting for.
    apiFetch<ArticleListOut>(`/articles?${query}`, {
      cache: "default",
      signal: controller.signal,
    })
      .then((data) => {
        if (cancelled) return;
        setItems(data.items);
        setTotal(data.total);
        setState("ready");
      })
      .catch((error: unknown) => {
        if (cancelled || (error as Error)?.name === "AbortError") return;
        setState("error");
      });
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [query, retryToken]);

  // "3 kritik gelişme", from the server's filtered total rather than from
  // `items.length` -- the two differ exactly when the cap fired, and a caption
  // that quietly said "12" for a section holding 40 would be the heading
  // lying about its own list.
  const caption =
    state === "ready" ? `${total} kritik gelişme · ${activeWindow.scopeLabel}` : undefined;

  return (
    <section className="flex flex-col gap-4">
      <SectionHeader
        title={category.label}
        caption={caption}
        glowVar={categoryVar(categorySlug)}
        // The paper prints the critical few; everything that ever ran is one
        // click away, pre-filtered to this beat.
        action={{ href: `/archive?category=${categorySlug}`, label: "Arşivde tümü" }}
      />

      {state === "loading" ? (
        <SectionSkeleton />
      ) : state === "error" ? (
        // A WAY BACK, not just a diagnosis. The sentence already told the two
        // cases apart -- an unread section is not an empty beat -- but it left
        // the reader with nothing to do about it and a page reload as the only
        // move, which throws away every filter they set to get here.
        <InlineSourceError
          message={`${category.label} haberleri okunamadı; bu dönemde gelişme olmadığı anlamına gelmez.`}
          onRetry={() => setRetryToken((token) => token + 1)}
          // No `pending`: the effect flips `state` back to "loading" in the
          // same commit as the retry, so this line is replaced by the section
          // skeleton for exactly as long as the request runs. The in-flight
          // report is the skeleton itself, not a label on a button that is no
          // longer on screen.
          className="text-sm"
        />
      ) : items.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {activeWindow.unbounded
            ? `Arşivde bu filtrelerle ${category.label.toLocaleLowerCase("tr")} gelişmesi yok.`
            : `Seçili dönemde (${activeWindow.scopeLabel}) kritik ${category.label.toLocaleLowerCase("tr")} gelişmesi yok.`}
        </p>
      ) : (
        <MotionList className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {items.map((article) => (
            <MotionItem key={article.id} className="h-full">
              <ArticleCard article={article} variant="grid" />
            </MotionItem>
          ))}
        </MotionList>
      )}
    </section>
  );
}

function SectionSkeleton() {
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
      {Array.from({ length: 3 }).map((_, index) => (
        <div key={index} className="flex flex-col gap-2 rounded-xl bg-card p-4 ring-1 ring-foreground/10">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-4/5" />
          <Skeleton className="mt-1 h-3 w-full" />
          <Skeleton className="h-3 w-3/4" />
          <Skeleton className="mt-2 h-2.5 w-24" />
        </div>
      ))}
    </div>
  );
}
