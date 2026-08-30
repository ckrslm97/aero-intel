import { describe, expect, it } from "vitest";

import { promotion } from "@/lib/__fixtures__/promotion";
import {
  campaignAmountLabel,
  campaignFacetCounts,
  campaignFieldLabel,
  campaignQueryString,
  campaignRegions,
  campaignRouteLabel,
  campaignStatusStyle,
  confidenceBandLabel,
  EMPTY_CAMPAIGN_FILTERS,
  filterCampaigns,
  formatChangeValue,
  groupDatelessCampaigns,
  hasActiveCampaignFilter,
  isDatelessCampaign,
  relativeTimeTr,
  reviewRequiredCount,
  sourceTierLabel,
} from "@/lib/campaigns";

describe("filterCampaigns", () => {
  const rows = [
    promotion({ id: "1", airline_code: "TK", campaign_type: "FLASH_SALE", status: "ACTIVE_BOOKING", confidence_band: "high", region: "europe" }),
    promotion({ id: "2", airline_code: "PC", campaign_type: "EARLY_BOOKING", status: "EXPIRED", confidence_band: "medium", region: "europe" }),
    promotion({ id: "3", airline_code: "TK", campaign_type: null, status: "UPCOMING", confidence_band: null, region: "asia", review_required: true }),
  ];

  it("returns everything when nothing is selected", () => {
    expect(filterCampaigns(rows, EMPTY_CAMPAIGN_FILTERS)).toHaveLength(3);
    expect(hasActiveCampaignFilter(EMPTY_CAMPAIGN_FILTERS)).toBe(false);
  });

  it("narrows on each dimension", () => {
    const only = (filters: Partial<typeof EMPTY_CAMPAIGN_FILTERS>) =>
      filterCampaigns(rows, { ...EMPTY_CAMPAIGN_FILTERS, ...filters }).map((r) => r.id);

    expect(only({ airline: "TK" })).toEqual(["1", "3"]);
    expect(only({ campaignType: "FLASH_SALE" })).toEqual(["1"]);
    expect(only({ status: "EXPIRED" })).toEqual(["2"]);
    expect(only({ band: "high" })).toEqual(["1"]);
    expect(only({ region: "asia" })).toEqual(["3"]);
    expect(only({ reviewOnly: true })).toEqual(["3"]);
  });

  it("combines dimensions as an intersection", () => {
    const rowsOut = filterCampaigns(rows, {
      ...EMPTY_CAMPAIGN_FILTERS,
      airline: "TK",
      status: "ACTIVE_BOOKING",
    });
    expect(rowsOut.map((r) => r.id)).toEqual(["1"]);
  });

  it("hides an unclassified row behind a type filter rather than calling it OTHER", () => {
    // The legacy row has campaign_type null. Bucketing it as OTHER would put
    // 200 never-classified rows under a label the classifier never assigned.
    const out = filterCampaigns(rows, { ...EMPTY_CAMPAIGN_FILTERS, campaignType: "OTHER" });
    expect(out).toEqual([]);
  });

  it("treats a null review_required as not-flagged", () => {
    // NULL means "never queued", which is not the review queue.
    const out = filterCampaigns([promotion({ review_required: null })], {
      ...EMPTY_CAMPAIGN_FILTERS,
      reviewOnly: true,
    });
    expect(out).toEqual([]);
  });
});

