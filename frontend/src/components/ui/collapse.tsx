"use client";

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";

import { collapseSection, reduceVariants, useMeasuredHeight } from "@/lib/motion";
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
 * a third. Behaviour is unchanged -- `reduceMotion` is now read here instead of
 * being threaded in as a prop, which is the only difference at the call sites.
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
  const reduceMotion = useReducedMotion();
  const [contentRef, measuredHeight] = useMeasuredHeight<HTMLDivElement>();
  const variants = collapseSection(measuredHeight);

  return (
    <AnimatePresence initial={false}>
      {open && (
        <motion.div
          variants={reduceMotion ? reduceVariants(variants) : variants}
          initial="hidden"
          animate="show"
          exit="exit"
          className={cn("overflow-hidden", className)}
        >
          <div ref={contentRef}>{children}</div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
