"use client";

import { motion } from "framer-motion";
import { useRef } from "react";

import { useFocusTrap } from "@/lib/focus-trap";
import { drawerPanel, drawerPanelLeft, overlayFade } from "@/lib/motion";
import { cn } from "@/lib/utils";

/**
 * THE slide-over shell: backdrop, panel, and the four things that make a panel
 * a dialog rather than a box that happens to be on top.
 *
 * WHAT IT REPLACES. Four hand-written copies of the same sixty lines -- the
 * article drawer, the campaign drawer, the risk drawer, the event drawer --
 * plus the mobile sidebar, which was the only true modal of the five and had
 * none of it. Between them they implemented THREE different focus behaviours:
 * two moved focus to their close button, one declared `aria-modal` and never
 * touched focus at all (so Tab walked straight out of an "aria-modal" dialog
 * into the page behind it), and the sidebar was not a dialog to a screen
 * reader in the first place. Only one of the five returned focus on close.
 *
 * WHAT IT GUARANTEES, for every drawer in the app:
 *
 *   * Escape closes it.
 *   * The page behind it does not scroll.
 *   * Focus lands INSIDE on open -- on the first focusable element (in
 *     practice the close button), or on the panel itself when it holds none.
 *   * Tab is trapped: the last element wraps to the first and Shift+Tab back.
 *     `aria-modal="true"` is a promise to a screen reader that the rest of the
 *     page is inert, and a dialog that lets Tab escape is lying about it.
 *   * Focus RETURNS to whatever had it when the drawer opened -- the card, the
 *     map row, the menu button -- not to the top of the document.
 *
 * Those four live in `lib/focus-trap.ts` rather than here, because the risk
 * map's popover is a dialog that CANNOT use this shell -- it is positioned by
 * arithmetic from a click on a canvas -- and it made the `aria-modal` promise
 * while implementing only Escape.
 *
 * NO `AnimatePresence`, and this is the load-bearing decision rather than a
 * stylistic one. Measured three separate times in this stack (framer-motion 12
 * + React 19): an exit animation RUNS -- the panel really does end at
 * translateX(100%) -- and then the exit-complete callback never fires, so the
 * subtree is never unmounted. The panel is off-screen and invisible while its
 * `fixed inset-0` backdrop stays over the page, and every click after the
 * first close lands on an invisible black overlay instead of on the app. A
 * modal that cannot be dismissed is a far worse failure than one that closes
 * without a 200ms slide, so the ENTRANCE is kept and the exit is dropped. The
 * caller simply renders nothing when it is closed.
 *
 * Reduced motion is honoured once, app-wide, by `<MotionConfig
 * reducedMotion="user">` (components/motion/motion-preferences.tsx) -- never
 * by branching on `useReducedMotion()` to pick a variant set, which disagrees
 * with itself across the server/client boundary.
 */
export function DrawerShell({
  onClose,
  label,
  side = "right",
  glowColor,
  className,
  overlayClassName,
  children,
}: {
  onClose: () => void;
  /** The dialog's accessible name. Required: a `role="dialog"` with no name is
   * announced as "dialog" and nothing else. */
  label: string;
  /** Which edge the panel enters from. `left` is the mobile navigation. */
  side?: "left" | "right";
  /** The seam light's colour, as a CSS value. Omitted means no seam light. */
  glowColor?: string;
  /** Panel classes -- width and anything page-specific. The positioning,
   * layout and chrome are fixed here so five drawers cannot drift apart. */
  className?: string;
  /** BACKDROP classes. Separate from `className` and not optional in spirit:
   * the mobile sidebar is `md:hidden`, and when only the panel carried that
   * class a phone rotated to landscape hid the panel -- close button included
   * -- while leaving its full-screen black-and-blur layer, plus the body
   * scroll lock, over the whole app. Any breakpoint or visibility rule that
   * applies to the panel has to be handed to the backdrop too. */
  overlayClassName?: string;
  children: React.ReactNode;
}) {
  const panelRef = useRef<HTMLElement | null>(null);

  useFocusTrap(panelRef, onClose);

  return (
    <>
      <motion.div
        variants={overlayFade}
        initial="hidden"
        animate="show"
        onClick={onClose}
        className={cn(
          "fixed inset-0 z-50 bg-black/50 backdrop-blur-[2px]",
          overlayClassName,
        )}
      />
      <motion.aside
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={label}
        // The panel takes focus itself when it holds nothing focusable, and is
        // the Shift+Tab wrap target. Not in the tab ORDER -- `-1` -- so it does
        // not add a stop of its own.
        tabIndex={-1}
        variants={side === "left" ? drawerPanelLeft : drawerPanel}
        initial="hidden"
        animate="show"
        style={glowColor ? ({ "--glow-color": glowColor } as React.CSSProperties) : undefined}
        className={cn(
          "fixed inset-y-0 z-50 flex w-full flex-col bg-card shadow-2xl focus:outline-none",
          side === "left" ? "left-0 border-r border-border" : "right-0 border-l border-border",
          className,
        )}
      >
        {glowColor && (
          <span
            aria-hidden
            className={cn(
              "pointer-events-none absolute inset-y-0 w-0.5 bg-gradient-to-b from-[var(--glow-color)] via-[var(--glow-color)]/40 to-transparent",
              side === "left" ? "right-0" : "left-0",
            )}
          />
        )}
        {children}
      </motion.aside>
    </>
  );
}
