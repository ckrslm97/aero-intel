import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { EventOut } from "@/lib/types";

import { EVENT_RADAR_KEY, EventRadarStrip } from "./event-radar-strip";

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({ apiFetch, API_BASE_URL: "http://test/api/v1" }));

/** The runner's jsdom does not expose `window.localStorage` (Node's own global
 * shadows it and is inert without --localstorage-file), so the persistence
 * this component is about would be untestable without a stand-in. An in-memory
 * Storage is the smallest one that still exercises the real code path -- the
 * component keeps calling `window.localStorage` exactly as it does in a
 * browser, and the same object is what these tests read back. */
function memoryStorage(): Storage {
  const entries = new Map<string, string>();
  return {
    get length() {
      return entries.size;
    },
    key: (index: number) => [...entries.keys()][index] ?? null,
    getItem: (key: string) => entries.get(key) ?? null,
    setItem: (key: string, value: string) => void entries.set(key, String(value)),
    removeItem: (key: string) => void entries.delete(key),
    clear: () => entries.clear(),
  };
}

const event = (id: string, name: string, overrides: Partial<EventOut> = {}): EventOut => ({
  id,
  name,
  starts: "2026-09-10",
  ends: "2026-09-12",
  city: "Berlin",
  country: "Almanya",
  region: "europe",
  url: "https://example.com/event",
  summary_tr: "",
  event_type: "conference",
  date_range_tr: "10-12 Eylül 2026",
  impact_level: "high",
  attendance: null,
  demand_effect_tr: "",
  // The three read-time fields the events endpoint grew: airports the city's
  // traffic actually uses, an importance score that is null whenever the
  // organiser publishes no headcount, and the signed distance to the start.
  relevant_airports: ["BER"],
  importance_score: null,
  days_until: 12,
  ...overrides,
});

const EVENTS = [event("e1", "IFA Berlin"), event("e2", "ITB Berlin")];

describe("EventRadarStrip", () => {
  beforeEach(() => {
    apiFetch.mockReset();
    apiFetch.mockResolvedValue(EVENTS);
    Object.defineProperty(window, "localStorage", {
      value: memoryStorage(),
      configurable: true,
      writable: true,
    });
  });

  it("starts collapsed, showing only a header with the count", async () => {
    // The row is reference material about the next two months; expanded by
    // default it pushed today's news below the fold on every visit.
    render(<EventRadarStrip />);

    expect(await screen.findByText(/2 etkinlik/)).toBeInTheDocument();
    expect(screen.queryByText("IFA Berlin")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /EVENT RADAR/ })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });

  it("expands on click and remembers the choice", async () => {
    const user = userEvent.setup();
    render(<EventRadarStrip />);

    await user.click(await screen.findByRole("button", { name: /EVENT RADAR/ }));

    expect(await screen.findByText("IFA Berlin")).toBeInTheDocument();
    // Same convention as the sidebar's aerointel_sidebar_collapsed.
    expect(window.localStorage.getItem(EVENT_RADAR_KEY)).toBe("true");
  });

  it("restores a stored expansion on the next visit", async () => {
    window.localStorage.setItem(EVENT_RADAR_KEY, "true");
    render(<EventRadarStrip />);

    expect(await screen.findByText("IFA Berlin")).toBeInTheDocument();
  });

  it("remembers a deliberate collapse too", async () => {
    const user = userEvent.setup();
    window.localStorage.setItem(EVENT_RADAR_KEY, "true");
    render(<EventRadarStrip />);

    await user.click(await screen.findByRole("button", { name: /EVENT RADAR/ }));

    expect(window.localStorage.getItem(EVENT_RADAR_KEY)).toBe("false");
  });

  it("opens itself on the Etkinlik view, where the radar is the subject", async () => {
    render(<EventRadarStrip autoExpand />);

    expect(await screen.findByText("IFA Berlin")).toBeInTheDocument();
  });

  it("does not slam shut when the reader leaves the Etkinlik view", async () => {
    const { rerender } = render(<EventRadarStrip autoExpand />);
    expect(await screen.findByText("IFA Berlin")).toBeInTheDocument();

    rerender(<EventRadarStrip autoExpand={false} />);

    // autoExpand only ever opens: a reader who opened the row must not have it
    // closed under them by a tab switch.
    expect(screen.getByText("IFA Berlin")).toBeInTheDocument();
  });

  it("renders nothing at all when there are no events", async () => {
    apiFetch.mockResolvedValue([]);
    const { container } = render(<EventRadarStrip />);

    await waitFor(() => expect(apiFetch).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when the request fails", async () => {
    apiFetch.mockRejectedValue(new Error("boom"));
    const { container } = render(<EventRadarStrip />);

    await waitFor(() => expect(apiFetch).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("shows an airport chip only when the event has curated airports", async () => {
    // `relevant_airports` is empty for entries that are not cities ("Çin
    // geneli", "Küresel") and for a city nobody has curated yet -- resolving
    // those automatically produced wrong airports, so an empty list is the
    // honest answer and it has to render as NO chip. An empty chip rail reads
    // as a loading state that never finished.
    apiFetch.mockResolvedValue([
      event("e1", "IFA Berlin", { relevant_airports: ["BER", "TXL"] }),
      event("e2", "Çin geneli tatil", { relevant_airports: [], city: "Çin geneli" }),
    ]);
    render(<EventRadarStrip autoExpand />);

    expect(await screen.findByText("IFA Berlin")).toBeInTheDocument();
    expect(screen.getByText("BER")).toBeInTheDocument();
    expect(screen.getByText("TXL")).toBeInTheDocument();
    // The second card is on screen; it simply carries no code.
    expect(screen.getByText("Çin geneli tatil")).toBeInTheDocument();
    expect(screen.queryAllByText(/^[A-Z]{3}$/)).toHaveLength(2);
  });

  it("omits the importance score rather than printing a zero for it", async () => {
    // Null means the organiser publishes no headcount, which the backend
    // refuses to score rather than scoring as zero (see
    // backend/app/services/event_scoring.py). "Önem 0.00" would be a claim the
    // system explicitly declined to make.
    apiFetch.mockResolvedValue([
      event("e1", "IFA Berlin", { importance_score: null }),
      event("e2", "ITB Berlin", { importance_score: 0.72 }),
    ]);
    render(<EventRadarStrip autoExpand />);

    expect(await screen.findByText("IFA Berlin")).toBeInTheDocument();
    expect(screen.getByText("Önem 0.72")).toBeInTheDocument();
    expect(screen.queryByText(/Önem 0\.00/)).not.toBeInTheDocument();
    expect(screen.queryAllByText(/^Önem /)).toHaveLength(1);
  });
});
