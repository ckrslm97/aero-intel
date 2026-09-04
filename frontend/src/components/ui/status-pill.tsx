import { CircleCheck, type LucideIcon } from "lucide-react";

import { SEVERITY_LADDER, toSeverity, type Severity } from "@/lib/severity";
import { cn } from "@/lib/utils";

export type StatusTone = "critical" | "warning" | "good" | "info" | "neutral";

/** Tone -> its icon and its classes.
 *
 * Four of the five tones are the severity ladder's own rungs, read straight
 * out of lib/severity.ts rather than restated here: `critical` IS
 * SEVERITY_LADDER.critical, `warning` is `high`, `info` is `medium`, `neutral`
 * is `unknown`. This table used to be an independent fifth copy of the ladder,
 * and it disagreed with the others about what "yüksek" looks like.
 *
 * `good` is the one tone that is NOT a severity, which is exactly why it lives
 * here and not there: a KPI moving the right way is good news, and there is no
 * such thing as a good risk. Keeping it out of the ladder is what stops a
 * low-severity anything from being drawn green again.
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
const fromRung = (rung: Severity): { icon: LucideIcon; className: string } => ({
  icon: SEVERITY_LADDER[rung].icon,
  className: SEVERITY_LADDER[rung].pill,
});

const TONES: Record<StatusTone, { icon: LucideIcon; className: string }> = {
  critical: fromRung("critical"),
  warning: fromRung("high"),
  good: { icon: CircleCheck, className: "bg-good/10 text-good ring-good/30" },
  info: fromRung("medium"),
  neutral: fromRung("unknown"),
};

/** The level/severity/priority pill, once.
 *
 * Kokpit had five separate meta tables saying the same thing in five slightly
 * different ways; this is the Kokpit-wide one. The severity tables OUTSIDE
 * Kokpit have since come along too -- the risk radar's pill, the öneriler
 * card's badge and the campaign alert strip all read lib/severity.ts now, so
 * this pill and those three cannot disagree about a word again.
 *
 * `lib/events.ts` EVENT_IMPACT_META is the one that is still its own table,
 * and deliberately: an event's `impact_level` grades DEMAND EFFECT, not risk.
 * A high-impact air show is good news. Folding it into the severity ladder
 * would be the same category error the ladder was built to stop.
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
 * rows cannot disagree about what "yüksek" looks like. The severity rungs go
 * through `toSeverity`, so a value from neither vocabulary falls to `neutral`
 * -- never to `good`, and never to a rung it was not given.
 *
 * `good` and `warning` are the two words Kokpit's own level vocabulary adds on
 * top of the ladder; they are matched before it, because "warning" is a level
 * name there and not the ladder's `high`.
 */
export function statusToneOf(level: string | null | undefined): StatusTone {
  if (level === "good") return "good";
  if (level === "warning") return "warning";
  const SEVERITY_TONE: Record<Severity, StatusTone> = {
    critical: "critical",
    high: "warning",
    medium: "info",
    low: "neutral",
    unknown: "neutral",
  };
  return SEVERITY_TONE[toSeverity(level)];
}
