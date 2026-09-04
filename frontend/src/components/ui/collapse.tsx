"use client";

import { motion } from "framer-motion";

import { collapseSection, useMeasuredHeight } from "@/lib/motion";
import { cn } from "@/lib/utils";

/** Animated-height reveal for a capped list or a collapsed panel.
 *
 * The wrapper animates to a MEASURED pixel height rather than to `"auto"`,
 * which cannot be composited and re-lays-out the content every frame; the
 * measurement is taken on the inner div, which the `overflow-hidden` wrapper
 * clips without constraining. `useMeasuredHeight` keeps a ResizeObserver on it
 * so a reflow moves the number with it.
 *
 * This is a straight de-duplication: `hubs-client.tsx` and `insights-client.tsx`
 * carried byte-identical `Expandable` components, and the Alert Merkezi needed
 * a third. `reduceMotion` is now read here instead of being threaded in as a
 * prop, which is the only difference at the call sites.
 *
 * CLOSING IS INSTANT, and that is a fix rather than a regression. The open
 * height animates; the close used to be handed to `AnimatePresence`, whose
 * exit-complete callback never fires in this stack (framer-motion 12 + React
 * 19) -- so a "closed" section stayed mounted at its full measured height and
 * simply never went away. See components/ui/drawer-shell.tsx for the
 * measurement.
 */
export function Collapse({
  open,
  children,
  className,
}: {
  open: boolean;
  children: React.ReactNode;
  className?: string;
}) {
  const [contentRef, measuredHeight] = useMeasuredHeight<HTMLDivElement>();
  // No `useReducedMotion()` branch: the preference is applied once, at
  // animation time, by <MotionConfig reducedMotion="user"> at the app root.
  // Branching on it here produced different markup on the server and the
  // client -- see components/motion/motion-preferences.tsx.
  const variants = collapseSection(measuredHeight);

  if (!open) return null;

  return (
    <motion.div
      variants={variants}
      initial="hidden"
      animate="show"
      className={cn("overflow-hidden", className)}
    >
      <div ref={contentRef}>{children}</div>
    </motion.div>
  );
}
