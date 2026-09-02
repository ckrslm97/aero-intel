import { describe, expect, it } from "vitest";

import {
  dayDelta,
  daysUntilTr,
  layoutEvents,
  MAX_EVENT_DAYS,
  monthsIn,
  shiftDay,
} from "./event-timeline";
import type { EventOut } from "./types";

function event(overrides: Partial<EventOut> & { id: string }): EventOut {
  return {
    name: "Etkinlik",
    starts: "2026-09-10",
    ends: "2026-09-10",
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

const FROM = "2026-09-01";

describe("day arithmetic", () => {
  it("counts calendar days, not 24-hour blocks across a DST boundary", () => {
    // Anchored at midday UTC: `new Date("2026-10-26")` is midnight, which is
    // the previous day for every reader west of Greenwich, and an event would
    // silently start a day early for them.
    expect(dayDelta("2026-10-24", "2026-10-27")).toBe(3);
    expect(dayDelta("2026-09-01", "2026-09-01")).toBe(0);
    expect(dayDelta("2026-09-05", "2026-09-01")).toBe(-4);
  });

  it("shifts across a month boundary", () => {
    expect(shiftDay("2026-08-30", 3)).toBe("2026-09-02");
  });
});

describe("layoutEvents", () => {
  it("walks a multi-day event out across every day it occupies", () => {
    // The month grid painted a five-day fair into five cells; the rail draws
    // it as one bar five columns wide. Same walk, one dimension.
    const layout = layoutEvents(
      [event({ id: "e1", starts: "2026-09-10", ends: "2026-09-14" })],
      { from: FROM, days: 30 },
    );

    expect(layout.placed).toHaveLength(1);
    expect(layout.placed[0].startIndex).toBe(9);
    expect(layout.placed[0].span).toBe(5);
    expect(layout.placed[0].isStart).toBe(true);
  });

  it("draws a run already under way as a continuation, with no name plate", () => {
    // Its name was stated on a day the reader cannot see, so repeating it at
    // the window's edge would claim the event starts today.
    const layout = layoutEvents(
      [event({ id: "e1", starts: "2026-08-28", ends: "2026-09-04" })],
      { from: FROM, days: 30 },
    );

    expect(layout.placed[0].isStart).toBe(false);
    // Clipped to the window: four days of the run are visible, not eight.
    expect(layout.placed[0].startIndex).toBe(0);
    expect(layout.placed[0].span).toBe(4);
  });

  it("clips a run that overflows the far end of the window", () => {
    const layout = layoutEvents(
      [event({ id: "e1", starts: "2026-09-28", ends: "2026-10-20" })],
      { from: FROM, days: 30 },
    );

    expect(layout.placed[0].startIndex).toBe(27);
    expect(layout.placed[0].span).toBe(3);
  });

  it("drops events entirely outside the window in either direction", () => {
    const layout = layoutEvents(
      [
        event({ id: "past", starts: "2026-07-01", ends: "2026-07-05" }),
        event({ id: "future", starts: "2027-01-01", ends: "2027-01-05" }),
      ],
      { from: FROM, days: 30 },
    );

    expect(layout.placed).toHaveLength(0);
    expect(layout.lanes).toBe(0);
  });

  it("refuses a row whose end precedes its start", () => {
    // Corrupt, not a zero-length event -- and the month grid's day-by-day walk
    // would have spun on it.
    const layout = layoutEvents(
      [event({ id: "e1", starts: "2026-09-10", ends: "2026-09-02" })],
      { from: FROM, days: 30 },
    );

    expect(layout.placed).toHaveLength(0);
  });

  it("caps a run that claims to last for decades", () => {
    // A malformed `ends` must not draw a bar the width of the page.
    const layout = layoutEvents(
      [event({ id: "e1", starts: "2026-09-02", ends: "2046-09-02" })],
      { from: FROM, days: 400 },
    );

    expect(layout.placed[0].span).toBe(MAX_EVENT_DAYS);
  });

  it("stacks overlapping events into lanes and leaves a column between them", () => {
    const layout = layoutEvents(
      [
        event({ id: "a", starts: "2026-09-02", ends: "2026-09-06" }),
        event({ id: "b", starts: "2026-09-04", ends: "2026-09-08" }),
        // Starts the day AFTER `a` ends -- adjacent, with no clear column
        // between them. It may not inherit a's lane: two bars that merely
        // touch read as one continuous bar.
        event({ id: "c", starts: "2026-09-07", ends: "2026-09-08" }),
      ],
      { from: FROM, days: 30 },
    );

    const lane = (id: string) => layout.placed.find((p) => p.event.id === id)!.lane;
    expect(lane("a")).toBe(0);
    expect(lane("b")).toBe(1);
    expect(lane("c")).toBe(2);
    expect(layout.lanes).toBe(3);
  });

  it("reuses a lane once a full day has cleared", () => {
    const layout = layoutEvents(
      [
        event({ id: "a", starts: "2026-09-02", ends: "2026-09-06" }),
        // One empty column (09-07) between them, which is the gap the packing
        // asks for.
        event({ id: "b", starts: "2026-09-08", ends: "2026-09-09" }),
      ],
      { from: FROM, days: 30 },
    );

    expect(layout.placed.map((p) => p.lane)).toEqual([0, 0]);
    expect(layout.lanes).toBe(1);
  });

  it("reserves room for a name written beside a bar too narrow to hold it", () => {
    // Most curated events run one to four days, so their bar cannot hold
    // "Aviation Africa Summit 2026" and the component writes it alongside.
    // Without the reservation the label would be drawn straight over the next
    // bar in the same lane -- the bars themselves do not overlap at all here.
    const items = [
      event({ id: "a", name: "Uzun Adlı Etkinlik", starts: "2026-09-02", ends: "2026-09-02" }),
      event({ id: "b", name: "Sonraki", starts: "2026-09-06", ends: "2026-09-06" }),
    ];

    expect(layoutEvents(items, { from: FROM, days: 30 }).lanes).toBe(1);
    // `reserve` returns the TOTAL columns the pair needs -- the bar plus the
    // label that follows it -- because the label is written after the bar, not
    // over it. Thirteen columns from a one-column bar reaches past `b`.
    expect(
      layoutEvents(items, { from: FROM, days: 30, reserve: (_e, span) => span + 12 }).lanes,
    ).toBe(2);
  });

  it("puts a genuinely later event back in the first lane", () => {
    const layout = layoutEvents(
      [
        event({ id: "a", starts: "2026-09-02", ends: "2026-09-03" }),
        event({ id: "b", starts: "2026-09-10", ends: "2026-09-11" }),
      ],
      { from: FROM, days: 30 },
    );

    expect(layout.placed.map((p) => p.lane)).toEqual([0, 0]);
    expect(layout.lanes).toBe(1);
  });

  it("orders two events that start the same day by run length, then by name", () => {
    // The sort has to be TOTAL, or two same-day events swap lanes between
    // renders for no reason the reader can see.
    const layout = layoutEvents(
      [
        event({ id: "short", name: "Bravo", starts: "2026-09-05", ends: "2026-09-05" }),
        event({ id: "long", name: "Alfa", starts: "2026-09-05", ends: "2026-09-09" }),
      ],
      { from: FROM, days: 30 },
    );

    expect(layout.placed.map((p) => p.event.id)).toEqual(["long", "short"]);
  });
});

describe("month bands", () => {
  it("clips the first and last month to the window", () => {
    // A header spanning all of September while only its last week is visible
    // would misstate the axis it labels.
    const months = monthsIn("2026-09-25", 40);

    expect(months.map((m) => m.key)).toEqual(["2026-09", "2026-10", "2026-11"]);
    expect(months[0]).toMatchObject({ startIndex: 0, span: 6 });
    expect(months[1]).toMatchObject({ startIndex: 6, span: 31 });
    expect(months[2]).toMatchObject({ startIndex: 37, span: 3 });
    expect(months[0].label).toBe("Eylül 2026");
  });
});

describe("daysUntilTr", () => {
  it("reads the backend's signed number rather than recomputing it", () => {
    expect(daysUntilTr(0)).toBe("bugün");
    expect(daysUntilTr(1)).toBe("yarın");
    expect(daysUntilTr(9)).toBe("9 gün sonra");
    // Negative for an event already under way, which the calendar keeps
    // because it filters on the end date.
    expect(daysUntilTr(-3)).toBe("3 gün önce başladı");
  });
});
