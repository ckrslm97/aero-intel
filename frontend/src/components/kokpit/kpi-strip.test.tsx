import { render, screen } from "@testing-library/react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { AnnualPoint, AnnualSeries } from "@/lib/types";

import { KpiStrip } from "./kpi-strip";

const point = (
  year: number,
  value: number,
  kind: AnnualPoint["kind"] = "actual",
): AnnualPoint => ({ year, value, kind });

const series = (overrides: Partial<AnnualSeries> = {}): AnnualSeries => ({
  metric_key: "passengers_ytd",
  label_tr: "Yolcu",
  unit: "yolcu",
  up_is_good: true,
  points: [point(2023, 4_400), point(2024, 4_800), point(2025, 4_970), point(2026, 5_090, "forecast")],
  ...overrides,
});

/** RASK and CASK share the unit ¢/ASK, so the metric NAME is the only thing
 * that tells them apart. That is what makes the label a correctness surface
 * rather than decoration. */
const rask = series({
  metric_key: "rask",
  label_tr: "RASK",
  unit: "¢/ASK",
  points: [point(2023, 9.1), point(2024, 9.3), point(2025, 9.34), point(2026, 10.08, "forecast")],
});

/** The real shape of `cask` in this database: no 2025 row at all (an upstream
 * de-duplication pass mistook a legitimately unchanged annual figure for a
 * copy -- D3 in the design spec). */
const cask = series({
  metric_key: "cask",
  label_tr: "CASK",
  unit: "¢/ASK",
  up_is_good: false,
  points: [point(2023, 8.4), point(2024, 8.67), point(2026, 9.66, "forecast")],
});

describe("KpiStrip", () => {
  it("keeps the metric name in a slot that cannot be crushed to zero height", () => {
    // The regression: the cell was a fixed `h-[76px]` around ~104px of
    // children, and the label carries `truncate` (overflow: hidden), whose
    // automatic minimum size resolves to 0. Flex therefore loaded the whole
    // overflow onto the label and it rendered 0px high at EVERY breakpoint --
    // so RASK and CASK, which both read "¢/ASK", were indistinguishable on
    // screen. jsdom does no layout, so the lock is on the two class decisions
    // that make the collapse impossible.
    const { container } = render(<KpiStrip series={[rask]} />);
    const label = screen.getByText("RASK");
    expect(label.className).toContain("shrink-0");
    expect(container.querySelector(".min-h-\\[104px\\]")).not.toBeNull();
    expect(container.querySelector(".h-\\[76px\\]")).toBeNull();
  });

  it("refuses a year-on-year pill when the previous YEAR is missing", () => {
    // 2024 -> 2026T is +%11,4 over two years. The cell used to print it in the
    // same pill its four neighbours fill with a single year's move, with
    // nothing on screen to say the windows differed.
    render(<KpiStrip series={[cask]} />);
    expect(screen.queryByText(/%11,4/)).not.toBeInTheDocument();
    expect(screen.getByTitle(/Önceki yılın noktası veritabanında yok/)).toBeInTheDocument();
  });

  it("prints the window on the pill when the comparison is a real one", () => {
    render(<KpiStrip series={[rask]} />);
    // Without this the yearly move wears the same badge shape as the "1g" /
    // "1h" pills two sections above.
    expect(screen.getByText("25→26T")).toBeInTheDocument();
  });

  it("renders the trailing cell as a sixth member of the same strip", () => {
    // Sektör Dengesi's unit-margin cell arrives this way rather than as a
    // four-column panel beside the strip: it is one derived figure in the same
    // shape as the five, and its own panel cost 287px of the fold to say it.
    const { container } = render(
      <KpiStrip series={[rask]} trailing={<div>Birim marj</div>} />,
    );
    expect(screen.getByText("Birim marj")).toBeInTheDocument();
    expect(container.querySelector(".xl\\:grid-cols-6")).not.toBeNull();
  });

  // The unit the IATA revenue rows are actually seeded with is a bare "$"
  // (backend/app/ingest/historical_seed.py), and the values are in the
  // hundreds of billions. A precision rule that read the "$" as "money price"
  // printed all thirteen digits in this 20px-tall cell, while the annual chart
  // one section down still drew the same figure as "1,1 Tn".
  it("compacts the revenue cell instead of printing thirteen digits", () => {
    const revenue = series({
      metric_key: "total_aviation_revenue_ytd",
      label_tr: "Sektör geliri",
      unit: "$",
      points: [
        point(2024, 966_000_000_000),
        point(2025, 1_007_000_000_000),
        point(2026, 1_050_000_000_000, "forecast"),
      ],
    });
    // The FIRST render (CountUp prints the final value before its animation
    // touches the node, and that is also what a JS-less reader sees).
    const html = renderToStaticMarkup(<KpiStrip series={[revenue]} />);
    expect(html).toContain(">1,1\u00a0Tn<");
    // What the two-decimal money rule printed into that same 20px cell. (The
    // year dots' hover titles DO carry the exact figure -- that is the point
    // of a tooltip, and a different job from the headline number.)
    expect(html).not.toContain(">1.050.000.000.000,00<");
  });

  it("says the series is missing rather than rendering an empty strip", () => {
    render(<KpiStrip series={[]} />);
    expect(screen.getByText(/IATA serisi henüz yüklenmedi/)).toBeInTheDocument();
  });

  it("keeps a build command out of the product surface", async () => {
    // "IATA serisi henüz yüklenmedi. make seed-ingest" was an operator's shell
    // command printed inside an executive dashboard: nothing the reader can
    // act on, and an assertion about the DATABASE over what is far more often
    // a five-second outage.
    render(<KpiStrip series={[]} />);
    expect(screen.queryByText(/seed-ingest/)).not.toBeInTheDocument();
    expect(screen.queryByText(/make /)).not.toBeInTheDocument();
  });

  it("separates a series that was not read from one that is genuinely empty", async () => {
    // Same empty `series` prop, opposite facts. Only the second is entitled to
    // say the series has not been loaded yet.
    const { unmount } = render(<KpiStrip series={[]} unavailable />);
    expect(screen.getByText(/IATA yıllık serisi okunamadı/)).toBeInTheDocument();
    expect(screen.queryByText(/henüz yüklenmedi/)).not.toBeInTheDocument();
    unmount();

    render(<KpiStrip series={[]} />);
    expect(screen.getByText(/IATA serisi henüz yüklenmedi/)).toBeInTheDocument();
    expect(screen.queryByText(/okunamadı/)).not.toBeInTheDocument();
  });
});
