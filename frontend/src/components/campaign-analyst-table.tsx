"use client";

import {
  BadgeCheck,
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
import { DenseTable, DenseTd, DenseTh } from "@/components/ui/dense-table";
import {
  campaignRouteLabel,
  campaignStatusStyle,
  confidenceBandLabel,
} from "@/lib/campaigns";
import {
  CAMPAIGN_KIND_LABELS_TR,
  CAMPAIGN_TYPE_LABELS_TR,
  type CampaignKind,
  type CampaignStatus,
  type CampaignType,
} from "@/lib/taxonomy.gen";
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
        "inline-flex w-fit shrink-0 items-center gap-1 whitespace-nowrap rounded-full border px-1.5 py-0.5 text-[10px] font-medium",
        style.className,
      )}
    >
      <Icon className="size-2.5" aria-hidden />
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
    <span className="inline-flex items-center gap-1 whitespace-nowrap">
      <span
        className={cn(
          "rounded-full border px-1.5 py-px text-[10px] font-medium",
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
        <span className="text-[10px] tabular-nums text-muted-foreground">
          {score.toFixed(2)}
        </span>
      )}
    </span>
  );
}

/** Fixed column widths, because `table-fixed` is what stops the two date
 * columns -- the only ones that may not wrap -- from squeezing the campaign
 * title into a four-line column. The table scrolls horizontally below 70rem
 * rather than reflowing: an analyst's table that rewraps at every breakpoint
 * cannot be scanned down a column, which is the entire reason it exists. */
const HEADERS: { label: string; numeric?: boolean; width: string }[] = [
  { label: "Havayolu", width: "w-[4rem]" },
  { label: "Kampanya", width: "w-[14.5rem]" },
  { label: "Rota", width: "w-[7rem]" },
  // The two date columns WRAP but never truncate. The backend's own strings
  // run to "15 Ekim 2024 - 31 Ağustos 2026" and
  // "24 Ağustos 2026 — bitiş belirtilmedi", so a no-wrap column wide enough
  // for the worst case would be 15rem each and would eat the campaign title.
  // A second line costs one row of height; a clipped sale window costs the
  // reader the answer.
  { label: "Satış dönemi", width: "w-[10rem]" },
  { label: "Seyahat dönemi", width: "w-[10rem]" },
  { label: "İndirim", numeric: true, width: "w-[3.5rem]" },
  { label: "Durum", width: "w-[8rem]" },
  // Wide enough for "Değerlendirilmedi" -- the band of the rows nobody ever
  // scored, which is a sentence about our pipeline and must not be truncated
  // into a different word.
  { label: "Güven", width: "w-[7rem]" },
  { label: "Kaynak", width: "w-[6rem]" },
];

/** The analyst table: one row per campaign, nine columns, no chart.
 *
 * This is the view the feed cannot be. The feed answers "what is happening and
 * when", one campaign at a time; a desk comparing eleven carriers on discount
 * depth, route scope and confidence needs the values side by side and sortable
 * by eye. The two are a toggle rather than a stack, because they answer the
 * same question from opposite ends and showing both at once halves each.
 *
 * v2 moved it onto `ui/dense-table.tsx` -- the 28px row the executive board
 * already uses -- so a screen holds about a third more rows without changing
 * a single value on it. The two date columns stay SEPARATE and adjacent, in
 * that order, for the same reason the feed row draws two tracks (§11).
 *
 * Every cell can be empty, and an empty cell says "—" rather than rendering
 * blank: on a table an unexplained gap reads as a rendering bug, not as a fact
 * about the source.
 *
 * There is no "show archive" toggle here and there is deliberately not going
 * to be one. EXPIRED campaigns are hidden by the API in v2, and an opt-in that
 * put them back in one view would make "the page never shows an expired
 * campaign" a claim with an asterisk. The CSV/JSON export is the audit path.
 */
