import type { Transition, Variants } from "framer-motion";

/** The app's shared animation vocabulary.
 *
 * These are the values that were already hand-written across
 * `newspaper-browser.tsx` and `sidebar.tsx`; they live here now so every
 * surface animates on the same clock instead of each page inventing its own
 * timing. Every consumer must gate them behind `useReducedMotion()` -- the
 * helpers below (`reduceVariants`, `hoverLift`) do that for you.
 */

/** Stagger parent. Children play ~50ms apart, capped by the child's own delay. */
export const staggerContainer: Variants = {
  hidden: {},
  show: {
    transition: { staggerChildren: 0.05, delayChildren: 0.02 },
  },
};

/** The standard entrance: a short fade with a small upward settle. */
export const fadeUpItem: Variants = {
  hidden: { opacity: 0, y: 12 },
  show: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.28, ease: [0.22, 1, 0.36, 1] },
  },
  exit: {
    opacity: 0,
    y: -8,
    transition: { duration: 0.18 },
  },
};

/** Card interaction spec: lift on hover, press in on tap. */
export const cardHover = {
  whileHover: { y: -2 },
  whileTap: { scale: 0.99 },
  transition: { type: "spring", stiffness: 400, damping: 30 } as Transition,
};

/** Drawer/modal backdrop. */
export const overlayFade: Variants = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { duration: 0.2 } },
  exit: { opacity: 0, transition: { duration: 0.15 } },
};

/** Slide-over panel, entering from the right edge. */
export const drawerPanel: Variants = {
  hidden: { x: "100%", opacity: 0.6 },
  show: {
    x: 0,
    opacity: 1,
    transition: { type: "spring", stiffness: 320, damping: 34 },
  },
  exit: { x: "100%", opacity: 0.6, transition: { duration: 0.2 } },
};

/** Collapsible section (hub panel "+N daha" expanders). */
export const collapseSection: Variants = {
  hidden: { height: 0, opacity: 0 },
  show: { height: "auto", opacity: 1, transition: { duration: 0.24 } },
  exit: { height: 0, opacity: 0, transition: { duration: 0.18 } },
};

/* --- "Approach lights" additions ---------------------------------------
 * Entrance/interaction only. Nothing below loops: every variant settles on a
 * final `show` state and stops. Glow-on-hover deliberately lives in CSS
 * (hover:glow / hover:shadow-elev-2) rather than here -- it is cheaper and it
 * picks up the per-mode --glow-alpha dial for free. Framer keeps owning
 * transforms.
 * -------------------------------------------------------------------- */

/** "Instrument power-on": a spring scale/opacity/y entrance for KPI and stat
 * cards, where `fadeUpItem` reads as too soft to register as a readout
 * coming alive. */
export const scalePopItem: Variants = {
  hidden: { opacity: 0, scale: 0.94, y: 10 },
  show: {
    opacity: 1,
    scale: 1,
    y: 0,
    transition: { type: "spring", stiffness: 420, damping: 30, mass: 0.7 },
  },
  exit: {
    opacity: 0,
    scale: 0.97,
    y: -6,
    transition: { duration: 0.16 },
  },
};

/** Stagger parent for filter chip rows -- much tighter than
 * `staggerContainer` (25ms) because a chip row re-runs on every filter
 * change and must not feel like it is loading. */
export const chipStagger: Variants = {
  hidden: {},
  show: {
    transition: { staggerChildren: 0.025, delayChildren: 0.01 },
  },
};

/** One chip popping in. */
export const chipPop: Variants = {
  hidden: { opacity: 0, scale: 0.86 },
  show: {
    opacity: 1,
    scale: 1,
    transition: { type: "spring", stiffness: 600, damping: 28, mass: 0.6 },
  },
};

/** A light bar drawing itself in from the left. Used for the section-header
 * and date-header hairlines. Pair with `origin-left`. */
export const railGrow: Variants = {
  hidden: { scaleX: 0, opacity: 0 },
  show: {
    scaleX: 1,
    opacity: 1,
    transition: { duration: 0.5, ease: [0.22, 1, 0.36, 1] },
  },
};

/** Cascades a drawer's interior AFTER the panel spring has landed, so the
 * content is not sliding while the panel is still travelling. */
export const drawerStagger: Variants = {
  hidden: {},
  show: {
    transition: { delayChildren: 0.18, staggerChildren: 0.05 },
  },
};

/** Strip every transform/opacity change out of a variant set, keeping the
 * shape so `variants=` / `initial=` / `animate=` names still resolve. Used
 * whenever `useReducedMotion()` is true. */
export function reduceVariants(variants: Variants): Variants {
  const flattened: Variants = {};
  for (const key of Object.keys(variants)) {
    // scaleX is flattened alongside scale so `railGrow` is reduced-motion-safe
    // like everything else -- without it a rail would still draw itself in.
    flattened[key] = {
      opacity: 1,
      x: 0,
      y: 0,
      scale: 1,
      scaleX: 1,
      transition: { duration: 0 },
    };
  }
  return flattened;
}

/** Hover/tap props for a card, or nothing at all under reduced motion. */
export function hoverLift(reduceMotion: boolean | null) {
  if (reduceMotion) return {};
  return {
    whileHover: cardHover.whileHover,
    whileTap: cardHover.whileTap,
    transition: cardHover.transition,
  };
}
