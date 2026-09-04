"use client";

import type { ClassValue } from "clsx";
import { useId } from "react";

import { cn } from "@/lib/utils";

/** The filter chip's classes, as a string, for the one caller that cannot use
 * the component: `filters/category-chip-row.tsx` draws each chip in its own
 * taxonomy hue through an inline style and animates each one individually, so
 * it composes these classes rather than rendering `<FilterChip>`.
 *
 * THE MEASURE IS `px-2.5 py-1 text-xs`, and it is not cosmetic. 12px text on a
 * 16px line plus 4px of padding each side is a 24px-high control -- the floor
 * WCAG 2.2 sets for a target with adequate spacing around it. The copies this
 * replaces ran as small as `px-2 py-0.5 text-[11px]`: a 17px tap target, on a
 * page whose filter panel is seven rows deep and is genuinely used on a phone.
 *
 * (The 48px an isolated target wants is not reachable here. These rows carry
 * up to eleven chips each and the panel's whole reason to exist is that a desk
 * can see seven filter dimensions at once; 48px chips would push five of the
 * seven below the fold. 24px plus the row's own 6px gap is the honest ceiling
 * for this control surface, and it is more than the 17px it replaces.)
 */
export function filterChipClass(active: boolean, className?: ClassValue) {
  return cn(
    "inline-flex min-h-6 items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium transition-colors",
    // A VISIBLE focus ring, on every chip. Five of the seven copies had none at
    // all, which on a page navigated entirely by chip rows means a keyboard
    // reader could not see where they were.
    "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
    active
      ? "bg-primary/12 text-primary ring-1 ring-primary/40 dark:glow-soft"
      : "border border-border text-muted-foreground hover:bg-accent",
    className,
  );
}

/**
 * One filter chip: a toggle that narrows the list beside it.
 *
 * WHAT IT REPLACES. Seven near-identical local `chip()` helpers across seven
 * pages, in four different sizes, of which two carried a focus ring. More
 * importantly they were rendered as PLAIN buttons: of the thirty-odd chips on
 * this site only five announced their state, so a screen reader read a filter
 * row as a list of buttons with no way to tell which one was doing the
 * filtering. `aria-pressed` is not optional here -- it IS the chip's state.
 *
 * `label` overrides the accessible name and exists mainly for the "Tümü"
 * chips. There are nine of them on the campaign page alone, all reading
 * literally "Tümü"; a reader tabbing through heard "Tümü, Tümü, Tümü" with no
 * way to know which axis each one cleared. Every one of them now names its
 * axis ("Tüm taşıyıcılar"), while the visible text stays the one word the
 * layout has room for.
 */
export function FilterChip({
  active,
  onClick,
  label,
  title,
  className,
  children,
}: {
  /** Drives both the lit styling and `aria-pressed`. */
  active: boolean;
  onClick: () => void;
  /** Accessible name, when the visible text is not enough on its own. */
  label?: string;
  title?: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      aria-label={label}
      title={title}
      className={filterChipClass(active, className)}
    >
      {children}
    </button>
  );
}

/**
 * A labelled row of chips.
 *
 * `role="group"` + `aria-labelledby` is what ties the chips to the word above
 * them. Without it the label is decorative text and a screen reader announces
 * eleven region chips with nothing saying they are regions -- which on a page
 * with five such rows is five indistinguishable lists of nouns.
 *
 * The label is rendered here rather than passed in as a node so a row cannot
 * be built without one.
 */
export function FilterChipGroup({
  label,
  /** Label above the chips instead of beside them -- for rows long enough that
   * an inline label costs a whole line of chips. */
  stacked = false,
  labelClassName,
  className,
  children,
}: {
  label: string;
  stacked?: boolean;
  labelClassName?: string;
  className?: string;
  children: React.ReactNode;
}) {
  const labelId = useId();
  if (stacked) {
    return (
      <div role="group" aria-labelledby={labelId} className={cn("flex flex-col gap-1.5", className)}>
        <span
          id={labelId}
          className={cn(
            "text-[11px] font-semibold uppercase tracking-wide text-muted-foreground",
            labelClassName,
          )}
        >
          {label}
        </span>
        <div className="flex flex-wrap gap-1.5">{children}</div>
      </div>
    );
  }
  return (
    <div
      role="group"
      aria-labelledby={labelId}
      className={cn("flex flex-wrap items-center gap-1.5", className)}
    >
      <span
        id={labelId}
        className={cn(
          "shrink-0 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground",
          labelClassName,
        )}
      >
        {label}
      </span>
      {children}
    </div>
  );
}