export function CampaignAnalystTable({
  rows,
  onSelect,
}: {
  rows: readonly PromotionOut[];
  onSelect: (promo: PromotionOut) => void;
}) {
  return (
    <Card size="sm" className="p-0">
      <div className="overflow-x-auto">
        <DenseTable className="min-w-[70rem] table-fixed">
          <thead>
            <tr className="border-b border-border">
              {HEADERS.map((header) => (
                <DenseTh key={header.label} numeric={header.numeric} className={header.width}>
                  {header.label}
                </DenseTh>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border/60">
            {rows.map((promo) => (
              <Row key={promo.id} promo={promo} onSelect={onSelect} />
            ))}
          </tbody>
        </DenseTable>
      </div>
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
    : promo.campaign_kind
      ? CAMPAIGN_KIND_LABELS_TR[promo.campaign_kind as CampaignKind]
      : null;

  return (
    <tr
      onClick={() => onSelect(promo)}
      className="cursor-pointer align-top transition-colors hover:bg-accent/60"
    >
      <DenseTd>
        <span className="flex items-center gap-1.5">
          <AirlineLogo code={promo.airline_code} name={promo.airline_name} className="size-4" />
          <span className="text-[11px] font-semibold tabular-nums">{promo.airline_code}</span>
        </span>
      </DenseTd>

      <DenseTd>
        {/* The row is clickable, but the button is what a keyboard and a screen
            reader can actually reach -- a clickable <tr> alone is a mouse-only
            control. */}
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            onSelect(promo);
          }}
          className="rounded text-left text-xs font-medium leading-snug hover:text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
        >
          {promo.title_tr}
        </button>
        <span className="mt-0.5 flex flex-wrap items-center gap-1 text-[10px] text-muted-foreground">
          <span>{typeLabel ?? "Sınıflandırılmadı"}</span>
          {promo.official_source_verified && (
            <BadgeCheck
              className="size-3 text-good"
              aria-label="Resmî kaynak doğrulandı"
            />
          )}
          {promo.review_required === true && (
            <span
              title="Güven eşiğinin altında: insan incelemesi bekliyor"
              className="inline-flex items-center gap-0.5 rounded-full border border-warning/40 bg-warning/10 px-1 text-warning"
            >
              <Flag className="size-2.5" aria-hidden />
              İnceleme
            </span>
          )}
          {promo.conflict_detected === true && (
            <span
              title="İki kaynak bir alanda çelişti; daha resmî olan kazandı"
              className="inline-flex items-center gap-0.5 rounded-full border border-critical/40 bg-critical/10 px-1 text-critical"
            >
              <Split className="size-2.5" aria-hidden />
              Çelişki
            </span>
          )}
        </span>
      </DenseTd>

      <DenseTd className="text-muted-foreground">
        {/* Truncated with the full text on hover: "Bölgesel: Orta Doğu, Asya,
            Afrika, Kuzey Amerika" is five wrapped lines in a 9rem column, and
            five lines of scope wording is not worth five rows of height. */}
        <span className="block truncate" title={campaignRouteLabel(promo)}>
          {campaignRouteLabel(promo)}
        </span>
      </DenseTd>

      <DenseTd className="tabular-nums text-muted-foreground">
        <span className="flex items-start gap-1">
          <span className="min-w-0">{promo.sale_range_tr}</span>
          {inferredYear && (
            <CircleAlert
              className="mt-0.5 size-3 shrink-0 text-warning"
              aria-label="Yıl kaynakta yazmıyordu, çıkarıldı"
            />
          )}
        </span>
      </DenseTd>

      <DenseTd className="tabular-nums text-muted-foreground">
        {promo.travel_range_tr}
      </DenseTd>

      <DenseTd numeric className="font-semibold">
        {promo.discount_pct !== null ? `%${promo.discount_pct}` : "—"}
      </DenseTd>

      <DenseTd>
        <CampaignStatusPill status={promo.status} />
      </DenseTd>

      <DenseTd className="overflow-hidden px-2">
        <ConfidencePill band={promo.confidence_band} score={promo.confidence_score} />
      </DenseTd>

      <DenseTd className="overflow-hidden">
        <a
          href={promo.url}
          target="_blank"
          rel="noopener noreferrer"
          onClick={(event) => event.stopPropagation()}
          className="flex items-center gap-1 rounded text-muted-foreground hover:text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
        >
          <span className="min-w-0 truncate">{promo.source_name}</span>
          <ExternalLink className="size-2.5 shrink-0" aria-hidden />
        </a>
        {promo.source_count > 1 && (
          <span
            title={`${promo.source_count} kaynak bu kampanyayı doğruladı`}
            className="ml-1 rounded-full bg-muted px-1 text-[10px] font-semibold tabular-nums text-muted-foreground"
          >
            ×{promo.source_count}
          </span>
        )}
      </DenseTd>
    </tr>
  );
}
