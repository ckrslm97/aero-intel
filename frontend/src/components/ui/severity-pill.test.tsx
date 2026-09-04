import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SEVERITY_LADDER } from "@/lib/severity";

import { SeverityPill } from "./severity-pill";

describe("SeverityPill", () => {
  it("prints the rung's word beside its colour", () => {
    // Colour is never the message on its own. The pill carries the word and a
    // glyph, so a reader who cannot separate the hues still reads the rung.
    render(<SeverityPill severity="high" />);
    const pill = screen.getByText("Yüksek");
    expect(pill.querySelector("svg")).toBeInTheDocument();
    expect(pill.className).toContain("warning");
  });

  it("draws Yüksek in the same hue the Sinyaller list does", () => {
    // The bug this replaced: the risk radar's own three-rung table gave `high`
    // the --critical red while lib/signals.ts gave it --warning amber, so one
    // word meant two colours depending on which page a reader was on.
    render(<SeverityPill severity="high" />);
    expect(screen.getByText("Yüksek").className).toContain(SEVERITY_LADDER.high.pill);
  });

  it("says Belirsiz rather than inventing a rung", () => {
    // A value from outside the ladder used to fall to `low` and be printed as
    // "Düşük" -- a grade this pipeline never assigned, presented as one it had.
    render(<SeverityPill severity="severe" />);
    expect(screen.getByText("Belirsiz")).toBeInTheDocument();
    expect(screen.queryByText("Düşük")).not.toBeInTheDocument();
  });

  it("never renders a severity in the good palette", () => {
    for (const rung of ["critical", "high", "medium", "low", "unknown"]) {
      const { unmount } = render(<SeverityPill severity={rung} />);
      expect(
        screen.getByText(SEVERITY_LADDER[rung as keyof typeof SEVERITY_LADDER].label).className,
      ).not.toContain("good");
      unmount();
    }
  });
});
