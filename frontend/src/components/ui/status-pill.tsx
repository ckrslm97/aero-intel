import { CircleAlert, CircleCheck, Info, Minus, TriangleAlert, type LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

export type StatusTone = "critical" | "warning" | "good" | "info" | "neutral";

/** Tone -> its icon and its classes.
 *
 * Every tone carries an ICON as well as a hue, and the caller always passes a
 * WORD. Colour alone is never the message here: this pill is read by people
 * on a dark terminal at a glance, and roughly one man in twelve cannot
 * separate the good and critical hues.
 *
 * `neutral` is the resting state and is deliberately not green. A driver whose
 * level could not be computed must not render as an all-clear -- the same rule
 * `SIGNAL_LEVEL_STYLES` states in lib/cockpit.ts, and the reason
 * CockpitSignal's `unknown` level exists at all.
 */
const TONES: Record<StatusTone, { icon: LucideIcon; className: string }> = {
  critical: {
    icon: TriangleAlert,
    className: "bg-critical/12 text-critical ring-critical/35",
  },
  warning: { icon: CircleAlert, className: "bg-warning/12 text-warning ring-warning/35" },
  good: { icon: CircleCheck, className: "bg-good/10 text-good ring-good/30" },
  info: { icon: Info, className: "bg-primary/10 text-primary ring-primary/30" },
  neutral: { icon: Minus, className: "bg-muted text-muted-foreground ring-border" },
};

/** The level/severity/priority pill, once.
 *
 * Kokpit had five separate meta tables saying the same thing in five slightly
 * different ways. This is the Kokpit-wide one; the four OUTSIDE Kokpit
 * (risk-radar-client, biz-signals, events-calendar, campaign-alert-strip) are
 * deliberately left alone -- three of them have tests, and converting all four
 * would tie this redesign to a cross-page refactor it does not need.
 */
export function StatusPill({
  tone,
  children,
  title,
  className,
}: {
  tone: StatusTone;
  children: React.ReactNode;
  title?: string;
  className?: string;
}) {
  const meta = TONES[tone] ?? TONES.neutral;
  const Icon = meta.icon;
  return (
    <span
      title={title}
      className={cn(
        "inline-flex w-fit shrink-0 items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ring-1",
        meta.className,
        className,
      )}
    >
      <Icon className="size-2.5" aria-hidden />
      {children}
    </span>
  );
}

/** CockpitSignal.level / SignalOut.severity -> a pill tone.
 *
 * Both vocabularies land here so the Günün Özeti tiles and the Sinyal Panosu
 * rows cannot disagree about what "yüksek" looks like. Anything unrecognised
 * falls to `neutral`, never to `good`.
 */
export function statusToneOf(level: string | null | undefined): StatusTone {
  switch (level) {
    case "critical":
      return "critical";
    case "high":
    case "warning":
      return "warning";
    case "good":
      return "good";
    case "medium":
    case "info":
      return "info";
    default:
      return "neutral";
  }
}
