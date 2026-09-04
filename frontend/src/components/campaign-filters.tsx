"use client";

import { SlidersHorizontal } from "lucide-react";
import { useMemo, useState } from "react";

import { AirlineLogo } from "@/components/airline-logo";
import { Collapse } from "@/components/ui/collapse";
import { FilterChip, FilterChipGroup } from "@/components/ui/filter-chip";
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

/** One labelled filter axis.
 *
 * A thin wrapper over `FilterChipGroup` rather than a div and a span: the
 * `role="group"` + `aria-labelledby` pairing is what tells a screen reader
 * that these eleven chips are the REGION axis. This panel stacks up to nine
 * such rows, and without the pairing they read as nine undifferentiated lists
 * of nouns -- with nine buttons in them all called "Tümü". */
function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <FilterChipGroup label={label} className="gap-1" labelClassName="w-[5.5rem]">
      {children}
    </FilterChipGroup>
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

  /** `allLabel` is passed in, never built from `label`. Gluing "leri" onto
   * "satış dönemi" produces "Tüm satış dönemileri" -- the "i" of "dönemi" is a
   * possessive suffix, not part of the stem -- and because this string is only
   * ever spoken by a screen reader, nobody looking at the page could see it.
   * The other eight rows on this panel spell their name out; so do these. */
  const periodRow = (
    key: "salePeriod" | "travelPeriod",
    label: string,
    allLabel: string,
  ) => (
    <Row label={label}>
      <FilterChip active={!filters[key]} onClick={() => clear(key)} label={allLabel}>
        Tümü
      </FilterChip>
      {CAMPAIGN_PERIODS.map((period) => (
        <FilterChip
          key={period}
          active={filters[key] === period}
          onClick={() => toggle(key, period as CampaignPeriod)}
        >
          {CAMPAIGN_PERIOD_LABELS_TR[period]}
        </FilterChip>
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
          <FilterChip
            active={!filters.airline}
            onClick={() => clear("airline")}
            label="Tüm taşıyıcılar"
          >
            Tümü
          </FilterChip>
          {carriers.map((carrier) => (
            <FilterChip
              key={carrier.code}
              active={filters.airline === carrier.code}
              onClick={() => toggle("airline", carrier.code)}
              title={carrier.name}
            >
              <AirlineLogo code={carrier.code} name={carrier.name} className="size-3" />
              {carrier.code}
              <span className="tabular-nums opacity-70">{counts.airline[carrier.code]}</span>
            </FilterChip>
          ))}
        </Row>
      )}

      {kinds.length > 0 && (
        <Row label="Tür">
          <FilterChip
            active={!filters.campaignKind}
            onClick={() => clear("campaignKind")}
            label="Tüm kampanya türleri"
          >
            Tümü
          </FilterChip>
          {kinds.map((kind) => (
            <FilterChip
              key={kind}
              active={filters.campaignKind === kind}
              onClick={() => toggle("campaignKind", kind)}
            >
              {CAMPAIGN_KIND_LABELS_TR[kind]}
              <span className="tabular-nums opacity-70">{counts.kind[kind]}</span>
            </FilterChip>
          ))}
        </Row>
      )}

      {statuses.length > 0 && (
        <Row label="Durum">
          <FilterChip
            active={!filters.status}
            onClick={() => clear("status")}
            label="Tüm durumlar"
          >
            Tümü
          </FilterChip>
          {statuses.map((status) => (
            <FilterChip
              key={status}
              active={filters.status === status}
              onClick={() => toggle("status", status)}
              title={campaignStatusStyle(status).label}
            >
              {campaignStatusStyle(status).short}
              <span className="tabular-nums opacity-70">{counts.status[status]}</span>
            </FilterChip>
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
              <FilterChip
                active={!filters.country}
                onClick={() => clear("country")}
                label="Tüm ülkeler"
              >
                Tümü
              </FilterChip>
              {countries.map((country) => (
                <FilterChip
                  key={country}
                  active={filters.country === country}
                  onClick={() => toggle("country", country)}
                >
                  {country}
                  <span className="tabular-nums opacity-70">{counts.country[country]}</span>
                </FilterChip>
              ))}
            </Row>
          )}

          {regions.length > 0 && (
            <Row label="Bölge">
              <FilterChip
                active={!filters.region}
                onClick={() => clear("region")}
                label="Tüm bölgeler"
              >
                Tümü
              </FilterChip>
              {regions.map((region) => (
                <FilterChip
                  key={region.slug}
                  active={filters.region === region.slug}
                  onClick={() => toggle("region", region.slug)}
                >
                  {region.name}
                  <span className="tabular-nums opacity-70">{counts.region[region.slug]}</span>
                </FilterChip>
              ))}
            </Row>
          )}

          {scopes.length > 0 && (
            <Row label="Rota">
              <FilterChip
                active={!filters.routeScope}
                onClick={() => clear("routeScope")}
                label="Tüm rota kapsamları"
              >
                Tümü
              </FilterChip>
              {scopes.map((scope) => (
                <FilterChip
                  key={scope}
                  active={filters.routeScope === scope}
                  onClick={() => toggle("routeScope", scope)}
                >
                  {ROUTE_SCOPE_LABELS_TR[scope]}
                  <span className="tabular-nums opacity-70">{counts.scope[scope]}</span>
                </FilterChip>
              ))}
            </Row>
          )}

          {types.length > 0 && (
            <Row label="Kampanya türü">
              <FilterChip
                active={!filters.campaignType}
                onClick={() => clear("campaignType")}
                label="Tüm kampanya tipleri"
              >
                Tümü
              </FilterChip>
              {types.map((type) => (
                <FilterChip
                  key={type}
                  active={filters.campaignType === type}
                  onClick={() => toggle("campaignType", type)}
                >
                  {CAMPAIGN_TYPE_LABELS_TR[type as CampaignType]}
                  <span className="tabular-nums opacity-70">{counts.type[type]}</span>
                </FilterChip>
              ))}
            </Row>
          )}

          {periodRow("salePeriod", "Satış dönemi", "Tüm satış dönemleri")}
          {periodRow("travelPeriod", "Seyahat dönemi", "Tüm seyahat dönemleri")}

          {(bands.length > 0 || counts.review > 0) && (
            <Row label="Güven">
              <FilterChip
                active={!filters.band}
                onClick={() => clear("band")}
                label="Tüm güven bantları"
              >
                Tümü
              </FilterChip>
              {bands.map((band) => (
                <FilterChip
                  key={band}
                  active={filters.band === band}
                  onClick={() => toggle("band", band)}
                >
                  {confidenceBandLabel(band)}
                  <span className="tabular-nums opacity-70">{counts.band[band]}</span>
                </FilterChip>
              ))}
              {counts.review > 0 && (
                <FilterChip
                  active={filters.reviewOnly}
                  onClick={() => onChange({ ...filters, reviewOnly: !filters.reviewOnly })}
                  title="Güven eşiğinin altında kalan, insan incelemesi bekleyen kayıtlar"
                  // Unlit, this chip is amber rather than the row's neutral
                  // grey: it is the only chip here that names a data-quality
                  // problem, and it has to be findable before it is pressed.
                  className={cn(!filters.reviewOnly && "border-warning/40 text-warning")}
                >
                  İnceleme gerekli
                  <span className="tabular-nums opacity-70">{counts.review}</span>
                </FilterChip>
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
