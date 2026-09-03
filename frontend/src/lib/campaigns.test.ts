import { describe, expect, it } from "vitest";

import { promotion } from "@/lib/__fixtures__/promotion";
import {
  campaignAmountLabel,
  campaignAttr,
  campaignCountries,
  campaignFacetCounts,
  campaignFieldLabel,
  campaignFiltersToSearchParams,
  campaignQueryString,
  campaignRegions,
  campaignRouteLabel,
  campaignStatusStyle,
  confidenceBandLabel,
  daysUntil,
  EMPTY_CAMPAIGN_FILTERS,
  filterCampaigns,
  formatChangeValue,
  hasActiveCampaignFilter,
  isUndatedCampaign,
  orderCampaigns,
  parseCampaignFilters,
  periodRange,
  relativeTimeTr,
  remainingDaysLabel,
  reviewRequiredCount,
  SELECTABLE_CAMPAIGN_STATUSES,
  sourceTierLabel,
  splitUndatedCampaigns,
  todayIso,
  windowOverlaps,
  type CampaignFilters,
} from "@/lib/campaigns";

const TODAY = "2026-09-03";

describe("filterCampaigns", () => {
  const rows = [
    promotion({ id: "1", airline_code: "TK", campaign_type: "FLASH_SALE", campaign_kind: "CAMPAIGN", status: "ACTIVE_BOOKING", confidence_band: "high", region: "europe" }),
    promotion({ id: "2", airline_code: "PC", campaign_type: "EARLY_BOOKING", campaign_kind: "CAMPAIGN", status: "BOOKING_CLOSED_TRAVEL_ACTIVE", confidence_band: "medium", region: "europe" }),
    promotion({ id: "3", airline_code: "TK", campaign_type: null, status: "UPCOMING", confidence_band: null, region: "asia", review_required: true }),
  ];

  it("returns everything when nothing is selected", () => {
    expect(filterCampaigns(rows, EMPTY_CAMPAIGN_FILTERS, TODAY)).toHaveLength(3);
    expect(hasActiveCampaignFilter(EMPTY_CAMPAIGN_FILTERS)).toBe(false);
  });

  it("narrows on each dimension", () => {
    const only = (filters: Partial<CampaignFilters>) =>
      filterCampaigns(rows, { ...EMPTY_CAMPAIGN_FILTERS, ...filters }, TODAY).map((r) => r.id);

    expect(only({ airline: "TK" })).toEqual(["1", "3"]);
    expect(only({ campaignType: "FLASH_SALE" })).toEqual(["1"]);
    expect(only({ campaignKind: "CAMPAIGN" })).toEqual(["1", "2"]);
    expect(only({ status: "BOOKING_CLOSED_TRAVEL_ACTIVE" })).toEqual(["2"]);
    expect(only({ band: "high" })).toEqual(["1"]);
    expect(only({ region: "asia" })).toEqual(["3"]);
    expect(only({ reviewOnly: true })).toEqual(["3"]);
  });

  it("narrows on route scope and country", () => {
    const routed = [
      promotion({
        id: "ond",
        route_scope: "OND",
        route_json: { origin: { country: "Türkiye" }, dest: { country: "Birleşik Krallık" } },
      }),
      promotion({ id: "net", route_scope: "NETWORK_WIDE" }),
    ];
    const only = (filters: Partial<CampaignFilters>) =>
      filterCampaigns(routed, { ...EMPTY_CAMPAIGN_FILTERS, ...filters }, TODAY).map((r) => r.id);

    expect(only({ routeScope: "OND" })).toEqual(["ond"]);
    expect(only({ country: "Türkiye" })).toEqual(["ond"]);
    // Case is the reader's problem, not theirs.
    expect(only({ country: "türkiye" })).toEqual(["ond"]);
    expect(only({ country: "Almanya" })).toEqual([]);
  });

  it("combines dimensions as an intersection", () => {
    const rowsOut = filterCampaigns(
      rows,
      { ...EMPTY_CAMPAIGN_FILTERS, airline: "TK", status: "ACTIVE_BOOKING" },
      TODAY,
    );
    expect(rowsOut.map((r) => r.id)).toEqual(["1"]);
  });

  it("hides an unclassified row behind a type filter rather than calling it OTHER", () => {
    // The legacy row has campaign_type null. Bucketing it as OTHER would put
    // 39 never-classified rows under a label the classifier never assigned.
    const out = filterCampaigns(rows, { ...EMPTY_CAMPAIGN_FILTERS, campaignType: "OTHER" }, TODAY);
    expect(out).toEqual([]);
  });

  it("treats a null review_required as not-flagged", () => {
    // NULL means "never queued", which is not the review queue.
    const out = filterCampaigns(
      [promotion({ review_required: null })],
      { ...EMPTY_CAMPAIGN_FILTERS, reviewOnly: true },
      TODAY,
    );
    expect(out).toEqual([]);
  });
});

