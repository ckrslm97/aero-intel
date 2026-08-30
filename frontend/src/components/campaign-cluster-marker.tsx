"use client";

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { AirlineLogo } from "@/components/airline-logo";
import { campaignAmountLabel } from "@/lib/campaigns";
import { chipPop, overlayFade, reduceVariants } from "@/lib/motion";
import type { PromotionOut } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Day only, and in UTC. The cluster is a whole day of announcements, so an
 * hour on the label would be one arbitrary row's clock standing in for 23. */
const CLUSTER_DAY_FORMAT = new Intl.DateTimeFormat("tr-TR", {
  day: "numeric",
  month: "long",
  timeZone: "UTC",
});

/** Popover width, in px. Duplicated as a number because the panel has to be
 * kept inside the viewport by arithmetic, not by a class name. */
const PANEL_WIDTH = 288;
/** Roughly what the panel needs below the marker before it flips above it. */
const PANEL_ROOM = 260;
const GAP = 8;

function dayLabel(day: string): string {
  const at = new Date(`${day}T00:00:00Z`);
  return Number.isNaN(at.getTime()) ? day : CLUSTER_DAY_FORMAT.format(at);
}

/** The "Yeni" flag, always beside its mark and never on top of it.
 *
 * It used to be `absolute -top-2 right-0` inside a button that also carried
 * Tailwind's `truncate` -- so the button clipped its own badge back inside
 * itself, and what should have sat above the bar landed on the bar's title
 * instead. That is the AJet overlap. Beside the mark it can cover nothing: it
 * is centred on the same 24px band every bar and diamond occupies, and it sits
 * on the far side of the mark's own text.
 *
 * `side` exists because "after" runs off the right edge of the grid for a bar
 * that reaches the last column, and the timeline card clips it. */
export function NewCampaignBadge({ side = "after" }: { side?: "after" | "before" }) {
  return (
    <span
      className={cn(
        "pointer-events-none absolute top-1/2 z-20 -translate-y-1/2 whitespace-nowrap rounded-full bg-signal px-1.5 py-px text-[9px] font-bold uppercase leading-tight text-white",
        side === "after" ? "left-full ml-1" : "right-full mr-1",
      )}
    >
      Yeni
    </span>
  );
}

/** Where the popover opens, measured from the marker at click time. */
interface Anchor {
  /** Viewport x of the marker's centre. */
  x: number;
  /** Viewport y just below the marker. */
  below: number;
  /** Viewport y just above the marker. */
  above: number;
}

/** N dateless campaigns from one carrier on one day, as a single mark.
 *
 * See `groupDatelessCampaigns` for why: a dateless campaign has no window to
 * draw, so it is marked at the day we saw it, and CSS grid pushes same-column
 * items onto new rows. Twenty-three of them turned the Singapore Airlines lane
 * into a viewport-tall column of identical diamonds. One diamond with a count
 * chip says the same thing in one row.
 *
 * The list behind it is a popover rather than a second drawer: the drawer is
 * this page's detail surface and it opens from any row here, so stacking two
 * of them would put a full-height panel between the reader and the one campaign
 * they were reaching for. It is portalled to the body because the timeline card
 * is `overflow-hidden` and the lane grid is its own stacking context -- an
 * absolutely positioned panel would be clipped by the first and painted under
 * the "Bugün" rule by the second. */
export function CampaignClusterMarker({
  items,
  day,
  airlineCode,
  airlineName,
  color,
  gridColumn,
  badgeSide = "after",
  isNew,
  onSelect,
}: {
  items: readonly PromotionOut[];
  /** "YYYY-MM-DD", the detected day the cluster shares. */
  day: string;
  airlineCode: string;
  airlineName: string;
  /** The carrier's own brand hex. Never a semantic hue -- see campaigns-client. */
  color: string;
  /** CSS `grid-column`, e.g. "12 / 13". */
  gridColumn: string;
  badgeSide?: "after" | "before";
  isNew: (promo: PromotionOut) => boolean;
  onSelect: (promo: PromotionOut) => void;
}) {
  const [anchor, setAnchor] = useState<Anchor | null>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  const fresh = items.some(isNew);
  const label = dayLabel(day);

  const close = useCallback(() => {
    setAnchor(null);
    buttonRef.current?.focus();
  }, []);

  const open = () => {
    const rect = buttonRef.current?.getBoundingClientRect();
    setAnchor(
      rect
        ? { x: rect.left + rect.width / 2, below: rect.bottom + GAP, above: rect.top - GAP }
        : { x: 0, below: 0, above: 0 },
    );
  };

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        aria-haspopup="dialog"
        aria-expanded={anchor !== null}
        title={`${airlineName}: ${items.length} kampanya, ${label} tarihinde tespit edildi`}
        aria-label={`${airlineName}, ${items.length} kampanya, satış tarihi açıklanmadı, ${label} tarihinde tespit edildi, listeyi aç`}
        onClick={() => (anchor ? close() : open())}
        style={{ gridColumn, "--glow-color": color } as React.CSSProperties}
        className="relative flex h-6 items-center justify-center self-center transition-transform duration-200 hover:-translate-y-0.5 motion-reduce:transform-none motion-reduce:transition-none"
      >
        {/* A diamond so it is never read as a one-day sale, plus the count --
            the chip is the whole point: it says the mark stands for more than
            one campaign without drawing more than one mark. */}
        <span className="flex items-center gap-1 rounded-full border border-border bg-card px-1.5 py-0.5 shadow-elev-1">
          <span
            className={cn(
              "size-2.5 shrink-0 rotate-45 rounded-[2px]",
              fresh && "glow animate-pulse-once",
            )}
            style={{ backgroundColor: color }}
          />
          <span className="text-[10px] font-bold leading-none tabular-nums">
            {items.length}
          </span>
        </span>
        {fresh && <NewCampaignBadge side={badgeSide} />}
      </button>

      {anchor !== null && typeof document !== "undefined" &&
        createPortal(
          <ClusterPopover
            anchor={anchor}
            items={items}
            dayLabel={label}
            airlineCode={airlineCode}
            airlineName={airlineName}
            color={color}
            isNew={isNew}
            onSelect={(promo) => {
              setAnchor(null);
              onSelect(promo);
            }}
            onClose={close}
          />,
          document.body,
        )}
    </>
  );
}

