import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { riskFunnel } from "@/lib/__fixtures__/risk";

import { RiskFunnel } from "./risk-funnel";

/** The production shape in miniature: fourteen thousand articles become nine
 * signals, and the last drop is a MERGE rather than a rejection. */
const STAGES = riskFunnel([
  { key: "toplam", label: "Toplam makale", passed: 13906 },
  { key: "risk_adayi", label: "Risk adayı", passed: 252, dropKind: null },
  { key: "pencere", label: "Pencere içinde (son 5 gün)", passed: 24, reason: "outside_window" },
  { key: "tekil", label: "Yinelenmemiş", passed: 22, reason: "duplicate" },
  { key: "guncel", label: "Güncel olay", passed: 20, reason: "not_current_event" },
  { key: "guven", label: "Güven kapısı", passed: 16, reason: "confidence_below_floor" },
  { key: "havacilik", label: "Havacılık ilgisi", passed: 13, reason: "aviation_relevance_low" },
  { key: "konum", label: "Konum doğrulandı", passed: 11, reason: "location_unresolved" },
  {
    key: "kume",
    label: "Kümeleme sonrası sinyal",
    passed: 9,
    dropKind: "merged",
    note: "Eleme değil, BİRLEŞME.",
  },
]);

describe("RiskFunnel", () => {
  it("draws every stage with what reached it and what left", () => {
    render(<RiskFunnel stages={STAGES} />);

    const rows = screen.getAllByRole("listitem");
    expect(rows).toHaveLength(9);
    expect(within(rows[0]).getByText("Toplam makale")).toBeInTheDocument();
    // Turkish grouping, because the numbers on this screen are read as
    // quantities and 13906 is not.
    expect(within(rows[0]).getByText("13.906")).toBeInTheDocument();
    expect(within(rows[8]).getByText("9")).toBeInTheDocument();
  });

  it("never calls the clustering merge a rejection", () => {
    // The distinction the whole component exists to preserve: a merged cluster
    // is still on the radar and a rejected article is not. Drawing them alike
    // would tell an analyst their event was thrown away when it is on the page
    // under another headline.
    render(<RiskFunnel stages={STAGES} onSelectReason={vi.fn()} />);

    const merge = screen.getAllByRole("listitem")[8];
    expect(within(merge).getByText(/tek sinyalde birleşti/)).toBeInTheDocument();
    expect(within(merge).queryByText(/elendi/)).not.toBeInTheDocument();
    expect(within(merge).queryByRole("button")).not.toBeInTheDocument();
  });

  it("offers a rejecting stage's count as a filter and reports the reason", async () => {
    const onSelectReason = vi.fn();
    render(<RiskFunnel stages={STAGES} onSelectReason={onSelectReason} />);

    const button = screen.getByRole("button", { name: /3 elendi · aviation_relevance_low/ });
    expect(button).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(button);
    expect(onSelectReason).toHaveBeenCalledWith("aviation_relevance_low");
  });

  it("clicking the active reason clears the filter rather than re-applying it", async () => {
    const onSelectReason = vi.fn();
    render(
      <RiskFunnel
        stages={STAGES}
        activeReason="aviation_relevance_low"
        onSelectReason={onSelectReason}
      />,
    );

    const button = screen.getByRole("button", { name: /aviation_relevance_low/ });
    expect(button).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(button);
    expect(onSelectReason).toHaveBeenCalledWith(null);
  });

  it("draws a stage that dropped nothing without an empty rejection line", () => {
    const flat = riskFunnel([
      { key: "toplam", label: "Toplam makale", passed: 4 },
      { key: "risk_adayi", label: "Risk adayı", passed: 4, dropKind: null },
    ]);
    render(<RiskFunnel stages={flat} onSelectReason={vi.fn()} />);
    expect(screen.queryByText(/elendi/)).not.toBeInTheDocument();
    expect(screen.queryByText(/ayrıldı/)).not.toBeInTheDocument();
  });

  it("renders nothing at all rather than an empty frame when there are no stages", () => {
    const { container } = render(<RiskFunnel stages={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("RiskFunnel with a stage that rejects for two reasons", () => {
  const split = riskFunnel([
    { key: "toplam", label: "Toplam makale", passed: 10 },
    {
      key: "konum",
      label: "Konum doğrulandı",
      passed: 7,
      reason: "location_unresolved",
      reasonCounts: { location_unresolved: 1, location_conflict: 2 },
    },
  ]);

  it("draws one chip per reason with its OWN count", async () => {
    // The bug this exists to prevent: a single chip labelled with the stage's
    // whole drop ("3 elendi · location_unresolved") that returns one row when
    // clicked, because the filter only ever carried the first reason.
    const onSelectReason = vi.fn();
    render(<RiskFunnel stages={split} onSelectReason={onSelectReason} />);

    const unresolved = screen.getByRole("button", { name: /1 elendi · location_unresolved/ });
    const conflict = screen.getByRole("button", { name: /2 elendi · location_conflict/ });
    expect(screen.queryByRole("button", { name: /3 elendi/ })).not.toBeInTheDocument();

    await userEvent.click(conflict);
    expect(onSelectReason).toHaveBeenCalledWith("location_conflict");
    expect(unresolved).toHaveAttribute("aria-pressed", "false");
  });

  it("marks only the chip that is actually filtering", () => {
    render(
      <RiskFunnel
        stages={split}
        activeReason="location_conflict"
        onSelectReason={vi.fn()}
      />,
    );
    expect(
      screen.getByRole("button", { name: /location_conflict/ }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByRole("button", { name: /location_unresolved/ }),
    ).toHaveAttribute("aria-pressed", "false");
  });

  it("hides a reason that rejected nothing this window", () => {
    // Zero-count reasons still reach the filter chips below the funnel (see
    // rejectionFilterOptions); inside the funnel they would be a button that
    // returns nothing, next to a bar that dropped nothing.
    const clean = riskFunnel([
      { key: "toplam", label: "Toplam makale", passed: 10 },
      {
        key: "konum",
        label: "Konum doğrulandı",
        passed: 9,
        reason: "location_unresolved",
        reasonCounts: { location_unresolved: 1, location_conflict: 0 },
      },
    ]);
    render(<RiskFunnel stages={clean} onSelectReason={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /location_conflict/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /1 elendi · location_unresolved/ })).toBeInTheDocument();
  });
});
