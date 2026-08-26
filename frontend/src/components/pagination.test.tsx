import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Pagination } from "./pagination";

describe("Pagination", () => {
  it("renders nothing for a single page", () => {
    const { container } = render(
      <Pagination page={1} totalPages={1} onPageChange={() => {}} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the current page and total", () => {
    render(<Pagination page={3} totalPages={12} onPageChange={() => {}} />);
    expect(screen.getByText("Sayfa 3 / 12")).toBeInTheDocument();
  });

  it("disables First/Previous on the first page", () => {
    render(<Pagination page={1} totalPages={5} onPageChange={() => {}} />);
    expect(screen.getByRole("button", { name: "İlk sayfa" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Önceki sayfa" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Sonraki sayfa" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Son sayfa" })).toBeEnabled();
  });

  it("disables Next/Last on the final page", () => {
    render(<Pagination page={5} totalPages={5} onPageChange={() => {}} />);
    expect(screen.getByRole("button", { name: "Sonraki sayfa" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Son sayfa" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "İlk sayfa" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Önceki sayfa" })).toBeEnabled();
  });

  it("calls onPageChange with the adjacent page on Next/Previous click", async () => {
    const user = userEvent.setup();
    const onPageChange = vi.fn();
    render(<Pagination page={3} totalPages={10} onPageChange={onPageChange} />);

    await user.click(screen.getByRole("button", { name: "Sonraki sayfa" }));
    expect(onPageChange).toHaveBeenLastCalledWith(4);

    await user.click(screen.getByRole("button", { name: "Önceki sayfa" }));
    expect(onPageChange).toHaveBeenLastCalledWith(2);
  });

  it("calls onPageChange with 1 and totalPages on First/Last click", async () => {
    const user = userEvent.setup();
    const onPageChange = vi.fn();
    render(<Pagination page={5} totalPages={20} onPageChange={onPageChange} />);

    await user.click(screen.getByRole("button", { name: "İlk sayfa" }));
    expect(onPageChange).toHaveBeenLastCalledWith(1);

    await user.click(screen.getByRole("button", { name: "Son sayfa" }));
    expect(onPageChange).toHaveBeenLastCalledWith(20);
  });

  it("navigates with the arrow keys and Home/End", async () => {
    const user = userEvent.setup();
    const onPageChange = vi.fn();
    render(<Pagination page={5} totalPages={20} onPageChange={onPageChange} />);

    const nav = screen.getByRole("navigation", { name: "Sayfalama" });
    nav.focus();

    await user.keyboard("{ArrowRight}");
    expect(onPageChange).toHaveBeenLastCalledWith(6);

    await user.keyboard("{ArrowLeft}");
    expect(onPageChange).toHaveBeenLastCalledWith(4);

    await user.keyboard("{Home}");
    expect(onPageChange).toHaveBeenLastCalledWith(1);

    await user.keyboard("{End}");
    expect(onPageChange).toHaveBeenLastCalledWith(20);
  });

  it("clamps a keyboard step past the edge to the edge itself, never beyond it", async () => {
    const user = userEvent.setup();
    const onPageChange = vi.fn();
    render(<Pagination page={1} totalPages={3} onPageChange={onPageChange} />);

    const nav = screen.getByRole("navigation", { name: "Sayfalama" });
    nav.focus();
    // Previous is disabled at page 1, but the keyboard handler has its own
    // clamp -- exercise that path directly rather than trusting the button's
    // disabled attribute alone. ArrowLeft at page 1 clamps to page 1, not 0.
    await user.keyboard("{ArrowLeft}");
    expect(onPageChange).toHaveBeenLastCalledWith(1);
  });
});
