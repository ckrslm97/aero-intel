import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { promotion } from "@/lib/__fixtures__/promotion";
import type { PromotionOut } from "@/lib/types";

import { CampaignDrawer } from "./campaign-drawer";

// The drawer fetches version/source history the moment it opens. These tests
// are about its shell -- Escape, focus -- so both endpoints answer empty.
vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(() => Promise.resolve([])),
}));

const promo = promotion();

/** The drawer as its page actually mounts it: opened by a focusable trigger
 * (a flow card, a table row), closed by nulling the selection. The trigger is
 * in the tree because focus hand-back is half of what is under test. */
function Harness() {
  const [selected, setSelected] = useState<PromotionOut | null>(null);
  return (
    <>
      <button type="button" onClick={() => setSelected(promo)}>
        Kampanyayı aç
      </button>
      <CampaignDrawer
        promotion={selected}
        brandHex="#c90019"
        onClose={() => setSelected(null)}
      />
    </>
  );
}

async function openDrawer(user: ReturnType<typeof userEvent.setup>) {
  const trigger = screen.getByRole("button", { name: "Kampanyayı aç" });
  await user.click(trigger);
  return {
    trigger,
    panel: await screen.findByRole("dialog", { name: "Kampanya ayrıntısı" }),
  };
}

/** AnimatePresence keeps the panel mounted through its exit spring, so
 * "closed" is something to wait for, not assert synchronously. */
async function waitForClosed() {
  await waitFor(
    () => expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    { timeout: 2000 },
  );
}

describe("CampaignDrawer", () => {
  it("closes on Escape", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await openDrawer(user);
    await user.keyboard("{Escape}");

    await waitForClosed();
  });

  it("takes focus when it opens, so the keyboard is in the drawer and not on the page behind it", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    const { panel } = await openDrawer(user);

    expect(panel).toHaveFocus();
  });

  it("hands focus back to the trigger after Escape", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    const { trigger } = await openDrawer(user);
    await user.keyboard("{Escape}");

    await waitForClosed();
    expect(trigger).toHaveFocus();
  });

  it("hands focus back to the trigger after the close button", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    const { trigger } = await openDrawer(user);
    await user.click(screen.getByRole("button", { name: "Kampanyayı kapat" }));

    await waitForClosed();
    expect(trigger).toHaveFocus();
  });
});