describe("date-window filters", () => {
  it("treats a missing edge as open and a missing window as no claim", () => {
    // "A campaign with no stated end has not been said to stop" -- the same
    // convention as the backend's campaign_status.
    expect(windowOverlaps("2026-09-01", null, TODAY, TODAY)).toBe(true);
    expect(windowOverlaps(null, "2026-09-30", TODAY, TODAY)).toBe(true);
    expect(windowOverlaps("2026-09-01", "2026-09-02", TODAY, TODAY)).toBe(false);
    expect(windowOverlaps("2026-10-01", "2026-10-30", TODAY, TODAY)).toBe(false);
    // Neither edge stated: an unstated window cannot support a claim about a
    // period, so it matches nothing rather than everything.
    expect(windowOverlaps(null, null, TODAY, TODAY)).toBe(false);
  });

  it("reads the sale and the travel window separately", () => {
    const rows = [
      promotion({
        id: "sale-now",
        status: "ACTIVE_BOOKING",
        sale_starts: "2026-09-01",
        sale_ends: "2026-09-10",
        travel_starts: "2027-01-01",
        travel_ends: "2027-03-31",
      }),
      promotion({
        id: "travel-now",
        status: "BOOKING_CLOSED_TRAVEL_ACTIVE",
        sale_starts: "2026-06-01",
        sale_ends: "2026-06-30",
        travel_starts: "2026-09-01",
        travel_ends: "2026-09-30",
      }),
    ];
    const ids = (filters: Partial<CampaignFilters>) =>
      filterCampaigns(rows, { ...EMPTY_CAMPAIGN_FILTERS, ...filters }, TODAY).map((r) => r.id);

    // The distinction the whole product rests on: "on sale now" and "flyable
    // now" are different campaigns.
    expect(ids({ salePeriod: "now" })).toEqual(["sale-now"]);
    expect(ids({ travelPeriod: "now" })).toEqual(["travel-now"]);
    expect(ids({ salePeriod: "90" })).toEqual(["sale-now"]);
  });

  it("never matches an undated campaign", () => {
    const undated = promotion({ id: "u", status: "UNKNOWN" });
    expect(
      filterCampaigns([undated], { ...EMPTY_CAMPAIGN_FILTERS, salePeriod: "90" }, TODAY),
    ).toEqual([]);
    expect(
      filterCampaigns([undated], { ...EMPTY_CAMPAIGN_FILTERS, travelPeriod: "90" }, TODAY),
    ).toEqual([]);
  });

  it("measures each horizon from today", () => {
    expect(periodRange("now", TODAY)).toEqual([TODAY, TODAY]);
    expect(periodRange("30", TODAY)).toEqual([TODAY, "2026-10-03"]);
    expect(periodRange("90", TODAY)).toEqual([TODAY, "2026-12-02"]);
  });

  it("counts whole days to a deadline", () => {
    expect(daysUntil("2026-09-05", TODAY)).toBe(2);
    expect(daysUntil("2026-09-03", TODAY)).toBe(0);
    expect(remainingDaysLabel("2026-09-05", TODAY)).toBe("2 gün kaldı");
    expect(remainingDaysLabel("2026-09-04", TODAY)).toBe("Son 1 gün");
    expect(remainingDaysLabel("2026-09-03", TODAY)).toBe("Bugün son gün");
  });

  it("reads today on the BACKEND's calendar -- UTC -- not the reader's", () => {
    // Every status, sort key and visibility decision behind these rows is cut
    // against `_today()` in backend/app/api/v1/promotions.py, which is
    // explicitly UTC. Deriving the page's own "today" from the reader's zone
    // put the two three hours apart, so between 00:00 and 03:00 TRT the card
    // contradicted the payload it was rendering.
    expect(todayIso(new Date("2026-09-03T00:00:00Z"))).toBe("2026-09-03");
    expect(todayIso(new Date("2026-09-03T23:59:59Z"))).toBe("2026-09-03");
    // 00:30 on 4 September in İstanbul is still 3 September where the API is
    // standing, and the API is the one that decided this row was still on sale.
    expect(todayIso(new Date("2026-09-03T21:30:00Z"))).toBe("2026-09-03");
    // And it does roll over -- on UTC's midnight, not on nobody's.
    expect(todayIso(new Date("2026-09-04T00:15:00Z"))).toBe("2026-09-04");
  });

  it("does not count down to a deadline the API has already passed", () => {
    // The failure this closes, end to end: a sale closing on 3 September, read
    // at 00:30 TRT on the 4th. The backend's day is still the 3rd, so the row
    // is still ACTIVE_BOOKING and is still in the payload -- and the card, on
    // the reader's local day, used to call it expired territory: "today" of
    // 2026-09-04 makes `daysUntil` negative and the period filter drop it.
    const atTrtMidnight = new Date("2026-09-03T21:30:00Z");
    const today = todayIso(atTrtMidnight);
    const closing = promotion({
      id: "closing",
      status: "ACTIVE_BOOKING",
      sale_starts: "2026-09-01",
      sale_ends: "2026-09-03",
    });

    expect(remainingDaysLabel("2026-09-03", today)).toBe("Bugün son gün");
    expect(
      filterCampaigns([closing], { ...EMPTY_CAMPAIGN_FILTERS, salePeriod: "now" }, today).map(
        (row) => row.id,
      ),
    ).toEqual(["closing"]);

    // The negative half: once UTC really has rolled over, the page agrees the
    // window is shut rather than counting down for another three hours.
    const nextDay = todayIso(new Date("2026-09-04T00:15:00Z"));
    expect(
      filterCampaigns([closing], { ...EMPTY_CAMPAIGN_FILTERS, salePeriod: "now" }, nextDay),
    ).toEqual([]);
  });
});

