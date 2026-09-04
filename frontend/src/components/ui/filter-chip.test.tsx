import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { FilterChip, FilterChipGroup, filterChipClass } from "./filter-chip";

describe("FilterChip", () => {
  it("announces whether it is the chip doing the filtering", async () => {
    // Of the thirty-odd chips on this site, five announced their state. A
    // filter row read as an undifferentiated list of buttons, with no way to
    // hear which one was narrowing the page.
    const onClick = vi.fn();
    const { rerender } = render(
      <FilterChip active={false} onClick={onClick}>
        Avrupa
      </FilterChip>,
    );
    const chip = screen.getByRole("button", { name: "Avrupa" });
    expect(chip).toHaveAttribute("aria-pressed", "false");

    await userEvent.click(chip);
    expect(onClick).toHaveBeenCalledTimes(1);

    rerender(
      <FilterChip active onClick={onClick}>
        Avrupa
      </FilterChip>,
    );
    expect(screen.getByRole("button", { name: "Avrupa" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("lets a chip be named by something other than the word it prints", () => {
    // Nine buttons across this app print the single word "Tümü". A reader
    // tabbing a filter panel heard it over and over with no way to know which
    // axis each one cleared.
    render(
      <>
        <FilterChip active onClick={vi.fn()} label="Tüm taşıyıcılar">
          Tümü
        </FilterChip>
        <FilterChip active={false} onClick={vi.fn()} label="Tüm bölgeler">
          Tümü
        </FilterChip>
      </>,
    );
    expect(screen.getByRole("button", { name: "Tüm taşıyıcılar" })).toHaveTextContent("Tümü");
    expect(screen.getByRole("button", { name: "Tüm bölgeler" })).toHaveTextContent("Tümü");
    // The visible word is unchanged -- this is a naming fix, not a copy change.
    expect(screen.getAllByText("Tümü")).toHaveLength(2);
  });

  it("does not claim a pressed state it does not have", () => {
    // Two call sites are ACTIONS, not toggles: "İstanbul'a dön" out of a dead
    // deep link, and "Temizle" beside the country select. With
    // `active={false}` a screen reader announced them as "toggle button, not
    // pressed", which invites a reader to press them again to un-press
    // something that was never pressed.
    render(
      <>
        <FilterChip onClick={vi.fn()}>Temizle</FilterChip>
        <FilterChip active={false} onClick={vi.fn()}>
          Avrupa
        </FilterChip>
      </>,
    );
    expect(screen.getByRole("button", { name: "Temizle" })).not.toHaveAttribute("aria-pressed");
    // ...and the toggle beside it still does, or this would be a licence to
    // drop the attribute everywhere.
    expect(screen.getByRole("button", { name: "Avrupa" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("carries a visible focus ring and a 24px target, lit or not", () => {
    // The copies this replaces ran as small as `px-2 py-0.5 text-[11px]` -- a
    // 17px tap target -- and five of the seven had no focus ring at all, on
    // pages navigated entirely through chip rows.
    for (const active of [true, false, undefined]) {
      const classes = filterChipClass(active);
      expect(classes).toContain("focus-visible:outline-ring");
      expect(classes).toContain("px-2.5");
      expect(classes).toContain("py-1");
      expect(classes).toContain("min-h-6");
    }
  });
});

describe("FilterChipGroup", () => {
  it("ties the chips to the axis they belong to", async () => {
    // Five such rows stack on the risk radar. Without `role="group"` +
    // `aria-labelledby` the labels are decorative text, and the rows read as
    // five indistinguishable lists of nouns.
    render(
      <>
        <FilterChipGroup label="Bölge">
          <FilterChip active onClick={vi.fn()} label="Tüm bölgeler">
            Tümü
          </FilterChip>
        </FilterChipGroup>
        <FilterChipGroup label="Şiddet" stacked>
          <FilterChip active={false} onClick={vi.fn()}>
            Yüksek
          </FilterChip>
        </FilterChipGroup>
      </>,
    );

    const region = screen.getByRole("group", { name: "Bölge" });
    const severity = screen.getByRole("group", { name: "Şiddet" });
    expect(region).toContainElement(screen.getByRole("button", { name: "Tüm bölgeler" }));
    expect(severity).toContainElement(screen.getByRole("button", { name: "Yüksek" }));
    // Two groups, two distinct labels -- the ids are generated per instance,
    // so two rows on one page cannot borrow each other's name.
    expect(region.getAttribute("aria-labelledby")).not.toBe(
      severity.getAttribute("aria-labelledby"),
    );
  });
});
