"use client";

import { useEffect, useMemo, useState } from "react";

import { SectionHeader } from "@/components/kokpit/section-header";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api";
import { layoutEvents, shiftDay } from "@/lib/event-timeline";
import {
  EVENT_TYPE_BAR,
  EVENT_TYPE_GLOW,
  EVENT_TYPE_LABELS_TR,
  EVENT_TYPE_PILL,
} from "@/lib/events";
import { categoryVar } from "@/lib/taxonomy";
import type { EventOut } from "@/lib/types";
import { cn } from "@/lib/utils";

/** How far the rail runs. Four months: long enough that a summer season is
 * visible from a spring morning, short enough that the reader is not scrolling
 * through a year of empty February. */
const HORIZON_DAYS = 120;

/** Pixels per day. The rail is a real, linear time axis -- a two-day fair is
 * half the width of a four-day one -- so this is the only number that decides
 * how wide the scroller is (120 days ≈ 1680px, about one screen and a quarter
 * at desktop width). */
const DAY_WIDTH = 14;

/** Height of one packed lane, including its gap. */
const LANE_HEIGHT = 30;

/** Below this a bar cannot hold its own name, so the name is written BESIDE
 * it. Most curated events run one to four days -- 14 to 56px -- so this is the
 * common case, not the exception. */
const MIN_NAMED_WIDTH = 110;

/** How wide a label is allowed to get before it is truncated. */
const MAX_LABEL_WIDTH = 190;

/** Gap between a bar and the label written beside it (Tailwind ml-1.5). */
const LABEL_GAP = 6;

/** Rough width of one character at the label's size (11px, medium weight).
 * A measured width would need a layout pass per event on every render to
 * answer a question whose only consumer is lane packing -- and packing only
 * needs to know "roughly this many columns", not a pixel. Erring high is the
 * safe direction: it reserves a little too much space rather than letting the
 * next bar be written over. */
const LABEL_CHAR_WIDTH = 6.2;

/** Total day-columns an event needs: its bar, plus the label written beside it
 * when the bar is too narrow to hold the name. A bar wide enough to carry its
 * own name needs nothing extra. */
function reserveColumns(name: string, span: number): number {
  if (span * DAY_WIDTH >= MIN_NAMED_WIDTH) return span;
  const label = Math.min(name.length * LABEL_CHAR_WIDTH, MAX_LABEL_WIDTH) + LABEL_GAP;
  return span + Math.ceil(label / DAY_WIDTH);
}

/** "EVENT TIMELINE" -- every curated event on one horizontal axis.
 *
 * WHY THIS REPLACED THE MONTH GRID
 * --------------------------------
 * The old calendar was a 7x6 cell grid with a month cursor: an Excel sheet.
 * It answers "what falls on the 14th", and the paper's question is "what is
 * coming" -- to answer that a reader had to page month by month and hold three
 * grids in their head, while a five-day fair straddling a month boundary was
 * drawn as two unrelated runs. One axis, scrolled, answers it in a glance and
 * draws a run as a run.
 *
 * WHAT WAS DROPPED WITH IT: THE CAMPAIGN RIBBONS
 * ----------------------------------------------
 * The grid carried a second layer -- rival sale windows, from /promotions,
 * drawn as thin ribbons above the date in each cell. That layer is NOT ported,
 * and the /promotions request goes with it. Three reasons, in order of weight:
 *
 *   1. Geometry. A ribbon worked because a grid cell had spare vertical room
 *      above its date. On a linear axis a campaign is a bar like any other,
 *      and a sale window is routinely seven months long -- so campaigns would
 *      be the widest objects on the rail, permanently, with the events they
 *      were meant to annotate reduced to specks between them.
 *   2. Colour. Ribbons wore carrier brand hex, a second colour system laid
 *      over the five type hues, on a page whose whole brief is fewer colours.
 *   3. Duplication. /kampanyalar already draws exactly this data on exactly
 *      this kind of axis, purpose-built, with the sale/travel distinction the
 *      ribbon could not show.
 *
 * The campaign layer is therefore one link away, not one toggle away. Nothing
 * about campaigns changed server-side.
 */
