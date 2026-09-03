import { describe, expect, it } from "vitest";

import { regionsOf } from "./network-signals";
import type { NetworkSignalGroup, NetworkSignalsOut } from "./types";

const group = (region: string, count: number): NetworkSignalGroup => ({
  region,
  count,
  articles: [],
});

const envelope = (regions: NetworkSignalGroup[]): NetworkSignalsOut => ({
  generated_at: "2026-09-01T00:00:00Z",
  window: { days: 30, since: "2026-08-02T00:00:00Z", until: "2026-09-01T00:00:00Z" },
  regions,
});

/** BOTH SHAPES, FOR AS LONG AS BOTH CAN ARRIVE.
 *
 * `GET /hubs/network-signals` became an envelope so the tab could stamp a real
 * "son güncelleme". The deploy is not atomic: the response is edge-cached for
 * 300s and served stale for 1500 more, so the new bundle can be handed the old
 * bare array for up to half an hour. Reading only `.regions` in that window
 * would show "sinyal yok" over a payload full of signals.
 */
describe("regionsOf", () => {
  it("reads the regions out of the envelope", () => {
    expect(regionsOf(envelope([group("europe", 14)]))).toEqual([group("europe", 14)]);
  });

  it("still understands the pre-envelope array a stale edge can serve", () => {
    expect(regionsOf([group("europe", 14)])).toEqual([group("europe", 14)]);
  });

  it("keeps 'no answer' distinct from 'answered with nothing'", () => {
    // The two states are drawn differently -- an error card versus an empty
    // state -- so flattening null to [] here would tell the caller the source
    // replied when it never did.
    expect(regionsOf(null)).toBeNull();
    expect(regionsOf([])).toEqual([]);
    expect(regionsOf(envelope([]))).toEqual([]);
  });
});
