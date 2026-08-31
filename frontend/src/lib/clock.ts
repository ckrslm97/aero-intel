/** The topbar clock's formatting, as pure functions.
 *
 * Kept out of the component for the reason lib/gazete.ts is: "does the header
 * say 14:32:05 or 2:32 PM, and does it say GMT+3 or +03" is a question about
 * formatting, not about rendering, and it is the half worth testing against a
 * frozen date.
 */

/** The desk's own city. One clock, not a row of them -- see the LiveClock
 * docstring for why a world-clock strip was dropped. */
export const LOCAL_CITY_TR = "İstanbul";

/** IANA zone behind every string this module produces. Named once so the time,
 * the date and the offset can never be formatted against three different
 * zones. */
export const LOCAL_TIME_ZONE = "Europe/Istanbul";

const TIME_FORMAT = new Intl.DateTimeFormat("tr-TR", {
  timeZone: LOCAL_TIME_ZONE,
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

/** "31 Ağu 2026" -- short month, so the whole line still fits a laptop
 * viewport next to the search box. */
const DATE_FORMAT = new Intl.DateTimeFormat("tr-TR", {
  timeZone: LOCAL_TIME_ZONE,
  day: "numeric",
  month: "short",
  year: "numeric",
});

/** The offset is FORMATTED, never hardcoded.
 *
 * Türkiye has been on a permanent UTC+3 since 2016, so "GMT+3" is a constant
 * today and writing it as one would be correct today -- and silently wrong the
 * first time that changes, on a label whose entire job is to say which clock
 * the reader is looking at. Intl reads the zone's own rules instead.
 */
const OFFSET_FORMAT = new Intl.DateTimeFormat("en-US", {
  timeZone: LOCAL_TIME_ZONE,
  timeZoneName: "shortOffset",
});

export interface LocalClock {
  /** "14:32:05", or the placeholder before the first client tick. */
  time: string;
  /** "31 Ağu 2026", or a placeholder. */
  date: string;
  /** "GMT+3", or a placeholder. */
  offset: string;
}

/** Placeholders rather than an empty header on the server render.
 *
 * The server has no business rendering a time at all -- it would be its own
 * clock, in its own zone, replaced a tick later by the reader's -- so the
 * markup it produces is the shape of a readout with no reading in it. Same
 * width as the real thing under `tabular-nums`, so nothing shifts when the
 * digits arrive.
 */
export const CLOCK_PLACEHOLDER: LocalClock = {
  time: "--:--:--",
  date: "—",
  offset: "GMT",
};

function offsetOf(date: Date): string {
  const part = OFFSET_FORMAT.formatToParts(date).find(
    (candidate) => candidate.type === "timeZoneName",
  );
  return part?.value ?? CLOCK_PLACEHOLDER.offset;
}

/** The three strings the topbar prints. `null` -- the pre-hydration snapshot
 * -- returns the placeholders rather than `new Date()`, so the server's markup
 * and the client's first paint are the same string. */
export function formatLocalClock(date: Date | null): LocalClock {
  if (date === null || Number.isNaN(date.getTime())) return CLOCK_PLACEHOLDER;
  return {
    time: TIME_FORMAT.format(date),
    date: DATE_FORMAT.format(date),
    offset: offsetOf(date),
  };
}
