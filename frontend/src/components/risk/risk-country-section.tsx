"use client";

import { ChevronDown, ExternalLink, MapPin } from "lucide-react";
import { useMemo, useState } from "react";

import { MotionItem, MotionRail } from "@/components/motion/motion-list";
import {
  AirportChips,
  AviationLinkMark,
  ConfidencePill,
  CoverageBadge,
  StaleBadge,
  TypePill,
  UntranslatedTag,
} from "@/components/risk/risk-meta";
import { SeverityPill } from "@/components/risk/severity-pill";
import { worldRegions } from "@/lib/nav";
import { headlinePresentation, partitionByVisibility } from "@/lib/risk";
import type { RiskCountry, RiskItem } from "@/lib/types";
import { cn } from "@/lib/utils";

const REGION_NAME: Record<string, string> = Object.fromEntries(
  worldRegions.map((r) => [r.slug, r.name]),
);

function formatDate(iso: string | null): string | null {
  if (!iso) return null;
  return new Date(iso).toLocaleDateString("tr-TR", { day: "numeric", month: "short" });
}

/** One country's block of the list, and the cards inside it.
 *
 * Split out of risk-radar-client.tsx rather than left inline because the
 * confidence-visibility rule it now carries -- weak signals present, counted,
 * de-emphasised and collapsed instead of hidden -- is the kind of thing that
 * has to be provable with a test, and the client component around it fetches
 * two endpoints and lazy-loads echarts before it renders anything at all. */

