"use client";

import { motion, useReducedMotion } from "framer-motion";
import type { ComponentPropsWithoutRef } from "react";

import { fadeUpItem, hoverLift, reduceVariants, staggerContainer } from "@/lib/motion";

type DivProps = Omit<
  ComponentPropsWithoutRef<typeof motion.div>,
  "variants" | "initial" | "animate"
>;

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
  ...props
}: DivProps & { lift?: boolean }) {
  const reduceMotion = useReducedMotion();
  return (
    <motion.div
      variants={reduceMotion ? reduceVariants(fadeUpItem) : fadeUpItem}
      {...(lift ? hoverLift(reduceMotion) : {})}
      {...props}
    >
      {children}
    </motion.div>
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
  ...props
}: LiProps & { lift?: boolean }) {
  const reduceMotion = useReducedMotion();
  return (
    <motion.li
      variants={reduceMotion ? reduceVariants(fadeUpItem) : fadeUpItem}
      {...(lift ? hoverLift(reduceMotion) : {})}
      {...props}
    >
      {children}
    </motion.li>
  );
}