describe("groupDatelessCampaigns", () => {
  /** A start-less campaign detected on `day`, i.e. one point marker. */
  const dateless = (id: string, airline: string, day: string) =>
    promotion({ id, airline_code: airline, sale_starts: null, detected_at: `${day}T09:00:00Z` });

  it("collapses a carrier's 23 same-day announcements into one cluster", () => {
    // The regression itself: Singapore Airlines published 23 route fares on one
    // day with no sale window, and the lane drew 23 diamonds in one column.
    const rows = Array.from({ length: 23 }, (_, i) =>
      dateless(`sq-${i}`, "SQ", "2026-08-29"),
    );

    const { clusters, singles, dated } = groupDatelessCampaigns(rows);

    expect(clusters).toHaveLength(1);
    expect(clusters[0].items).toHaveLength(23);
    expect(clusters[0].airlineCode).toBe("SQ");
    expect(clusters[0].day).toBe("2026-08-29");
    expect(clusters[0].key).toBe("SQ:2026-08-29");
    expect(singles).toEqual([]);
    expect(dated).toEqual([]);
  });

  it("leaves dated campaigns entirely alone", () => {
    const withDates = promotion({ id: "bar", sale_starts: "2026-09-01", sale_ends: "2026-09-30" });
    const openEnded = promotion({ id: "open", sale_starts: "2026-09-01", sale_ends: null });
    const rows = [
      withDates,
      dateless("p1", "TK", "2026-08-29"),
      openEnded,
      dateless("p2", "TK", "2026-08-29"),
    ];

    const { dated, clusters, singles } = groupDatelessCampaigns(rows);

    // A published start is a bar, whatever the end date says.
    expect(dated).toEqual([withDates, openEnded]);
    expect(isDatelessCampaign(openEnded)).toBe(false);
    expect(clusters).toHaveLength(1);
    expect(clusters[0].items.map((p) => p.id)).toEqual(["p1", "p2"]);
    expect(singles).toEqual([]);
  });

  it("keeps two carriers announcing on the same day apart", () => {
    const rows = [
      dateless("tk-1", "TK", "2026-08-29"),
      dateless("sq-1", "SQ", "2026-08-29"),
      dateless("tk-2", "TK", "2026-08-29"),
      dateless("sq-2", "SQ", "2026-08-29"),
    ];

    const { clusters } = groupDatelessCampaigns(rows);

    expect(clusters.map((c) => c.key)).toEqual(["TK:2026-08-29", "SQ:2026-08-29"]);
    expect(clusters.every((c) => c.items.length === 2)).toBe(true);
  });

  it("keeps one carrier's two different days apart", () => {
    const rows = [
      dateless("a", "SQ", "2026-08-29"),
      dateless("b", "SQ", "2026-08-30"),
      dateless("c", "SQ", "2026-08-30"),
    ];

    const { clusters, singles } = groupDatelessCampaigns(rows);

    expect(singles.map((p) => p.id)).toEqual(["a"]);
    expect(clusters).toHaveLength(1);
    expect(clusters[0].day).toBe("2026-08-30");
  });

  it("leaves a lone dateless campaign as a plain point marker", () => {
    // A count chip reading "1" is noise, so a bucket of one is never a cluster.
    const { clusters, singles } = groupDatelessCampaigns([dateless("only", "PC", "2026-08-29")]);
    expect(clusters).toEqual([]);
    expect(singles.map((p) => p.id)).toEqual(["only"]);
  });

  it("does not merge rows whose detection date cannot be read", () => {
    // Two undateable rows are two unknowns, not one campaign seen twice.
    const rows = [
      promotion({ id: "x", airline_code: "TK", sale_starts: null, detected_at: "" }),
      promotion({ id: "y", airline_code: "TK", sale_starts: null, detected_at: "" }),
    ];
    const { clusters, singles } = groupDatelessCampaigns(rows);
    expect(clusters).toEqual([]);
    expect(singles.map((p) => p.id)).toEqual(["x", "y"]);
  });

  it("returns empty buckets for an empty window", () => {
    expect(groupDatelessCampaigns([])).toEqual({ dated: [], singles: [], clusters: [] });
  });
});

describe("campaignAmountLabel", () => {
  it("prefers the published discount rate", () => {
    expect(campaignAmountLabel(promotion({ discount_pct: 40 }))).toBe("%40");
  });

  it("falls back to the starting price with its currency", () => {
    const label = campaignAmountLabel(
      promotion({ discount_pct: null, attrs_json: { price_floor: 899, currency: "TRY" } }),
    );
    expect(label).toBe("899 TRY");
  });

  it("says nothing rather than showing a dash for a campaign with no number", () => {
    expect(campaignAmountLabel(promotion({ discount_pct: null }))).toBeNull();
    expect(
      campaignAmountLabel(promotion({ discount_pct: null, attrs_json: { cabin: "ECONOMY" } })),
    ).toBeNull();
  });
});

