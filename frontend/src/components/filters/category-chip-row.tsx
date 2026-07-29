"use client";

import { motion, useReducedMotion } from "framer-motion";

import { chipPop, chipStagger, reduceVariants } from "@/lib/motion";
import { CATEGORIES, categoryVar } from "@/lib/taxonomy";
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

  const stagger = reduceMotion ? reduceVariants(chipStagger) : chipStagger;
  const pop = reduceMotion ? reduceVariants(chipPop) : chipPop;

  /** A selected chip burns in its own category color rather than in the one
   * neutral primary fill every row used to share -- the whole point of having
   * 11 validated category hues. Inline because the slug -> token name
   * transform is invisible to Tailwind's scanner. */
  const litStyle = (slug: string): React.CSSProperties => {
    const hue = categoryVar(slug);
    return {
      "--glow-color": hue,
      color: hue,
      backgroundColor: `color-mix(in srgb, ${hue} 14%, transparent)`,
    } as React.CSSProperties;
  };

  if (variant === "plain") {
    const chip = (active: boolean) =>
      cn(
        "rounded-full px-2.5 py-1 text-xs font-medium transition-colors",
        active
          ? "ring-1 ring-current/40 dark:glow-soft"
          : "border border-border text-muted-foreground hover:bg-accent",
      );
    // Each chip drives its own entrance instead of a stagger-orchestrating
    // parent: a `motion` parent set to `display:contents` (required so this
    // row contributes no box of its own -- the caller's FilterRow owns the
    // flex layout) can't be measured by Framer Motion, which left staggered
    // children stuck mid-animation. A plain, non-animating div still gives
    // the layout-only wrapper; the stagger becomes a per-index delay.
    const popTransition = (index: number) =>
      reduceMotion
        ? { duration: 0 }
        : { type: "spring" as const, stiffness: 600, damping: 28, mass: 0.6, delay: index * 0.025 };

    return (
      // Deliberately NOT re-keyed on `value`: remounting the row to re-pop
      // the chips on every filter change would unmount the button the user
      // just activated and drop keyboard focus to the body. The selection's
      // colour change is the feedback; the pop is an entrance.
      <div style={{ display: "contents" }}>
        {includeAll && (
          <motion.button
            initial="hidden"
            animate="show"
            variants={pop}
            transition={popTransition(0)}
            type="button"
            onClick={() => onChange(null)}
            className={cn(
              chip(!value),
              !value && "bg-primary/12 text-primary",
            )}
            style={!value ? ({ "--glow-color": "var(--primary)" } as React.CSSProperties) : undefined}
          >
            Tümü
          </motion.button>
        )}
        {ordered.map((c, i) => {
          const active = value === c.slug;
          const isFocus = focusStyling && c.slug === pinned;
          return (
            <motion.button
              key={c.slug}
              initial="hidden"
              animate="show"
              variants={pop}
              transition={popTransition(includeAll ? i + 1 : i)}
              type="button"
              onClick={() => onChange(active ? null : c.slug)}
              style={active ? litStyle(c.slug) : undefined}
              className={cn(
                chip(active),
                !active &&
                  isFocus &&
                  "border-category-revenue-management/50 bg-category-revenue-management/10 text-category-revenue-management hover:bg-category-revenue-management/20",
              )}
            >
              {c.label}
            </motion.button>
          );
        })}
      </div>
    );
  }

  return (
    // Deliberately NOT re-keyed on `value`, unlike the plain row above: this
    // is the variant that carries the shared-element `layoutId` pill, and
    // remounting the row on every click would destroy the element the pill
    // slides between. The chips pop once, on mount; after that the pill is
    // the thing that moves.
    <motion.div
      variants={stagger}
      initial="hidden"
      animate="show"
      className={cn(
        "flex gap-1.5 overflow-x-auto pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden",
        className,
      )}
    >
      {includeAll && (
        <motion.button
          variants={pop}
          type="button"
          onClick={() => onChange(null)}
          style={
            value === null
              ? ({ "--glow-color": "var(--primary)" } as React.CSSProperties)
              : undefined
          }
          className={cn(
            "relative flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-semibold transition-colors",
            value === null
              ? "bg-primary/12 text-primary ring-1 ring-primary/40 dark:glow-soft"
              : "text-muted-foreground hover:bg-accent",
          )}
        >
          Tümü
        </motion.button>
      )}
      {ordered.map((c) => {
        const Icon = c.icon;
        const active = c.slug === value;
        const count = counts?.[c.slug];
        const isFocus = focusStyling && c.slug === pinned;
        return (
          <motion.button
            key={c.slug}
            variants={pop}
            type="button"
            onClick={() => onChange(c.slug)}
            style={
              active
                ? ({ "--glow-color": categoryVar(c.slug) } as React.CSSProperties)
                : undefined
            }
            className={cn(
              "relative flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-semibold transition-colors",
              active
                ? cn(c.textClass, "ring-1 ring-current/40 dark:glow-soft")
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
          </motion.button>
        );
      })}
    </motion.div>
  );
}
