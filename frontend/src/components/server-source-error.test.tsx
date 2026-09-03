import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { resetNavigation } from "@/lib/__fixtures__/next-navigation";

import { ServerSourceError } from "./server-source-error";

const refresh = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", async () => ({
  ...(await import("@/lib/__fixtures__/next-navigation")),
  useRouter: () => ({ refresh }),
}));

describe("ServerSourceError", () => {
  beforeEach(() => {
    refresh.mockReset();
    resetNavigation("/");
  });

  it("renders nothing when every source answered", () => {
    // The common case by far. A warning strip that appears on a healthy page
    // is the fastest way to train a reader to ignore warning strips.
    const { container } = render(<ServerSourceError sources={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("names the sources it did not get, and re-runs the server render on retry", async () => {
    // Kokpit is server-rendered, so there is no per-source `retry()` to call --
    // the request that failed happened during the render itself. `router.refresh()`
    // re-runs that render against the same URL, which re-issues exactly the
    // fetches that failed. Naming the sources is what lets a reader see, after
    // the refresh, whether this particular line is still there.
    const user = userEvent.setup();
    render(<ServerSourceError sources={["Kur panosu", "Enerji panosu"]} />);

    expect(
      screen.getByText(/Okunamadı: Kur panosu, Enerji panosu/),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Yeniden dene/ }));
    expect(refresh).toHaveBeenCalledOnce();
  });
});
