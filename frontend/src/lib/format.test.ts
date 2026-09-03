import { describe, expect, it } from "vitest";

import {
  DISPLAY_TIME_ZONE,
  formatCompactNumber,
  formatDateTr,
  formatDayMonthTr,
  formatDayTr,
  formatDeltaPoints,
  formatMetricValue,
  formatMonthTr,
  formatRate,
  formatShortDateTr,
  formatSignedPct,
  formatStampTr,
  kpiDeltaLabel,
  shiftDayIso,
  utcDayIso,
} from "./format";

describe("formatCompactNumber", () => {
  it("formats large numbers in Turkish compact notation", () => {
    // Intl's tr-TR compact formatter separates the number and the unit with
    // a non-breaking space (U+00A0) -- built via an escape sequence rather
    // than typed literally, since it is visually indistinguishable from a
    // normal space in an editor.
    expect(formatCompactNumber(1_500_000)).toBe("1,5 Mn");
  });

  it("leaves small numbers unabbreviated", () => {
    expect(formatCompactNumber(42)).toBe("42");
  });
});

describe("formatRate", () => {
  it("uses Turkish separators at two decimals", () => {
    expect(formatRate(41.7231)).toBe("41,72");
    // Thousands separator, for a rate like USD/JPY or a $/bbl price.
    expect(formatRate(1234.5)).toBe("1.234,50");
  });

  it("pads to two decimals rather than dropping a trailing zero", () => {
    expect(formatRate(3.75)).toBe("3,75");
    expect(formatRate(52)).toBe("52,00");
  });
});

describe("formatSignedPct", () => {
  it("puts the percent sign before the number, Turkish-style", () => {
    expect(formatSignedPct(2.36)).toBe("+%2,4");
    expect(formatSignedPct(-2.36)).toBe("-%2,4");
  });

  it("leaves a zero change unsigned", () => {
    expect(formatSignedPct(0)).toBe("%0,0");
  });

  it("honours a requested precision", () => {
    expect(formatSignedPct(23.4, 0)).toBe("+%23");
  });
});

describe("formatMetricValue", () => {
  // THE regression this function exists for: /kpi/fx_eur_usd rendered its
  // reading with the dashboard's compact formatter and printed "1,1", while
  // Kokpit printed the same number as "1,0850". One metric, one page apart,
  // two answers.
  it("quotes a cross below 10 to four decimals", () => {
    expect(formatMetricValue(1.085, "USD", "fx_eur_usd")).toBe("1,0850");
    expect(formatMetricValue(0.857, "GBP", "fx_eur_gbp")).toBe("0,8570");
  });

  it("quotes a rate at or above 10 to two, where the fourth digit says nothing", () => {
    expect(formatMetricValue(41.7231, "TRY", "fx_usd_try")).toBe("41,72");
    expect(formatMetricValue(147.2, "JPY", "fx_usd_jpy")).toBe("147,20");
  });

  // The unit cannot decide this one: kpi_service.py stores only the QUOTE
  // currency ("TRY", "USD"), which a price could carry too. The key is the
  // only thing on the wire that says "this is a cross".
  it("reads the FX rule off the metric key, not off the unit", () => {
    expect(formatMetricValue(1.085, "USD", "some_other_metric")).toBe("1,1");
    expect(formatMetricValue(1.085, "USD", "fx_eur_usd")).toBe("1,0850");
  });

  it("keeps two decimals for percent, cent and per-something price units", () => {
    expect(formatMetricValue(83.45, "%")).toBe("83,45");
    expect(formatMetricValue(8.632, "¢/RPK")).toBe("8,63");
    expect(formatMetricValue(68.4, "$/bbl")).toBe("68,40");
    expect(formatMetricValue(3.214, "$/MMBtu")).toBe("3,21");
  });

  // The other half of that rule, and the one that got away: a BARE "$" is the
  // unit the IATA revenue rows are seeded with (historical_seed.py), and their
  // values are in the hundreds of billions. Treating every "$" as a quoted
  // price printed thirteen digits in the KPI strip and on /kpi/... while the
  // annual chart beside them still read "1,1 Tn".
  it("compacts a bare-dollar magnitude instead of printing every digit", () => {
    expect(formatMetricValue(1_050_000_000_000, "$", "total_aviation_revenue_ytd")).toBe(
      "1,1\u00a0Tn",
    );
    expect(formatMetricValue(693_000_000_000, "$", "passenger_revenue_ytd")).toBe("693\u00a0Mr");
    // ... and the price it is NOT to be confused with keeps its cents.
    expect(formatMetricValue(68.4, "$/bbl")).toBe("68,40");
  });

  // The negative half: a counter is read as a magnitude, and forcing two
  // decimals onto 341 200 000 passengers would be precision nobody asked for
  // and nobody can check.
  it("still compacts a large counter", () => {
    // U+00A0 between number and unit, as in the formatCompactNumber suite.
    expect(formatMetricValue(1_500_000, "yolcu", "passengers_ytd")).toBe("1,5\u00a0Mn");
    expect(formatMetricValue(42, null, null)).toBe("42");
  });

  it("survives a missing unit and a missing key", () => {
    expect(formatMetricValue(42.5)).toBe("42,5");
  });
});

