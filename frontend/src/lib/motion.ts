"use client";

import type { Transition, Variants } from "framer-motion";
import { useCallback, useRef, useState } from "react";

/** The app's shared animation vocabulary.
 *
 * These are the values that were already hand-written across
 * `newspaper-browser.tsx` and `sidebar.tsx`; they live here now so every
 * surface animates on the same clock instead of each page inventing its own
 * timing. The reduced-motion preference is applied ONCE, app-wide, by
 * `<MotionConfig reducedMotion="user">` (components/motion/motion-preferences.tsx);
 * never branch on `useReducedMotion()` to choose a VARIANT SET, because that
 * hook disagrees with itself across the server/client boundary.
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

/** Measure an element's natural height, for collapse animations.
 *
 * Returns `[ref, height]`. Attach the ref to the *content* inside the
 * `overflow-hidden` wrapper whose height is animated -- the content has to be
 * height-unconstrained for the measurement to mean anything (the wrapper
 * clips it, it does not squash it).
 *
 * Why this exists: `height: "auto"` is not an animatable value the compositor
 * can handle. Framer resolves it by laying the element out twice per frame,
 * so a 240ms expand is ~15 forced synchronous layouts of the subtree -- the
 * one animation in this app that could actually be felt. Animating to a pixel
 * number instead is a plain interpolation.
 *
 * A ResizeObserver rather than a single measurement on mount: the wrapper ends
 * up pinned to this exact number, so anything that reflows the content
 * afterwards -- a viewport resize rewrapping a line, a late webfont, the
 * content itself being swapped -- has to move the number with it, or the
 * wrapper clips what it can no longer fit. That is the one way a measured
 * height can be worse than "auto", and the observer closes it.
 */
export function useMeasuredHeight<T extends HTMLElement>(): [
  (node: T | null) => void,
  number,
] {
  const [height, setHeight] = useState(0);
  const observerRef = useRef<ResizeObserver | null>(null);

  // A callback ref rather than a ref object + effect: the measured content is
  // typically mounted *later* than the component holding the hook (a collapse
  // renders nothing while closed), and a `useLayoutEffect` with a stable
  // dependency list would have run once against a null ref and never again.
  // A callback ref fires on every attach and detach, still during commit and
  // so still before paint.
  const ref = useCallback((node: T | null) => {
    observerRef.current?.disconnect();
    observerRef.current = null;
    if (!node) return;
    const measure = () => setHeight(node.offsetHeight);
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    observerRef.current = observer;
  }, []);

  return [ref, height];
}

/** Collapsible section (hub panel "+N daha" expanders).
 *
 * Takes the open height in pixels -- see `useMeasuredHeight` for why this is a
 * number and not `"auto"`. Under reduced motion `reduceVariants` drops the
 * `height` key entirely, so the section is simply laid out at its natural
 * height with no animation at all; the measurement is then unused, exactly as
 * before this became a factory.
 */
export function collapseSection(height: number): Variants {
  return {
    hidden: { height: 0, opacity: 0 },
    show: { height, opacity: 1, transition: { duration: 0.24 } },
    exit: { height: 0, opacity: 0, transition: { duration: 0.18 } },
  };
}

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

/** Hover/tap props for a card.
 *
 * No reduced-motion argument any more: `<MotionConfig reducedMotion="user">`
 * at the app root reduces these transforms for a reader who asked for it,
 * and doing it there rather than here keeps the decision out of render (which
 * is what made it a hydration mismatch). */
export function hoverLift() {
  return {
    whileHover: cardHover.whileHover,
    whileTap: cardHover.whileTap,
    transition: cardHover.transition,
  };
}
