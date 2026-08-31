"use client";

import { ArrowUpRight, Clock, Info, MapPin } from "lucide-react";
import Link from "next/link";

import { AirlineLogo } from "@/components/airline-logo";
import { relativeTimeTr } from "@/lib/campaigns";
import { worldRegions } from "@/lib/nav";
import { severityStyle } from "@/lib/signals";
import type { SignalOut } from "@/lib/types";
import { cn } from "@/lib/utils";

const REGION_NAME: Record<string, string> = Object.fromEntries(
  worldRegions.map((region) => [region.slug, region.name]),
);

/** One signal, from whichever stream produced it.
 *
 * Every line on the card is a field the owning stream published. In
 * particular:
 *
 *   * the severity pill prints the band that stream already decided, and the ⓘ
 *     note prints `severity_basis_tr` verbatim -- including, for the four
 *     streams that publish no severity at all, the sentence saying so. A "Düşük"
 *     pill on a route announcement is not a judgement that the route is
 *     unimportant; the note is what says which it is.
 *   * `confidence_score` appears only where the stream carries one (a risk
 *     cluster does, a campaign alert does not). It is never defaulted, so an
 *     absent score renders as no chip rather than as a low one.
 *   * `detected_at` is null for a rolling-window signal, and the card prints
 *     "—" rather than the time it happened to render.
 */
export function SignalCard({ signal }: { signal: SignalOut }) {
  const style = severityStyle(signal.severity);
  const region = signal.region ? (REGION_NAME[signal.region] ?? signal.region) : null;

  return (
    <article
      style={{ "--glow-color": style.glowVar } as React.CSSProperties}
      className="edge-lit flex flex-col gap-2 rounded-xl border bg-card bg-card-sheen p-4 shadow-elev-1"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={cn(
            "shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
            style.pill,
          )}
        >
          {signal.severity_label_tr}
        </span>
        <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          {signal.type_label_tr}
        </span>
        <span aria-hidden className="h-3 w-px bg-border" />
        <span className="text-[11px] text-muted-foreground">{signal.kind_label_tr}</span>
        <span className="ml-auto flex shrink-0 items-center gap-1 text-[11px] tabular-nums text-muted-foreground">
          <Clock className="size-3" aria-hidden />
          {signal.detected_at ? relativeTimeTr(signal.detected_at) : "—"}
        </span>
      </div>

      <p className="text-sm font-semibold leading-snug text-card-foreground">
        {signal.title_tr}
      </p>
      {signal.detail_tr && (
        <p className="text-xs leading-relaxed text-muted-foreground">{signal.detail_tr}</p>
      )}

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[11px] text-muted-foreground">
        {signal.airline_codes.length > 0 && (
          <span className="flex items-center gap-1.5">
            {signal.airline_codes.slice(0, 4).map((code) => (
              <span key={code} className="flex items-center gap-1 font-medium">
                <AirlineLogo code={code} className="size-4 rounded-[3px]" />
                {code}
              </span>
            ))}
          </span>
        )}
        {region && (
          <span className="flex items-center gap-1">
            <MapPin className="size-3" aria-hidden />
            {region}
          </span>
        )}
        {signal.confidence_score !== null && (
          <span className="tabular-nums" title="Kaynak akışının kendi güven skoru (0-1)">
            Güven {signal.confidence_score.toFixed(2)}
          </span>
        )}
      </div>

      <div className="mt-auto flex flex-wrap items-center gap-x-3 gap-y-1 pt-1 text-[10px] text-muted-foreground">
        {/* A <span title>, not a tooltip component: it must survive with no JS,
            and it is reference material a reader consults once. Same idiom as
            Kokpit's signal tiles. */}
        <span
          title={signal.severity_basis_tr}
          className="flex cursor-help items-center gap-1"
        >
          <Info className="size-3" aria-hidden />
          Şiddet gerekçesi
        </span>
        <span className="truncate">Kaynak: {signal.source_label}</span>
        {signal.href && (
          <Link
            href={signal.href}
            className="ml-auto flex items-center gap-0.5 rounded font-medium text-primary underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          >
            Detay
            <ArrowUpRight className="size-3" aria-hidden />
          </Link>
        )}
      </div>
    </article>
  );
}
