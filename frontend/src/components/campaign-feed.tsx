"use client";

import { BadgeCheck, ChevronDown } from "lucide-react";
import { useState } from "react";

import { AirlineLogo } from "@/components/airline-logo";
import { CampaignStatusPill } from "@/components/campaign-analyst-table";
import { CampaignWindows } from "@/components/campaign-windows";
import { Collapse } from "@/components/ui/collapse";
import {
  campaignAmountLabel,
  campaignRouteLabel,
  relativeTimeTr,
} from "@/lib/campaigns";
import {
  CAMPAIGN_KIND_LABELS_TR,
  CAMPAIGN_TYPE_LABELS_TR,
  type CampaignKind,
  type CampaignType,
} from "@/lib/taxonomy.gen";
import type { PromotionOut } from "@/lib/types";
import { cn } from "@/lib/utils";

/** "Son 48 saatte ilk kez görüldü", as three letters. The window itself comes
 * from the API (`/promotions/new-count`), never from a number retyped here. */
export function NewCampaignPill() {
  return (
    <span className="rounded-full bg-signal px-1.5 py-px text-[9px] font-bold uppercase leading-4 tracking-wide text-white">
      Yeni
    </span>
  );
}

/** The carrier is on the record for this campaign -- it has a source row at
 * tier `official`.
 *
 * Rendered only when true, and only in the feed: a "no official source" mark
 * on two rows out of three is noise, not information. The drawer states both
 * sides, because that is where a reader has come to ask. */
export function OfficialSourceMark({ className }: { className?: string }) {
  return (
    <BadgeCheck
      className={cn("size-3.5 shrink-0 text-good", className)}
      aria-label="Resmî kaynak doğrulandı"
    />
  );
}

function typeLine(promo: PromotionOut): string | null {
  const kind = promo.campaign_kind
    ? CAMPAIGN_KIND_LABELS_TR[promo.campaign_kind as CampaignKind]
    : null;
  const type = promo.campaign_type
    ? (CAMPAIGN_TYPE_LABELS_TR[promo.campaign_type as CampaignType] ??
      promo.campaign_type)
    : null;
  return type ?? kind;
}

/** One campaign in the feed: carrier, name, route, the two windows, discount,
 * status. Nothing else.
 *
 * Deliberately a ROW inside a shared bordered list rather than a card of its
 * own. Twelve cards is twelve borders, twelve shadows and twelve gaps of
 * whitespace for twelve facts, and the owner's brief for this page is density
 * without clutter; a divided list carries the same content in about half the
 * vertical space and gives the eye one left edge to run down instead of
 * twelve.
 */
export function CampaignFeedRow({
  promo,
  isNew,
  onSelect,
}: {
  promo: PromotionOut;
  isNew: boolean;
  onSelect: () => void;
}) {
  const amount = campaignAmountLabel(promo);
  const route = campaignRouteLabel(promo);
  const type = typeLine(promo);

  return (
    <button
      type="button"
      onClick={onSelect}
      className="group grid w-full grid-cols-[auto_1fr] items-start gap-x-3 gap-y-2 px-3 py-3 text-left transition-colors hover:bg-accent/50 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring sm:grid-cols-[auto_1fr_auto]"
    >
      <AirlineLogo
        code={promo.airline_code}
        name={promo.airline_name}
        className="mt-0.5 size-6 shrink-0"
      />

      <span className="flex min-w-0 flex-col gap-1.5">
        <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
          <span className="text-[11px] font-semibold tabular-nums text-muted-foreground">
            {promo.airline_code}
          </span>
          <span className="min-w-0 text-sm font-medium leading-snug text-foreground group-hover:text-primary">
            {promo.title_tr}
          </span>
          {isNew && <NewCampaignPill />}
          {promo.official_source_verified && <OfficialSourceMark />}
        </span>

        <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-muted-foreground">
          {route !== "—" && <span className="font-medium text-foreground/70">{route}</span>}
          {type && (
            <>
              {route !== "—" && <span aria-hidden>·</span>}
              <span>{type}</span>
            </>
          )}
          <span aria-hidden>·</span>
          <span className="truncate">{promo.source_name}</span>
          <span aria-hidden>·</span>
          <span className="tabular-nums">{relativeTimeTr(promo.detected_at)}</span>
        </span>

        <CampaignWindows promo={promo} className="max-w-md" />
      </span>

      <span className="col-start-2 flex items-center gap-2 sm:col-start-3 sm:flex-col sm:items-end sm:gap-1.5">
        {amount && (
          <span className="text-base font-semibold tabular-nums leading-none">{amount}</span>
        )}
        <CampaignStatusPill status={promo.status} />
      </span>
    </button>
  );
}

