import { Flame, Info, Megaphone, Radar, TrendingUp, type LucideIcon } from "lucide-react";
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

/* THERE IS NO DIRECTION ARROW ON THESE TILES, and there cannot be one.
 *
 * The tiles used to print one, derived like this: critical or warning pointed
 * UP, good pointed DOWN, unknown pointed nowhere. That is not a direction, it
 * is the severity band drawn twice -- and drawn as the one thing on the tile a
 * reader would take for a measurement. "Yakıt riski · DİKKAT ▲" reads as
 * "fuel went up"; the level says only that Brent's percentile crossed a
 * threshold, which it can do while the price is falling.
 *
 * `CockpitSignal` carries no direction field, and the backend refuses to
 * invent one for the same reason (see cockpit_signals_service.py). So the tile
 * carries the band, in words and colour, and nothing that looks like a trend.
 */

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
    // One column below `sm`. At 375px the four-across grid left each label a
    // 23px box against a 53px word, so all four tiles read "KU…", "YA…",
    // "RİS…", "RA…" -- four identical tiles, and no way to see which driver
    // was the one saying DİKKAT.
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {signals.map((signal) => {
        const Icon = SIGNAL_ICONS[signal.key] ?? Info;
        const detail = [
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
            <StatusPill tone={statusToneOf(signal.level)}>{signal.level_label_tr}</StatusPill>
            {/* The number, the threshold, the method and the source, in the
                accessibility tree rather than only in a `title`.

                `title` is a mouse affordance: it never opens on touch and
                browsers do not surface it on keyboard focus. A tile with no
                `href` is not focusable at all, so for those readers the
                caveat did not exist. Screen readers DO read this span as part
                of the tile, and the `title` stays for pointer users. */}
            <span className="sr-only">{detail}</span>
          </>
        );

        const className = cn(
          "flex min-h-[72px] w-full items-center gap-2 rounded-lg border border-border bg-card/60 px-3",
          signal.href &&
            "transition-colors hover:bg-accent/40 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
        );

        return signal.href ? (
          <Link key={signal.key} href={signal.href} title={detail} className={className}>
            {inner}
          </Link>
        ) : (
          <div key={signal.key} title={detail} className={className}>
            {inner}
          </div>
        );
      })}
    </div>
  );
}