describe("campaignRegions", () => {
  it("reads the flat column, the market list and the resolved route", () => {
    expect(campaignRegions(promotion({ region: "europe" }))).toEqual(["europe"]);
    expect(
      campaignRegions(promotion({ region: null, markets: "europe, londra, middle-east" })).sort(),
    ).toEqual(["europe", "middle-east"]);
    expect(
      campaignRegions(
        promotion({ region: null, route_json: { origin: { region: "europe" }, dest: { region: "asia" } } }),
      ).sort(),
    ).toEqual(["asia", "europe"]);
  });

  it("does not mistake a city name for a region slug", () => {
    expect(campaignRegions(promotion({ region: null, markets: "londra, dubai" }))).toEqual([]);
  });
});

describe("campaignFacetCounts", () => {
  const rows = [
    promotion({ id: "1", airline_code: "TK", campaign_type: "FLASH_SALE" }),
    promotion({ id: "2", airline_code: "TK", campaign_type: "EARLY_BOOKING" }),
    promotion({ id: "3", airline_code: "PC", campaign_type: "FLASH_SALE" }),
  ];

  it("counts every value when nothing is filtered", () => {
    expect(campaignFacetCounts(rows, EMPTY_CAMPAIGN_FILTERS, "airline")).toEqual({
      TK: 2,
      PC: 1,
    });
  });

  it("counts a facet against every OTHER filter, not against itself", () => {
    const filters = { ...EMPTY_CAMPAIGN_FILTERS, airline: "TK" as string | null };
    // The type row is narrowed by the carrier...
    expect(campaignFacetCounts(rows, filters, "campaignType")).toEqual({
      FLASH_SALE: 1,
      EARLY_BOOKING: 1,
    });
    // ...but the carrier row still shows what the other carrier would give,
    // or clicking PC would be a click into a chip that reads 0.
    expect(campaignFacetCounts(rows, filters, "airline")).toEqual({ TK: 2, PC: 1 });
  });

  it("gives an unclassified row no chip at all", () => {
    expect(campaignFacetCounts([promotion()], EMPTY_CAMPAIGN_FILTERS, "campaignType")).toEqual({});
  });
});

describe("reviewRequiredCount", () => {
  it("counts flagged rows within the other active filters", () => {
    const rows = [
      promotion({ id: "1", airline_code: "TK", review_required: true }),
      promotion({ id: "2", airline_code: "PC", review_required: true }),
      promotion({ id: "3", airline_code: "TK", review_required: false }),
    ];
    expect(reviewRequiredCount(rows, EMPTY_CAMPAIGN_FILTERS)).toBe(2);
    expect(reviewRequiredCount(rows, { ...EMPTY_CAMPAIGN_FILTERS, airline: "TK" })).toBe(1);
  });
});

describe("campaignStatusStyle", () => {
  it("maps each status to its own Turkish word and tone", () => {
    expect(campaignStatusStyle("ACTIVE_BOOKING").short).toBe("Satışta");
    expect(campaignStatusStyle("ACTIVE_BOOKING").className).toContain("good");
    expect(campaignStatusStyle("UPCOMING").className).toContain("primary");
    expect(campaignStatusStyle("BOOKING_CLOSED_TRAVEL_ACTIVE").className).toContain("warning");
    // Over is history, not an alarm: muted, never red.
    expect(campaignStatusStyle("EXPIRED").className).not.toContain("critical");
    expect(campaignStatusStyle("UNKNOWN").className).toContain("dashed");
  });

  it("falls back to UNKNOWN for a status this build has never heard of", () => {
    expect(campaignStatusStyle("SOMETHING_NEW").short).toBe("Belirsiz");
  });
});