describe("splitUndatedCampaigns", () => {
  it("moves the campaigns with no date of any kind into their own group", () => {
    // The measurement this whole layout rests on: 70 of 83 production rows are
    // UNKNOWN, and interleaved they bury the 13 that carry a real window.
    const dated = promotion({ id: "d", status: "ACTIVE_BOOKING", sale_starts: "2026-09-01" });
    const undated = promotion({ id: "u", status: "UNKNOWN" });

    const split = splitUndatedCampaigns([dated, undated]);

    expect(split.dated.map((p) => p.id)).toEqual(["d"]);
    expect(split.undated.map((p) => p.id)).toEqual(["u"]);
    // Nothing is dropped -- it is moved.
    expect(split.dated.length + split.undated.length).toBe(2);
  });

  it("keeps a campaign with travel dates and no sale dates in the main feed", () => {
    // The API calls this ACTIVE_BOOKING: we know when it can be FLOWN, which
    // is a real dated fact. Splitting on "has no sale start" -- what the old
    // swimlane did -- would have exiled it.
    const travelOnly = promotion({
      id: "t",
      status: "ACTIVE_BOOKING",
      sale_starts: null,
      sale_ends: null,
      travel_starts: "2026-10-01",
      travel_ends: "2026-12-31",
    });
    expect(isUndatedCampaign(travelOnly)).toBe(false);
    expect(splitUndatedCampaigns([travelOnly]).dated).toHaveLength(1);
  });

  it("returns empty groups for an empty list", () => {
    expect(splitUndatedCampaigns([])).toEqual({ dated: [], undated: [] });
  });
});

