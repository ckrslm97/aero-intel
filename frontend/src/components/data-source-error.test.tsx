import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  DataSourceError,
  InlineSourceError,
  LastUpdatedStamp,
  StaleDataBanner,
} from "./data-source-error";

describe("DataSourceError", () => {
  it("shows the honest empty-source message and calls onRetry on click", async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    render(<DataSourceError onRetry={onRetry} lastUpdated={null} />);

    expect(screen.getByText("Veri geçici olarak kullanılamıyor.")).toBeInTheDocument();
    // No prior successful fetch -- nothing dishonest to claim about "last time".
    expect(screen.queryByText(/Son başarılı güncelleme/)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Yeniden dene/ }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("shows the last successful time when one exists", () => {
    render(<DataSourceError onRetry={() => {}} lastUpdated={new Date("2026-08-26T14:30:00Z")} />);
    expect(screen.getByText(/Son başarılı güncelleme: 14:30 UTC/)).toBeInTheDocument();
  });

  // A retry that is running looks exactly like one that was never clicked
  // unless the button says so -- and the reader, reading a screen that has not
  // changed, clicks again. `pending` is useDataSource's own in-flight flag, so
  // the label is a report about a real request rather than a timed animation.
  it("reports a retry that is still in flight, and refuses to fire a second one", async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    render(<DataSourceError onRetry={onRetry} lastUpdated={null} pending />);

    const button = screen.getByRole("button", { name: /Deneniyor/ });
    expect(button).toBeDisabled();
    await user.click(button);
    expect(onRetry).not.toHaveBeenCalled();
  });

  it("offers a plain retry while nothing is in flight", async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    render(<DataSourceError onRetry={onRetry} lastUpdated={null} pending={false} />);

    const button = screen.getByRole("button", { name: /Yeniden dene/ });
    expect(button).toBeEnabled();
    await user.click(button);
    expect(onRetry).toHaveBeenCalledOnce();
  });
});

describe("StaleDataBanner", () => {
  it("reads as stale, not as a fresh update, and offers retry", async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    render(<StaleDataBanner onRetry={onRetry} lastUpdated={new Date("2026-08-26T09:15:00Z")} />);

    expect(screen.getByText(/Güncellenemedi/)).toBeInTheDocument();
    expect(screen.getByText(/09:15 UTC/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Yeniden dene/ }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("says the refresh is running while it runs", () => {
    render(
      <StaleDataBanner
        onRetry={() => {}}
        lastUpdated={new Date("2026-08-26T09:15:00Z")}
        pending
      />,
    );

    // Still the stale wording next to it: old data is on screen, and a request
    // being in flight does not make it fresh.
    expect(screen.getByText(/Güncellenemedi/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Deneniyor/ })).toBeDisabled();
  });
});

describe("LastUpdatedStamp", () => {
  it("renders nothing without a date -- never a fabricated timestamp", () => {
    const { container } = render(<LastUpdatedStamp date={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders the UTC time when a date is given", () => {
    render(<LastUpdatedStamp date={new Date("2026-08-26T16:45:00Z")} />);
    expect(screen.getByText("Son güncelleme: 16:45 UTC")).toBeInTheDocument();
  });
});

describe("InlineSourceError", () => {
  it("says the source was not read, and can be asked again in place", async () => {
    // The branch that exists so a counting surface never has to fall back to a
    // number. Where `DataSourceError` would push the page around -- a table
    // cell, a filter strip, a drawer section -- this is what says the same
    // thing in one line.
    const user = userEvent.setup();
    const onRetry = vi.fn();
    render(<InlineSourceError message="Gün sayaçları okunamadı." onRetry={onRetry} />);

    expect(screen.getByRole("status")).toHaveTextContent("Gün sayaçları okunamadı.");
    await user.click(screen.getByRole("button", { name: /Yeniden dene/ }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("reports a retry that is still running, like every other retry in the app", () => {
    render(<InlineSourceError message="Okunamadı." onRetry={() => {}} pending />);
    expect(screen.getByRole("button", { name: /Deneniyor/ })).toBeDisabled();
  });

  it("renders no control where the surface genuinely cannot re-ask", () => {
    // Omitting `onRetry` is a statement about the surface, not a shortcut: a
    // button that cannot do anything is worse than no button.
    render(<InlineSourceError message="Okunamadı." />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Okunamadı.");
  });
});
