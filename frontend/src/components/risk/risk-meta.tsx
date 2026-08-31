"use client";

import {
  Activity,
  CloudLightning,
  Flame,
  Info,
  Landmark,
  Megaphone,
  Mountain,
  Plane,
  ShieldAlert,
  Swords,
  Waves,
  type LucideIcon,
} from "lucide-react";

import { aviationLinkLabel, confidenceBand, coverageBadge, staleBadge } from "@/lib/risk";
import { RISK_TYPES, type RiskTypeSlug } from "@/lib/taxonomy.gen";
import type { RiskItem } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Icons only. The slugs, families and Turkish labels come from the backend via
 * taxonomy.gen.ts -- they used to be retyped in the page, which meant renaming
 * a risk type in Python left it rendering a label for a slug the API no longer
 * sent.
 *
 * The icons are chosen so FAMILY reads from the icon alone, without colour:
 * natural hazards get weather/terrain glyphs, conflict gets institutional and
 * martial ones. The map encodes the same split again as marker shape. */
export const TYPE_ICONS: Record<RiskTypeSlug, LucideIcon> = {
  earthquake: Activity,
  flood: Waves,
  wildfire: Flame,
  volcano: Mountain,
  storm: CloudLightning,
  war: Swords,
  coup: Landmark,
  attack: ShieldAlert,
  unrest: Megaphone,
};

export const TYPE_META: Record<string, { label: string; family: string; icon: LucideIcon }> =
  Object.fromEntries(
    RISK_TYPES.map((type) => [
      type.slug,
      { label: type.labelTr, family: type.family, icon: TYPE_ICONS[type.slug] },
    ]),
  );

export const TYPE_ORDER = RISK_TYPES.map((type) => type.slug);

export const FAMILY_META: Record<string, string> = {
  natural: "Doğal",
  conflict: "Çatışma",
};

/** Icon for a slug, read as a property rather than returned from a call: a
 * function that returns a component reads to the lint rule (and to React) as a
 * component defined during render, which would remount it every frame. Every
 * call site does `TYPE_META[slug]?.icon ?? FALLBACK_TYPE_ICON` for that
 * reason. */
export const FALLBACK_TYPE_ICON: LucideIcon = Info;

/** Type pill: icon + Turkish label, in the neutral secondary token. Type is
 * identity, not magnitude -- colouring it would compete with severity, which
 * is the only thing on this page allowed to be loud. */
export function TypePill({ item }: { item: Pick<RiskItem, "risk_type" | "risk_type_label_tr"> }) {
  const Icon = TYPE_META[item.risk_type]?.icon ?? FALLBACK_TYPE_ICON;
  return (
    <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-full bg-secondary px-2 py-0.5 text-[10px] font-medium text-secondary-foreground">
      <Icon className="size-3" aria-hidden />
      {item.risk_type_label_tr}
    </span>
  );
}

/** "Yeni" / "Güncellendi", or nothing.
 *
 * A quiet tag, never a flash: `animate-pulse-once` on disaster news would be
 * theatre. Both carry a title that says what the badge is about (the coverage)
 * and, for "Güncellendi", what it is explicitly NOT about (the event's own
 * status) -- see lib/risk.ts coverageBadge. */
export function CoverageBadge({ item }: { item: Pick<RiskItem, "is_fresh" | "is_updated"> }) {
  const badge = coverageBadge(item);
  if (!badge) return null;
  return (
    <span
      title={badge.title}
      className={cn(
        "inline-flex items-center whitespace-nowrap rounded-full border px-1.5 py-px text-[9px] font-bold uppercase leading-tight",
        badge.tone === "new"
          ? "border-signal/40 bg-signal/10 text-signal"
          : "border-border bg-muted text-muted-foreground",
      )}
    >
      {badge.label}
    </span>
  );
}

