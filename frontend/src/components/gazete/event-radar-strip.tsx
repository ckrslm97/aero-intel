"use client";

import { CalendarDays, ChevronDown, MapPin } from "lucide-react";
import { useEffect, useState } from "react";

import { Collapse } from "@/components/ui/collapse";
import { apiFetch } from "@/lib/api";
import { daysUntilTr } from "@/lib/event-timeline";
import { shiftDayIso, utcDayIso } from "@/lib/format";
import {
  EVENT_IMPACT_META,
  EVENT_TYPE_GLOW,
  EVENT_TYPE_LABELS_TR,
} from "@/lib/events";
import type { EventOut } from "@/lib/types";
import { cn } from "@/lib/utils";

/** How far ahead the radar looks. Roughly two months: far enough that a
 * capacity decision can still be made, near enough that the row is not a
 * year-planner nobody scrolls. */
const HORIZON_DAYS = 60;

const MAX_EVENTS = 8;

/** The reader's own expand/collapse choice, remembered across visits.
 *
 * Same convention as the sidebar's `aerointel_sidebar_collapsed` (see
 * components/layout/app-shell.tsx): one key, a stringified boolean, restored on
 * mount. Stored EXPANDED rather than collapsed so the absent key -- a first
 * visit -- reads as false, which is the default this strip wants.
 */
export const EVENT_RADAR_KEY = "aerointel_event_radar_expanded";

/** The window's edges, as day keys, in the zone the ANSWER is signed in.
 *
 * This used to step the calendar in the READER's zone (`setDate` on a local
 * Date) and then read the result off in UTC (`toISOString`) -- two clocks in
 * three lines. The local step is worth exactly 24 hours except across a DST
 * transition, where it is 23 or 25 and drags the UTC day-key it is read in
 * onto the wrong day: a 60-day horizon that lands one day short or one day
 * long, twice a year, for no stated reason.
 *
 * UTC end to end, and UTC specifically, because the number rendered beside
 * every event on this strip is the backend's `days_until`, signed against a UTC
 * "today" (`_today` in backend/app/api/v1/events.py). A window cut on one
 * calendar and labelled from another can put "bugün" on an event the window
 * itself excluded.
 */
function isoDay(offsetDays: number): string {
  return shiftDayIso(utcDayIso(), offsetDays);
}

/** "Event Radar" -- the curated demand events coming up.
 *
 * Reads the existing /events endpoint; nothing new server-side. Sorted by
 * impact first and date second, because the question this row answers is
 * "what is big enough to plan around", not "what is next on the calendar" --
 * the timeline underneath answers the second one.
 *
 * `impact_level` is hand-curated (backend/app/models/event.py), never
 * inferred, which is exactly why it is safe to sort on: it is somebody's
 * judgement, recorded, rather than a model's guess restated as a number.
 *
 * COLLAPSED BY DEFAULT
 * --------------------
 * A row of eight cards about the next two months pushed today's news below the
 * fold on every visit -- an "önümüzdeki 60 gün" panel is reference material,
 * not the paper's lead. So the default is a one-line header stating the count,
 * and the row itself is one click away.
 *
 * Two things override the default, in this order:
 *
 *   * the reader's own stored choice, which wins for good once made, and
 *   * the Etkinlik filter, where the radar IS the subject of the view the
 *     reader just selected -- it auto-expands there on the first render after
 *     the selection, and a reader who then collapses it keeps it collapsed.
 *
 * THE CARD is the one thing this round changed. It used to be an outbound link
 * carrying an impact pill, a name, a date and a city. It is now a button that
 * opens the detail panel -- an organiser's page is the LAST thing a revenue
 * desk needs and it is still one click further in -- and it carries the two
 * fields the taxonomy round added: `relevant_airports`, which is what turns an
 * event into a station a desk actually sells, and `importance_score`, which is
 * null far more often than not and therefore renders as nothing at all rather
 * than as a zero.
 */
