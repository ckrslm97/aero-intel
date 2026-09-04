import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { DrawerShell } from "./drawer-shell";

/** A page with a trigger and a drawer, wired the way every caller wires it:
 * closed means the shell is not rendered at all. */
function Page() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Aç
      </button>
      <button type="button">Arkadaki düğme</button>
      {open && (
        <DrawerShell onClose={() => setOpen(false)} label="Test çekmecesi">
          <button type="button" onClick={() => setOpen(false)}>
            Kapat
          </button>
          <a href="https://example.com">Kaynak</a>
        </DrawerShell>
      )}
    </>
  );
}

describe("DrawerShell", () => {
  it("leaves nothing behind when it closes", async () => {
    // THE BUG THIS SHELL EXISTS FOR. Wrapped in `AnimatePresence`, the panel's
    // exit animation ran and its completion callback never fired, so the
    // subtree was never unmounted: the panel ended off-screen while its
    // `fixed inset-0` backdrop stayed over the page, swallowing every click
    // after the first close. Nothing may survive the close -- not the dialog,
    // and not the full-screen layer under it.
    const user = userEvent.setup();
    const { container } = render(<Page />);

    await user.click(screen.getByRole("button", { name: "Aç" }));
    expect(screen.getByRole("dialog", { name: "Test çekmecesi" })).toBeInTheDocument();
    expect(container.querySelectorAll(".fixed.inset-0")).toHaveLength(1);

    await user.click(screen.getByRole("button", { name: "Kapat" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(container.querySelectorAll(".fixed.inset-0")).toHaveLength(0);

    // ...and the page behind it is clickable again, which is the thing a
    // reader actually noticed was broken.
    await user.click(screen.getByRole("button", { name: "Arkadaki düğme" }));
  });

  it("moves focus in on open and hands it back on close", async () => {
    const user = userEvent.setup();
    render(<Page />);
    const trigger = screen.getByRole("button", { name: "Aç" });
    trigger.focus();

    await user.click(trigger);
    // The close button is the first focusable inside, and it is where focus
    // lands: it is the one control every reader needs, and it makes Tab start
    // inside the dialog rather than behind it.
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Kapat" }));

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    // Back to the row the reader came from, not to the top of the document.
    expect(document.activeElement).toBe(trigger);
  });

  it("keeps Tab inside the dialog", async () => {
    // `aria-modal="true"` is a promise that the rest of the page is inert.
    // Two of the four drawers this shell replaces made that promise and then
    // let Tab walk straight out into the page behind them.
    const user = userEvent.setup();
    render(<Page />);
    await user.click(screen.getByRole("button", { name: "Aç" }));

    const close = screen.getByRole("button", { name: "Kapat" });
    const link = screen.getByRole("link", { name: "Kaynak" });

    await user.tab();
    expect(document.activeElement).toBe(link);
    await user.tab();
    expect(document.activeElement).toBe(close);
    await user.tab({ shift: true });
    expect(document.activeElement).toBe(link);
  });

  it("counts a <summary> as a stop in the ring", async () => {
    // `summary` is focusable in every browser but matches none of the other
    // selectors, so a panel that grew a `<details>` would have a Tab stop the
    // trap could not see -- and Tab from the last summary would walk straight
    // out of an `aria-modal` dialog. No panel has one today; the selector
    // carries it so that stays true when one does.
    const user = userEvent.setup();
    render(
      <DrawerShell onClose={() => {}} label="Test çekmecesi">
        <button type="button">Kapat</button>
        <details>
          <summary>Kaynaklar</summary>
          <p>Üç kaynak</p>
        </details>
      </DrawerShell>,
    );
    const close = screen.getByRole("button", { name: "Kapat" });
    const summary = screen.getByText("Kaynaklar");
    expect(document.activeElement).toBe(close);

    await user.tab();
    expect(document.activeElement).toBe(summary);
    // The wrap: the summary is the LAST stop, so Tab comes back to the close
    // button instead of leaving the dialog.
    await user.tab();
    expect(document.activeElement).toBe(close);
  });

  it("hands the backdrop the classes its caller gives it", () => {
    // The mobile sidebar is `md:hidden` and the backdrop took no classes from
    // the caller at all, so above `md` the panel vanished while its
    // full-viewport black-and-blur layer stayed over the app. See
    // components/layout/sidebar.test.tsx for the scenario.
    const { container } = render(
      <DrawerShell onClose={() => {}} label="Test çekmecesi" overlayClassName="md:hidden">
        <button type="button">Kapat</button>
      </DrawerShell>,
    );
    expect(container.querySelector(".fixed.inset-0")).toHaveClass("md:hidden");
  });

  it("locks the page behind it and unlocks it again", async () => {
    const user = userEvent.setup();
    render(<Page />);
    expect(document.body.style.overflow).toBe("");

    await user.click(screen.getByRole("button", { name: "Aç" }));
    expect(document.body.style.overflow).toBe("hidden");

    await user.keyboard("{Escape}");
    expect(document.body.style.overflow).toBe("");
  });

  it("does not re-run its focus and lock effect when the caller re-renders", () => {
    // Every drawer's hand-written copy of this effect listed `onClose` in its
    // dependency array, so a caller passing an inline arrow re-ran the whole
    // effect on every render -- and the cleanup, which restores focus, fired
    // with it. That is a drawer that yanks focus back to the card behind it
    // while the reader is in it.
    const outside = document.createElement("button");
    document.body.append(outside);
    outside.focus();

    const { rerender } = render(
      <DrawerShell onClose={() => {}} label="Test çekmecesi">
        <button type="button">Kapat</button>
      </DrawerShell>,
    );
    const close = screen.getByRole("button", { name: "Kapat" });
    expect(document.activeElement).toBe(close);

    close.blur();
    rerender(
      <DrawerShell onClose={() => {}} label="Test çekmecesi">
        <button type="button">Kapat</button>
      </DrawerShell>,
    );
    // A new `onClose` identity, and focus has NOT been thrown back outside.
    expect(document.activeElement).not.toBe(outside);
    outside.remove();
  });

  it("calls the CURRENT onClose, not the one it mounted with", async () => {
    // The flip side of not depending on `onClose`: the handler is read through
    // a ref, so a caller that swaps it still gets the new one on Escape.
    const user = userEvent.setup();
    const first = vi.fn();
    const second = vi.fn();
    const { rerender } = render(
      <DrawerShell onClose={first} label="Test çekmecesi">
        <button type="button">Kapat</button>
      </DrawerShell>,
    );
    rerender(
      <DrawerShell onClose={second} label="Test çekmecesi">
        <button type="button">Kapat</button>
      </DrawerShell>,
    );

    await user.keyboard("{Escape}");
    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledTimes(1);
  });
});
