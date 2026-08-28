import { describe, expect, it } from "vitest";

import { promotion } from "@/lib/__fixtures__/promotion";
import {
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
  hasActiveCampaignFilter,
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
