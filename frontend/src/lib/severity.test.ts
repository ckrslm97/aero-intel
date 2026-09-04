import { describe, expect, it } from "vitest";

import { statusToneOf } from "@/components/ui/status-pill";
import {
  SEVERITY_LADDER,
  priorityToSeverity,
  severityMeta,
  toSeverity,
  type Severity,
} from "@/lib/severity";
import { SEVERITY_STYLES, severityStyle } from "@/lib/signals";

const RUNGS: Severity[] = ["critical", "high", "medium", "low", "unknown"];

describe("severity ladder", () => {
  it("gives every rung a word and a glyph, not only a colour", () => {
    // Roughly one man in twelve cannot separate this palette's red from its
    // green. A rung that carried only a hue would be unreadable to them, and
    // this is the surface a desk decides what to read first from.
    for (const rung of RUNGS) {
      expect(SEVERITY_LADDER[rung].label).toBeTruthy();
      expect(SEVERITY_LADDER[rung].icon).toBeTruthy();
    }
  });

  it("never draws a low or unknown severity in the good token", () => {
    // The rule this ladder exists to enforce. `recommendations-client.tsx`
    // used to give `low` the --good palette, so a low-importance
    // recommendation rendered in the same green the rest of the app means "this
    // is going well" by. A low-severity risk is a war that is going slightly
    // less badly.
    for (const rung of ["low", "unknown"] as const) {
      const meta = SEVERITY_LADDER[rung];
      for (const value of [meta.pill, meta.dot, meta.text, meta.glowVar]) {
        expect(value).not.toContain("good");
      }
    }
  });

  it("separates the rungs a reader has to act on", () => {
    // critical/high/medium are the three that take a hue; low and unknown are
    // both deliberately neutral, and the WORD is what tells them apart.
    expect(SEVERITY_LADDER.critical.dot).not.toBe(SEVERITY_LADDER.high.dot);
    expect(SEVERITY_LADDER.high.dot).not.toBe(SEVERITY_LADDER.medium.dot);
    expect(SEVERITY_LADDER.low.dot).toBe(SEVERITY_LADDER.unknown.dot);
    expect(SEVERITY_LADDER.low.label).not.toBe(SEVERITY_LADDER.unknown.label);
  });

  it("sends anything it does not recognise to unknown, never to a rung", () => {
    // A stream publishing "severe", a null from a column that was never
    // filled, a hand-edited ?severity=pink. None of them may be flattered into
    // a band, and none may land on the bottom rung either -- "we could not read
    // this" is a different statement from "this is unimportant".
    for (const value of ["severe", "HIGH", "", null, undefined]) {
      expect(toSeverity(value)).toBe("unknown");
    }
    expect(severityMeta("uydurma")).toBe(SEVERITY_LADDER.unknown);
    expect(toSeverity("high")).toBe("high");
  });

  it("maps a campaign alert's priority onto the same rungs", () => {
    expect(priorityToSeverity("CRITICAL")).toBe("critical");
    expect(priorityToSeverity("HIGH")).toBe("high");
    expect(priorityToSeverity("MEDIUM")).toBe("medium");
    // INFO was GRADED, and graded as unimportant -- that is the bottom rung,
    // not a missing reading.
    expect(priorityToSeverity("INFO")).toBe("low");
    expect(priorityToSeverity("URGENT")).toBe("unknown");
    expect(priorityToSeverity(null)).toBe("unknown");
  });
});

describe("one ladder, every consumer", () => {
  it("is the same table lib/signals.ts serves the Sinyaller page from", () => {
    // Not "looks the same": the same object. A copy is a thing that can drift,
    // and six copies is how "Yüksek" came to mean two different colours.
    for (const rung of RUNGS) {
      expect(SEVERITY_STYLES[rung]).toBe(SEVERITY_LADDER[rung]);
      expect(severityStyle(rung)).toBe(SEVERITY_LADDER[rung]);
    }
  });

  it("gives Kokpit's status pill the ladder's own tones", () => {
    // `statusToneOf` is Kokpit's vocabulary bridge. "high" has to reach the
    // WARNING tone here, because that is the hue the ladder gives `high`
    // everywhere else -- the Sinyal Panosu row and the risk radar badge are
    // reading the same word.
    expect(statusToneOf("critical")).toBe("critical");
    expect(statusToneOf("high")).toBe("warning");
    expect(statusToneOf("medium")).toBe("info");
    expect(statusToneOf("low")).toBe("neutral");
    expect(statusToneOf("unknown")).toBe("neutral");
    // Kokpit's own level vocabulary adds two words the ladder has no rung for.
    expect(statusToneOf("good")).toBe("good");
    expect(statusToneOf("warning")).toBe("warning");
    // ...and anything else falls to neutral, NEVER to good.
    for (const value of ["severe", "", null, undefined]) {
      expect(statusToneOf(value)).toBe("neutral");
    }
  });
});
