"use client";

import { MotionConfig } from "framer-motion";

/**
 * One app-wide answer to `prefers-reduced-motion`, applied at ANIMATION time
 * rather than at render time.
 *
 * The bug this fixes was a hydration mismatch, and it was structural rather
 * than incidental. `useReducedMotion()` returns false on the server (there is
 * no media query there) and true on a client that asked for stillness, so a
 * component that chose between two variant sets with it -- `MotionList`,
 * `MotionItem`, `MotionRail`, `Collapse` -- served `opacity: 0;
 * transform: scaleX(0)` from the server and rendered `opacity: 1;
 * transform: none` on the client. React reported it as
 * "some attributes ... didn't match ... This won't be patched up", which is
 * the serious form of the warning: the DOM keeps the server's inline styles.
 *
 * `MotionConfig reducedMotion="user"` moves the decision inside Framer: every
 * component below renders the SAME markup in both places and Framer simply
 * jumps transforms to their final value instead of animating them. Nothing has
 * to remember to branch, so nothing can branch inconsistently.
 */
export function MotionPreferences({ children }: { children: React.ReactNode }) {
  return <MotionConfig reducedMotion="user">{children}</MotionConfig>;
}
