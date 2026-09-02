import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { SignalOut } from "@/lib/types";

import { KOKPIT_STREAMS, SignalStream, selectStreamSignals } from "./signal-stream";

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({ apiFetch, API_BASE_URL: "http://test/api/v1" }));

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
    href: "/sinyaller",
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
      signal({ id: "a", stream: "kokpit" }), // -> Günün Özeti
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
});

describe("SignalStream", () => {
  beforeEach(() => {
    apiFetch.mockReset();
  });

  /** `/signals` answers with an envelope, not a bare array.
   *
   * This is a REGRESSION LOCK, and it is mounted rather than pure on purpose.
   * The selector above is a pure function over `SignalOut[]`, so it stays
   * green no matter what the component actually hands it -- the component
   * originally declared the response as `SignalOut[]`, which type-checked,
   * linted and passed every test on this page while throwing
   * "rows.filter is not a function" the first time the real API answered.
   * Only a test that feeds the endpoint's TRUE shape can catch that.
   */
  it("reads the signals out of the endpoint's envelope", async () => {
    apiFetch.mockResolvedValue({
      days: 30,
      total: 2,
      streams: [],
      generated_at: "2026-09-02T08:00:00Z",
      signals: [
        signal({ id: "a", stream: "kokpit", title_tr: "Kur Riski" }),
        signal({ id: "b", stream: "rival_events", title_tr: "QR yeni hat: DOH–MXP" }),
      ],
    });

    render(<SignalStream />);

    expect(await screen.findByText("QR yeni hat: DOH–MXP")).toBeInTheDocument();
    // ...and the envelope's other streams are still filtered out.
    expect(screen.queryByText("Kur Riski")).not.toBeInTheDocument();
  });

  it("shows the empty note when the envelope carries neither stream", async () => {
    apiFetch.mockResolvedValue({
      days: 30,
      total: 1,
      streams: [],
      generated_at: "2026-09-02T08:00:00Z",
      signals: [signal({ id: "a", stream: "risk" })],
    });

    render(<SignalStream />);

    expect(
      await screen.findByText("Rakip olayı veya stratejik gelişme sinyali yok."),
    ).toBeInTheDocument();
  });
});