describe("formatDeltaPoints", () => {
  it("names the unit a percentage metric actually moves in", () => {
    // A load factor going 83,0 -> 83,4 rose 0,4 POINTS. Its percent form
    // (+%0,48) is a number nobody in revenue management would recognise,
    // printed under the unit they do.
    expect(formatDeltaPoints(0.4)).toBe("+0,4 puan");
    expect(formatDeltaPoints(-1.25)).toBe("-1,3 puan");
    expect(formatDeltaPoints(0)).toBe("0,0 puan");
  });
});

describe("kpiDeltaLabel", () => {
  // The backend fills exactly one of the pair (see KpiOut in lib/types.ts),
  // and its contract note pointed at this helper by name while nothing
  // implemented it -- the detail page open-coded the choice instead.
  it("prints a percent move as a percent and a points move in points", () => {
    expect(kpiDeltaLabel(4.2, null)).toBe("+%4,2");
    expect(kpiDeltaLabel(null, 0.4)).toBe("+0,4 puan");
    expect(kpiDeltaLabel(null, -1.2)).toBe("-1,2 puan");
  });

  it("prefers the percent when a caller somehow has both", () => {
    // A load factor is the points case; nothing should ever send both, and if
    // something does, one deterministic answer beats two surfaces guessing.
    expect(kpiDeltaLabel(0.48, 0.4)).toBe("+%0,5");
  });

  // Zero IS a measurement ("unchanged"); a missing comparison is not.
  it("keeps a real zero and refuses to invent one", () => {
    expect(kpiDeltaLabel(0, null)).toBe("%0,0");
    expect(kpiDeltaLabel(null, 0)).toBe("0,0 puan");
    expect(kpiDeltaLabel(null, null)).toBeNull();
  });
});


describe("formatMetricValue: olmayan hassasiyeti uydurmaz", () => {
  it("yüzde değerini kaynağın taşıdığı kadar basar", () => {
    // IATA'nın 2026 doluluk tahmini 84,0 -- ikinci ondalık kaynakta YOK.
    expect(formatMetricValue(84, "%", "load_factor")).toBe("84");
    expect(formatMetricValue(83.5, "%", "load_factor")).toBe("83,5");
  });

  it("fiyat ve birim maliyet ise kuruşunu KORUR", () => {
    // Bir kotasyonun kuruşu kotasyonun parçası: 68,4 $/bbl diye fiyat yazılmaz.
    expect(formatMetricValue(68.4, "$/bbl", "oil_price")).toBe("68,40");
    expect(formatMetricValue(8.6, "¢/RPK", "yield_per_rpk")).toBe("8,60");
    expect(formatMetricValue(10.08, "¢/ASK", "rask")).toBe("10,08");
  });

  it("kur paritesinde sondaki sıfır KORUNUR", () => {
    // 1,085 ile 1,0850 aynı kotasyon değil: dördüncü hane hareket eden hane.
    expect(formatMetricValue(1.085, "USD", "fx_eur_usd")).toBe("1,0850");
    expect(formatMetricValue(48.3, "TRY", "fx_usd_try")).toBe("48,30");
  });
});

