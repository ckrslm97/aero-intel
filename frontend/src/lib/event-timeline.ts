/** Laying a calendar of events out along ONE horizontal axis.
 *
 * This replaces the month grid the Etkinlik Takvimi used to draw. A grid is a
 * spreadsheet: it answers "what falls on the 14th", and to answer "what is
 * coming" a reader had to page through it a month at a time and hold three
 * months in their head. The paper's question is the second one, so the axis is
 * time running left to right and the reader scrolls it instead of paging.
 *
 * Everything here is pure. The rendering component (components/gazete/
 * event-timeline.tsx) does the DOM; this file does the arithmetic, so the two
 * things that can actually be wrong -- how a multi-day event is walked out, and
 * how overlapping events are stacked -- are testable without a browser.
 *
 * DATES ARE ANCHORED AT MIDDAY UTC, the same convention the month grid used:
 * `new Date("2026-08-01")` is midnight UTC, which is the previous day for
 * every reader west of Greenwich, and an event would silently start a day
 * early for them.
 */
import type { EventOut } from "@/lib/types";

/** Safety rail on the day-by-day walk: a malformed row (ends before starts, or
 * an ends decades out) must not spin the loop or produce a bar the width of
 * the page. Longer than any real entry -- carried over from the grid, where it
 * existed for the same reason. */
export const MAX_EVENT_DAYS = 62;

const DAY_MS = 86_400_000;

/** One event, placed. `startIndex` is days from the window's first day, `span`
 * is how many days it occupies INSIDE the window, `lane` is which row of the
 * rail it was packed into. */
export interface PlacedEvent {
  event: EventOut;
  startIndex: number;
  span: number;
  /** False when the event was already running when the window opened -- the
   * rail then draws a continuation bar with no name plate, because the name
   * was stated on a day the reader cannot see. Same start/continuation
   * distinction the month grid drew, rotated ninety degrees. */
  isStart: boolean;
  lane: number;
}

export interface TimelineMonth {
  /** "2026-08" -- stable key, and what `monthLabelTr` formats. */
  key: string;
  label: string;
  /** Days from the window's first day to this month's first visible day. */
  startIndex: number;
  /** How many of this month's days are inside the window. */
  span: number;
}

export interface TimelineLayout {
  /** The window's first day, "YYYY-MM-DD". */
  from: string;
  days: number;
  months: TimelineMonth[];
  placed: PlacedEvent[];
  /** How many lanes the packing needed. 0 when nothing was placed. */
  lanes: number;
}

function atNoonUtc(isoDay: string): number {
  return new Date(`${isoDay}T12:00:00Z`).getTime();
}

/** Days between two "YYYY-MM-DD" strings, positive when `to` is later. */
export function dayDelta(from: string, to: string): number {
  return Math.round((atNoonUtc(to) - atNoonUtc(from)) / DAY_MS);
}

/** "YYYY-MM-DD" for `from` shifted by `offset` days. */
export function shiftDay(from: string, offset: number): string {
  return new Date(atNoonUtc(from) + offset * DAY_MS).toISOString().slice(0, 10);
}

/** "2026-08" -> "Ağustos 2026". Midday UTC so no reader's timezone can shift
 * it onto the previous month. */
export function monthLabelTr(monthKey: string): string {
  return new Date(`${monthKey}-01T12:00:00Z`).toLocaleDateString("tr-TR", {
    month: "long",
    year: "numeric",
  });
}

/** "3 gün sonra" / "bugün" / "12 gün önce başladı".
 *
 * Reads `days_until` rather than recomputing it: the backend signs it against
 * a UTC "today" (backend/app/api/v1/events.py `_today`), and a browser
 * recomputing it in local time would disagree with the same number rendered in
 * the detail panel next to it.
 */
export function daysUntilTr(daysUntil: number): string {
  if (daysUntil === 0) return "bugün";
  if (daysUntil === 1) return "yarın";
  if (daysUntil > 0) return `${daysUntil} gün sonra`;
  return `${Math.abs(daysUntil)} gün önce başladı`;
}

/** Greedy lane packing: an event takes the first lane whose last placed bar
 * ends before it starts.
 *
 * Greedy rather than optimal on purpose. The optimal packing minimises lanes
 * but reorders events between them as the set changes, so a reader who filters
 * the rail watches every bar jump rows. First-fit keeps an event's lane stable
 * as long as what precedes it is stable, which is what makes the rail readable
 * while a filter is being adjusted.
 */