/** "ESKİ", or nothing.
 *
 * Muted by design -- `bg-muted`, no border colour, no glow: this is the one
 * tag on the page that means "pay less attention", and it would be absurd for
 * it to be the loudest thing on the card. Only drawn in the wide windows,
 * where old coverage genuinely sits next to today's; see lib/risk.ts
 * staleBadge. */
export function StaleBadge({
  item,
  windowDays,
}: {
  item: Pick<RiskItem, "is_fresh" | "is_updated" | "last_reported_at" | "published_at">;
  windowDays: number;
}) {
  const badge = staleBadge(item, windowDays);
  if (!badge) return null;
  return (
    <span
      title={badge.title}
      className="inline-flex items-center whitespace-nowrap rounded-full border border-border bg-muted px-1.5 py-px text-[9px] font-bold uppercase leading-tight text-muted-foreground/80"
    >
      {badge.label}
    </span>
  );
}

/** "otomatik çeviri yok" -- the app's existing quiet tag, reused verbatim.
 *
 * Same wording and same weight as article-analysis-drawer.tsx's, on purpose:
 * a reader who has learned what it means on one page must not have to learn a
 * second phrase for the same fact here. */
export function UntranslatedTag() {
  return (
    <span className="inline-flex items-center whitespace-nowrap rounded-full bg-secondary px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-secondary-foreground">
      otomatik çeviri yok
    </span>
  );
}

/** The confidence band as a pill plus the raw score -- both, always. The band
 * is what a person compares across rows, the score is what they argue with; a
 * band with no number behind it is an opinion. Lifted from the campaign
 * analyst table's pill, with the band derived here because /risks serves a
 * score and no band. */
export function ConfidencePill({ score }: { score: number | null }) {
  const band = confidenceBand(score);
  if (band === null) return <span className="text-[11px] text-muted-foreground">—</span>;
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
      <span
        className={cn(
          "rounded-full border px-2 py-0.5 text-[11px] font-medium",
          band === "high"
            ? "border-good/40 bg-good/10 text-good"
            : band === "medium"
              ? "border-warning/40 bg-warning/10 text-warning"
              : "border-dashed border-border text-muted-foreground",
        )}
      >
        {band === "high" ? "Yüksek" : band === "medium" ? "Orta" : "Düşük"}
      </span>
      <span className="text-[11px] tabular-nums text-muted-foreground">
        {(score ?? 0).toFixed(2)}
      </span>
    </span>
  );
}

/** A small plane on signals whose coverage names an airport (or whose event
 * type is itself an aviation operation). Nothing at all on the rest: most
 * signals are indirect, and a badge on the majority is noise. */
export function AviationLinkMark({ link, className }: { link: string; className?: string }) {
  const meta = aviationLinkLabel(link);
  if (!meta) return null;
  return (
    <span title={meta.title} className={cn("inline-flex items-center text-primary", className)}>
      <Plane className="size-3" aria-hidden />
      <span className="sr-only">{meta.label}</span>
    </span>
  );
}

/** Airport codes as chips, labelled "Anılan" -- never "Etkilenen".
 *
 * The distinction is the whole point: the entity gazetteer found the airport's
 * name in the article's text, which is evidence the story mentions it and
 * nothing more. There is no operations feed behind this product that could
 * support a claim about impact. The full name rides along as a title, because
 * a bare three-letter code is not a place to anyone who does not already know
 * it. */
export function AirportChips({
  airports,
  className,
}: {
  airports: RiskItem["airports"];
  className?: string;
}) {
  if (airports.length === 0) return null;
  return (
    <span className={cn("flex flex-wrap items-center gap-1", className)}>
      <span className="text-[10px] text-muted-foreground">Anılan:</span>
      {airports.map((airport) => (
        <span
          key={airport.code}
          title={`${airport.name} — haberde anılıyor; etkilendiği anlamına gelmez`}
          className="rounded border border-border px-1 py-px font-mono text-[10px] tabular-nums text-muted-foreground"
        >
          {airport.code}
        </span>
      ))}
    </span>
  );
}
