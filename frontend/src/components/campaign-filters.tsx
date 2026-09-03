"use client";

import { SlidersHorizontal } from "lucide-react";
import { useMemo, useState } from "react";

import { AirlineLogo } from "@/components/airline-logo";
import { Collapse } from "@/components/ui/collapse";
import {
  CAMPAIGN_PERIOD_LABELS_TR,
  CAMPAIGN_PERIODS,
  campaignFacetCounts,
  campaignStatusStyle,
  confidenceBandLabel,
  EMPTY_CAMPAIGN_FILTERS,
  hasActiveCampaignFilter,
  reviewRequiredCount,
  SELECTABLE_CAMPAIGN_STATUSES,
  type CampaignFilters,
  type CampaignPeriod,
} from "@/lib/campaigns";
import { airlineTabs, worldRegions } from "@/lib/nav";
import {
  CAMPAIGN_KIND_LABELS_TR,
  CAMPAIGN_KINDS,
  CAMPAIGN_TYPE_LABELS_TR,
  CAMPAIGN_TYPES,
  ROUTE_SCOPE_LABELS_TR,
  ROUTE_SCOPES,
  type CampaignType,
} from "@/lib/taxonomy.gen";
import type { PromotionOut } from "@/lib/types";
import { cn } from "@/lib/utils";

/** The lit-chip pattern shared with Gazete / Öneriler / Risk Radarı. No new
 * token, no new hue: the chrome stays neutral so the only saturated things on
 * this page are the status pills that earn it. */
const chip = (active: boolean) =>
  cn(
    "flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
    active
      ? "bg-primary/12 text-primary ring-1 ring-primary/40"
      : "border border-border text-muted-foreground hover:bg-accent",
  );

/** Which dimensions live in the collapsed panel. Seven filter rows on screen
 * at once is a control surface, not a page: the owner's brief asks for three
 * or four visible and the rest behind "Daha fazla filtre".
 *
 * The three that stay out are the three a desk reaches for first -- WHO ran
 * it, WHAT KIND of offer it is, and WHERE IT IS IN TIME. Country, region,
 * route scope, campaign type, the two period windows and the confidence
 * controls are all narrowing tools, used after a reader already knows roughly
 * what they are looking at. */
const EXTENDED_KEYS = [
  "country",
  "region",
  "routeScope",
  "campaignType",
  "salePeriod",
  "travelPeriod",
  "band",
  "reviewOnly",
] as const;

function extendedCount(filters: CampaignFilters): number {
  return EXTENDED_KEYS.filter((key) =>
    key === "reviewOnly" ? filters.reviewOnly : filters[key] !== null,
  ).length;
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-1">
      <span className="w-[5.5rem] shrink-0 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        {label}
      </span>
      {children}
    </div>
  );
}

/** The whole filter surface: three rows on screen, the rest one click away.
 *
 * Counts on every chip are computed against every OTHER active filter, so the
 * number a chip carries is what clicking it would actually leave. A chip that
 * would leave nothing is not rendered at all -- an always-complete list of
 * eleven carriers with nine of them reading 0 is a list of dead ends.
 */