export function EventTimeline({ onSelect }: { onSelect?: (event: EventOut) => void }) {
  const [events, setEvents] = useState<EventOut[] | null>(null);
  const [error, setError] = useState(false);

  // Read once per mount: the window's origin has to be stable across renders,
  // and the page is not open across a midnight boundary in any meaningful
  // sense.
  const [from] = useState(() => new Date().toISOString().slice(0, 10));

  useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams({
      date_from: from,
      date_to: shiftDay(from, HORIZON_DAYS - 1),
    });
    apiFetch<EventOut[]>(`/events?${params.toString()}`, {
      cache: "default",
      signal: controller.signal,
    })
      .then(setEvents)
      .catch((err: unknown) => {
        if ((err as Error)?.name === "AbortError") return;
        setError(true);
      });
    return () => controller.abort();
  }, [from]);

  const layout = useMemo(
    () =>
      layoutEvents(events ?? [], {
        from,
        days: HORIZON_DAYS,
        reserve: (event, span) => reserveColumns(event.name, span),
      }),
    [events, from],
  );

  if (error) {
    return (
      <section className="flex flex-col gap-4">
        <SectionHeader title="EVENT TIMELINE" glowVar={categoryVar("events")} />
        <p className="text-sm text-muted-foreground">
          Etkinlik zaman çizelgesi yüklenemedi. Sunucu çalışıyor mu?
        </p>
      </section>
    );
  }

  // An empty calendar hides the whole block: the timeline is an addition to
  // the paper, and a labelled empty rail is a heading over nothing.
  if (events !== null && layout.placed.length === 0) return null;

  const width = layout.days * DAY_WIDTH;
  const railHeight = Math.max(layout.lanes, 1) * LANE_HEIGHT;

  return (
    <section aria-label="Event Timeline" className="flex flex-col gap-4">
      <SectionHeader
        title="EVENT TIMELINE"
        caption={
          events === null
            ? undefined
            : `${layout.placed.length} etkinlik · önümüzdeki ${HORIZON_DAYS} gün`
        }
        glowVar={categoryVar("events")}
      />

      {events === null ? (
        <Skeleton className="h-40 w-full rounded-xl" />
      ) : (
        <div
          // The axis scrolls; the page does not. `overscroll-x-contain` stops
          // a horizontal flick from walking the browser back a page.
          className="overflow-x-auto overscroll-x-contain pb-2"
        >
          <div style={{ width }} className="relative flex flex-col gap-2">
            {/* Month band. Each label sits over exactly the days of its own
                month inside the window, so the first and last are partial --
                a header spanning all of August while only its last week is
                visible would misstate the axis it labels. */}
            <div className="flex items-end border-b border-border pb-1">
              {layout.months.map((month) => (
                <div
                  key={month.key}
                  style={{ width: month.span * DAY_WIDTH }}
                  className="shrink-0 border-l border-border pl-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground first:border-l-0 first:pl-0"
                >
                  <span className="block truncate">{month.label}</span>
                </div>
              ))}
            </div>

            <div className="relative" style={{ height: railHeight }}>
              {/* "Bugün": the rail always starts today, so the marker is a
                  hairline at the origin rather than a computed position. */}
              <span
                aria-hidden
                className="absolute inset-y-0 left-0 w-px bg-signal"
                style={{ boxShadow: "0 0 6px var(--signal)" }}
              />
              {layout.placed.map(({ event, startIndex, span, isStart, lane }) => {
                const barWidth = span * DAY_WIDTH;
                // Start vs continuation, the same distinction the month grid
                // drew: the day an event BEGINS carries its name; a run that
                // was already under way when the window opened carries only a
                // bar, because its name was stated on a day off screen.
                const insideName = isStart && barWidth >= MIN_NAMED_WIDTH;
                return (
                  <button
                    key={event.id}
                    type="button"
                    onClick={() => onSelect?.(event)}
                    title={`${event.name} — ${event.date_range_tr}`}
                    style={{
                      left: startIndex * DAY_WIDTH,
                      width: barWidth,
                      top: lane * LANE_HEIGHT,
                      "--glow-color": EVENT_TYPE_GLOW[event.event_type],
                    } as React.CSSProperties}
                    className={cn(
                      "group absolute flex h-6 items-center rounded-md text-left transition-all duration-200",
                      "hover:z-10",
                      insideName &&
                        cn(
                          "overflow-hidden px-2 shadow-[inset_2px_0_0_0_currentColor]",
                          EVENT_TYPE_PILL[event.event_type],
                        ),
                    )}
                  >
                    {insideName ? (
                      <span className="truncate text-[11px] font-medium leading-none">
                        {event.name}
                      </span>
                    ) : (
                      <>
                        {/* A run of one to four days is 14-56px of bar: too
                            narrow for a name, so the bar is the mark and the
                            name is written beside it. The lane packing was
                            told how much room that name needs, so it cannot
                            be written over the next bar in this lane. */}
                        <span
                          aria-hidden
                          className={cn(
                            "h-1.5 w-full rounded-full",
                            EVENT_TYPE_BAR[event.event_type],
                          )}
                        />
                        {/* A continuation carries no name: it was stated on a
                            day the reader cannot see, and repeating it here
                            would claim the event starts today. */}
                        {isStart && (
                          <span
                            style={{ maxWidth: MAX_LABEL_WIDTH }}
                            className="pointer-events-none absolute left-full ml-1.5 truncate text-[11px] font-medium leading-none text-muted-foreground group-hover:text-foreground"
                          >
                            {event.name}
                          </span>
                        )}
                      </>
                    )}
                    <span className="sr-only">
                      {event.name} — {event.date_range_tr}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* The legend is permanent, so a bar's hue can be decoded without
          hovering it. Not a filter row: the rail is 120 days of a curated
          calendar, and filtering it by type is a question the detail panel
          and the radar above already serve better. */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-muted-foreground">
        {(Object.keys(EVENT_TYPE_LABELS_TR) as EventOut["event_type"][]).map((type) => (
          <span key={type} className="flex items-center gap-1">
            <span
              aria-hidden
              className={cn("size-1.5 rounded-full", EVENT_TYPE_BAR[type])}
            />
            {EVENT_TYPE_LABELS_TR[type]}
          </span>
        ))}
        <span className="flex items-center gap-1">
          <span aria-hidden className="h-3 w-px bg-signal" />
          Bugün
        </span>
      </div>
    </section>
  );
}
