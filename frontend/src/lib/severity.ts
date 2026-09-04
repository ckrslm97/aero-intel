/** THE severity ladder. One rung set, one label, one colour, for the whole app.
 *
 * WHY THIS FILE EXISTS. Severity was written out six times -- lib/signals.ts,
 * risk/severity-pill.tsx, recommendations-client.tsx, ui/status-pill.tsx,
 * campaign-alert-strip.tsx and kokpit/alert-center.tsx -- and the six did not
 * agree. "Yüksek" was CRITICAL red on the öneriler page and WARNING orange on
 * the sinyaller page; "Orta" was orange on the risk radar and blue on Kokpit;
 * a low-importance recommendation was drawn in --good, i.e. the same green the
 * rest of the app reserves for "this is fine". A reader who learns the colour
 * on one page is then actively misled by the next one, which is worse than
 * having no colour language at all.
 *
 * THE RUNGS are the five `SignalSeverity` values the backend already publishes
 * (backend/app/schemas/signals.py). Anything else -- a stream that publishes
 * "severe", a null, a typo in a query string -- lands on `unknown`, never on a
 * rung that would flatter it.
 *
 * TWO RULES THIS FILE ENFORCES, both of which one of the six copies broke:
 *
 *   1. `low` is NEUTRAL, not green. --good means "this is going well". A
 *      low-severity risk signal is a war that is going slightly less badly; a
 *      low-priority alert is still an alert. Neither is good news.
 *   2. `unknown` is neutral too, and deliberately NOT the bottom rung's twin
 *      in meaning: it means the driver could not be read. It must never render
 *      as an all-clear.
 *
 * COLOUR IS NEVER THE MESSAGE. Every rung carries an `icon` and a `label`, and
 * every consumer here renders at least one of them beside the hue. Roughly one
 * man in twelve cannot separate this palette's red from its green.
 */
import { CircleAlert, CircleHelp, Info, TriangleAlert, type LucideIcon } from "lucide-react";

/** critical > high > medium > low, and `unknown` off to the side.
 *
 * Mirrors `SignalSeverity` in lib/types.ts; declared here rather than imported
 * so this module stays the definition of the ladder rather than a decoration
 * on one page's payload type. */
export type Severity = "critical" | "high" | "medium" | "low" | "unknown";

export interface SeverityMeta {
  /** The Turkish word that rides beside the colour. */
  label: string;
  /** The glyph that rides beside the colour. */
  icon: LucideIcon;
  /** Pill: tinted ground + text + ring, in one class string. */
  pill: string;
  /** The bare status dot, where a pill would not fit. */
  dot: string;
  /** Text-only, for a count or a heading that takes the rung's hue. */
  text: string;
  /** The CSS custom-property value a card's edge light is set to. */
  glowVar: string;
}

/** Severity -> how loudly it is drawn.
 *
 * Only the top three take a hue. A list where every row is coloured tells a
 * reader nothing about which one to read first -- the rule kokpit's alert
 * centre and the campaign strip both already followed, kept here rather than
 * re-decided per page.
 */
export const SEVERITY_LADDER: Record<Severity, SeverityMeta> = {
  critical: {
    label: "Kritik",
    icon: TriangleAlert,
    pill: "bg-critical/12 text-critical ring-1 ring-critical/35",
    dot: "bg-critical",
    text: "text-critical",
    glowVar: "var(--critical)",
  },
  high: {
    label: "Yüksek",
    icon: TriangleAlert,
    pill: "bg-warning/12 text-warning ring-1 ring-warning/35",
    dot: "bg-warning",
    text: "text-warning",
    glowVar: "var(--warning)",
  },
  medium: {
    label: "Orta",
    icon: CircleAlert,
    pill: "bg-signal/10 text-signal ring-1 ring-signal/30",
    dot: "bg-signal",
    text: "text-signal",
    glowVar: "var(--signal)",
  },
  low: {
    label: "Düşük",
    icon: Info,
    pill: "bg-muted text-muted-foreground ring-1 ring-border",
    dot: "bg-muted-foreground",
    text: "text-muted-foreground",
    glowVar: "var(--muted-foreground)",
  },
  unknown: {
    // "Belirsiz", not "Düşük": the two rungs look alike on purpose (neither is
    // loud) and mean completely different things. The WORD is what separates
    // them, which is the whole reason every rung carries one.
    label: "Belirsiz",
    icon: CircleHelp,
    pill: "bg-muted text-muted-foreground ring-1 ring-border",
    dot: "bg-muted-foreground",
    text: "text-muted-foreground",
    glowVar: "var(--muted-foreground)",
  },
};

/** Any incoming value -> a rung. Everything unrecognised, including `null`,
 * becomes `unknown` -- never `low`, and never the green one. */
export function toSeverity(value: string | null | undefined): Severity {
  return value !== null && value !== undefined && value in SEVERITY_LADDER
    ? (value as Severity)
    : "unknown";
}

/** The rung's presentation. Same fallback rule as `toSeverity`. */
export function severityMeta(value: string | null | undefined): SeverityMeta {
  return SEVERITY_LADDER[toSeverity(value)];
}

/** A campaign alert's PRIORITY -> this ladder's severity.
 *
 * `CampaignAlert.priority` (lib/types.ts) is its own four-value vocabulary
 * shipped by the alerts endpoint. It is a severity in everything but name, and
 * the two were drawn from separate tables until now -- which is how "Yüksek"
 * came to mean two different colours depending on which list a reader was
 * looking at. `INFO` maps to `low` rather than to `unknown`: an INFO alert was
 * graded, and graded as unimportant. That is a rung, not a missing reading. */
export function priorityToSeverity(
  priority: string | null | undefined,
): Severity {
  switch (priority) {
    case "CRITICAL":
      return "critical";
    case "HIGH":
      return "high";
    case "MEDIUM":
      return "medium";
    case "INFO":
      return "low";
    default:
      return "unknown";
  }
}
