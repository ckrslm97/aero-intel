import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { EventOut } from "@/lib/types";

import { EventTimeline } from "./event-timeline";

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({ apiFetch, API_BASE_URL: "http://test/api/v1" }));

function event(overrides: Partial<EventOut> & { id: string; name: string }): EventOut {
  const today = new Date().toISOString().slice(0, 10);
  return {
    starts: today,
    ends: today,
    city: "Berlin",
    country: "Almanya",
    region: "europe",
    url: "https://example.com",
    summary_tr: "",
    event_type: "conference",
    date_range_tr: "10 Eylül 2026",
    impact_level: "medium",
    attendance: null,
    demand_effect_tr: "",
    relevant_airports: [],
    importance_score: null,
    days_until: 0,
    ...overrides,
  };
}

describe("EventTimeline", () => {
  beforeEach(() => {
    apiFetch.mockReset();
    apiFetch.mockResolvedValue([]);
  });

  it("hides the whole block when nothing falls inside the horizon", async () => {
    // The timeline is an ADDITION to the paper, unlike the two news sections,
    // which keep their heading and say the wire was quiet. A labelled empty
    // rail is a heading over nothing.
    const { container } = render(<EventTimeline />);

    await waitFor(() => expect(apiFetch).toHaveBeenCalled());
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("keeps the heading and says so when the request fails", async () => {
    // "Nothing is coming" and "we could not ask" are different statements.
    apiFetch.mockRejectedValue(new Error("boom"));
    render(<EventTimeline />);

    expect(await screen.findByText(/yüklenemedi/)).toBeInTheDocument();
  });

  it("names every event it places, and counts them in the caption", async () => {
    apiFetch.mockResolvedValue([
      event({ id: "e1", name: "Routes World 2026" }),
      event({ id: "e2", name: "MRO Europe 2026" }),
    ]);
    render(<EventTimeline />);

    expect(await screen.findByText(/2 etkinlik/)).toBeInTheDocument();
    // Both names are on the rail -- a bar too narrow to hold its name writes
    // it alongside rather than dropping it.
    expect(screen.getAllByText("Routes World 2026").length).toBeGreaterThan(0);
    expect(screen.getAllByText("MRO Europe 2026").length).toBeGreaterThan(0);
  });

  it("asks the API for its own horizon rather than the whole calendar", async () => {
    render(<EventTimeline />);

    await waitFor(() => expect(apiFetch).toHaveBeenCalled());
    const url = new URL(apiFetch.mock.calls[0][0], "http://test");
    expect(url.searchParams.get("date_from")).toBe(new Date().toISOString().slice(0, 10));
    expect(url.searchParams.get("date_to")).toBeTruthy();
  });
});
