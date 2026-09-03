import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { NavLinks, navPathname } from "@/components/layout/sidebar";

const mockPathname = vi.hoisted(() => ({ value: "/" }));
vi.mock("next/navigation", () => ({ usePathname: () => mockPathname.value }));

/** The production bug, as a rule.
 *
 * Vercel's runtime ISR re-render of `/` serves an RSC payload whose canonical
 * path is "/index", so the server rendered every nav item inactive while the
 * browser rendered Kokpit active -- two children against four, which is a
 * STRUCTURAL hydration mismatch (React #418) and cost the whole document a
 * client-side re-render.
 *
 * Both halves are pinned: the path is normalised, and -- the part that
 * actually makes the mismatch impossible -- the marker changes classes rather
 * than the shape of the tree, so no future disagreement about the pathname can
 * bring the error back.
 */
describe("nav aktiflik işareti", () => {
  it("/index yolunu / olarak okur", () => {
    expect(navPathname("/index")).toBe("/");
    expect(navPathname("/newspaper")).toBe("/newspaper");
    expect(navPathname("/")).toBe("/");
  });

  function childCounts() {
    return screen
      .getAllByRole("link")
      .map((link) => link.childElementCount);
  }

  it("aktif ve pasif bağlantı aynı sayıda düğüm üretir", () => {
    mockPathname.value = "/index";
    const { unmount } = render(<NavLinks />);
    const inactive = childCounts();
    unmount();

    mockPathname.value = "/";
    render(<NavLinks />);
    const active = childCounts();

    expect(active).toEqual(inactive);
    // ...and the render really did differ, or the assertion above proves
    // nothing: exactly one item must be marked.
    // classList, not a substring test: the INACTIVE class string carries
    // "hover:text-sidebar-accent-foreground", which contains the active token.
    expect(
      screen
        .getAllByRole("link")
        .filter((link) => link.classList.contains("text-sidebar-accent-foreground")),
    ).toHaveLength(1);
  });
});