/** The feed itself: one bordered surface, rows divided by hairlines. */
export function CampaignFeed({
  rows,
  isNew,
  onSelect,
}: {
  rows: readonly PromotionOut[];
  isNew: (promo: PromotionOut) => boolean;
  onSelect: (promo: PromotionOut) => void;
}) {
  return (
    <div className="divide-y divide-border overflow-hidden rounded-lg border border-border bg-card">
      {rows.map((promo) => (
        <CampaignFeedRow
          key={promo.id}
          promo={promo}
          isNew={isNew(promo)}
          onSelect={() => onSelect(promo)}
        />
      ))}
    </div>
  );
}

/** The undated group: campaigns nobody published a single date for.
 *
 * The owner's call, and the reason the main feed is readable at all. On
 * 2026-09-03 seventy of eighty-three publishable campaigns were UNKNOWN --
 * news-derived detections with no sale window, no travel window and nothing to
 * verify. Interleaved into the feed they buried the thirteen campaigns that
 * DO have a verified window under five times their number of rows that cannot
 * answer "can I still buy this".
 *
 * So they are moved, not dropped, and everything about this section says so:
 * it sits below the feed, it is muted, it names itself and its count in the
 * heading, and it opens closed. A reader who wants them is one click away; a
 * reader who does not is never asked to scroll past them.
 *
 * The rows are one line each -- carrier, title, discount, age. There are no
 * window bars, because there are no windows; drawing empty tracks seventy
 * times would be seventy assertions that we looked and found nothing, which is
 * true but not worth 400 pixels.
 */
export function CampaignUndatedSection({
  rows,
  isNew,
  onSelect,
}: {
  rows: readonly PromotionOut[];
  isNew: (promo: PromotionOut) => boolean;
  onSelect: (promo: PromotionOut) => void;
}) {
  const [open, setOpen] = useState(false);
  if (rows.length === 0) return null;

  return (
    <section aria-label="Tarih belirtilmemiş kampanyalar" className="flex flex-col gap-2">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-fit items-center gap-2 rounded text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
      >
        Tarih belirtilmemiş
        <span className="rounded-full bg-muted px-1.5 py-px text-[10px] tabular-nums">
          {rows.length}
        </span>
        <ChevronDown
          className={cn("size-3.5 transition-transform", open && "rotate-180")}
          aria-hidden
        />
      </button>
      <p className="text-[10px] leading-relaxed text-muted-foreground">
        Kaynak ne satış ne de seyahat dönemi yayımladı. Kampanya gerçek, penceresi
        bilinmiyor — bu yüzden ana akışta değil, burada.
      </p>

      <Collapse open={open}>
        <div className="divide-y divide-border/60 overflow-hidden rounded-lg border border-dashed border-border">
          {rows.map((promo) => (
            <button
              key={promo.id}
              type="button"
              onClick={() => onSelect(promo)}
              className="group flex w-full items-center gap-2 px-3 py-1.5 text-left transition-colors hover:bg-accent/50 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring"
            >
              <AirlineLogo
                code={promo.airline_code}
                name={promo.airline_name}
                className="size-4 shrink-0 opacity-80"
              />
              <span className="w-7 shrink-0 text-[10px] font-semibold tabular-nums text-muted-foreground">
                {promo.airline_code}
              </span>
              <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground group-hover:text-foreground">
                {promo.title_tr}
              </span>
              {isNew(promo) && <NewCampaignPill />}
              {campaignAmountLabel(promo) && (
                <span className="shrink-0 text-[11px] font-semibold tabular-nums text-muted-foreground">
                  {campaignAmountLabel(promo)}
                </span>
              )}
              <span className="hidden w-16 shrink-0 text-right text-[10px] tabular-nums text-muted-foreground sm:block">
                {relativeTimeTr(promo.detected_at)}
              </span>
            </button>
          ))}
        </div>
      </Collapse>
    </section>
  );
}
