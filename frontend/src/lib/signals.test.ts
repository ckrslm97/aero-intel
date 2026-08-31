import { describe, expect, it } from "vitest";

import {
  countBy,
  filterSignals,
  KIND_ORDER,
  NO_FILTERS,
  SEVERITY_ORDER,
  SEVERITY_STYLES,
  severityStyle,
} from "@/lib/signals";
import type { SignalKind, SignalOut, SignalSeverity } from "@/lib/types";

function signal(
  id: string,
  kind: SignalKind,
  severity: SignalSeverity,
): SignalOut {
  return {
    id,
    stream: "test",
    kind,
    kind_label_tr: kind,
    type_label_tr: "t",
    severity,
    severity_label_tr: severity,
    severity_basis_tr: "b",
    title_tr: id,
    detail_tr: null,
    region: null,
    airline_codes: [],
    detected_at: null,
    confidence_score: null,
    source_label: "s",
    href: null,
  };
}

const FEED: SignalOut[] = [
  signal("a", "risk", "high"),
  signal("b", "risk", "low"),
  signal("c", "competitor", "critical"),
  signal("d", "competitor", "low"),
  signal("e", "market", "low"),
];

describe("severity styling", () => {
  it("styles every severity the API can send", () => {
    for (const severity of SEVERITY_ORDER) {
      expect(SEVERITY_STYLES[severity]).toBeDefined();
    }
  });

  it("gives only the top three a hue", () => {
    // A list where every row is coloured tells a reader nothing about which
    // one to read first -- the same rule the alert centre already set.
    expect(severityStyle("low").dot).toBe(severityStyle("unknown").dot);
    expect(severityStyle("critical").dot).not.toBe(severityStyle("low").dot);
    expect(severityStyle("high").dot).not.toBe(severityStyle("critical").dot);
  });

  it("never renders an unreadable driver as an all-clear", () => {
    // `unknown` means the driver could not be read, not that everything is
    // fine. It is neutral, and specifically not the --good token.
    expect(severityStyle("unknown").pill).not.toContain("good");
  });

  it("falls back to the neutral style for a value it has never heard of", () => {
    expect(severityStyle("made_up")).toBe(SEVERITY_STYLES.unknown);
  });

  it("orders the chip rows worst-first, matching the API's own sort", () => {
    expect(SEVERITY_ORDER[0]).toBe("critical");
    expect(SEVERITY_ORDER.at(-1)).toBe("unknown");
    expect(new Set(KIND_ORDER).size).toBe(KIND_ORDER.length);
  });
});

describe("filtering", () => {
  it("keeps everything with no filters", () => {
    expect(filterSignals(FEED, NO_FILTERS)).toHaveLength(5);
  });

  it("narrows on one axis at a time", () => {
    expect(
      filterSignals(FEED, { ...NO_FILTERS, kind: "risk" }).map((row) => row.id),
    ).toEqual(["a", "b"]);
    expect(
      filterSignals(FEED, { ...NO_FILTERS, severity: "low" }).map((row) => row.id),
    ).toEqual(["b", "d", "e"]);
  });

  it("intersects the two axes", () => {
    expect(
      filterSignals(FEED, { kind: "competitor", severity: "low" }).map((row) => row.id),
    ).toEqual(["d"]);
  });

  it("preserves the API's order rather than re-sorting", () => {
    // The backend already sorted by severity then recency; a second
    // client-side sort would be a second chance to disagree with it.
    expect(filterSignals(FEED, NO_FILTERS).map((row) => row.id)).toEqual([
      "a",
      "b",
      "c",
      "d",
      "e",
    ]);
  });
});

describe("chip counts", () => {
  it("counts the whole feed when nothing is selected", () => {
    expect(countBy(FEED, "kind", NO_FILTERS)).toEqual({
      risk: 2,
      competitor: 2,
      market: 1,
    });
  });

  it("cross-counts: an axis is counted over the OTHER axis's selection", () => {
    // Counting over the already-filtered list would make every chip but the
    // active one read 0 the moment one was pressed -- a chip row that erases
    // its own options.
    const counts = countBy(FEED, "kind", { kind: "risk", severity: null });
    expect(counts).toEqual({ risk: 2, competitor: 2, market: 1 });
  });

  it("narrows a kind count by the severity that is selected", () => {
    expect(countBy(FEED, "kind", { kind: null, severity: "low" })).toEqual({
      risk: 1,
      competitor: 1,
      market: 1,
    });
  });

  it("narrows a severity count by the kind that is selected", () => {
    expect(countBy(FEED, "severity", { kind: "risk", severity: null })).toEqual({
      high: 1,
      low: 1,
    });
  });
});
