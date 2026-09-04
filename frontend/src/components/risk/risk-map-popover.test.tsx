import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { riskItem } from "@/lib/__fixtures__/risk";

import { RiskMapPopover } from "./risk-map-popover";

/** A map row that opens the popover, wired the way risk-map.tsx wires it:
 * closed means the popover is not rendered at all. The trigger stands in for
 * the marker, which in production is painted into a canvas and has no DOM node
 * of its own. */
function Page() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        İşaretçi
      </button>
      <button type="button">Arkadaki düğme</button>
      {open && (
        <RiskMapPopover
          anchor={{ x: 100, below: 200, above: 180 }}
          country="Yunanistan"
          city="Rodos"
          items={[
            riskItem({ id: "r1", headline: "Rodos'ta yangın" }),
            riskItem({ id: "r2", headline: "Atina'da grev" }),
          ]}
          onSelect={() => {}}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}

/** THE DEFECT. This panel declared `role="dialog" aria-modal="true"` -- a
 * promise to a screen reader that the rest of the page is inert -- and
 * implemented Escape and nothing else. Tab walked straight out into the page
 * behind it, and on close focus fell to `<body>`, so a keyboard reader who
 * opened a marker could not get back to the map they came from. It now runs
 * the same `lib/focus-trap.ts` the drawers run. */
describe("risk haritası popover'ı", () => {
  it("aria-modal sözünü tutar: Tab dışarı çıkmaz", async () => {
    const user = userEvent.setup();
    render(<Page />);
    await user.click(screen.getByRole("button", { name: "İşaretçi" }));

    const panel = screen.getByRole("dialog");
    // Focus lands on the panel, not on row one: a marker can stand for eight
    // events, and pre-selecting the first would have a reader hear a single
    // headline where the useful fact is that there are eight.
    expect(document.activeElement).toBe(panel);

    const close = screen.getByRole("button", { name: "Listeyi kapat" });
    const behind = screen.getByRole("button", { name: "Arkadaki düğme" });

    await user.tab();
    expect(document.activeElement).toBe(close);
    await user.tab();
    expect(panel).toContainElement(document.activeElement as HTMLElement);
    await user.tab();
    expect(panel).toContainElement(document.activeElement as HTMLElement);
    // The wrap, and the negative half of it: three Tab presses past the last
    // row never reach the page underneath.
    await user.tab();
    expect(document.activeElement).toBe(close);
    expect(document.activeElement).not.toBe(behind);
  });

  it("kapanınca odağı geldiği satıra iade eder", async () => {
    const user = userEvent.setup();
    render(<Page />);
    const trigger = screen.getByRole("button", { name: "İşaretçi" });
    trigger.focus();
    await user.click(trigger);
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    // Not `<body>`: the row the reader opened.
    expect(document.activeElement).toBe(trigger);
  });

  it("arkasındaki sayfayı kaydırılamaz yapar ve geri açar", async () => {
    const user = userEvent.setup();
    render(<Page />);
    expect(document.body.style.overflow).toBe("");

    await user.click(screen.getByRole("button", { name: "İşaretçi" }));
    // The panel is positioned from the click's viewport coordinates -- a
    // scrolling page behind it would slide the marker out from under it.
    expect(document.body.style.overflow).toBe("hidden");

    await user.keyboard("{Escape}");
    expect(document.body.style.overflow).toBe("");
  });
});
