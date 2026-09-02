import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { CockpitSignal } from "@/lib/types";

import { DailySummary } from "./daily-summary";

const signal = (overrides: Partial<CockpitSignal> = {}): CockpitSignal => ({
  key: "fx",
  label_tr: "Kur",
  level: "warning",
  level_label_tr: "Dikkat",
  value_label: "48,2505 TRY",
  reason_tr: "USD/TRY haftalık %1,2 yükseldi.",
  method_tr: "Eşik: haftalık %1'i aşan hareket.",
  source: "Yahoo Finance",
  source_url: null,
  href: "/kpi/fx_usd_try",
  as_of: "2026-08-30T19:50:00Z",
  ...overrides,
});

describe("DailySummary", () => {
  it("prints the label and the level, and no number at all", () => {
    // THE INVARIANT. USD/TRY and Brent are already printed at full size in
    // Market Pulse; a figure here would be the same reading's third appearance
    // on one screen. Carrying no number closes that off in the data rather
    // than in a style rule a later maintainer can undo.
    render(<DailySummary signals={[signal()]} />);

    expect(screen.getByText("Kur")).toBeInTheDocument();
    expect(screen.getByText("Dikkat")).toBeInTheDocument();
    expect(screen.queryByText(/48,2505/)).not.toBeInTheDocument();
    expect(screen.queryByText(/%1,2/)).not.toBeInTheDocument();
  });

  it("keeps the number, the reason, the method and the source one hover away", () => {
    render(<DailySummary signals={[signal()]} />);
    const tile = screen.getByText("Kur").closest("[title]");
    expect(tile?.getAttribute("title")).toContain("48,2505 TRY");
    expect(tile?.getAttribute("title")).toContain("Eşik: haftalık %1'i aşan hareket.");
    expect(tile?.getAttribute("title")).toContain("Yahoo Finance");
  });

  it("never renders an unreadable driver as an all-clear", () => {
    render(<DailySummary signals={[signal({ level: "unknown", level_label_tr: "Bilinmiyor" })]} />);
    const pill = screen.getByText("Bilinmiyor");
    expect(pill.className).not.toMatch(/text-good/);
    expect(pill.className).toContain("text-muted-foreground");
  });

  it("says the signals could not be produced rather than showing four blank tiles", () => {
    render(<DailySummary signals={[]} />);
    expect(screen.getByText("Sinyal üretilemedi.")).toBeInTheDocument();
  });

  it("renders every driver it is given, each with its own tile", () => {
    render(
      <DailySummary
        signals={[
          signal(),
          signal({ key: "fuel", label_tr: "Yakıt", level: "critical", level_label_tr: "Yüksek" }),
          signal({ key: "risk", label_tr: "Risk", level: "good", level_label_tr: "Sakin" }),
          signal({ key: "competitor", label_tr: "Rekabet", level: "warning" }),
        ]}
      />,
    );
    for (const label of ["Kur", "Yakıt", "Risk", "Rekabet"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });
});