function ClusterPopover({
  anchor,
  items,
  dayLabel: label,
  airlineCode,
  airlineName,
  color,
  isNew,
  onSelect,
  onClose,
}: {
  anchor: Anchor;
  items: readonly PromotionOut[];
  dayLabel: string;
  airlineCode: string;
  airlineName: string;
  color: string;
  isNew: (promo: PromotionOut) => boolean;
  onSelect: (promo: PromotionOut) => void;
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

  // Focus lands on the panel, not on the first campaign: the list can be 23
  // long, and pre-selecting row one would have a screen reader announce a
  // single title where the useful fact is that there are 23 of them.
  useEffect(() => {
    panelRef.current?.focus();
  }, []);

  const viewportWidth = typeof window === "undefined" ? PANEL_WIDTH : window.innerWidth;
  const viewportHeight = typeof window === "undefined" ? 0 : window.innerHeight;

  // The panel's own left edge, not a centre plus a CSS translate: framer-motion
  // writes `transform` inline for the pop-in spring, which silently overwrites
  // a Tailwind `-translate-x-1/2` and leaves the panel half a width off its
  // mark. Arithmetic here is the only placement the animation cannot undo --
  // and it has to be arithmetic anyway, because the marker can sit in the last
  // of 56 day columns and a panel centred there would hang off the screen.
  const left = Math.min(
    Math.max(anchor.x - PANEL_WIDTH / 2, GAP),
    Math.max(viewportWidth - PANEL_WIDTH - GAP, GAP),
  );
  const roomBelow = viewportHeight - anchor.below;
  const flip = roomBelow < PANEL_ROOM && anchor.above > roomBelow;
  const position: React.CSSProperties = flip
    ? { left, bottom: Math.max(viewportHeight - anchor.above, GAP) }
    : { left, top: Math.max(anchor.below, GAP) };

  return (
    <AnimatePresence>
      <motion.div
        key="cluster-overlay"
        variants={reduceMotion ? reduceVariants(overlayFade) : overlayFade}
        initial="hidden"
        animate="show"
        exit="exit"
        onClick={onClose}
        // Dark enough to catch a click, light enough that the lane behind it is
        // still legible -- this is a list about the mark you just clicked, so
        // hiding the mark would be self-defeating. The drawer's 50% backdrop is
        // for a panel that replaces the page; this one only borrows it.
        className="fixed inset-0 z-40 bg-black/20"
      />
      <motion.div
        key="cluster-panel"
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={`${airlineName}, ${items.length} tarihsiz kampanya`}
        tabIndex={-1}
        variants={reduceMotion ? reduceVariants(chipPop) : chipPop}
        initial="hidden"
        animate="show"
        style={{ ...position, width: PANEL_WIDTH, "--glow-color": color } as React.CSSProperties}
        className="fixed z-40 overflow-hidden rounded-xl border border-border bg-popover text-popover-foreground shadow-elev-2 outline-none"
      >
        <header className="flex items-start gap-2 border-b border-border px-3 py-2">
          <AirlineLogo code={airlineCode} name={airlineName} className="mt-0.5 size-4 shrink-0" />
          <div className="flex min-w-0 flex-col">
            <span className="truncate text-xs font-semibold">{airlineName}</span>
            <span className="text-[11px] text-muted-foreground tabular-nums">
              {items.length} kampanya · satış tarihi açıklanmadı · {label}
            </span>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Listeyi kapat"
            className="ml-auto shrink-0 rounded-md p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            <X className="size-3.5" />
          </button>
        </header>

        <ul className="max-h-72 overflow-y-auto py-1">
          {items.map((promo) => {
            const amount = campaignAmountLabel(promo);
            return (
              <li key={promo.id}>
                <button
                  type="button"
                  onClick={() => onSelect(promo)}
                  className="flex w-full items-start gap-2 px-3 py-1.5 text-left transition-colors hover:bg-accent"
                >
                  <span className="min-w-0 flex-1 text-[11px] font-medium leading-snug">
                    {promo.title_tr}
                  </span>
                  {isNew(promo) && (
                    <span className="shrink-0 rounded-full bg-signal px-1.5 py-px text-[9px] font-bold uppercase leading-tight text-white">
                      Yeni
                    </span>
                  )}
                  {amount !== null && (
                    <span className="shrink-0 text-[11px] font-bold tabular-nums">
                      {amount}
                    </span>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      </motion.div>
    </AnimatePresence>
  );
}
