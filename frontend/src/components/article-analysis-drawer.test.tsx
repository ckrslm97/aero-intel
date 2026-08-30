import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { article } from "@/lib/__fixtures__/article";
import type { ArticleOut } from "@/lib/types";

import { ArticleAnalysisDrawer } from "./article-analysis-drawer";

const story = article();

/** The drawer as article-drawer-context actually mounts it: opened by a
 * focusable trigger (an article card), closed by nulling the selection. The
 * trigger is in the tree because focus hand-back is half of what is under
 * test. */
function Harness() {
  const [selected, setSelected] = useState<ArticleOut | null>(null);
  return (
    <>
      <button type="button" onClick={() => setSelected(story)}>
        Haberi aç
      </button>
      <ArticleAnalysisDrawer article={selected} onClose={() => setSelected(null)} />
    </>
  );
}

async function openDrawer(user: ReturnType<typeof userEvent.setup>) {
  const trigger = screen.getByRole("button", { name: "Haberi aç" });
  await user.click(trigger);
  return {
    trigger,
    panel: await screen.findByRole("dialog", { name: "Haber analizi" }),
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

describe("ArticleAnalysisDrawer", () => {
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
    await user.click(screen.getByRole("button", { name: "Analizi kapat" }));

    await waitForClosed();
    expect(trigger).toHaveFocus();
  });
});
