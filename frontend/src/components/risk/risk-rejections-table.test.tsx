import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { riskRejection } from "@/lib/__fixtures__/risk";

import { RiskRejectionsTable } from "./risk-rejections-table";

describe("RiskRejectionsTable", () => {
  it("shows the values the rule read, not just the label it produced", () => {
    // The whole point of the table. A row saying "havacılıkla ilgisiz" and
    // nothing else asks the reader to trust the label -- which is the failure
    // this revision exists to fix.
    render(
      <RiskRejectionsTable
        rows={[
          riskRejection({
            title: "Ukraine strikes Russian pipeline station",
            aviation_relevance_score: 0.1,
            aviation_relevance_source: "llm",
            location_confidence: 0.8,
            detected_country: "Russia",
          }),
        ]}
      />,
    );

    expect(screen.getByText("Ukraine strikes Russian pipeline station")).toBeInTheDocument();
    expect(screen.getByText("Havacılıkla ilgisiz")).toBeInTheDocument();
    expect(screen.getByText("0.10")).toBeInTheDocument();
    expect(screen.getByText("llm")).toBeInTheDocument();
    expect(screen.getByText("Russia (0.80)")).toBeInTheDocument();
  });

  it("says 'ölçülmedi' for a null score and never 0.00", () => {
    // "We did not measure this" and "we measured this and it was zero" are
    // different facts, and a table that draws them identically re-creates on
    // screen the exact bug the backend gates were rewritten to remove.
    render(<RiskRejectionsTable rows={[riskRejection({ confidence_score: null })]} />);
    expect(screen.getAllByText("ölçülmedi").length).toBeGreaterThan(0);
    expect(screen.queryByText("0.00")).not.toBeInTheDocument();
  });

  it("names every other gate the row would also have failed", () => {
    render(
      <RiskRejectionsTable
        rows={[
          riskRejection({
            reason: "not_current_event",
            reason_label_tr: "Güncel olay değil",
            also_failed: ["confidence_below_floor", "location_unresolved"],
          }),
        ]}
      />,
    );
    // Without this, a reader fixes the named reason and watches the row stay
    // hidden for a reason nothing told them about.
    expect(
      screen.getByText("+ confidence_below_floor, location_unresolved"),
    ).toBeInTheDocument();
  });

  it("shows each named place with the ROLE it played", () => {
    // "United States · source" beside a story about Japan is the
    // Washington/Japan bug rendered legible. Without the role, a correct
    // refusal cannot be told apart from a broken resolver.
    render(
      <RiskRejectionsTable
        rows={[
          riskRejection({
            reason: "location_unresolved",
            reason_label_tr: "Konum doğrulanamadı",
            mentioned_locations: [
              { name: "United States", kind: "country", role: "source" },
              { name: "Japan", kind: "country", role: "event" },
            ],
          }),
        ]}
      />,
    );

    const cell = screen.getByText("United States").closest("span");
    expect(cell).not.toBeNull();
    expect(within(cell as HTMLElement).getByText("· source")).toBeInTheDocument();
    expect(screen.getByText("Japan")).toBeInTheDocument();
  });

  it("renders a dash rather than a blank cell when the article named no place", () => {
    render(<RiskRejectionsTable rows={[riskRejection()]} />);
    // An unexplained gap on a table reads as a rendering bug, not as a fact
    // about the source.
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
    expect(screen.getByText("Konum çözülemedi")).toBeInTheDocument();
  });

  it("draws a header row and no body rows for an empty list", () => {
    render(<RiskRejectionsTable rows={[]} />);
    expect(screen.getByText("Başlık")).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(1);
  });
});
