"use client";

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { ChevronDown } from "lucide-react";
import { useEffect, useState } from "react";

import { apiFetch } from "@/lib/api";
import { applyWindowParams, sourceTierLabelTr, type WindowOption } from "@/lib/gazete";
import { collapseSection, reduceVariants, useMeasuredHeight } from "@/lib/motion";
import type { ArticleSourceFacetOut } from "@/lib/types";
import { cn } from "@/lib/utils";

/** How many outlets the row shows before its expander. Ten is roughly where a
 * chip row stops being scannable at a glance on a laptop; the rest are one
 * click away rather than absent, because "my outlet is not on the list" is a
 * worse failure than "I had to expand it". */
const VISIBLE = 10;

/** What the endpoint is asked for. Thirty is roughly the active source
 * catalogue -- past that a filter becomes a directory. */
const FETCH_LIMIT = 30;

/** "Kaynak" -- the named-outlet chips, one rung below the tier chips.
 *
 * The options come from `/articles/source-facets`, which counts the SAME
 * window and quality filters the list below uses. That is the whole reason it
 * is a request rather than a pass over the loaded articles: the list is
 * paginated thirty at a time, so chips derived from what is on screen would
 * describe page 1, and their counts would move as the reader paged.
 *
 * The facets deliberately ignore the current tier and source selection, so
 * pressing a chip narrows the LIST and never the row -- a filter row that
 * deletes its own options as soon as one is used is a trap.
 *
 * Renders nothing at all when the window has fewer than two outlets: a
 * "Kaynak: Hepsi | Reuters" row over a list that is entirely Reuters is a
 * control with no choice in it.
 */
export function SourceFilterRow({
  window: windowOption,
  category,
  minImportance,
  excludedCategories,
  value,
  onChange,
}: {
  window: WindowOption;
  category: string;
  minImportance: number;
  excludedCategories: readonly string[];
  value: string | null;
  onChange: (source: string | null) => void;
}) {
  const reduceMotion = useReducedMotion();
  const [facets, setFacets] = useState<ArticleSourceFacetOut[]>([]);
  const [expanded, setExpanded] = useState(false);
  const [restRef, restHeight] = useMeasuredHeight<HTMLDivElement>();

  useEffect(() => {
    const controller = new AbortController();
    const params = applyWindowParams(
      new URLSearchParams({
        category,
        limit: String(FETCH_LIMIT),
        translated_only: "true",
        min_importance: String(minImportance),
      }),
      windowOption,
    );
    excludedCategories.forEach((slug) => params.append("exclude_categories", slug));

    apiFetch<ArticleSourceFacetOut[]>(`/articles/source-facets?${params.toString()}`, {
      cache: "default",
      signal: controller.signal,
    })
      .then(setFacets)
      .catch(() => {
        /* no facets -> no row, rather than a row of nothing */
      });
    return () => controller.abort();
  }, [category, minImportance, excludedCategories, windowOption]);

  if (facets.length < 2) return null;

  const head = facets.slice(0, VISIBLE);
  const rest = facets.slice(VISIBLE);
  const variants = collapseSection(restHeight);

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        Kaynak adı
      </span>
      <SourceChip active={value === null} onClick={() => onChange(null)} label="Hepsi" />
      {head.map((facet) => (
        <SourceChip
          key={facet.name}
          active={value === facet.name}
          onClick={() => onChange(value === facet.name ? null : facet.name)}
          label={facet.name}
          count={facet.count}
          // The effective tier the backend resolved -- the same string an
          // article card badges the outlet with, so the two cannot disagree.
          title={`${facet.name} · ${sourceTierLabelTr(facet.tier)} · ${facet.count} haber`}
        />
      ))}

      {rest.length > 0 && (
        <button
          type="button"
          onClick={() => setExpanded((open) => !open)}
          aria-expanded={expanded}
          className="flex items-center gap-1 rounded-full border border-dashed border-border px-2.5 py-1 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
        >
          {expanded ? "Daha az" : `+${rest.length} kaynak daha`}
          <ChevronDown
            aria-hidden
            className={cn(
              "size-3 transition-transform motion-reduce:transition-none",
              expanded && "rotate-180",
            )}
          />
        </button>
      )}

      {/* Full-width so the revealed chips wrap under the row rather than
          trailing off the end of it. */}
      <div className="w-full">
        <AnimatePresence initial={false}>
          {expanded && rest.length > 0 && (
            <motion.div
              key="rest"
              variants={reduceMotion ? reduceVariants(variants) : variants}
              initial="hidden"
              animate="show"
              exit="exit"
              className="overflow-hidden"
            >
              <div ref={restRef} className="flex flex-wrap gap-1.5 pt-1.5">
                {rest.map((facet) => (
                  <SourceChip
                    key={facet.name}
                    active={value === facet.name}
                    onClick={() => onChange(value === facet.name ? null : facet.name)}
                    label={facet.name}
                    count={facet.count}
                    title={`${facet.name} · ${sourceTierLabelTr(facet.tier)} · ${facet.count} haber`}
                  />
                ))}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}

function SourceChip({
  active,
  onClick,
  label,
  count,
  title,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  count?: number;
  title?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      aria-pressed={active}
      // Spelled out rather than left to the DOM: the label and the count are
      // adjacent spans, so the derived accessible name of "Outlet 1" with 13
      // stories would be the unreadable "Outlet 113".
      aria-label={count === undefined ? label : `${label}, ${count} haber`}
      className={cn(
        "flex max-w-[14rem] items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
        active
          ? "bg-primary text-primary-foreground"
          : "border border-border text-muted-foreground hover:bg-accent",
      )}
    >
      <span className="truncate">{label}</span>
      {count !== undefined && (
        <span className={cn("tabular-nums", active ? "opacity-80" : "opacity-70")}>
          {count}
        </span>
      )}
    </button>
  );
}