describe("campaignRouteLabel", () => {
  it("prefers the stated OND pair", () => {
    expect(campaignRouteLabel(promotion({ ond: "IST-LHR" }))).toBe("IST-LHR");
    expect(campaignRouteLabel(promotion({ origin_code: "IST", dest_code: "CDG" }))).toBe(
      "IST-CDG",
    );
  });

  it("names the scope rather than inventing a pair for a regional campaign", () => {
    // "Türkiye'den Avrupa'ya" is not IST-LHR -- the whole reason route_scope
    // exists as a column.
    expect(
      campaignRouteLabel(promotion({ route_scope: "REGION", region: "europe" })),
    ).toBe("Bölgesel: Avrupa");
    expect(campaignRouteLabel(promotion({ route_scope: "NETWORK_WIDE" }))).toBe("Tüm ağ");
    expect(
      campaignRouteLabel(
        promotion({
          route_scope: "COUNTRY",
          route_json: { origin: { country: "Türkiye" }, dest: { country: "Almanya" } },
        }),
      ),
    ).toBe("Ülke: Türkiye → Almanya");
  });

  it("says nothing rather than something invented when no route is known", () => {
    expect(campaignRouteLabel(promotion())).toBe("—");
  });
});

describe("labels", () => {
  it("names confidence bands and the never-assessed case in Turkish", () => {
    expect(confidenceBandLabel("high")).toBe("Yüksek");
    expect(confidenceBandLabel("medium")).toBe("Orta");
    expect(confidenceBandLabel(null)).toBe("Değerlendirilmedi");
  });

  it("names source tiers, and passes an unknown tier through", () => {
    expect(sourceTierLabel("official")).toBe("Resmî");
    expect(sourceTierLabel("newsroom")).toBe("Basın odası");
    expect(sourceTierLabel("secondary")).toBe("İkincil");
    expect(sourceTierLabel(null)).toBe("Bilinmiyor");
  });

  it("translates field names and leaves an unmapped one visible", () => {
    expect(campaignFieldLabel("sale_ends")).toBe("Satış bitişi");
    expect(campaignFieldLabel("some_new_column")).toBe("some_new_column");
  });

  it("renders a missing value as a word, never as an empty string", () => {
    // "the carrier removed the end date" and "we failed to render it" must not
    // look the same.
    expect(formatChangeValue(null)).toBe("belirtilmedi");
    expect(formatChangeValue("")).toBe("belirtilmedi");
    expect(formatChangeValue(40)).toBe("40");
    expect(formatChangeValue(true)).toBe("Evet");
    expect(formatChangeValue(["a", "b"])).toBe('["a","b"]');
  });
});

describe("relativeTimeTr", () => {
  const now = Date.parse("2026-08-28T12:00:00Z");

  it("is coarse on purpose", () => {
    expect(relativeTimeTr("2026-08-28T11:59:40Z", now)).toBe("az önce");
    expect(relativeTimeTr("2026-08-28T11:30:00Z", now)).toBe("30 dk önce");
    expect(relativeTimeTr("2026-08-28T09:00:00Z", now)).toBe("3 sa önce");
    expect(relativeTimeTr("2026-08-26T12:00:00Z", now)).toBe("2 gün önce");
  });

  it("returns nothing for an unparseable timestamp", () => {
    expect(relativeTimeTr("not-a-date", now)).toBe("");
  });
});

describe("campaignQueryString", () => {
  it("carries the visible filters and the window to the API", () => {
    const query = campaignQueryString(
      {
        airline: "TK",
        campaignType: "FLASH_SALE",
        status: "ACTIVE_BOOKING",
        region: "europe",
        band: "high",
        reviewOnly: true,
      },
      { from: "2026-08-17", to: "2026-10-11" },
    );
    const params = new URLSearchParams(query);
    expect(params.get("date_from")).toBe("2026-08-17");
    expect(params.get("date_to")).toBe("2026-10-11");
    expect(params.get("airline")).toBe("TK");
    expect(params.get("campaign_type")).toBe("FLASH_SALE");
    expect(params.get("status")).toBe("ACTIVE_BOOKING");
    expect(params.get("region")).toBe("europe");
    expect(params.get("band")).toBe("high");
    expect(params.get("review_required")).toBe("true");
  });

  it("emits nothing for an unfiltered view", () => {
    expect(campaignQueryString(EMPTY_CAMPAIGN_FILTERS)).toBe("");
  });
});
