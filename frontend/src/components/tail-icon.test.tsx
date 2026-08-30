import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TailIcon } from "./tail-icon";
import { airlineTabs } from "@/lib/nav";

// The tail fin is what a carrier is drawn with when the logo CDN does not
// answer, so a carrier missing from its colour table degrades to a
// `currentColor` silhouette -- the fallback's own version of the bare "SQ" bug.
describe("TailIcon", () => {
  it.each(airlineTabs.map((a) => [a.code, a.color] as const))(
    "draws %s in its own brand colour",
    (code, color) => {
      const { container } = render(<TailIcon code={code} />);
      const fin = container.querySelector("path");
      expect(fin).not.toBeNull();
      expect(fin!.getAttribute("fill")).toBe(color);
    },
  );

  it("still draws something for a carrier it has never heard of", () => {
    const { container } = render(<TailIcon code="ZZ" />);
    expect(container.querySelector("path")?.getAttribute("fill")).toBe("currentColor");
  });
});
