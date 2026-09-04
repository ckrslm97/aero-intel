"use client";

import { useEffect, useRef, type RefObject } from "react";

/** Everything focusable a Tab press can reach, in DOM order. Deliberately not
 * a library: the panels this guards contain buttons, links, the odd
 * `<summary>` and nothing exotic. `:not([disabled])` and the negative-tabindex
 * exclusion are what keep a disabled retry button or a scroll container out of
 * the ring.
 *
 * `summary` is listed even though no panel currently opens a `<details>`. It
 * is focusable in every browser but matches none of the other selectors, so a
 * panel that grew one would put a Tab stop inside the ring that `first`/`last`
 * could not see -- and Tab from the last summary would walk straight out of an
 * `aria-modal` dialog. A hole that only appears once someone adds markup is
 * worse than one that is visible now. */
export const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"])';

/**
 * The four things that make a panel a dialog rather than a box on top: Escape
 * closes it, the page behind it does not scroll, Tab cannot leave it, and
 * focus goes back where it came from on close.
 *
 * A HOOK RATHER THAN A COMPONENT because the two callers cannot share a shell.
 * `ui/drawer-shell.tsx` owns a full-height slide-over; `risk/risk-map-popover.tsx`
 * is a 300px panel positioned by arithmetic from a click on a canvas, since an
 * ECharts marker has no DOM node to anchor to. The popover declared
 * `role="dialog" aria-modal="true"` and implemented only Escape -- so Tab
 * walked out into the page behind it and closing dropped focus on `<body>`,
 * leaving a keyboard reader unable to get back to the map row they opened.
 * `aria-modal` is a promise about the rest of the page, and a dialog that lets
 * Tab escape is lying about it.
 *
 * MOUNT/UNMOUNT ONLY. The effect depends on nothing: `onClose` is read through
 * a ref precisely so a caller passing an inline arrow cannot re-run it on
 * every render, which would fire the cleanup -- and the cleanup restores focus.
 * That is a dialog that yanks focus back to the card behind it while the
 * reader is typing in it.
 *
 * @param panelRef  The dialog element. Must be rendered before the effect runs.
 * @param onClose   Called on Escape. Read through a ref, so it may change.
 * @param focusPanel  Put focus on the panel itself instead of on the first
 *   focusable inside it. The drawer wants the first control (its close
 *   button); the map popover does not, because a marker can stand for eight
 *   events and pre-selecting row one would have a screen reader announce a
 *   single headline where the useful fact is that there are eight.
 */
export function useFocusTrap(
  panelRef: RefObject<HTMLElement | null>,
  onClose: () => void,
  { focusPanel = false }: { focusPanel?: boolean } = {},
): void {
  /** Whatever had focus when the dialog opened -- a card, a map row, a feed
   * item. A ref rather than state: it must not cause a render. */
  const returnFocusRef = useRef<HTMLElement | null>(null);

  const closeRef = useRef(onClose);
  useEffect(() => {
    closeRef.current = onClose;
  }, [onClose]);

  /** Read once, at mount, because that is the only moment it is used: where
   * focus LANDS is decided when the dialog opens. Never reassigned -- a
   * caller that flipped it mid-life would be describing a decision that has
   * already been made. */
  const focusPanelRef = useRef(focusPanel);

  useEffect(() => {
    returnFocusRef.current = document.activeElement as HTMLElement | null;

    const panel = panelRef.current;
    // In every drawer the first focusable is the close button, which is the
    // one control every reader needs and which makes Tab start inside the
    // dialog rather than behind it. A panel with nothing focusable in it takes
    // focus itself.
    (focusPanelRef.current
      ? panel
      : (panel?.querySelector<HTMLElement>(FOCUSABLE) ?? panel)
    )?.focus();

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
    // and `focusPanel` are both behind refs for exactly this reason -- so the
    // empty dependency list is complete rather than suppressed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}