describe("orderCampaigns", () => {
  const row = (
    id: string,
    status: string,
    extra: Partial<Parameters<typeof promotion>[0]> = {},
  ) => promotion({ id, status: status as never, ...extra });

  it("puts what is buyable today first, soonest deadline first inside it", () => {
    const soon = row("soon", "ACTIVE_BOOKING", { sale_ends: "2026-09-05" });
    const later = row("later", "ACTIVE_BOOKING", { sale_ends: "2026-09-25" });
    const openEnded = row("open", "ACTIVE_BOOKING", { sale_ends: null });

    const ordered = orderCampaigns([later, openEnded, soon]).map((p) => p.id);

    // "No deadline" is not "deadline is today": an open-ended sale sorts
    // behind every stated one.
    expect(ordered).toEqual(["soon", "later", "open"]);
  });

  it("follows the API's bucket order and never invents a different one", () => {
    const rows = [
      row("unknown", "UNKNOWN"),
      row("closed", "BOOKING_CLOSED_TRAVEL_ACTIVE"),
      row("upcoming", "UPCOMING", { sale_starts: "2026-10-01" }),
      row("active", "ACTIVE_BOOKING", { sale_ends: "2026-09-10" }),
    ];
    expect(orderCampaigns(rows).map((p) => p.id)).toEqual([
      "active",
      "upcoming",
      "closed",
      "unknown",
    ]);
  });

  it("breaks ties on newest-first-seen, not on detection order", () => {
    const older = row("older", "UNKNOWN", {
      first_seen_at: "2026-08-01T00:00:00Z",
      detected_at: "2026-09-01T00:00:00Z",
    });
    const newer = row("newer", "UNKNOWN", {
      first_seen_at: "2026-09-01T00:00:00Z",
      detected_at: "2026-08-01T00:00:00Z",
    });
    expect(orderCampaigns([older, newer]).map((p) => p.id)).toEqual(["newer", "older"]);
  });

  it("orders upcoming campaigns by the day they open", () => {
    const late = row("late", "UPCOMING", { sale_starts: "2026-12-01" });
    const early = row("early", "UPCOMING", { sale_starts: "2026-09-20" });
    expect(orderCampaigns([late, early]).map((p) => p.id)).toEqual(["early", "late"]);
  });
});

describe("EXPIRED is never reachable from the page", () => {
  it("is not offered as a filter chip", () => {
    // The API hides expired rows by default; offering the chip would be
    // offering an empty result with no way to explain it.
    expect(SELECTABLE_CAMPAIGN_STATUSES).not.toContain("EXPIRED");
  });

  it("is dropped from a hand-edited URL rather than applied", () => {
    const filters = parseCampaignFilters(new URLSearchParams("status=EXPIRED"));
    expect(filters.status).toBeNull();
  });

  it("is never asked for on the wire", () => {
    const query = campaignQueryString(
      { ...EMPTY_CAMPAIGN_FILTERS, status: "ACTIVE_BOOKING" },
      TODAY,
    );
    expect(query).not.toContain("include_expired");
    expect(campaignQueryString(EMPTY_CAMPAIGN_FILTERS, TODAY)).not.toContain("expired");
  });
});

