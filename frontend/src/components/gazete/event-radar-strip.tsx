"use client";

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { CalendarDays, ChevronDown, MapPin } from "lucide-react";
import { useEffect, useState } from "react";

import { apiFetch } from "@/lib/api";
import { collapseSection, reduceVariants, useMeasuredHeight } from "@/lib/motion";
import type { EventOut } from "@/lib/types";
import { cn } from "@/lib/utils";

/** How far ahead the radar looks. Roughly two months: far enough that a
 * capacity decision can still be made, near enough that the row is not a
 * year-planner nobody scrolls. */
const HORIZON_DAYS = 60;

const IMPACT_META: Record<EventOut["impact_level"], { label: string; className: string; rank: number }> = {
  high: { label: "Yüksek etki", className: "border-critical/40 bg-critical/10 text-critical", rank: 0 },
  medium: { label: "Orta etki", className: "border-warning/40 bg-warning/10 text-warning", rank: 1 },
  low: { label: "Düşük etki", className: "border-border bg-muted text-muted-foreground", rank: 2 },
};

const MAX_EVENTS = 8;

/** The reader's own expand/collapse choice, remembered across visits.
 *
 * Same convention as the sidebar's `aerointel_sidebar_collapsed` (see
 * components/layout/app-shell.tsx): one key, a stringified boolean, restored on
 * mount. Stored EXPANDED rather than collapsed so the absent key -- a first
 * visit -- reads as false, which is the default this strip wants.
 */
export const EVENT_RADAR_KEY = "aerointel_event_radar_expanded";

function isoDay(offsetDays: number): string {
  const date = new Date();
  date.setDate(date.getDate() + offsetDays);
  return date.toISOString().slice(0, 10);
}

/** "Etkinlik Radarı" -- the curated demand events coming up.
 *
 * Reads the existing /events endpoint; nothing new server-side. Sorted by
 * impact first and date second, because the question this row answers is
 * "what is big enough to plan around", not "what is next on the calendar" --
 * the calendar itself already answers the second one and is one click away.
 *
 * `impact_level` is hand-curated (backend/app/models/event.py), never
 * inferred, which is exactly why it is safe to sort on: it is somebody's
 * judgement, recorded, rather than a model's guess restated as a number.
 *
 * COLLAPSED BY DEFAULT
 * --------------------
 * It sits third among the strips above the article list, and a horizontal row
 * of eight cards about the next two months was pushing today's news below the
 * fold on every visit -- an "önümüzdeki 60 gün" panel is reference material,
 * not the paper's lead. So the default is a one-line header stating the count,
 * and the row itself is one click away.
 *
 * Two things override the default, in this order:
 *
 *   * the reader's own stored choice, which wins for good once made, and
 *   * the Etkinlik tab, where the strip IS the subject of the page the reader
 *     just opened -- it auto-expands there on the first render after the tab
 *     is selected, and a reader who then collapses it keeps it collapsed.
 */
export function EventRadarStrip({
  onOpenCalendar,
  autoExpand = false,
}: {
  onOpenCalendar?: () => void;
  /** True on the Etkinlik tab: the strip opens itself, once, on arrival. */
  autoExpand?: boolean;
}) {
  const reduceMotion = useReducedMotion();
  const [events, setEvents] = useState<EventOut[]>([]);
  const [expanded, setExpanded] = useState(false);
  const [contentRef, contentHeight] = useMeasuredHeight<HTMLDivElement>();

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- restoring a persisted UI preference on mount, same as app-shell.tsx
    setExpanded(window.localStorage.getItem(EVENT_RADAR_KEY) === "true");
  }, []);

  useEffect(() => {
    // Only ever opens. `autoExpand` going false (leaving the Etkinlik tab)
    // must not slam the strip shut on a reader who opened it deliberately.
    if (!autoExpand) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- the tab selection is the trigger; there is nothing to derive it from during render
    setExpanded(true);
  }, [autoExpand]);

  useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams({
      date_from: isoDay(0),
      date_to: isoDay(HORIZON_DAYS),
    });
    apiFetch<EventOut[]>(`/events?${params.toString()}`, {
      cache: "default",
      signal: controller.signal,
    })
      .then((rows) =>
        setEvents(
          [...rows]
            .sort(
              (a, b) =>
                IMPACT_META[a.impact_level].rank - IMPACT_META[b.impact_level].rank ||
                a.starts.localeCompare(b.starts),
            )
            .slice(0, MAX_EVENTS),
        ),
      )
      .catch(() => {
        /* the radar is an addition to the paper, never a precondition */
      });
    return () => controller.abort();
  }, []);

  if (events.length === 0) return null;

  function toggle() {
    setExpanded((open) => {
      const next = !open;
      window.localStorage.setItem(EVENT_RADAR_KEY, String(next));
      return next;
    });
  }

  const variants = collapseSection(contentHeight);

  return (
    <section aria-label="Etkinlik radarı" className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={toggle}
          aria-expanded={expanded}
          className="flex items-center gap-2 rounded-md text-sm font-semibold uppercase tracking-wide text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
        >
          <CalendarDays className="size-4" aria-hidden />
          <h2 className="text-sm font-semibold uppercase tracking-wide">Etkinlik Radarı</h2>
          {/* The count is the whole point of a collapsed header: it says
              whether opening the row is worth it. */}
          <span className="text-[11px] font-normal normal-case tracking-normal tabular-nums text-muted-foreground">
            {events.length} etkinlik · önümüzdeki {HORIZON_DAYS} gün
          </span>
          <ChevronDown
            aria-hidden
            className={cn(
              "size-4 transition-transform motion-reduce:transition-none",
              expanded && "rotate-180",
            )}
          />
        </button>
        {onOpenCalendar && (
          <button
            type="button"
            onClick={onOpenCalendar}
            className="ml-auto rounded-md border border-border px-2 py-1 text-[11px] font-medium transition-colors hover:bg-accent"
          >
            Takvimi aç
          </button>
        )}
      </div>

      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            key="events"
            variants={reduceMotion ? reduceVariants(variants) : variants}
            initial="hidden"
            animate="show"
            exit="exit"
            className="overflow-hidden"
          >
            <div ref={contentRef} className="flex gap-2 overflow-x-auto pb-1">
              {events.map((event) => (
                <a
                  key={event.id}
                  href={event.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex w-56 shrink-0 flex-col gap-1.5 rounded-lg border border-border bg-card p-3 transition-colors hover:bg-accent/40"
                >
                  <span
                    className={cn(
                      "w-fit rounded-full border px-2 py-0.5 text-[10px] font-semibold",
                      IMPACT_META[event.impact_level].className,
                    )}
                  >
                    {IMPACT_META[event.impact_level].label}
                  </span>
                  <span className="line-clamp-2 text-xs font-medium leading-snug text-card-foreground">
                    {event.name}
                  </span>
                  {/* Pre-formatted server-side so the frontend never
                      re-implements Turkish month names. */}
                  <span className="text-[11px] tabular-nums text-muted-foreground">
                    {event.date_range_tr}
                  </span>
                  <span className="flex items-center gap-1 text-[11px] text-muted-foreground">
                    <MapPin className="size-3 shrink-0" aria-hidden />
                    <span className="truncate">
                      {event.city}
                      {event.country ? `, ${event.country}` : ""}
                    </span>
                  </span>
                </a>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  );
}
