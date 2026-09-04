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

/** Drivers whose band is printed on their own Market Pulse cell.
 *
 * THIS IS THE PAGE'S LAST DUPLICATION, CLOSED IN THE DATA.
 *
 * The section used to render all four drivers. Two of them -- USD/TRY and
 * Brent -- are cells in Market Pulse two hundred pixels above, printing the
 * reading at 26px with both of its deltas; the tile added exactly one word to
 * that ("DİKKAT") and spent a quarter of the section's height doing it. Since
 * the owner's own Market Pulse spec asked for a STATUS in every cell, the word
 * now sits on the cell that already carries the number (market-pulse-row.tsx),
 * and this section carries the drivers that have no cell of their own.
 *
 * Fuel in particular was appearing THREE times before this change -- the pulse
 * cell, a Sektör Dengesi percentile row and this tile -- against an explicit
 * instruction that fuel appear as a SINGLE signal.
 *
 * The section is not removed: it is item 4 of the owner's ordering, and the
 * risk and competition drivers genuinely appear nowhere else on the page as a
 * judgement. If the backend ever adds a fifth driver with no pulse cell, it
 * lands here automatically. */
export const PULSE_BANDED_KEYS = new Set<CockpitSignal["key"]>(["fx", "fuel"]);

/**
 * GÜNÜN ÖZETİ -- glyphs, and not one number.
 *
 * WHY NO NUMBERS
 * --------------
 * Two reasons, and the second is the important one.
 *
 * 1. The owner asked for "icon + trend + short label", explicitly not prose
 *    and not a bulleted news list. This is that, literally.
 *
 * 2. It makes duplication STRUCTURALLY impossible rather than merely
 *    discouraged. A tile that printed a reading would be printing something
 *    that already exists elsewhere on this page at full size; choosing not to
 *    carry numbers at all closes that off in the data, where a later
 *    maintainer cannot reopen it by restyling a card.
 *
 * The numbers, the threshold that produced the level, the method and the
 * source are all still one hover away in the tile's `title`, and in the
 * accessibility tree for readers who cannot hover. A caveat a reader must
 * hover to find is not an acceptable CAVEAT -- but a DETAIL they consult once
 * is exactly what a tooltip is for.
 *
 * The levels are computed server-side and merely rendered here, so this row
 * and any other surface drawing the same tiles cannot disagree about what
 * "Dikkat" means. The tiles reach this page inside `/signals`'
 * `cockpit_tiles` -- the same computation the feed's `kokpit` rows were
 * flattened from, so the tile and its card on /sinyaller are one banding,
 * not two.
 */
export function DailySummary({ signals }: { signals: CockpitSignal[] }) {
  const tiles = signals.filter((signal) => !PULSE_BANDED_KEYS.has(signal.key));

  if (signals.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-border px-3 py-2 text-xs text-muted-foreground">
        Sinyal üretilemedi.
      </p>
    );
  }

  if (tiles.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-border px-3 py-2 text-xs text-muted-foreground">
        Bugünün sürücülerinin tümü Market Pulse hücrelerinde bantlandı.
      </p>
    );
  }

  return (
    // One column below `sm`. At 375px the four-across grid left each label a
    // 23px box against a 53px word, so all four tiles read "KU…", "YA…",
    // "RİS…", "RA…" -- four identical tiles, and no way to see which driver
    // was the one saying DİKKAT.
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {tiles.map((signal) => {
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
          // 56px, down from 72. The tile carries an icon, a word and a band;
          // the extra sixteen pixels were spent on nothing and the section
          // below the fold paid for them.
          "flex min-h-[56px] w-full items-center gap-2 rounded-lg border border-border bg-card/60 px-3 py-2",
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
