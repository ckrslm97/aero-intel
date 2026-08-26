import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DataSourceError, LastUpdatedStamp, StaleDataBanner } from "./data-source-error";

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
