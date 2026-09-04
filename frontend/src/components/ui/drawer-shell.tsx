"use client";

import { motion } from "framer-motion";
import { useEffect, useRef } from "react";

import { drawerPanel, drawerPanelLeft, overlayFade } from "@/lib/motion";
import { cn } from "@/lib/utils";

/** Everything focusable a Tab press can reach, in DOM order. Deliberately not
 * a library: the panels here contain buttons, links, a details/summary or two
 * and nothing exotic. `:not([disabled])` and the negative-tabindex exclusion
 * are what keep a disabled retry button or a scroll container out of the ring. */
const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

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
 *   * Focus lands INSIDE on open -- on `initialFocusRef` if given, otherwise
 *     on the first focusable element (in practice the close button), otherwise
 *     on the panel itself.
 *   * Tab is trapped: the last element wraps to the first and Shift+Tab back.
 *     `aria-modal="true"` is a promise to a screen reader that the rest of the
 *     page is inert, and a dialog that lets Tab escape is lying about it.
 *   * Focus RETURNS to whatever had it when the drawer opened -- the card, the
 *     map row, the menu button -- not to the top of the document.
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
  children: React.ReactNode;
}) {
  const panelRef = useRef<HTMLElement | null>(null);

  /** Whatever had focus when the drawer opened -- a card, a map popover row, a
   * feed item. Captured on open and focused again on close, so a keyboard
   * reader is returned to the row they came from instead of to the top of the
   * document. A ref rather than state: it must not cause a render. */
  const returnFocusRef = useRef<HTMLElement | null>(null);

  /** `onClose` behind a ref so the effect below can depend on NOTHING and run
   * exactly once per mount. It used to sit in the dependency array of each
   * drawer's copy, which means a caller passing an inline arrow re-ran the
   * whole effect on every render -- and the cleanup, which restores focus,
   * fired every time. That is a drawer that yanks focus back to the card
   * behind it while the reader is typing in it. */
  const closeRef = useRef(onClose);
  useEffect(() => {
    closeRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    returnFocusRef.current = document.activeElement as HTMLElement | null;

    // The first focusable inside the panel -- in every current caller that is
    // the close button, which is the one control every reader needs and which
    // makes Tab start inside the dialog rather than behind it. A panel with
    // nothing focusable in it takes focus itself.
    const panel = panelRef.current;
    (panel?.querySelector<HTMLElement>(FOCUSABLE) ?? panel)?.focus();

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        closeRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const node = panelRef.current;
      if (!node) return;
      // No visibility filter, deliberately. The panels' collapsible sections
      // UNMOUNT their contents rather than hiding them (components/ui/collapse.tsx),
      // so everything this selector finds is really reachable -- and every
      // cheap way to ask "is this laid out?" (`offsetParent`, `getClientRects`)
      // answers "no" for every element under jsdom, which would silently
      // collapse the trap to a single stop wherever this is tested.
      const focusable = Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (focusable.length === 0) {
        event.preventDefault();
        node.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;
      if (!(active instanceof Node) || !node.contains(active)) {
        // Focus got out -- a click on the backdrop, a control that removed
        // itself, a programmatic blur. Tab pulls it straight back in rather
        // than resuming the document's order behind an `aria-modal` dialog.
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
        return;
      }
      if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      } else if (event.shiftKey && (active === first || active === node)) {
        event.preventDefault();
        last.focus();
      }
    }

    document.addEventListener("keydown", onKeyDown);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
      returnFocusRef.current?.focus?.();
    };
    // Mount/unmount only. Nothing in here reads a prop directly -- `onClose`
    // is behind `closeRef` for exactly this reason -- so the empty dependency
    // list is complete rather than suppressed.
  }, []);

  return (
    <>
      <motion.div
        variants={overlayFade}
        initial="hidden"
        animate="show"
        onClick={onClose}
        className="fixed inset-0 z-50 bg-black/50 backdrop-blur-[2px]"
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
