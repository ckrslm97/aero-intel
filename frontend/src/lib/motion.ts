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
 *
 * THERE ARE NO `exit` VARIANTS IN THIS FILE, and adding one would be a bug
 * rather than a feature. Every `exit` needs an `AnimatePresence` to drive it,
 * and in this stack (framer-motion 12 + React 19) an exit animation runs and
 * then never reports completion -- so the "leaving" subtree is never
 * unmounted. Measured three separate times here, on three different surfaces:
 * a drawer left a full-screen invisible backdrop swallowing every click, a
 * filtered card list kept the cards the filter had just excluded, and a hub
 * panel stopped updating after the second switch. The app animates things IN
 * and removes them outright. See components/ui/drawer-shell.tsx.
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
};

/** Slide-over panel, entering from the right edge.
 *
 * NO `exit` key any more, and its absence is deliberate. Every drawer in this
 * app is mounted and unmounted outright rather than wrapped in
 * `AnimatePresence` -- measured three times in this stack (framer-motion 12 +
 * React 19), the exit animation runs and its completion callback never fires,
 * so the subtree is never unmounted and a `fixed inset-0` backdrop is left
 * over the page forever. Leaving a dead `exit` variant here would be an
 * invitation to wire it back up. See components/ui/drawer-shell.tsx. */
export const drawerPanel: Variants = {
  hidden: { x: "100%", opacity: 0.6 },
  show: {
    x: 0,
    opacity: 1,
    transition: { type: "spring", stiffness: 320, damping: 34 },
  },
};

/** The same panel entering from the LEFT edge -- the mobile navigation. */
export const drawerPanelLeft: Variants = {
  hidden: { x: "-100%", opacity: 0.6 },
  show: {
    x: 0,
    opacity: 1,
    transition: { type: "spring", stiffness: 320, damping: 34 },
  },
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
 * number and not `"auto"`. Under reduced motion `<MotionConfig
 * reducedMotion="user">` reduces the animation, so the section simply appears
 * at its open height instead of unrolling to it.
 */
export function collapseSection(height: number): Variants {
  return {
    hidden: { height: 0, opacity: 0 },
    show: { height, opacity: 1, transition: { duration: 0.24 } },
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

/* `reduceVariants(...)` used to live here: it flattened a variant set so a
 * caller could hand a still version to `variants=` when `useReducedMotion()`
 * was true. It is gone, along with its last three callers, because using it
 * REQUIRED the branch the docblock at the top of this file forbids -- and the
 * hook it branched on answers false on the server and true on a client that
 * asked for stillness. `<MotionConfig reducedMotion="user">` reduces the same
 * animations at animation time, where both sides of the boundary render the
 * same markup. */

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