export function CampaignFilterBar({
  promotions,
  filters,
  today,
  onChange,
  children,
}: {
  /** The UNFILTERED set. Facet counts have to be computed against it. */
  promotions: readonly PromotionOut[];
  filters: CampaignFilters;
  today: string;
  onChange: (next: CampaignFilters) => void;
  /** The view toggle and the export links, pushed to the right of the header
   * row by the caller so this component owns filters and nothing else. */
  children?: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);

  const counts = useMemo(
    () => ({
      airline: campaignFacetCounts(promotions, filters, "airline", today),
      kind: campaignFacetCounts(promotions, filters, "campaignKind", today),
      type: campaignFacetCounts(promotions, filters, "campaignType", today),
      status: campaignFacetCounts(promotions, filters, "status", today),
      region: campaignFacetCounts(promotions, filters, "region", today),
      country: campaignFacetCounts(promotions, filters, "country", today),
      scope: campaignFacetCounts(promotions, filters, "routeScope", today),
      band: campaignFacetCounts(promotions, filters, "band", today),
      review: reviewRequiredCount(promotions, filters, today),
    }),
    [promotions, filters, today],
  );

  /** Single-select: clicking the lit chip clears it. */
  const toggle = <K extends keyof CampaignFilters>(key: K, value: CampaignFilters[K]) =>
    onChange({
      ...filters,
      [key]: filters[key] === value ? EMPTY_CAMPAIGN_FILTERS[key] : value,
    });
  const clear = <K extends keyof CampaignFilters>(key: K) =>
    onChange({ ...filters, [key]: EMPTY_CAMPAIGN_FILTERS[key] });

  const carriers = airlineTabs.filter((a) => (counts.airline[a.code] ?? 0) > 0);
  const kinds = CAMPAIGN_KINDS.filter((k) => (counts.kind[k] ?? 0) > 0);
  const statuses = SELECTABLE_CAMPAIGN_STATUSES.filter((s) => (counts.status[s] ?? 0) > 0);
  const types = CAMPAIGN_TYPES.filter((t) => (counts.type[t] ?? 0) > 0);
  const regions = worldRegions.filter((r) => (counts.region[r.slug] ?? 0) > 0);
  const scopes = ROUTE_SCOPES.filter((s) => (counts.scope[s] ?? 0) > 0);
  const bands = ["high", "medium"].filter((b) => (counts.band[b] ?? 0) > 0);
  const countries = Object.keys(counts.country).sort((a, b) =>
    a.localeCompare(b, "tr"),
  );

  const extended = extendedCount(filters);

  const periodRow = (
    key: "salePeriod" | "travelPeriod",
    label: string,
  ) => (
    <Row label={label}>
      <button type="button" onClick={() => clear(key)} className={chip(!filters[key])}>
        Tümü
      </button>
      {CAMPAIGN_PERIODS.map((period) => (
        <button
          key={period}
          type="button"
          onClick={() => toggle(key, period as CampaignPeriod)}
          className={chip(filters[key] === period)}
        >
          {CAMPAIGN_PERIOD_LABELS_TR[period]}
        </button>
      ))}
    </Row>
  );

  return (
    <div className="flex flex-col gap-1.5 rounded-lg border border-border bg-card/40 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <SlidersHorizontal className="size-3.5 text-muted-foreground" aria-hidden />
        <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          Filtreler
        </span>
        {hasActiveCampaignFilter(filters) && (
          <button
            type="button"
            onClick={() => onChange(EMPTY_CAMPAIGN_FILTERS)}
            className="rounded text-[11px] font-medium text-primary hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          >
            Filtreleri temizle
          </button>
        )}
        {children && <div className="ml-auto flex items-center gap-1.5">{children}</div>}
      </div>

      {carriers.length > 0 && (
        <Row label="Taşıyıcı">
          <button
            type="button"
            onClick={() => clear("airline")}
            className={chip(!filters.airline)}
          >
            Tümü
          </button>
          {carriers.map((carrier) => (
            <button
              key={carrier.code}
              type="button"
              title={carrier.name}
              onClick={() => toggle("airline", carrier.code)}
              className={chip(filters.airline === carrier.code)}
            >
              <AirlineLogo code={carrier.code} name={carrier.name} className="size-3" />
              {carrier.code}
              <span className="tabular-nums opacity-70">{counts.airline[carrier.code]}</span>
            </button>
          ))}
        </Row>
      )}

      {kinds.length > 0 && (
        <Row label="Tür">
          <button
            type="button"
            onClick={() => clear("campaignKind")}
            className={chip(!filters.campaignKind)}
          >
            Tümü
          </button>
          {kinds.map((kind) => (
            <button
              key={kind}
              type="button"
              onClick={() => toggle("campaignKind", kind)}
              className={chip(filters.campaignKind === kind)}
            >
              {CAMPAIGN_KIND_LABELS_TR[kind]}
              <span className="tabular-nums opacity-70">{counts.kind[kind]}</span>
            </button>
          ))}
        </Row>
      )}

      {statuses.length > 0 && (
        <Row label="Durum">
          <button
            type="button"
            onClick={() => clear("status")}
            className={chip(!filters.status)}
          >
            Tümü
          </button>
          {statuses.map((status) => (
            <button
              key={status}
              type="button"
              title={campaignStatusStyle(status).label}
              onClick={() => toggle("status", status)}
              className={chip(filters.status === status)}
            >
              {campaignStatusStyle(status).short}
              <span className="tabular-nums opacity-70">{counts.status[status]}</span>
            </button>
          ))}
        </Row>
      )}

      <div className="flex flex-wrap items-center gap-2 pt-0.5">
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          className="rounded text-[11px] font-medium text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
        >
          {open ? "Daha az filtre" : "Daha fazla filtre"}
          {extended > 0 && (
            <span className="ml-1 rounded-full bg-primary/12 px-1.5 py-px text-[10px] font-semibold tabular-nums text-primary">
              {extended}
            </span>
          )}
        </button>
      </div>

      <Collapse open={open}>
        <div className="flex flex-col gap-1.5 border-t border-border pt-2">
          {countries.length > 0 && (
            <Row label="Ülke">
              <button
                type="button"
                onClick={() => clear("country")}
                className={chip(!filters.country)}
              >
                Tümü
              </button>
              {countries.map((country) => (
                <button
                  key={country}
                  type="button"
                  onClick={() => toggle("country", country)}
                  className={chip(filters.country === country)}
                >
                  {country}
                  <span className="tabular-nums opacity-70">{counts.country[country]}</span>
                </button>
              ))}
            </Row>
          )}

          {regions.length > 0 && (
            <Row label="Bölge">
              <button
                type="button"
                onClick={() => clear("region")}
                className={chip(!filters.region)}
              >
                Tümü
              </button>
              {regions.map((region) => (
                <button
                  key={region.slug}
                  type="button"
                  onClick={() => toggle("region", region.slug)}
                  className={chip(filters.region === region.slug)}
                >
                  {region.name}
                  <span className="tabular-nums opacity-70">{counts.region[region.slug]}</span>
                </button>
              ))}
            </Row>
          )}

          {scopes.length > 0 && (
            <Row label="Rota">
              <button
                type="button"
                onClick={() => clear("routeScope")}
                className={chip(!filters.routeScope)}
              >
                Tümü
              </button>
              {scopes.map((scope) => (
                <button
                  key={scope}
                  type="button"
                  onClick={() => toggle("routeScope", scope)}
                  className={chip(filters.routeScope === scope)}
                >
                  {ROUTE_SCOPE_LABELS_TR[scope]}
                  <span className="tabular-nums opacity-70">{counts.scope[scope]}</span>
                </button>
              ))}
            </Row>
          )}

          {types.length > 0 && (
            <Row label="Kampanya türü">
              <button
                type="button"
                onClick={() => clear("campaignType")}
                className={chip(!filters.campaignType)}
              >
                Tümü
              </button>
              {types.map((type) => (
                <button
                  key={type}
                  type="button"
                  onClick={() => toggle("campaignType", type)}
                  className={chip(filters.campaignType === type)}
                >
                  {CAMPAIGN_TYPE_LABELS_TR[type as CampaignType]}
                  <span className="tabular-nums opacity-70">{counts.type[type]}</span>
                </button>
              ))}
            </Row>
          )}

          {periodRow("salePeriod", "Satış dönemi")}
          {periodRow("travelPeriod", "Seyahat dönemi")}

          {(bands.length > 0 || counts.review > 0) && (
            <Row label="Güven">
              <button
                type="button"
                onClick={() => clear("band")}
                className={chip(!filters.band)}
              >
                Tümü
              </button>
              {bands.map((band) => (
                <button
                  key={band}
                  type="button"
                  onClick={() => toggle("band", band)}
                  className={chip(filters.band === band)}
                >
                  {confidenceBandLabel(band)}
                  <span className="tabular-nums opacity-70">{counts.band[band]}</span>
                </button>
              ))}
              {counts.review > 0 && (
                <button
                  type="button"
                  aria-pressed={filters.reviewOnly}
                  onClick={() => onChange({ ...filters, reviewOnly: !filters.reviewOnly })}
                  title="Güven eşiğinin altında kalan, insan incelemesi bekleyen kayıtlar"
                  className={cn(
                    chip(filters.reviewOnly),
                    !filters.reviewOnly && "border-warning/40 text-warning",
                  )}
                >
                  İnceleme gerekli
                  <span className="tabular-nums opacity-70">{counts.review}</span>
                </button>
              )}
            </Row>
          )}

          <p className="pt-1 text-[10px] leading-relaxed text-muted-foreground">
            Satış ve seyahat dönemi filtreleri, kaynağın <em>yayımladığı</em> pencereye
            bakar. Hiç tarih açıklanmamış kampanyalar bu iki filtreyle eşleşmez; onlar
            sayfanın altındaki &quot;Tarih belirtilmemiş&quot; grubunda durur.
          </p>
        </div>
      </Collapse>
    </div>
  );
}