export function CountrySection({
  group,
  windowDays,
  onSelect,
}: {
  group: RiskCountry;
  windowDays: number;
  onSelect: (item: RiskItem) => void;
}) {
  // The server already sorted the weak tail last, so this only splits -- see
  // lib/risk.ts partitionByVisibility.
  const { normal, low } = useMemo(() => partitionByVisibility(group.items), [group.items]);
  const [showLow, setShowLow] = useState(false);

  return (
    <MotionItem className="flex flex-col gap-3">
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-sm font-semibold">{group.country}</h3>
          {group.region && (
            <span className="rounded-full bg-secondary px-2 py-0.5 text-[10px] font-medium text-secondary-foreground">
              {REGION_NAME[group.region] ?? group.region}
            </span>
          )}
          <span className="text-[11px] tabular-nums text-muted-foreground">
            {group.count} sinyal
          </span>
        </div>
        {/* Plain --border rail. No colour at country level: the page's whole
            colour budget is spent on item severity, one level down. */}
        <MotionRail
          staggered
          style={{ "--glow-color": "var(--border)" } as React.CSSProperties}
        />
      </div>

      <div className="flex flex-col gap-2.5">
        {normal.map((item) => (
          <RiskCard key={item.id} item={item} windowDays={windowDays} onSelect={onSelect} />
        ))}
      </div>

      {/* Collapsed, and collapsed rather than dropped on purpose. These
          signals cleared the publish floor -- the server would not have sent
          them otherwise -- they are just thinly sourced: one telling, from an
          outlet weighted below this catalogue's default. Hiding them outright
          would be a second, invisible editorial cut on top of the one the API
          already documents; leaving them inline would let a single blog outweigh
          three agencies on the same screen. So: present, counted, named as what
          they are, and closed until asked for. */}
      {low.length > 0 && (
        <div className="flex flex-col gap-2">
          <button
            type="button"
            onClick={() => setShowLow((value) => !value)}
            aria-expanded={showLow}
            className="flex w-fit items-center gap-1.5 rounded-md px-1 py-0.5 text-[11px] text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          >
            <ChevronDown
              className={cn("size-3.5 transition-transform", showLow && "rotate-180")}
              aria-hidden
            />
            Düşük güvenli sinyaller ({low.length})
          </button>
          {showLow && (
            <>
              <p className="text-[11px] leading-relaxed text-muted-foreground/80">
                Tek kaynaklı ve güven puanı düşük sinyaller. Doğrulanmadıkları
                anlamına gelmez; yalnızca tek bir haber tarafından bildirildiler.
              </p>
              <div className="flex flex-col gap-2">
                {low.map((item) => (
                  <RiskCard
                    key={item.id}
                    item={item}
                    windowDays={windowDays}
                    onSelect={onSelect}
                  />
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </MotionItem>
  );
}

export function RiskCard({
  item,
  windowDays,
  onSelect,
}: {
  item: RiskItem;
  windowDays: number;
  onSelect: (item: RiskItem) => void;
}) {
  const isLow = item.visibility === "low";
  // A low-confidence signal keeps its severity in the pill and loses it in the
  // chrome: no lit edge, no warning rail, smaller type, muted card. The fact
  // stays readable; the emphasis does not outrun the evidence.
  const isHigh = item.severity === "high" && !isLow;
  const isMedium = item.severity === "medium" && !isLow;
  const headline = headlinePresentation(item);

  return (
    <article
      style={isHigh ? ({ "--glow-color": "var(--critical)" } as React.CSSProperties) : undefined}
      className={cn(
        "group relative flex flex-col rounded-xl border bg-card transition-all duration-200",
        isLow ? "gap-1.5 border-dashed p-3 opacity-80" : "gap-2 p-4",
        // The emphatic-but-sober dial. Only high severity gets a lit edge; it
        // is a static 3px rail, not a strobe. On a bad day the page visibly
        // carries more red -- that is the signal, and it needs no animation.
        isHigh && "edge-lit hover:glow-edge",
        isMedium && "border-l-2 border-l-warning",
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <TypePill item={item} />
        <SeverityPill severity={item.severity} />
        <CoverageBadge item={item} />
        <StaleBadge item={item} windowDays={windowDays} />
        <AviationLinkMark link={item.aviation_link} />
        {formatDate(item.published_at) && (
          <span className="ml-auto text-[10px] tabular-nums text-muted-foreground">
            {formatDate(item.published_at)}
          </span>
        )}
      </div>

      {/* The whole card opens the drawer, and the heading carries the button so
          a keyboard reader reaches it by the headline rather than by an unnamed
          region. The stretched pseudo-element is what makes the rest of the
          card clickable without nesting the source link inside a button. */}
      <h4 className={cn("font-medium leading-snug", isLow ? "text-[13px]" : "text-sm")}>
        <button
          type="button"
          onClick={() => onSelect(item)}
          // The source-language headline as a tooltip: the Turkish is a
          // machine's paraphrase, and a paraphrase whose original is hidden
          // cannot be checked. Null when nothing was translated, so an
          // untranslated card does not get its own words echoed back at it.
          title={headline.original ?? undefined}
          className="text-left after:absolute after:inset-0 after:content-[''] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
        >
          {headline.text}
        </button>
      </h4>

      {headline.untranslated && <UntranslatedTag />}

      {item.summary_tr && !isLow && (
        <p className="line-clamp-2 text-[13px] leading-relaxed text-muted-foreground">
          {item.summary_tr}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[11px] text-muted-foreground">
        {(item.city || item.country) && (
          <span className="flex items-center gap-1">
            <MapPin className="size-3" aria-hidden />
            {[item.city, item.country].filter(Boolean).join(" · ")}
          </span>
        )}
        {item.source_name && <span className="font-medium">{item.source_name}</span>}
        {item.source_count > 1 && <span>+{item.source_count - 1} kaynak daha</span>}
        <ConfidencePill score={item.confidence_score} />
        <AirportChips airports={item.airports} />
        <a
          href={item.url}
          target="_blank"
          rel="noopener noreferrer"
          // relative + z-10 so this link stays reachable above the card-wide
          // stretched hit area behind it.
          className="relative z-10 ml-auto flex items-center gap-1 font-medium text-primary hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
        >
          Kaynak
          <ExternalLink className="size-3" aria-hidden />
        </a>
      </div>
    </article>
  );
}