function packLanes(items: { startIndex: number; slot: number }[]): number[] {
  const laneEnds: number[] = [];
  return items.map((item) => {
    const end = item.startIndex + item.slot;
    // One column of breathing room, so two bars that merely touch do not read
    // as one continuous bar.
    const lane = laneEnds.findIndex((laneEnd) => laneEnd < item.startIndex);
    if (lane === -1) {
      laneEnds.push(end);
      return laneEnds.length - 1;
    }
    laneEnds[lane] = end;
    return lane;
  });
}

/** Place every event that touches [from, from + days) onto the rail.
 *
 * Events are walked day by day, exactly as the month grid walked them into
 * cells -- a five-day fair occupies five columns, not one -- but the walk is
 * only there to CLIP the run to the window and to reject a malformed row; the
 * output is one bar per event rather than one entry per day, because a
 * horizontal axis can draw a run as a run.
 *
 * Sorted by start day, then by the longer run first, then by name: the sort
 * has to be total, or two events starting the same day would swap lanes
 * between renders for no reason the reader can see.
 *
 * `reserve` is how the rail keeps NAMES legible. Most curated events run one
 * to four days, which at any sane column width is a bar far too narrow to
 * hold "Aviation Africa Summit 2026" -- so the component writes the name
 * beside the bar instead, and tells the packing (bar AND label, in columns)
 * how much room the pair really needs. Without it the label would be drawn
 * over the next bar in the same lane. Pixels stay in the component; this
 * module only ever counts days.
 */
export function layoutEvents(
  events: readonly EventOut[],
  {
    from,
    days,
    reserve,
  }: {
    from: string;
    days: number;
    /** Total columns the event needs, its own `span` included. */
    reserve?: (event: EventOut, span: number) => number;
  },
): TimelineLayout {
  const windowEnd = days - 1;
  const clipped: Omit<PlacedEvent, "lane">[] = [];

  for (const event of events) {
    const startOffset = dayDelta(from, event.starts);
    const endOffset = dayDelta(from, event.ends);
    if (!Number.isFinite(startOffset) || !Number.isFinite(endOffset)) continue;
    // A row whose end precedes its start is corrupt, not a zero-length event.
    if (endOffset < startOffset) continue;
    // Entirely outside the window in either direction.
    if (endOffset < 0 || startOffset > windowEnd) continue;

    const visibleStart = Math.max(startOffset, 0);
    const visibleEnd = Math.min(endOffset, windowEnd, startOffset + MAX_EVENT_DAYS - 1);
    clipped.push({
      event,
      startIndex: visibleStart,
      span: visibleEnd - visibleStart + 1,
      // Only the day the event really begins carries its name plate.
      isStart: startOffset >= 0,
    });
  }

  clipped.sort(
    (a, b) =>
      a.startIndex - b.startIndex ||
      b.span - a.span ||
      a.event.name.localeCompare(b.event.name, "tr"),
  );

  const lanes = packLanes(
    clipped.map((item) => ({
      startIndex: item.startIndex,
      slot: Math.max(item.span, reserve?.(item.event, item.span) ?? 0),
    })),
  );
  const placed = clipped.map((item, index) => ({ ...item, lane: lanes[index] }));

  return {
    from,
    days,
    months: monthsIn(from, days),
    placed,
    lanes: placed.length === 0 ? 0 : Math.max(...placed.map((p) => p.lane)) + 1,
  };
}

/** The month bands over the window, each clipped to it. The first and last are
 * usually partial -- the rail starts today, not on the first of the month, and
 * a header that spanned the whole of August while only showing its last week
 * would misstate the axis it labels. */
export function monthsIn(from: string, days: number): TimelineMonth[] {
  const months: TimelineMonth[] = [];
  for (let index = 0; index < days; index += 1) {
    const day = shiftDay(from, index);
    const key = day.slice(0, 7);
    const last = months[months.length - 1];
    if (last && last.key === key) last.span += 1;
    else months.push({ key, label: monthLabelTr(key), startIndex: index, span: 1 });
  }
  return months;
}
