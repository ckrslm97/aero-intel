import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { IataIndicatorOut } from "@/lib/types";

import { IataOutlook } from "./iata-outlook";

// The annual chart is an echarts instance behind a lazy boundary; this suite is
// about which FIGURES the panel prints, so the chart is stubbed out.
vi.mock("@/components/kokpit/annual-trend-chart-lazy", () => ({
  AnnualTrendChart: () => <div data-testid="annual-chart" />,
}));

const indicator = (overrides: Partial<IataIndicatorOut> = {}): IataIndicatorOut => ({
  metric: "net_profit",
  kind: "forecast",
  value: 23.0,
  unit: "USD milyar",
  period_start: "2026-01-01",
  period_end: "2026-12-31",
  period_label_tr: "2026",
  region: null,
  publication_date: "2026-06-01",
  source_url: "https://iata.org",
  interpretation_tr: null,
  previous_value: 41.0,
  previous_publication_date: "2025-12-01",
  previous_source_url: "https://iata.org/dec-2025",
  ...overrides,
});

describe("IataOutlook", () => {
  it("prints both profit lines and a revision tile for each one on record", () => {
    // The owner asked for "one main trend chart plus 3-4 critical metrics".
    // The endpoint carries five, but `load_factor`, `passenger_demand` and
    // `rpk_growth` are already on this page to the decimal (Market Pulse's
    // DOLULUK cell, the KPI strip's YOLCU card, Market Pulse's TALEP delta).
    // What is left that appears nowhere else is the two profit levels and how
    // far IATA has moved them since its previous edition.
    render(
      <IataOutlook
        series={[]}
        indicators={[
          indicator(),
          indicator({ metric: "ebit", value: 48.0, previous_value: 72.8 }),
        ]}
      />,
    );

    expect(screen.getByText("Net kâr")).toBeInTheDocument();
    expect(screen.getByText("EBIT")).toBeInTheDocument();
    expect(screen.getByText(/Revizyon · Net kâr/)).toBeInTheDocument();
    expect(screen.getByText(/Revizyon · EBIT/)).toBeInTheDocument();
    expect(screen.getByText(/-18/)).toBeInTheDocument();
    expect(screen.getAllByText(/aşağı revize/)).toHaveLength(2);
  });

  it("says 'değişmedi' rather than 'yukarı revize' when the figure did not move", () => {
    // REGRESSION LOCK. `revision !== null` admits zero, and the earlier
    // `revision < 0 ? "aşağı" : "yukarı"` therefore printed "0 milyar $ ·
    // yukarı revize" for a number IATA had reprinted unchanged -- a direction
    // claimed for something that did not move.
    render(<IataOutlook series={[]} indicators={[indicator({ previous_value: 23.0 })]} />);
    expect(screen.getByText(/değişmedi/)).toBeInTheDocument();
    expect(screen.queryByText(/revize/)).not.toBeInTheDocument();
  });

  it("prints no revision tile when the previous edition is not on record", () => {
    render(
      <IataOutlook
        series={[]}
        indicators={[indicator({ previous_value: null, previous_publication_date: null })]}
      />,
    );
    expect(screen.getByText("Net kâr")).toBeInTheDocument();
    expect(screen.queryByText(/Revizyon/)).not.toBeInTheDocument();
  });

  it("carries no regional selector, because every row's region is NULL", () => {
    const { container } = render(<IataOutlook series={[]} indicators={[indicator()]} />);
    expect(container.querySelector("select")).toBeNull();
    expect(screen.queryByText(/Avrupa|Orta Doğu|Asya/)).not.toBeInTheDocument();
  });

  it("says the profit indicators are unseeded rather than rendering an empty column", () => {
    render(<IataOutlook series={[]} indicators={[]} />);
    expect(screen.getByText("Kâr göstergeleri henüz seed edilmedi.")).toBeInTheDocument();
  });
});
