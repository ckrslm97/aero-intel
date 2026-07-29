"use client";

import { motion, useReducedMotion } from "framer-motion";

import { CATEGORIES } from "@/lib/taxonomy";
import { cn } from "@/lib/utils";

const PINNED_DEFAULT = "revenue_management";

/** Pinned slug first, everything else alphabetised by Turkish label. The
 * backend keeps its own canonical order, so this is a render-time sort. */
export function orderCategories(pinned: string | null) {
  const rest = CATEGORIES.filter((c) => c.slug !== pinned).sort((a, b) =>
    a.label.localeCompare(b.label, "tr"),
  );
  const head = CATEGORIES.find((c) => c.slug === pinned);
  return head ? [head, ...rest] : rest;
}

export interface CategoryChipRowProps {
  /** Selected slug, or null when "Tümü" is active (requires `includeAll`). */
  value: string | null;
  onChange: (slug: string | null) => void;
  /** Slug rendered first in the row. Defaults to Gelir Yönetimi. */
  pinned?: string | null;
  /** Render a leading "Tümü" chip that clears the filter. */
  includeAll?: boolean;
  /** Keep the pinned category in its own colour even when inactive --
   * the portal's focus category has to stand apart in the row. */
  focusStyling?: boolean;
  /** Optional per-slug article counts, rendered as a trailing badge. */
  counts?: Record<string, number>;
  /** "pill" = the Gazete bar (icon + colour + sliding pill). "plain" = the
   * neutral filter chips used by Öneriler/İçgörüler. */
  variant?: "pill" | "plain";
  /** Distinct id per mounted row so two rows don't share one sliding pill. */
  layoutId?: string;
  className?: string;
}

export function CategoryChipRow({
  value,
  onChange,
  pinned = PINNED_DEFAULT,
  includeAll = false,
  focusStyling = false,
  counts,
  variant = "pill",
  layoutId = "activeCategoryPill",
  className,
}: CategoryChipRowProps) {
  const reduceMotion = useReducedMotion();
  const ordered = orderCategories(pinned);

  if (variant === "plain") {
    const chip = (active: boolean) =>
      cn(
        "rounded-full px-2.5 py-1 text-xs font-medium transition-colors",
        active
          ? "bg-primary text-primary-foreground"
          : "border border-border text-muted-foreground hover:bg-accent",
      );
    return (
      <>
        {includeAll && (
          <button type="button" onClick={() => onChange(null)} className={chip(!value)}>
            Tümü
          </button>
        )}
        {ordered.map((c) => {
          const active = value === c.slug;
          const isFocus = focusStyling && c.slug === pinned;
          return (
            <button
              key={c.slug}
              type="button"
              onClick={() => onChange(active ? null : c.slug)}
              className={cn(
                chip(active),
                !active &&
                  isFocus &&
                  "border-category-revenue-management/50 bg-category-revenue-management/10 text-category-revenue-management hover:bg-category-revenue-management/20",
              )}
            >
              {c.label}
            </button>
          );
        })}
      </>
    );
  }

  return (
    <div
      className={cn(
        "flex gap-1.5 overflow-x-auto pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden",
        className,
      )}
    >
      {includeAll && (
        <button
          type="button"
          onClick={() => onChange(null)}
          className={cn(
            "relative flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-semibold transition-colors",
            value === null
              ? "bg-primary text-primary-foreground"
              : "text-muted-foreground hover:bg-accent",
          )}
        >
          Tümü
        </button>
      )}
      {ordered.map((c) => {
        const Icon = c.icon;
        const active = c.slug === value;
        const count = counts?.[c.slug];
        const isFocus = focusStyling && c.slug === pinned;
        return (
          <button
            key={c.slug}
            type="button"
            onClick={() => onChange(c.slug)}
            className={cn(
              "relative flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-semibold transition-colors",
              active
                ? c.textClass
                : isFocus
                  ? "border border-category-revenue-management/50 bg-category-revenue-management/10 text-category-revenue-management hover:bg-category-revenue-management/20"
                  : "text-muted-foreground hover:bg-accent",
            )}
          >
            {active && (
              <motion.span
                layoutId={layoutId}
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
  );
}