describe("filter URL round-trip", () => {
  const filters: CampaignFilters = {
    airline: "TK",
    campaignKind: "CAMPAIGN",
    campaignType: "FLASH_SALE",
    status: "ACTIVE_BOOKING",
    region: "europe",
    country: "Türkiye",
    routeScope: "OND",
    salePeriod: "30",
    travelPeriod: "90",
    band: "high",
    reviewOnly: true,
  };

  it("survives a trip through the address bar unchanged", () => {
    const params = campaignFiltersToSearchParams(filters);
    expect(parseCampaignFilters(new URLSearchParams(params.toString()))).toEqual(filters);
  });

  it("writes nothing at all for an unfiltered page", () => {
    expect(campaignFiltersToSearchParams(EMPTY_CAMPAIGN_FILTERS).toString()).toBe("");
  });

  it("leaves unrelated params alone", () => {
    const params = campaignFiltersToSearchParams(
      { ...EMPTY_CAMPAIGN_FILTERS, airline: "PC" },
      new URLSearchParams("view=table"),
    );
    expect(params.get("view")).toBe("table");
    expect(params.get("airline")).toBe("PC");
  });

  it("clears a key rather than writing an empty one", () => {
    const params = campaignFiltersToSearchParams(
      EMPTY_CAMPAIGN_FILTERS,
      new URLSearchParams("airline=TK&review=true"),
    );
    expect(params.toString()).toBe("");
  });

  it("drops a value this build has never heard of", () => {
    // A hand-edited ?sale=forever would otherwise narrow the page to nothing
    // while every chip still read "Tümü".
    const filtersOut = parseCampaignFilters(new URLSearchParams("sale=forever&travel=30"));
    expect(filtersOut.salePeriod).toBeNull();
    // ...while the neighbouring valid one still lands.
    expect(filtersOut.travelPeriod).toBe("30");
  });

  it("reads an empty search string as no filters", () => {
    expect(parseCampaignFilters(new URLSearchParams())).toEqual(EMPTY_CAMPAIGN_FILTERS);
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

describe("campaignAttr", () => {
  it("reads a free-form attribute without trusting its type", () => {
    const promo = promotion({
      attrs_json: { cabin: " BUSINESS ", promo_code: "", price_floor: 899, junk: { a: 1 } },
    });
    expect(campaignAttr(promo, "cabin")).toBe("BUSINESS");
    expect(campaignAttr(promo, "promo_code")).toBeNull();
    expect(campaignAttr(promo, "price_floor")).toBe("899");
    expect(campaignAttr(promo, "junk")).toBeNull();
    expect(campaignAttr(promotion(), "cabin")).toBeNull();
  });
});

describe("campaignRegions and campaignCountries", () => {
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

  it("reads the structured markets column too, not the route alone", () => {
    // `markets_json` is what the SERVER filters on (`_regions_of` /
    // `_countries_of`, backend/app/api/v1/promotions.py). It was missing from
    // PromotionOut, so this page could only see the route -- and the CSV
    // export, which runs the server-side filter, selected rows the chip row
    // could not even offer. One dimension, two answers.
    expect(
      campaignRegions(
        promotion({ region: null, markets_json: { regions: ["europe", " middle-east "] } }),
      ).sort(),
    ).toEqual(["europe", "middle-east"]);
    expect(
      campaignCountries(promotion({ markets_json: { countries: ["Almanya", " Japonya "] } })).sort(),
    ).toEqual(["Almanya", "Japonya"]);
  });

  it("reads countries off the resolved route as well as the market list", () => {
    expect(
      campaignCountries(
        promotion({ route_json: { origin: { country: "Türkiye" }, dest: { country: "Japonya" } } }),
      ).sort(),
    ).toEqual(["Japonya", "Türkiye"]);
    expect(campaignCountries(promotion())).toEqual([]);
  });

  it("contributes nothing for a legacy row whose markets were never extracted", () => {
    // NULL is not an empty list: an unextracted campaign names no market,
    // which is not the same claim as naming none. Neither shape may invent a
    // chip, and neither may crash the facet builder.
    expect(campaignCountries(promotion({ markets_json: null }))).toEqual([]);
    expect(campaignRegions(promotion({ region: null, markets_json: null }))).toEqual([]);
    expect(campaignRegions(promotion({ region: null, markets_json: {} }))).toEqual([]);
  });
});

describe("markets_json and the filters", () => {
  // The screen filter and the CSV export must select the SAME rows. The export
  // runs `_regions_of` / `_countries_of` server-side; these assert the client
  // reads the same column for the same answer.
  const berlin = promotion({
    id: "berlin",
    region: null,
    route_json: null,
    markets_json: { countries: ["Almanya"], regions: ["europe"] },
  });
  const tokyo = promotion({
    id: "tokyo",
    region: null,
    route_json: { origin: { country: "Türkiye" }, dest: { country: "Japonya", region: "asia" } },
    markets_json: null,
  });

  it("selects a campaign whose only mention of a country lives in markets_json", () => {
    expect(filterCampaigns([berlin, tokyo], { ...EMPTY_CAMPAIGN_FILTERS, country: "Almanya" }, TODAY))
      .toEqual([berlin]);
    expect(filterCampaigns([berlin, tokyo], { ...EMPTY_CAMPAIGN_FILTERS, region: "europe" }, TODAY))
      .toEqual([berlin]);
  });

  it("still selects on the route for a row that has no markets_json", () => {
    // The negative half: reading the new column must not stop the old one
    // working, or the fix would trade one under-selection for another.
    expect(filterCampaigns([berlin, tokyo], { ...EMPTY_CAMPAIGN_FILTERS, country: "Japonya" }, TODAY))
      .toEqual([tokyo]);
    expect(filterCampaigns([berlin, tokyo], { ...EMPTY_CAMPAIGN_FILTERS, region: "asia" }, TODAY))
      .toEqual([tokyo]);
  });

  it("offers a chip for every value it would then select on", () => {
    // The chip row is built from `campaignFacetCounts`, so a value that
    // matches the filter but counts zero is a filter nobody can reach.
    expect(campaignFacetCounts([berlin, tokyo], EMPTY_CAMPAIGN_FILTERS, "country", TODAY)).toEqual({
      Almanya: 1,
      Japonya: 1,
      "Türkiye": 1,
    });
    expect(campaignFacetCounts([berlin, tokyo], EMPTY_CAMPAIGN_FILTERS, "region", TODAY)).toEqual({
      europe: 1,
      asia: 1,
    });
  });
});

describe("campaignFacetCounts", () => {
  const rows = [
    promotion({ id: "1", airline_code: "TK", campaign_type: "FLASH_SALE" }),
    promotion({ id: "2", airline_code: "TK", campaign_type: "EARLY_BOOKING" }),
    promotion({ id: "3", airline_code: "PC", campaign_type: "FLASH_SALE" }),
  ];

  it("counts every value when nothing is filtered", () => {
    expect(campaignFacetCounts(rows, EMPTY_CAMPAIGN_FILTERS, "airline", TODAY)).toEqual({
      TK: 2,
      PC: 1,
    });
  });

  it("counts a facet against every OTHER filter, not against itself", () => {
    const filters = { ...EMPTY_CAMPAIGN_FILTERS, airline: "TK" as string | null };
    // The type row is narrowed by the carrier...
    expect(campaignFacetCounts(rows, filters, "campaignType", TODAY)).toEqual({
      FLASH_SALE: 1,
      EARLY_BOOKING: 1,
    });
    // ...but the carrier row still shows what the other carrier would give,
    // or clicking PC would be a click into a chip that reads 0.
    expect(campaignFacetCounts(rows, filters, "airline", TODAY)).toEqual({ TK: 2, PC: 1 });
  });

  it("gives an unclassified row no chip at all", () => {
    expect(campaignFacetCounts([promotion()], EMPTY_CAMPAIGN_FILTERS, "campaignType", TODAY)).toEqual({});
    expect(campaignFacetCounts([promotion()], EMPTY_CAMPAIGN_FILTERS, "campaignKind", TODAY)).toEqual({});
  });
});

describe("reviewRequiredCount", () => {
  it("counts flagged rows within the other active filters", () => {
    const rows = [
      promotion({ id: "1", airline_code: "TK", review_required: true }),
      promotion({ id: "2", airline_code: "PC", review_required: true }),
      promotion({ id: "3", airline_code: "TK", review_required: false }),
    ];
    expect(reviewRequiredCount(rows, EMPTY_CAMPAIGN_FILTERS, TODAY)).toBe(2);
    expect(reviewRequiredCount(rows, { ...EMPTY_CAMPAIGN_FILTERS, airline: "TK" }, TODAY)).toBe(1);
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
    expect(campaignStatusStyle("UNKNOWN").short).toBe("Tarihsiz");
  });

  it("falls back to UNKNOWN for a status this build has never heard of", () => {
    expect(campaignStatusStyle("SOMETHING_NEW").short).toBe("Tarihsiz");
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
    expect(campaignFieldLabel("ticketing_end")).toBe("Biletleme bitişi");
    expect(campaignFieldLabel("campaign_kind")).toBe("Kampanya sınıfı");
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
  it("carries the visible filters to the API", () => {
    const query = campaignQueryString(
      {
        ...EMPTY_CAMPAIGN_FILTERS,
        airline: "TK",
        campaignKind: "CAMPAIGN",
        campaignType: "FLASH_SALE",
        status: "ACTIVE_BOOKING",
        region: "europe",
        country: "Türkiye",
        band: "high",
        reviewOnly: true,
        salePeriod: "30",
      },
      TODAY,
    );
    const params = new URLSearchParams(query);
    expect(params.get("airline")).toBe("TK");
    expect(params.get("campaign_kind")).toBe("CAMPAIGN");
    expect(params.get("campaign_type")).toBe("FLASH_SALE");
    expect(params.get("status")).toBe("ACTIVE_BOOKING");
    expect(params.get("region")).toBe("europe");
    expect(params.get("country")).toBe("Türkiye");
    expect(params.get("band")).toBe("high");
    expect(params.get("review_required")).toBe("true");
    // The one period filter the endpoint can express.
    expect(params.get("date_from")).toBe(TODAY);
    expect(params.get("date_to")).toBe("2026-10-03");
  });

  it("emits nothing for an unfiltered view", () => {
    expect(campaignQueryString(EMPTY_CAMPAIGN_FILTERS, TODAY)).toBe("");
  });
});
