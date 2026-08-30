import { describe, expect, it } from "vitest";

import { airlineTabs } from "@/lib/nav";
import { CARRIER_CODES, CARRIER_NAMES, RIVAL_CODES } from "@/lib/taxonomy.gen";

// Why these exist: Singapore Airlines was added to the backend's carrier
// master, started producing campaigns, and rendered on the Kampanyalar page as
// the bare string "SQ" in the default accent colour -- because the carrier set
// was written out twice and only a hand-copied literal connected them. nav.ts
// now throws at import time when a backend carrier has no brand entry; these
// tests are what make that throw a red test rather than a red page, and they
// check the two things the throw cannot: that the identity is real rather than
// a placeholder, and that no two carriers claim the same colour.
describe("carrier brand identity", () => {
  it("covers every carrier the backend can attribute a campaign to", () => {
    const branded = new Set(airlineTabs.map((a) => a.code));
    expect(CARRIER_CODES.filter((code) => !branded.has(code))).toEqual([]);
  });

  it("brands nobody the backend does not know", () => {
    const known = new Set<string>(CARRIER_CODES);
    expect(airlineTabs.filter((a) => !known.has(a.code))).toEqual([]);
  });

  it("gives every carrier a real name and a real hex", () => {
    for (const airline of airlineTabs) {
      // The name is the backend's, so a carrier cannot silently fall back to
      // its own IATA code the way SQ did.
      expect(airline.name).toBe(CARRIER_NAMES[airline.code]);
      expect(airline.name).not.toBe(airline.code);
      expect(airline.color).toMatch(/^#[0-9a-f]{6}$/);
    }
  });

  it("gives each carrier a colour of its own", () => {
    const colors = airlineTabs.map((a) => a.color);
    expect(new Set(colors).size).toBe(colors.length);
  });

  it("can draw every rival the Gazete's aggregate chip stands for", () => {
    const branded = new Set<string>(airlineTabs.map((a) => a.code));
    expect(RIVAL_CODES.filter((code) => !branded.has(code))).toEqual([]);
  });

  it("keeps Singapore Airlines branded, not bare", () => {
    // The reported bug, pinned: name, hex and -- via the code, which is all
    // components/airline-logo.tsx needs -- a logo.
    const sq = airlineTabs.find((a) => a.code === "SQ");
    expect(sq).toEqual({ code: "SQ", name: "Singapore Airlines", color: "#1d4886" });
  });
});
