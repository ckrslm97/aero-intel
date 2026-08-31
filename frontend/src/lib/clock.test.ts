import { describe, expect, it } from "vitest";

import { CLOCK_PLACEHOLDER, formatLocalClock, LOCAL_TIME_ZONE } from "@/lib/clock";

// 12:00 UTC on 31 August 2026. İstanbul is UTC+3, so the wall clock reads
// 15:00 -- which is the whole point of the header showing local time: a reader
// comparing it against a "son güncelleme" stamp should not have to add three.
const NOON_UTC = new Date("2026-08-31T12:00:00Z");

describe("topbar clock", () => {
  it("reads İstanbul's wall clock, to the second, in 24-hour form", () => {
    expect(formatLocalClock(NOON_UTC).time).toBe("15:00:00");
  });

  it("writes the date the Turkish short way", () => {
    expect(formatLocalClock(NOON_UTC).date).toBe("31 Ağu 2026");
  });

  it("formats the offset from the zone's own rules rather than hardcoding it", () => {
    // Türkiye has been on a permanent UTC+3 since 2016, so this is a constant
    // today -- and would be silently wrong the day that changes if it were
    // written out as a literal.
    expect(formatLocalClock(NOON_UTC).offset).toBe("GMT+3");
    expect(LOCAL_TIME_ZONE).toBe("Europe/Istanbul");
  });

  it("crosses midnight into the next local day, not the next UTC one", () => {
    // 22:30 UTC on the 31st is 01:30 on 1 September in İstanbul. A header that
    // paired the local time with the UTC date would be wrong for three hours
    // every night.
    const clock = formatLocalClock(new Date("2026-08-31T22:30:00Z"));
    expect(clock.time).toBe("01:30:00");
    expect(clock.date).toBe("1 Eyl 2026");
  });

  it("renders placeholders before the first client tick", () => {
    // The server snapshot is null: it must not render its own clock, in its
    // own zone, only for the browser to replace it a tick later -- that is a
    // hydration mismatch dressed up as a feature.
    expect(formatLocalClock(null)).toEqual(CLOCK_PLACEHOLDER);
    expect(CLOCK_PLACEHOLDER.time).toBe("--:--:--");
  });

  it("falls back to the placeholder for an unusable date", () => {
    expect(formatLocalClock(new Date("nonsense"))).toEqual(CLOCK_PLACEHOLDER);
  });
});
