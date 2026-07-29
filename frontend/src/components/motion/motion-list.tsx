"use client";

import { motion, useReducedMotion } from "framer-motion";
import type { ComponentPropsWithoutRef } from "react";

import {
  fadeUpItem,
  hoverLift,
  railGrow,
  reduceVariants,
  scalePopItem,
  staggerContainer,
} from "@/lib/motion";
import { cn } from "@/lib/utils";

type DivProps = Omit<
  ComponentPropsWithoutRef<typeof motion.div>,
  "variants" | "initial" | "animate"
>;

/** Which entrance a staggered child plays. `scalePop` is the "instrument
 * power-on" spring used by KPI/stat tiles; `fadeUp` is the default everywhere
 * else. Exposed as a prop rather than a second wrapper component so server
 * components can opt in without crossing the client boundary themselves. */
export type MotionItemVariant = "fadeUp" | "scalePop";

const ITEM_VARIANTS = {
  fadeUp: fadeUpItem,
  scalePop: scalePopItem,
} as const;

/** A staggered entrance container.
 *
 * Deliberately thin: server components (the dashboard, the edition page) can
 * wrap a section in this and get the app's entrance animation without being
 * converted to client components themselves -- only the wrapper crosses the
 * boundary, the children stay server-rendered.
 */
export function MotionList({ children, ...props }: DivProps) {
  const reduceMotion = useReducedMotion();
  return (
    <motion.div
      variants={reduceMotion ? reduceVariants(staggerContainer) : staggerContainer}
      initial="hidden"
      animate="show"
      {...props}
    >
      {children}
    </motion.div>
  );
}

/** One staggered child. `lift` adds the shared card hover/press interaction. */
export function MotionItem({
  children,
  lift = false,
  variant = "fadeUp",
  ...props
}: DivProps & { lift?: boolean; variant?: MotionItemVariant }) {
  const reduceMotion = useReducedMotion();
  const itemVariants = ITEM_VARIANTS[variant];
  return (
    <motion.div
      variants={reduceMotion ? reduceVariants(itemVariants) : itemVariants}
      {...(lift ? hoverLift(reduceMotion) : {})}
      {...props}
    >
      {children}
    </motion.div>
  );
}

/** An approach-light bar that draws itself in from the left.
 *
 * Sits under a section heading. Standalone by default (`initial`/`animate` of
 * its own) so a server component can drop one in; inside a `MotionList` the
 * parent's stagger drives it instead -- pass `staggered` to defer to it. */
export function MotionRail({
  className,
  staggered = false,
  style,
  ...props
}: Omit<
  ComponentPropsWithoutRef<typeof motion.span>,
  "variants" | "initial" | "animate"
> & { staggered?: boolean }) {
  const reduceMotion = useReducedMotion();
  return (
    <motion.span
      aria-hidden
      variants={reduceMotion ? reduceVariants(railGrow) : railGrow}
      {...(staggered ? {} : { initial: "hidden", animate: "show" })}
      className={cn("hairline-glow block w-full origin-left", className)}
      style={style}
      {...props}
    />
  );
}

type LiProps = Omit<
  ComponentPropsWithoutRef<typeof motion.li>,
  "variants" | "initial" | "animate"
>;

/** `MotionItem` for list semantics -- same variants, renders an `<li>`. */
export function MotionListItem({
  children,
  lift = false,
  variant = "fadeUp",
  ...props
}: LiProps & { lift?: boolean; variant?: MotionItemVariant }) {
  const reduceMotion = useReducedMotion();
  const itemVariants = ITEM_VARIANTS[variant];
  return (
    <motion.li
      variants={reduceMotion ? reduceVariants(itemVariants) : itemVariants}
      {...(lift ? hoverLift(reduceMotion) : {})}
      {...props}
    >
      {children}
    </motion.li>
  );
}
