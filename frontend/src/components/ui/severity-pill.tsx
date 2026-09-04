import { severityMeta } from "@/lib/severity";
import { cn } from "@/lib/utils";

/** The severity badge, once, for the whole app.
 *
 * ICON + WORD + hue, in that order of importance. The house rule that colour
 * never carries meaning alone applies here with full force: this is the badge
 * a desk scans to decide what to read first, and a misread costs the most.
 *
 * It replaces `components/risk/severity-pill.tsx`, which owned a THREE-rung
 * table of its own (high/medium/low, high drawn in --critical) while
 * lib/signals.ts drew a five-rung one (high drawn in --warning). The risk
 * radar and the signal list therefore printed the same word "Yüksek" in two
 * different colours. Both now read the same ladder (lib/severity.ts).
 *
 * A rung this component's caller does not carry is simply never rendered: a
 * page whose data only has high/medium/low never shows `critical`, and an
 * unrecognised value shows `Belirsiz` rather than being flattered into a rung.
 */
export function SeverityPill({
  severity,
  className,
}: {
  severity: string | null | undefined;
  className?: string;
}) {
  const meta = severityMeta(severity);
  const Icon = meta.icon;
  return (
    <span
      className={cn(
        "inline-flex w-fit shrink-0 items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
        meta.pill,
        className,
      )}
    >
      <Icon className="size-3" aria-hidden />
      {meta.label}
    </span>
  );
}
