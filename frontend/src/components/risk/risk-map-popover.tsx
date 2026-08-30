"use client";

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { X } from "lucide-react";
import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";

import { CoverageBadge, TypePill } from "@/components/risk/risk-meta";
import { severityMeta } from "@/components/risk/severity-pill";
import { chipPop, overlayFade, reduceVariants } from "@/lib/motion";
import type { RiskItem } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Popover width, in px. Duplicated as a number because the panel has to be
 * kept inside the viewport by arithmetic, not by a class name -- same reason
 * campaign-cluster-marker.tsx carries one. */
const PANEL_WIDTH = 300;
/** Roughly what the panel needs below the click before it flips above it. */
const PANEL_ROOM = 260;
const GAP = 8;

const TIME = new Intl.DateTimeFormat("tr-TR", {
  timeZone: "UTC",
  day: "numeric",
  month: "short",
});

/** Where the popover opens, in viewport coordinates. A map marker has no DOM
 * node to measure -- it is painted into a canvas -- so unlike the campaign
 * cluster marker this anchor comes from the click event itself. */
export interface MapAnchor {
  x: number;
  below: number;
  above: number;
}

/** The events stacked under one map marker.
 *
 * A marker is a (place, type, severity) bucket, so it can stand for four
 * separate wildfires in Greece. The tooltip says how many; this says WHICH, and
 * hands each one to the drawer. A popover rather than a second drawer, for the
 * reason campaign-cluster-marker gives: the drawer is the page's detail
 * surface and opens from any row here, so stacking two of them would put a
 * full-height panel between the reader and the event they were reaching for.
 *
 * Portalled to the body because the map card clips its own overflow and the
 * ECharts canvas is its own stacking context. */
export function RiskMapPopover({
  anchor,
  country,
  city,
  items,
  onSelect,
  onClose,
}: {
  anchor: MapAnchor;
  country: string;
  city: string | null;
  items: RiskItem[];
  onSelect: (item: RiskItem) => void;
  onClose: () => void;
}) {
  const reduceMotion = useReducedMotion();
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  // Focus lands on the panel, not on the first row: a marker can stand for
  // eight events, and pre-selecting row one would have a screen reader announce
  // a single headline where the useful fact is that there are eight.
  useEffect(() => {
    panelRef.current?.focus();
  }, []);

  if (typeof document === "undefined") return null;

  const viewportWidth = typeof window === "undefined" ? PANEL_WIDTH : window.innerWidth;
  const viewportHeight = typeof window === "undefined" ? 0 : window.innerHeight;

  // The panel's own left edge, not a centre plus a CSS translate:
  // framer-motion writes `transform` inline for the pop-in, which silently
  // overwrites a Tailwind `-translate-x-1/2`. Arithmetic is the only placement
  // the animation cannot undo -- and it is needed anyway, because a marker can
  // sit against the right edge of the map.
  const left = Math.min(
    Math.max(anchor.x - PANEL_WIDTH / 2, GAP),
    Math.max(viewportWidth - PANEL_WIDTH - GAP, GAP),
  );
  const roomBelow = viewportHeight - anchor.below;
  const flip = roomBelow < PANEL_ROOM && anchor.above > roomBelow;
  const position: React.CSSProperties = flip
    ? { left, bottom: Math.max(viewportHeight - anchor.above, GAP) }
    : { left, top: Math.max(anchor.below, GAP) };

  const place = city ? `${country} · ${city}` : country;

  return createPortal(
    <AnimatePresence>
      <motion.div
        key="risk-map-overlay"
        variants={reduceMotion ? reduceVariants(overlayFade) : overlayFade}
        initial="hidden"
        animate="show"
        exit="exit"
        onClick={onClose}
        // Light enough that the map behind stays legible: this is a list about
        // the marker you just clicked, so hiding the marker would be
        // self-defeating.
        className="fixed inset-0 z-40 bg-black/20"
      />
      <motion.div
        key="risk-map-panel"
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={`${place}, ${items.length} sinyal`}
        tabIndex={-1}
        variants={reduceMotion ? reduceVariants(chipPop) : chipPop}
        initial="hidden"
        animate="show"
        style={{ ...position, width: PANEL_WIDTH } as React.CSSProperties}
        className="fixed z-40 overflow-hidden rounded-xl border border-border bg-popover text-popover-foreground shadow-elev-2 outline-none"
      >
        <header className="flex items-start gap-2 border-b border-border px-3 py-2">
          <div className="flex min-w-0 flex-col">
            <span className="truncate text-xs font-semibold">{place}</span>
            <span className="text-[11px] tabular-nums text-muted-foreground">
              {items.length} sinyal · ülke/şehir merkezi
            </span>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Listeyi kapat"
            className="ml-auto shrink-0 rounded-md p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          >
            <X className="size-3.5" />
          </button>
        </header>

        <ul className="max-h-72 overflow-y-auto py-1">
          {items.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                onClick={() => onSelect(item)}
                className="flex w-full flex-col items-start gap-1 px-3 py-2 text-left transition-colors hover:bg-accent focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring"
              >
                <span className="flex flex-wrap items-center gap-1.5">
                  <TypePill item={item} />
                  <span
                    aria-hidden
                    className={cn("size-2 rounded-full", severityMeta(item.severity).dotClassName)}
                  />
                  <span className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                    {severityMeta(item.severity).label}
                  </span>
                  <CoverageBadge item={item} />
                </span>
                <span className="text-[11px] font-medium leading-snug">{item.headline}</span>
                {item.published_at && (
                  <span className="text-[10px] tabular-nums text-muted-foreground">
                    {TIME.format(new Date(item.published_at))}
                  </span>
                )}
              </button>
            </li>
          ))}
        </ul>
      </motion.div>
    </AnimatePresence>,
    document.body,
  );
}
