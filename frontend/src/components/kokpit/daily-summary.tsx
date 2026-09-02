import {
  ArrowDownRight,
  ArrowUpRight,
  Flame,
  Info,
  Megaphone,
  Minus,
  Radar,
  TrendingUp,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";

import { StatusPill, statusToneOf } from "@/components/ui/status-pill";
import type { CockpitSignal } from "@/lib/types";
import { cn } from "@/lib/utils";

const SIGNAL_ICONS: Record<CockpitSignal["key"], LucideIcon> = {
  fx: TrendingUp,
  fuel: Flame,
  risk: Radar,
  competitor: Megaphone,
};

/** Which way the tile points. Derived from the LEVEL, not from a number:
 * `CockpitSignal` carries no direction field, and `unknown` deliberately
 * points nowhere rather than resolving to "steady". */
function ArrowFor({ level }: { level: CockpitSignal["level"] }) {
  if (level === "critical" || level === "warning") {
    return <ArrowUpRight className="size-3.5 shrink-0" aria-hidden />;
  }
  if (level === "good") return <ArrowDownRight className="size-3.5 shrink-0" aria-hidden />;
  return <Minus className="size-3.5 shrink-0" aria-hidden />;
}

/**
 * GÜNÜN ÖZETİ -- four glyphs, and not one number.
 *
 * WHY NO NUMBERS
 * --------------
 * Two reasons, and the second is the important one.
 *
 * 1. The owner asked for "icon + trend + short label", explicitly not prose
 *    and not a bulleted news list. This is that, literally.
 *
 * 2. It makes the page's worst duplication STRUCTURALLY impossible rather than
 *    merely discouraged. The four drivers behind these tiles are USD/TRY,
 *    Brent, the risk stream and rival campaign volume -- and the first two are
 *    printed, at full size, in Market Pulse about two hundred pixels above.
 *    A tile that printed "48,2505" here would be the third appearance of one
 *    reading on one screen. Choosing not to carry the number at all closes
 *    that off in the data, where a later maintainer cannot accidentally
 *    reopen it by restyling a card.
 *
 * The numbers, the threshold that produced the level, the method and the
 * source are all still one hover away, in the tile's `title`. A caveat a
 * reader must hover to find is not an acceptable CAVEAT -- but a DETAIL they
 * consult once is exactly what a tooltip is for.
 *
 * This replaces `SignalBoard` (four tall tiles, each with a headline figure
 * and a sentence) and absorbs the signal chips from the deleted "Bugünün
 * İstihbaratı" block. The levels are still computed server-side and merely
 * rendered here, so this row and any other surface reading `/kokpit/signals`
 * cannot disagree about what "Dikkat" means.
 */
export function DailySummary({ signals }: { signals: CockpitSignal[] }) {
  if (signals.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-border p-4 text-center text-xs text-muted-foreground">
        Sinyal üretilemedi.
      </p>
    );
  }

  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {signals.map((signal) => {
        const Icon = SIGNAL_ICONS[signal.key] ?? Info;
        const title = [
          signal.value_label,
          signal.reason_tr,
          signal.method_tr,
          `Kaynak: ${signal.source}`,
        ]
          .filter(Boolean)
          .join("\n\n");

        const inner = (
          <>
            <Icon className="size-4 shrink-0 text-muted-foreground" aria-hidden />
            <span className="min-w-0 flex-1 truncate text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              {signal.label_tr}
            </span>
            <ArrowFor level={signal.level} />
            <StatusPill tone={statusToneOf(signal.level)}>{signal.level_label_tr}</StatusPill>
          </>
        );

        const className = cn(
          "flex h-[72px] w-full items-center gap-2 rounded-lg border border-border bg-card/60 px-3",
          signal.href &&
            "transition-colors hover:bg-accent/40 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
        );

        return signal.href ? (
          <Link key={signal.key} href={signal.href} title={title} className={className}>
            {inner}
          </Link>
        ) : (
          <div key={signal.key} title={title} className={className}>
            {inner}
          </div>
        );
      })}
    </div>
  );
}
