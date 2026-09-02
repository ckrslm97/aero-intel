import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { CockpitSignal } from "@/lib/types";

import { DailySummary } from "./daily-summary";

/** The default driver is `risk`, NOT `fx`: fx and fuel now carry their band on
 * their own Market Pulse cell and are filtered out of this section. */
const signal = (overrides: Partial<CockpitSignal> = {}): CockpitSignal => ({
  key: "risk",
  label_tr: "Risk radarı",
  level: "warning",
  level_label_tr: "Dikkat",
  value_label: "3 yüksek şiddetli olay",
  reason_tr: "Son 14 günde 3 yüksek şiddetli risk sinyali.",
  method_tr: "Eşik: 14 günde 2'den fazla yüksek şiddetli sinyal.",
  source: "Risk Radarı",
  source_url: null,
  href: "/risk-radari",
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

    expect(screen.getByText("Risk radarı")).toBeInTheDocument();
    expect(screen.getByText("Dikkat")).toBeInTheDocument();
    // The number exists in the tile, but only for assistive technology: the
    // reading, its threshold, its method and its source are what a sighted
    // reader gets from the tooltip, and a tile with no `href` is not focusable
    // for anyone else to reach it. Nothing of it is in the visual field, which
    // is the duplication this component exists to prevent -- USD/TRY and Brent
    // are already printed at 26px two sections above.
    const detail = screen.getByText(/3 yüksek şiddetli olay/);
    expect(detail).toHaveClass("sr-only");
  });

  it("keeps the number, the reason, the method and the source one hover away", () => {
    render(<DailySummary signals={[signal()]} />);
    const tile = screen.getByText("Risk radarı").closest("[title]");
    expect(tile?.getAttribute("title")).toContain("3 yüksek şiddetli olay");
    expect(tile?.getAttribute("title")).toContain("Eşik: 14 günde");
    expect(tile?.getAttribute("title")).toContain("Risk Radarı");
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

  it("does not reprint a driver whose band is already on its Market Pulse cell", () => {
    // THE DUPLICATION THIS ROUND CLOSED. USD/TRY and Brent are cells in Market
    // Pulse two hundred pixels above, printing the reading at 26px with both
    // deltas; the tile added exactly one word to that and spent a quarter of
    // the section's height doing it. Fuel in particular was appearing THREE
    // times on a page instructed to show it once. The band now sits on the
    // cell that already carries the number, and this section carries the
    // drivers that have no cell of their own.
    render(
      <DailySummary
        signals={[
          signal({ key: "fx", label_tr: "Kur riski" }),
          signal({ key: "fuel", label_tr: "Yakıt riski", level: "critical" }),
          signal({ key: "risk", label_tr: "Risk radarı", level: "good", level_label_tr: "Sakin" }),
          signal({ key: "competitor", label_tr: "Rakip aktivitesi" }),
        ]}
      />,
    );
    expect(screen.queryByText("Kur riski")).not.toBeInTheDocument();
    expect(screen.queryByText("Yakıt riski")).not.toBeInTheDocument();
    expect(screen.getByText("Risk radarı")).toBeInTheDocument();
    expect(screen.getByText("Rakip aktivitesi")).toBeInTheDocument();
  });

  it("says so rather than rendering an empty row when every driver is banded above", () => {
    render(
      <DailySummary
        signals={[signal({ key: "fx" }), signal({ key: "fuel" })]}
      />,
    );
    expect(
      screen.getByText("Bugünün sürücülerinin tümü Market Pulse hücrelerinde bantlandı."),
    ).toBeInTheDocument();
  });

  it("draws no direction glyph, because the level is not a direction", () => {
    // The tiles used to derive an arrow from the SEVERITY BAND: critical and
    // warning pointed up, good pointed down. That is the band drawn twice, and
    // drawn as the one thing on the tile a reader would take for a
    // measurement -- "Yakıt riski · DİKKAT ▲" reads as "fuel went up", which
    // the level does not say and `CockpitSignal` carries no field to support.
    const { container } = render(
      <DailySummary signals={[signal({ level: "good", level_label_tr: "Sakin" })]} />,
    );
    expect(container.querySelectorAll("svg.lucide-arrow-up-right")).toHaveLength(0);
    expect(container.querySelectorAll("svg.lucide-arrow-down-right")).toHaveLength(0);
    // Exactly two glyphs remain: the driver's own icon and the pill's.
    expect(container.querySelectorAll("svg")).toHaveLength(2);
  });

  it("puts the detail where a screen reader can reach it on an unlinked tile", () => {
    // A tile with no `href` is not focusable, and `title` is a pointer
    // affordance: it never opens on touch and browsers do not surface it on
    // keyboard focus. For those readers the caveat simply did not exist.
    render(<DailySummary signals={[signal({ href: null })]} />);
    expect(screen.getByText(/Kaynak: Risk Radarı/)).toHaveClass("sr-only");
  });
});
