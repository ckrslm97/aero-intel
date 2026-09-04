import { describe, expect, it } from "vitest";

import { ALERT_STREAMS } from "@/components/kokpit/alert-center";
import { PULSE_STREAMS } from "@/components/kokpit/competitive-pulse";
import { KOKPIT_STREAMS } from "@/components/kokpit/signal-stream";

/** Every stream `/signals` composes, from
 * backend/app/services/signals_service.py STREAMS. Restated here rather than
 * derived, so ADDING a stream to the backend fails this file instead of
 * quietly landing on a page that draws it nowhere. */
const BACKEND_STREAMS = [
  "kokpit",
  "campaign_alerts",
  "risk",
  "rival_events",
  "strategic",
  "network",
  "momentum",
] as const;

/** The Kokpit stream is not in any of the three sets: it does not reach the
 * page as `SignalOut` rows at all. It arrives in its own shape, as
 * `cockpit_tiles`, and is drawn by Market Pulse's bands (section 2) and Günün
 * Özeti (section 4). Named here so "covered by nothing" and "covered
 * elsewhere, on purpose" cannot look the same. */
const DRAWN_AS_TILES = ["kokpit"];

/**
 * ONE FEED, ONE ROW, ONE PLACE.
 *
 * Kokpit and /sinyaller read the same `/signals` response. Kokpit then splits
 * it across three sections by stream. That split has exactly two ways to go
 * wrong, and both are silent:
 *
 *   * a stream in TWO sets is printed twice on one page, so a reader scrolling
 *     Kokpit counts the same alert as two;
 *   * a stream in NO set is dropped from Kokpit without a word, and the only
 *     evidence is a section that looks quiet.
 *
 * Neither shows up in a rendering test, because each component looks correct
 * on its own. It only shows up here.
 */
describe("Kokpit'in sinyal akışını bölüştürmesi", () => {
  const sets: [string, Set<string>][] = [
    ["Sinyal Panosu", KOKPIT_STREAMS],
    ["Alert Merkezi", ALERT_STREAMS],
    ["Rekabet", PULSE_STREAMS],
  ];

  it("covers every stream the backend composes", () => {
    const drawn = new Set([...sets.flatMap(([, set]) => [...set]), ...DRAWN_AS_TILES]);

    expect([...drawn].sort()).toEqual([...BACKEND_STREAMS].sort());
  });

  it("never draws one stream in two sections", () => {
    const seen = new Map<string, string>();
    for (const [section, set] of sets) {
      for (const stream of set) {
        expect(seen.get(stream), `${stream} already drawn by ${seen.get(stream)}`).toBe(
          undefined,
        );
        seen.set(stream, section);
      }
    }
  });

  it("names no stream the backend does not publish", () => {
    // The other direction: a set holding a key that no longer exists is a
    // section that can only ever be empty, and it would read as "nothing is
    // happening in this stream" forever.
    for (const [section, set] of sets) {
      for (const stream of set) {
        expect(BACKEND_STREAMS as readonly string[], section).toContain(stream);
      }
    }
  });
});
