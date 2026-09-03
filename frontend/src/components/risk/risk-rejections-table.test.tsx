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

  it("paints a row rejected AT the threshold, not only one below it", () => {
    // THE REGRESSION. The gate passes strictly ABOVE 0.60
    // (`_confidence_verdict`, backend/app/services/risk_quality.py), while
    // this column coloured on `score < 0.60` -- so a row rejected at exactly
    // 0.60 sat in a table of rejections in ordinary type, reading as a value
    // that had cleared the bar.
    render(
      <RiskRejectionsTable
        rows={[
          riskRejection({
            reason: "confidence_below_floor",
            reason_label_tr: "Güven eşiğin altında",
            confidence_score: 0.6,
            confidence_gate_passed: false,
            confidence_gate_reason: "below_gate",
            gates: { currency: true, confidence: false, aviation: true, location: true },
          }),
        ]}
      />,
    );

    const score = screen.getByText("0.60");
    expect(score.className).toContain("text-critical");
    expect(score.getAttribute("title")).toContain("kapı: eledi");
    expect(screen.getByText("eşiğin altında")).toBeInTheDocument();
  });

  it("leaves an exempted low score uncoloured, and says which rung carried it", () => {
    // The other direction, and the reason the colour reads the VERDICT rather
    // than the number: a 0.12 published because a second outlet told the same
    // story did not fail this gate, and painting it red would invent a
    // rejection the pipeline never made.
    render(
      <RiskRejectionsTable
        rows={[
          riskRejection({
            reason: "aviation_relevance_low",
            confidence_score: 0.12,
            confidence_gate_passed: true,
            confidence_gate_reason: "corroborated",
            gates: { currency: true, confidence: true, aviation: false, location: true },
          }),
        ]}
      />,
    );

    const score = screen.getByText("0.12");
    expect(score.className).not.toContain("text-critical");
    expect(score.getAttribute("title")).toContain("kapı: geçti");
    expect(screen.getByText("çoklu kaynak muafiyeti")).toBeInTheDocument();
  });

  it("colours the place a map gate refused, and leaves an accepted one plain", () => {
    render(
      <RiskRejectionsTable
        rows={[
          riskRejection({
            detected_country: "Russia",
            location_confidence: 0.4,
            gates: { currency: true, confidence: true, aviation: true, location: false },
          }),
          riskRejection({
            article_id: "2",
            detected_country: "Japan",
            location_confidence: 0.9,
            gates: { currency: true, confidence: true, aviation: false, location: true },
          }),
        ]}
      />,
    );

    expect(screen.getByText("Russia (0.40)").className).toContain("text-critical");
    expect(screen.getByText("Japan (0.90)").className).not.toContain("text-critical");
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
