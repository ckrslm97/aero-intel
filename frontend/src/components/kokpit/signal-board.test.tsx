import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { CockpitSignal } from "@/lib/types";

import { SignalBoard } from "./signal-board";

const signal = (overrides: Partial<CockpitSignal> = {}): CockpitSignal => ({
  key: "fx",
  label_tr: "Kur Riski",
  level: "warning",
  level_label_tr: "Dikkat",
  value_label: "+%3,4",
  reason_tr: "USD/TRY 41,72 · 30 günde +%3,4.",
  method_tr: "Mutlak 30 günlük değişim bantlanır.",
  source: "Yahoo Finance",
  source_url: "https://finance.yahoo.com",
  href: "/kpi/fx_usd_try",
  as_of: "2026-08-30T11:00:00Z",
  ...overrides,
});

describe("SignalBoard", () => {
  it("prints the driver, its band and the reason together", () => {
    render(<SignalBoard signals={[signal()]} />);

    expect(screen.getByText("Kur Riski")).toBeInTheDocument();
    expect(screen.getByText("+%3,4")).toBeInTheDocument();
    expect(screen.getByText("Dikkat")).toBeInTheDocument();
    expect(screen.getByText(/30 günde/)).toBeInTheDocument();
  });

  it("makes the method and the source reachable without leaving the tile", () => {
    render(<SignalBoard signals={[signal()]} />);

    const note = screen.getByText(/Yöntem/);
    expect(note).toHaveAttribute("title", expect.stringContaining("bantlanır"));
    expect(note).toHaveAttribute("title", expect.stringContaining("Yahoo Finance"));
  });

  it("links a tile to its own page when there is one, and does not fake one otherwise", () => {
    const { rerender } = render(<SignalBoard signals={[signal({ href: "/risk-radari" })]} />);
    expect(screen.getByRole("link")).toHaveAttribute("href", "/risk-radari");

    rerender(<SignalBoard signals={[signal({ href: null })]} />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("shows an unreadable driver as neutral, never as an all-clear", () => {
    render(
      <SignalBoard
        signals={[signal({ level: "unknown", level_label_tr: "Veri yok", value_label: "—" })]}
      />,
    );
    const pill = screen.getByText("Veri yok");
    expect(pill.className).toContain("muted");
    expect(pill.className).not.toContain("text-good");
  });

  it("says so plainly when there are no signals at all", () => {
    render(<SignalBoard signals={[]} />);
    expect(screen.getByText(/hesaplanamıyor/)).toBeInTheDocument();
  });
});
