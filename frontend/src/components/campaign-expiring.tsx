"use client";

import { Timer } from "lucide-react";

import { AirlineLogo } from "@/components/airline-logo";
import {
  campaignAmountLabel,
  campaignRouteLabel,
  remainingDaysLabel,
} from "@/lib/campaigns";
import type { PromotionOut } from "@/lib/types";
import { cn } from "@/lib/utils";

/** How many rows the band shows before it stops. Past this it stops being a
 * band and becomes a second feed. */
const LIMIT = 6;

/** BİTMEK ÜZERE -- the campaigns whose booking window closes this week.
 *
 * Fed by `GET /promotions/expiring?days=7`, and the reason that endpoint
 * exists rather than a client-side `sale_ends <= today + 7`: a campaign in
 * BOOKING_CLOSED_TRAVEL_ACTIVE also has a `sale_ends` in the recent past and
 * would sail straight through the naive filter. "Bitmek üzere" printed over a
 * campaign that already stopped selling is not a smaller error than showing an
 * expired one -- it is the same error with a countdown on it. The endpoint
 * gates on ACTIVE_BOOKING first, so every row here is genuinely still buyable.
 *
 * The whole section disappears when nothing is closing. An urgency band that
 * is empty most days trains a reader to stop looking at it.
 *
 * One row is one sentence: TK · IST-LHR · %20 · 2 gün kaldı.
 */
export function CampaignExpiring({
  rows,
  today,
  onSelect,
}: {
  rows: readonly PromotionOut[];
  /** "YYYY-MM-DD". Passed in rather than read here so the countdown cannot
   * disagree with the rest of the page about what day it is. */
  today: string;
  onSelect: (promo: PromotionOut) => void;
}) {
  if (rows.length === 0) return null;
  const shown = rows.slice(0, LIMIT);

  return (
    <section aria-label="Bitmek üzere olan kampanyalar" className="flex flex-col gap-2">
      <h2 className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
        <Timer className="size-3.5 text-warning" aria-hidden />
        Bitmek üzere
        <span className="rounded-full bg-muted px-1.5 py-px text-[10px] tabular-nums">
          {rows.length}
        </span>
      </h2>

      <ul className="divide-y divide-border overflow-hidden rounded-lg border border-warning/30 bg-card">
        {shown.map((promo) => {
          const route = campaignRouteLabel(promo);
          const amount = campaignAmountLabel(promo);
          const left = promo.sale_ends ? remainingDaysLabel(promo.sale_ends, today) : null;
          return (
            <li key={promo.id}>
              <button
                type="button"
                onClick={() => onSelect(promo)}
                className="group flex w-full items-center gap-2 px-3 py-1.5 text-left transition-colors hover:bg-accent/50 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring"
              >
                <AirlineLogo
                  code={promo.airline_code}
                  name={promo.airline_name}
                  className="size-4 shrink-0"
                />
                <span className="w-7 shrink-0 text-[11px] font-semibold tabular-nums">
                  {promo.airline_code}
                </span>
                <span
                  className={cn(
                    "min-w-0 max-w-[55%] shrink truncate text-[11px] font-medium sm:max-w-[14rem]",
                    route === "—" ? "text-muted-foreground" : "text-foreground/80",
                  )}
                >
                  {route === "—" ? "Rota belirtilmedi" : route}
                </span>
                {/* The owner's line is "TK · IST-LHR · %20 · 2 gün kaldı". The
                    campaign's own name is the part that goes when there is no
                    room for it: on a phone the deadline and the rate are what
                    the band is for, and the name is one tap away. */}
                <span className="hidden min-w-0 flex-1 truncate text-[11px] text-muted-foreground group-hover:text-foreground sm:block">
                  {promo.title_tr}
                </span>
                <span className="ml-auto flex shrink-0 items-center gap-2">
                  {amount && (
                    <span className="text-xs font-semibold tabular-nums">{amount}</span>
                  )}
                  {left && (
                    <span className="whitespace-nowrap rounded-full border border-warning/40 bg-warning/10 px-1.5 py-px text-[10px] font-semibold tabular-nums text-warning">
                      {left}
                    </span>
                  )}
                </span>
              </button>
            </li>
          );
        })}
      </ul>

      {rows.length > shown.length && (
        <p className="text-[10px] text-muted-foreground">
          {rows.length - shown.length} kampanya daha bu hafta kapanıyor; hepsi aşağıdaki
          akışta.
        </p>
      )}
    </section>
  );
}
