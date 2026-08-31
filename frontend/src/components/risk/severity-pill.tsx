"use client";

import { CircleAlert, Info, TriangleAlert, type LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

/** Severity is icon + word, always. The house rule that colour never carries
 * meaning alone applies here with full force -- this is the surface where a
 * misread costs the most.
 *
 * `low` is deliberately NOT the --good token. A "good" war is a category
 * error, and the events calendar's low-impact badge already set this neutral
 * precedent (see events-calendar.tsx IMPACT_META).
 *
 * The pill was written out three times (risk-radar-client, risk-map's legend,
 * biz-signals) before it lived here. The third copy is gone with biz-signals
 * itself (the section moved to /sinyaller, which draws its own severity pill
 * over a five-value ladder that includes `critical` and `unknown` -- see
 * lib/signals.ts SEVERITY_STYLES); risk-map's legend is still its own copy,
 * left alone on purpose because it belongs to another page.
 */
export const RISK_SEVERITY_META: Record<
  string,
  { label: string; icon: LucideIcon; className: string; dotClassName: string }
> = {
  high: {
    label: "Yüksek",
    icon: TriangleAlert,
    className: "border-critical/40 bg-critical/10 text-critical",
    dotClassName: "bg-critical",
  },
  medium: {
    label: "Orta",
    icon: CircleAlert,
    className: "border-warning/40 bg-warning/10 text-warning",
    dotClassName: "bg-warning",
  },
  low: {
    label: "Düşük",
    icon: Info,
    className: "border-border bg-muted text-muted-foreground",
    dotClassName: "bg-muted-foreground/50",
  },
};

export function severityMeta(severity: string) {
  return RISK_SEVERITY_META[severity] ?? RISK_SEVERITY_META.low;
}

export function SeverityPill({
  severity,
  className,
}: {
  severity: string;
  className?: string;
}) {
  const meta = severityMeta(severity);
  const Icon = meta.icon;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
        meta.className,
        className,
      )}
    >
      <Icon className="size-3" aria-hidden />
      {meta.label}
    </span>
  );
}
