import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { filterSignals, NO_FILTERS } from "@/lib/signals";
import type { SignalOut } from "@/lib/types";

import { KOKPIT_STREAMS, SignalStream, selectStreamSignals } from "./signal-stream";

const signal = (overrides: Partial<SignalOut> = {}): SignalOut =>
  ({
    id: "s1",
    stream: "rival_events",
    kind: "competitor",
    kind_label_tr: "Rakip",
    type_label_tr: "Yeni hat",
    severity: "medium",
    severity_label_tr: "Orta",
    severity_basis_tr: "…",
    title_tr: "QR yeni hat duyurusu: DOH–MXP",
    detail_tr: null,
    region: "europe",
    airline_codes: ["QR"],
    detected_at: "2026-08-30T17:00:00Z",
    confidence_score: null,
    source_label: "Reuters",
    href: "/newspaper?airline=QR",
    ...overrides,
  }) as SignalOut;

describe("selectStreamSignals", () => {
  it("carries exactly the two streams that have nowhere else on the page", () => {
    // Too narrow and the board is permanently empty; too wide and it reprints
    // the Alert Merkezi two sections below it. Both failures are silent.
    expect([...KOKPIT_STREAMS].sort()).toEqual(["rival_events", "strategic"]);
  });

  it("drops the five streams that are already rendered elsewhere", () => {
    const rows = selectStreamSignals([
      signal({ id: "a", stream: "kokpit" }), // -> Market Pulse + Günün Özeti
      signal({ id: "b", stream: "campaign_alerts" }), // -> Alert Merkezi
      signal({ id: "c", stream: "risk" }), // -> Alert Merkezi
      signal({ id: "d", stream: "network" }), // -> Rekabet
      signal({ id: "e", stream: "momentum" }), // -> Rekabet
      signal({ id: "f", stream: "rival_events" }),
      signal({ id: "g", stream: "strategic" }),
    ]);
    expect(rows.map((row) => row.id)).toEqual(["f", "g"]);
  });

  it("keeps the backend's own ordering rather than re-sorting", () => {
    // `sort_signals` ranks severity and recency together; re-sorting here
    // would make this board and /sinyaller disagree about what matters most.
    const rows = selectStreamSignals([
      signal({ id: "low", severity: "low", stream: "strategic" }),
      signal({ id: "high", severity: "high", stream: "rival_events" }),
    ]);
    expect(rows.map((row) => row.id)).toEqual(["low", "high"]);
  });

  it("caps the board at six rows", () => {
    const rows = selectStreamSignals(
      Array.from({ length: 12 }, (_, i) => signal({ id: `s${i}` })),
    );
    expect(rows).toHaveLength(6);
  });

  it("has nothing to show when neither stream produced anything", () => {
    expect(selectStreamSignals([signal({ stream: "risk" })])).toEqual([]);
  });

  /** THE POINT OF THE WHOLE ROUND, as an assertion.
   *
   * Kokpit and /sinyaller read the same `/signals` response. This board is a
   * prefix of the rows /sinyaller draws for the same two streams -- same
   * objects, same order, no second sort anywhere. If either surface ever
   * re-ranks, this is what fails. */
  it("shows a prefix of what /sinyaller shows, in the same order", () => {
    const feed = [
      signal({ id: "1", stream: "strategic", severity: "high" }),
      signal({ id: "2", stream: "kokpit" }),
      signal({ id: "3", stream: "rival_events", severity: "medium" }),
      signal({ id: "4", stream: "risk" }),
      signal({ id: "5", stream: "strategic", severity: "low" }),
    ];

    const board = selectStreamSignals(feed).map((row) => row.id);
    // What /sinyaller lists, unfiltered, restricted to the same two streams.
    const page = filterSignals(feed, NO_FILTERS)
      .filter((row) => KOKPIT_STREAMS.has(row.stream))
      .map((row) => row.id);

    expect(board).toEqual(page.slice(0, board.length));
  });
});

describe("SignalStream", () => {
  it("draws only its two streams out of the list it is handed", () => {
    render(
      <SignalStream
        signals={[
          signal({ id: "a", stream: "kokpit", title_tr: "Kur Riski" }),
          signal({ id: "b", stream: "rival_events", title_tr: "QR yeni hat: DOH–MXP" }),
        ]}
      />,
    );

    expect(screen.getByText("QR yeni hat: DOH–MXP")).toBeInTheDocument();
    expect(screen.queryByText("Kur Riski")).not.toBeInTheDocument();
  });

  it("shows the empty note when the list carries neither stream", () => {
    render(<SignalStream signals={[signal({ id: "a", stream: "risk" })]} />);

    expect(
      screen.getByText("Rakip olayı veya stratejik gelişme sinyali yok."),
    ).toBeInTheDocument();
  });

  it("says how many it cut, rather than looking complete", () => {
    // A board that quietly showed six of nineteen would read as "these are all
    // of them" -- the one thing a truncated list must never do.
    render(
      <SignalStream
        signals={Array.from({ length: 9 }, (_, i) =>
          signal({ id: `s${i}`, title_tr: `Sinyal ${i}` }),
        )}
      />,
    );

    expect(screen.getByText(/9 sinyalden ilk 6 tanesi/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Tümü Sinyaller/ })).toHaveAttribute(
      "href",
      "/sinyaller",
    );
  });

  it("stays silent about truncation when nothing was cut", () => {
    render(
      <SignalStream
        signals={Array.from({ length: 2 }, (_, i) => signal({ id: `s${i}` }))}
      />,
    );

    expect(screen.queryByText(/tanesi/)).not.toBeInTheDocument();
  });

  it("prints a dash rather than a time for an undated signal", () => {
    render(<SignalStream signals={[signal({ id: "a", detected_at: null })]} />);

    expect(screen.getByText("—")).toBeInTheDocument();
  });
});
