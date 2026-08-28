"use client";

import {
  CalendarClock,
  CircleAlert,
  CircleDashed,
  CircleDot,
  CircleSlash,
  ExternalLink,
  Flag,
  Split,
  type LucideIcon,
} from "lucide-react";

import { AirlineLogo } from "@/components/airline-logo";
import { Card } from "@/components/ui/card";
import {
  campaignRouteLabel,
  campaignStatusStyle,
  confidenceBandLabel,
} from "@/lib/campaigns";
import { CAMPAIGN_TYPE_LABELS_TR, type CampaignStatus, type CampaignType } from "@/lib/taxonomy.gen";
import type { PromotionOut } from "@/lib/types";
import { cn } from "@/lib/utils";

/** One glyph per status, so the state survives a greyscale print and a reader
 * who cannot separate the hues: a filled dot is running, a hollow ring is
 * still ahead, a clock is "booking closed but the travel window is live", a
 * slash is over, a dashed ring is "we do not know". */
const STATUS_ICONS: Record<CampaignStatus, LucideIcon> = {
  ACTIVE_BOOKING: CircleDot,
  UPCOMING: CircleDashed,
  BOOKING_CLOSED_TRAVEL_ACTIVE: CalendarClock,
  EXPIRED: CircleSlash,
  UNKNOWN: CircleDashed,
};

export function CampaignStatusPill({ status }: { status: string }) {
  const style = campaignStatusStyle(status);
  const Icon = STATUS_ICONS[status as CampaignStatus] ?? STATUS_ICONS.UNKNOWN;
  return (
    <span
      title={style.label}
      className={cn(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-medium",
        style.className,
      )}
    >
      <Icon className="size-3" aria-hidden />
      {style.short}
    </span>
  );
}

/** The confidence band as a pill plus the raw score.
 *
 * Both, always: the band is what a person compares across rows, the score is
 * what they argue with. A band with no number behind it is an opinion. */
export function ConfidencePill({
  band,
  score,
}: {
  band: string | null;
  score: number | null;
}) {
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
        {confidenceBandLabel(band)}
      </span>
      {score !== null && (
        <span className="text-[11px] tabular-nums text-muted-foreground">
          {score.toFixed(2)}
        </span>
      )}
    </span>
  );
}

const HEADERS = [
  "Havayolu",
  "Kampanya",
  "Rota",
  "Satış dönemi",
  "Seyahat dönemi",
  "İndirim",
  "Durum",
  "Güven",
  "Kaynak",
] as const;

/** The analyst table: one row per campaign, nine columns, no chart.
 *
 * This is the view the swimlane cannot be. A timeline answers "when", brilliantly
 * and only that; a desk comparing eleven carriers on discount depth, route scope
 * and confidence needs the values side by side and sortable by eye. The two are
 * offered as a toggle rather than stacked, because they answer the same question
 * from opposite ends and showing both at once halves each.
 *
 * Every cell can be empty, and an empty cell says "—" rather than rendering
 * blank: on a table an unexplained gap reads as a rendering bug, not as a fact
 * about the source.
 */
export function CampaignAnalystTable({
  rows,
  onSelect,
}: {
  rows: readonly PromotionOut[];
  onSelect: (promo: PromotionOut) => void;
}) {
  return (
    <Card className="overflow-x-auto p-0">
      <table className="w-full min-w-[64rem] text-sm">
        <thead>
          <tr className="border-b border-border text-left text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            {HEADERS.map((header) => (
              <th key={header} className="px-3 py-2.5 whitespace-nowrap">
                {header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {rows.map((promo) => (
            <Row key={promo.id} promo={promo} onSelect={onSelect} />
          ))}
        </tbody>
      </table>
    </Card>
  );
}

function Row({
  promo,
  onSelect,
}: {
  promo: PromotionOut;
  onSelect: (promo: PromotionOut) => void;
}) {
  const inferredYear = Boolean(
    promo.date_flags_json && (promo.date_flags_json as { inferred_year?: unknown }).inferred_year,
  );
  const typeLabel = promo.campaign_type
    ? (CAMPAIGN_TYPE_LABELS_TR[promo.campaign_type as CampaignType] ?? promo.campaign_type)
    : null;

  return (
    <tr
      onClick={() => onSelect(promo)}
      className="cursor-pointer align-top transition-colors hover:bg-accent/60"
    >
      <td className="px-3 py-2.5">
        <span className="flex items-center gap-1.5">
          <AirlineLogo code={promo.airline_code} name={promo.airline_name} className="size-4" />
          <span className="text-xs font-semibold tabular-nums">{promo.airline_code}</span>
        </span>
      </td>

      <td className="max-w-[22rem] px-3 py-2.5">
        {/* The row is clickable, but the button is what a keyboard and a screen
            reader can actually reach -- a clickable <tr> alone is a mouse-only
            control. */}
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            onSelect(promo);
          }}
          className="text-left font-medium leading-snug hover:text-primary"
        >
          {promo.title_tr}
        </button>
        <span className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
          <span>{typeLabel ?? "Sınıflandırılmadı"}</span>
          {promo.review_required === true && (
            <span
              title="Güven eşiğinin altında: insan incelemesi bekliyor"
              className="inline-flex items-center gap-0.5 rounded-full border border-warning/40 bg-warning/10 px-1.5 text-warning"
            >
              <Flag className="size-2.5" aria-hidden />
              İnceleme
            </span>
          )}
          {promo.conflict_detected === true && (
            <span
              title="İki kaynak bir alanda çelişti; daha resmî olan kazandı"
              className="inline-flex items-center gap-0.5 rounded-full border border-critical/40 bg-critical/10 px-1.5 text-critical"
            >
              <Split className="size-2.5" aria-hidden />
              Çelişki
            </span>
          )}
        </span>
      </td>

      <td className="px-3 py-2.5 text-xs text-muted-foreground">
        {campaignRouteLabel(promo)}
      </td>

      <td className="px-3 py-2.5 text-xs tabular-nums text-muted-foreground">
        <span className="flex items-center gap-1">
          {promo.sale_range_tr}
          {inferredYear && (
            <CircleAlert
              className="size-3 shrink-0 text-warning"
              aria-label="Yıl kaynakta yazmıyordu, çıkarıldı"
            />
          )}
        </span>
      </td>

      <td className="px-3 py-2.5 text-xs tabular-nums text-muted-foreground">
        {promo.travel_range_tr}
      </td>

      <td className="px-3 py-2.5 text-right font-semibold tabular-nums">
        {promo.discount_pct !== null ? `%${promo.discount_pct}` : "—"}
      </td>

      <td className="px-3 py-2.5">
        <CampaignStatusPill status={promo.status} />
      </td>

      <td className="px-3 py-2.5">
        <ConfidencePill band={promo.confidence_band} score={promo.confidence_score} />
      </td>

      <td className="px-3 py-2.5 text-xs">
        <a
          href={promo.url}
          target="_blank"
          rel="noopener noreferrer"
          onClick={(event) => event.stopPropagation()}
          className="inline-flex items-center gap-1 text-muted-foreground hover:text-primary"
        >
          <span className="max-w-[9rem] truncate">{promo.source_name}</span>
          <ExternalLink className="size-3 shrink-0" aria-hidden />
        </a>
        {promo.source_count > 1 && (
          <span
            title={`${promo.source_count} kaynak bu kampanyayı doğruladı`}
            className="ml-1 rounded-full bg-muted px-1.5 text-[10px] font-semibold tabular-nums text-muted-foreground"
          >
            ×{promo.source_count}
          </span>
        )}
      </td>
    </tr>
  );
}
