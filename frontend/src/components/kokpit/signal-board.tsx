import { Flame, Info, Megaphone, Radar, TrendingUp, type LucideIcon } from "lucide-react";
import Link from "next/link";

import { MotionItem, MotionList } from "@/components/motion/motion-list";
import { signalLevelStyle } from "@/lib/cockpit";
import type { CockpitSignal } from "@/lib/types";
import { cn } from "@/lib/utils";

const SIGNAL_ICONS: Record<CockpitSignal["key"], LucideIcon> = {
  fx: TrendingUp,
  fuel: Flame,
  risk: Radar,
  competitor: Megaphone,
};

function SignalTile({ signal }: { signal: CockpitSignal }) {
  const Icon = SIGNAL_ICONS[signal.key] ?? Info;
  const style = signalLevelStyle(signal.level);

  const inner = (
    <>
      <div className="flex items-center gap-2">
        <Icon className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
        <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          {signal.label_tr}
        </span>
        <span
          className={cn(
            "ml-auto shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
            style.pill,
          )}
        >
          {signal.level_label_tr}
        </span>
      </div>

      <p className="text-xl font-semibold tabular-nums leading-none dark:text-glow">
        {signal.value_label}
      </p>

      <p className="text-[11px] leading-relaxed text-muted-foreground">{signal.reason_tr}</p>

      {/* The method note is a <span title>, not a tooltip component: it must
          survive with no JS, and it is reference material a reader consults
          once, not something they need on every glance. */}
      <span
        title={`${signal.method_tr}\n\nKaynak: ${signal.source}`}
        className="mt-auto flex w-fit cursor-help items-center gap-1 text-[10px] text-muted-foreground"
      >
        <Info className="size-3" aria-hidden />
        Yöntem &amp; kaynak
      </span>
    </>
  );

  const className = cn(
    "edge-lit flex h-full flex-col gap-1.5 rounded-xl border bg-card bg-card-sheen p-3 transition-shadow duration-300",
    signal.href &&
      "hover:glow-edge focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
  );

  return signal.href ? (
    <Link
      href={signal.href}
      style={{ "--glow-color": style.glowVar } as React.CSSProperties}
      className={className}
    >
      {inner}
    </Link>
  ) : (
    <div style={{ "--glow-color": style.glowVar } as React.CSSProperties} className={className}>
      {inner}
    </div>
  );
}

/** "Sinyal Panosu": four tiles, four real drivers, four stated thresholds.
 *
 * The thing this deliberately is NOT is a composite 0-100 health score. See
 * backend/app/services/cockpit_signals_service.py's module docstring for the
 * argument -- in short, blending an FX move, a Brent percentile, a count of
 * clustered disaster reports and a count of rival press releases needs weights
 * nobody can defend, and produces a number that looks precise and means
 * nothing.
 *
 * The levels themselves are computed server-side and simply rendered here, so
 * this board and the "Yakıt & Enerji" panel's chip cannot disagree about what
 * "Dikkat" means.
 */
export function SignalBoard({ signals }: { signals: CockpitSignal[] }) {
  if (signals.length === 0) {
    return (
      <p className="rounded-xl border border-dashed border-border p-6 text-sm text-muted-foreground">
        Sinyaller şu anda hesaplanamıyor.
      </p>
    );
  }

  return (
    <MotionList className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      {signals.map((signal) => (
        <MotionItem key={signal.key} variant="scalePop" className="h-full">
          <SignalTile signal={signal} />
        </MotionItem>
      ))}
    </MotionList>
  );
}