describe("dates in a named zone", () => {
  it("prints one instant as one string, whatever the runtime's zone is", () => {
    // THE BUG: these formatters were built per-component with no `timeZone`, so
    // they formatted in whatever zone the RUNTIME was in -- UTC on the
    // pre-render node, the reader's zone in the browser. The same article
    // stamp was measured rendering three hours apart on two surfaces of this
    // site. Pinning the zone is what makes the assertion below possible at
    // all: it is true on a UTC CI box and on a laptop in İstanbul.
    expect(DISPLAY_TIME_ZONE).toBe("Europe/Istanbul");
    expect(formatStampTr("2026-09-03T11:32:00Z")).toBe("3 Eyl 2026 14:32");
    expect(formatShortDateTr("2026-09-03T11:32:00Z")).toBe("3 Eyl 14:32");
  });

  it("keeps a DATE-ONLY value on the day it names", () => {
    // "2026-09-04" parses as UTC midnight, which is 3 September in every zone
    // west of Greenwich: the /newspaper/2026-09-04 masthead read "3 Eylül" for
    // a reader in New York, one day off the route they had just clicked. The
    // midday anchor leaves no offset from UTC-11 to UTC+12 able to move it.
    expect(formatDayTr("2026-09-04")).toBe("4 Eylül 2026 Cuma");
    // And an INSTANT is still read in the display zone rather than in UTC:
    // 22:00 UTC is already the next day in İstanbul, and the page says so.
    expect(formatDayTr("2026-09-03T22:00:00Z")).toBe("4 Eylül 2026 Cuma");
  });

  it("holds a stated campaign window on the day the carrier stated", () => {
    // campaign-drawer.tsx anchored these at UTC MIDNIGHT and then formatted
    // with no `timeZone`, so a ticketing period ending "2026-09-30" printed
    // "29 Eyl 2026" in every zone west of Greenwich -- the answer off by a day
    // on the row an analyst reads to decide whether a fare is still on sale.
    expect(formatDateTr("2026-09-30")).toBe("30 Eyl 2026");
    expect(formatDateTr("2026-09-04")).toBe("4 Eyl 2026");
    // An instant is still read in the display zone: 22:00 UTC is already
    // tomorrow in İstanbul.
    expect(formatDateTr("2026-09-03T22:00:00Z")).toBe("4 Eyl 2026");
  });

  it("prints a month and a bare day in the same pinned zone", () => {
    // An IATA edition published at 23:00Z on 30 November is a December edition
    // in İstanbul and a November one in London; which month a publisher
    // published in is not a fact about where the reader is sitting.
    expect(formatMonthTr("2025-11-30T23:00:00Z")).toBe("Ara 2025");
    expect(formatDayMonthTr("2026-09-03T21:30:00Z")).toBe("4 Eyl");
  });

  it("returns null rather than 'Invalid Date' for a value it cannot read", () => {
    for (const value of [null, undefined, "", "not-a-date"]) {
      expect(formatDayTr(value)).toBeNull();
      expect(formatStampTr(value)).toBeNull();
      expect(formatShortDateTr(value)).toBeNull();
      expect(formatDateTr(value)).toBeNull();
      expect(formatMonthTr(value)).toBeNull();
      expect(formatDayMonthTr(value)).toBeNull();
    }
  });
});

describe("day keys", () => {
  it("reads the day key in UTC, the calendar the backend keeps", () => {
    // A day key is compared against dates the API decided (`_today()` in
    // backend/app/api/v1/promotions.py is explicitly UTC), so it is the one
    // date on this site that is NOT read in the display zone.
    expect(utcDayIso(new Date("2026-09-03T23:59:59Z"))).toBe("2026-09-03");
    expect(utcDayIso(new Date("2026-09-04T00:00:01Z"))).toBe("2026-09-04");
  });

  it("steps whole calendar days, not 24-hour blocks", () => {
    expect(shiftDayIso("2026-09-03", 30)).toBe("2026-10-03");
    expect(shiftDayIso("2026-09-03", -3)).toBe("2026-08-31");
    // Across a DST transition: the local day either side of 29 March 2026 is
    // 23 or 25 hours long, so arithmetic in a reader's zone lands a 60-day
    // horizon one day out. These are calendar keys and stay calendar
    // arithmetic.
    expect(shiftDayIso("2026-03-28", 3)).toBe("2026-03-31");
    expect(shiftDayIso("2026-10-24", 3)).toBe("2026-10-27");
  });
});