export function EventRadarStrip({
  onSelect,
  autoExpand = false,
}: {
  /** Opens the shared detail panel, which the page owns -- one drawer for the
   * radar and the timeline, rather than two that could disagree. */
  onSelect?: (event: EventOut) => void;
  /** True on the Etkinlik view: the strip opens itself, once, on arrival. */
  autoExpand?: boolean;
}) {
  const [events, setEvents] = useState<EventOut[]>([]);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- restoring a persisted UI preference on mount, same as app-shell.tsx
    setExpanded(window.localStorage.getItem(EVENT_RADAR_KEY) === "true");
  }, []);

  useEffect(() => {
    // Only ever opens. `autoExpand` going false (leaving the Etkinlik view)
    // must not slam the strip shut on a reader who opened it deliberately.
    if (!autoExpand) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- the selection is the trigger; there is nothing to derive it from during render
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
                EVENT_IMPACT_META[a.impact_level].rank -
                  EVENT_IMPACT_META[b.impact_level].rank ||
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

  return (
    <section aria-label="Event Radar" className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={toggle}
          aria-expanded={expanded}
          className="flex items-center gap-2 rounded-md text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
        >
          <CalendarDays className="size-4" aria-hidden />
          {/* Pre-uppercased: lang="tr" + text-transform:uppercase maps "i" to
              "İ", which turned this into "EVENT RADAR" only by luck and the
              timeline's title into "EVENT TİMELİNE". */}
          <h2 className="text-xs font-semibold uppercase tracking-[0.14em]">EVENT RADAR</h2>
          {/* The count is the whole point of a collapsed header: it says
              whether opening the row is worth it. */}
          <span className="text-[11px] font-normal normal-case tracking-normal tabular-nums">
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
      </div>

      <Collapse open={expanded}>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {events.map((event) => (
            <EventRadarCard key={event.id} event={event} onSelect={onSelect} />
          ))}
        </div>
      </Collapse>
    </section>
  );
}

/** ETKİNLİK ADI / tarih / şehir, ülke / etki seviyesi / havalimanı kodları --
 * the owner's card, top to bottom, and geometrically unlike a news tile: the
 * name is set in the type's own hue against a hairline of the same, and the
 * airport codes are monospaced, because a station code is an identifier and
 * setting one in the body face makes it read as a word. */
function EventRadarCard({
  event,
  onSelect,
}: {
  event: EventOut;
  onSelect?: (event: EventOut) => void;
}) {
  const impact = EVENT_IMPACT_META[event.impact_level];
  const place = [event.city, event.country].filter(Boolean).join(", ");

  return (
    <button
      type="button"
      onClick={() => onSelect?.(event)}
      style={{ "--glow-color": EVENT_TYPE_GLOW[event.event_type] } as React.CSSProperties}
      className={cn(
        "group flex h-full flex-col gap-2 rounded-xl bg-card p-4 text-left transition-all duration-200",
        "ring-1 ring-foreground/10 hover:-translate-y-0.5 hover:ring-(--glow-color)",
        "motion-reduce:transform-none motion-reduce:transition-none",
      )}
    >
      <div className="flex items-baseline justify-between gap-2 text-[10px] uppercase tracking-[0.1em]">
        <span className="font-semibold text-(--glow-color)">
          {EVENT_TYPE_LABELS_TR[event.event_type]}
        </span>
        <span className="normal-case tracking-normal tabular-nums text-muted-foreground">
          {daysUntilTr(event.days_until)}
        </span>
      </div>

      <span className="line-clamp-2 text-[15px] font-semibold leading-snug tracking-tight text-card-foreground group-hover:text-primary">
        {event.name}
      </span>

      {/* Pre-formatted server-side so the frontend never re-implements Turkish
          month names. */}
      <span className="text-xs tabular-nums text-muted-foreground">{event.date_range_tr}</span>

      {place && (
        <span className="flex items-center gap-1 text-xs text-muted-foreground">
          <MapPin className="size-3 shrink-0" aria-hidden />
          <span className="truncate">{place}</span>
        </span>
      )}

      <div className="mt-auto flex flex-wrap items-center gap-1.5 pt-1.5">
        <span
          className={cn(
            "rounded-full border px-2 py-0.5 text-[10px] font-semibold",
            impact.className,
          )}
        >
          {impact.label}
        </span>
        {/* Empty for entries that are not cities ("Çin geneli", "Küresel") and
            for a city nobody has curated yet -- so no chips at all rather than
            an empty rail, which would read as a loading state that never
            finished. */}
        {event.relevant_airports.slice(0, 3).map((code) => (
          <span
            key={code}
            className="rounded-full bg-muted px-1.5 py-0.5 font-mono text-[10px] font-semibold text-muted-foreground"
          >
            {code}
          </span>
        ))}
        {event.relevant_airports.length > 3 && (
          <span className="text-[10px] tabular-nums text-muted-foreground">
            +{event.relevant_airports.length - 3}
          </span>
        )}
        {/* Null means "the organiser publishes no headcount", which the
            backend refuses to score rather than scoring as zero -- so the
            chip is absent, not "0.00". */}
        {event.importance_score !== null && (
          <span
            title="Etkinlik önem skoru (0-1): etki seviyesi, katılımcı sayısı ve süre"
            className="ml-auto text-[10px] font-semibold tabular-nums text-muted-foreground"
          >
            Önem {event.importance_score.toFixed(2)}
          </span>
        )}
      </div>
    </button>
  );
}
