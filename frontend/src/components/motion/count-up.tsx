"use client";

import { animate, useReducedMotion } from "framer-motion";
import { useEffect, useRef } from "react";

export interface CountUpProps {
  value: number;
  /** How the running number is rendered. Defaults to a rounded integer.
   * Pass `formatCompactNumber` (lib/format) for KPI-style values. */
  format?: (value: number) => string;
  /** Seconds. */
  duration?: number;
  className?: string;
}

/** A number that counts up to `value` once, then holds still.
 *
 * Written directly into the span's `textContent` by framer's imperative
 * `animate()` rather than through state, so a 900ms count does not push ~55
 * re-renders through React for every KPI on the page.
 *
 * The server/first render prints the final formatted value, so the number is
 * correct before hydration and correct forever after if JS never runs. Under
 * `prefers-reduced-motion` it simply stays at that value.
 *
 * A later `value` change animates from the previous value, not from zero --
 * a KPI refresh should read as the needle moving, not as the instrument
 * rebooting.
 */
export function CountUp({
  value,
  format = (v: number) => String(Math.round(v)),
  duration = 0.9,
  className,
}: CountUpProps) {
  const reduceMotion = useReducedMotion();
  const ref = useRef<HTMLSpanElement>(null);
  // null until the first animation has run -- that first pass starts from 0
  // (the instrument powering on), every later one from where it left off.
  const previous = useRef<number | null>(null);
  // Latest-ref so an inline `format` arrow from the parent cannot restart an
  // in-flight animation on an unrelated re-render.
  const formatRef = useRef(format);

  useEffect(() => {
    formatRef.current = format;
  });

  useEffect(() => {
    const node = ref.current;
    if (!node) return;

    const from = previous.current ?? 0;
    previous.current = value;

    if (reduceMotion || from === value) {
      node.textContent = formatRef.current(value);
      return;
    }

    const controls = animate(from, value, {
      duration,
      ease: [0.22, 1, 0.36, 1],
      onUpdate: (latest) => {
        node.textContent = formatRef.current(latest);
      },
      onComplete: () => {
        node.textContent = formatRef.current(value);
      },
    });

    return () => controls.stop();
  }, [value, duration, reduceMotion]);

  return (
    <span ref={ref} className={className}>
      {format(value)}
    </span>
  );
}
