/** The events calendar's display vocabulary, in one place.
 *
 * Lifted verbatim out of the deleted components/events-calendar.tsx so the
 * radar, the timeline and the detail panel cannot drift into three different
 * colours for "Fuar". Nothing here is new -- same five --chart-* hues for the
 * five event types, same status tokens for impact.
 */
import type { EventOut } from "@/lib/types";

/** Declared in --chart-1..5 order: this record drives the type legend, so its
 * order is the order the reader meets the hues in. */
export const EVENT_TYPE_LABELS_TR: Record<EventOut["event_type"], string> = {
  airshow: "Fuar",
  sports: "Spor",
  holiday: "Bayram/Tatil",
  conference: "Konferans",
  festival: "Festival",
};

/** Five event types, five chart tokens -- the app's validated dataviz hues,
 * used here as *content* colour. Literal class strings so Tailwind's scanner
 * sees them. */
export const EVENT_TYPE_PILL: Record<EventOut["event_type"], string> = {
  airshow: "bg-chart-1/15 text-chart-1",
  sports: "bg-chart-2/15 text-chart-2",
  holiday: "bg-chart-3/15 text-chart-3",
  conference: "bg-chart-4/15 text-chart-4",
  festival: "bg-chart-5/15 text-chart-5",
};

/** Continuation of a run gets a thin bar rather than a repeated name plate:
 * the name is already stated where the event begins, the bar just carries the
 * run forward. */
export const EVENT_TYPE_BAR: Record<EventOut["event_type"], string> = {
  airshow: "bg-chart-1/50",
  sports: "bg-chart-2/50",
  holiday: "bg-chart-3/50",
  conference: "bg-chart-4/50",
  festival: "bg-chart-5/50",
};

export const EVENT_TYPE_GLOW: Record<EventOut["event_type"], string> = {
  airshow: "var(--chart-1)",
  sports: "var(--chart-2)",
  holiday: "var(--chart-3)",
  conference: "var(--chart-4)",
  festival: "var(--chart-5)",
};

/** Impact rides on the status palette, not on the type tints above: it is a
 * state (how hard this hits demand), not another category. The caller always
 * prints the WORD, so colour is never the only signal.
 *
 * `rank` is the radar's sort key -- impact first, date second, because the
 * question a radar answers is "what is big enough to plan around", not "what
 * is next on the calendar". */
export const EVENT_IMPACT_META: Record<
  EventOut["impact_level"],
  { label: string; className: string; rank: number }
> = {
  high: {
    label: "Yüksek etki",
    className: "border-critical/40 bg-critical/10 text-critical",
    rank: 0,
  },
  medium: {
    label: "Orta etki",
    className: "border-warning/40 bg-warning/10 text-warning",
    rank: 1,
  },
  low: {
    label: "Düşük etki",
    className: "border-border bg-muted text-muted-foreground",
    rank: 2,
  },
};

export const ATTENDANCE_FORMAT = new Intl.NumberFormat("tr-TR");
