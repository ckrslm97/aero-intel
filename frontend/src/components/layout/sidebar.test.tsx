import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { MobileSidebar, NavLinks, navPathname } from "@/components/layout/sidebar";

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

/** The mobile menu, wired the way `app-shell.tsx` wires it. */
function Shell() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Menü
      </button>
      <MobileSidebar open={open} onClose={() => setOpen(false)} />
    </>
  );
}

describe("mobil menü", () => {
  it("kapanınca geriye görünmez bir tıklama bariyeri bırakmaz", async () => {
    // The menu was the app's only true modal and its `AnimatePresence` exit
    // never completes in this stack, so the first close left a full-viewport
    // backdrop over the page. On a phone that reads as the app having locked
    // up: every later tap lands on an invisible black layer.
    mockPathname.value = "/";
    const user = userEvent.setup();
    const { container } = render(<Shell />);

    await user.click(screen.getByRole("button", { name: "Menü" }));
    expect(container.querySelectorAll(".fixed.inset-0")).toHaveLength(1);

    await user.click(screen.getByRole("button", { name: "Menüyü kapat" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(container.querySelectorAll(".fixed.inset-0")).toHaveLength(0);
  });

  it("bir diyalogdur ve adı vardır", async () => {
    // It covers the page and takes a tap outside to dismiss, and it used to
    // say none of that: no role, no `aria-modal`, no accessible name, no
    // Escape. A screen reader user was handed a list of links with no way to
    // know they were in an overlay, and no way to leave it.
    mockPathname.value = "/";
    const user = userEvent.setup();
    render(<Shell />);
    const trigger = screen.getByRole("button", { name: "Menü" });
    trigger.focus();
    await user.click(trigger);

    expect(screen.getByRole("dialog", { name: "Ana menü" })).toBeInTheDocument();
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: "Menüyü kapat" }),
    );

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(document.activeElement).toBe(trigger);
  });
});
