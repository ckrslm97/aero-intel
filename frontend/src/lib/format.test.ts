import { describe, expect, it } from "vitest";

import {
  formatCompactNumber,
  formatDeltaPoints,
  formatMetricValue,
  formatRate,
  formatSignedPct,
  kpiDeltaLabel,
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
