import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ArticleDrawerProvider, useArticleDrawer } from "./article-drawer-context";

// The real panel is 500 lines of enrichment rendering and pulls in a lazy
// sources list; what this file is about is whether the drawer is MOUNTED, so a
// stand-in with the same two load-bearing parts -- the dialog and the
// full-viewport backdrop under it -- takes its place.
function PanelStandIn({ onClose }: { onClose: () => void }) {
  return (
    <>
      <div className="fixed inset-0" data-testid="backdrop" />
      <div role="dialog" aria-label="Haber analizi">
        <button type="button" onClick={onClose}>
          Kapat
        </button>
      </div>
    </>
  );
}

// `next/dynamic` resolves its chunk asynchronously, which this file has no
// opinion about: the stand-in is substituted synchronously so the assertions
// are about mounting and unmounting rather than about chunk timing. The
// indirection through a render-time wrapper is what lets the stand-in be
// declared below the mock -- `dynamic()` itself runs at import time, before
// this file's own body.
vi.mock("next/dynamic", () => ({
  default: () => (props: { onClose: () => void }) => <PanelStandIn {...props} />,
}));

const article = { id: "a1", url: "https://example.com/a1" };

function Opener() {
  const { open } = useArticleDrawer();
  return (
    <>
      <button
        type="button"
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        onClick={() => open(article as any)}
      >
        Habere bak
      </button>
      <button type="button">Arkadaki kart</button>
    </>
  );
}

describe("ArticleDrawerProvider", () => {
  it("unmounts the drawer on close instead of keeping it mounted forever", async () => {
    // The provider used to carry an `everOpened` flag that stuck true after the
    // first open, so the drawer stayed mounted for the rest of the session --
    // deliberately, so `AnimatePresence` could play its exit. That exit never
    // completes in this stack, so what actually stayed on screen was a
    // full-viewport `fixed inset-0` backdrop that swallowed every click on the
    // newspaper behind it.
    const user = userEvent.setup();
    render(
      <ArticleDrawerProvider>
        <Opener />
      </ArticleDrawerProvider>,
    );

    expect(screen.queryByTestId("backdrop")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Habere bak" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByTestId("backdrop")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Kapat" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByTestId("backdrop")).not.toBeInTheDocument();

    // The click that used to land on the invisible layer.
    await user.click(screen.getByRole("button", { name: "Arkadaki kart" }));
  });
});
