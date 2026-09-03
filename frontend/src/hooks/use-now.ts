import { useMemo, useSyncExternalStore } from "react";

/** A clock that ticks in the BROWSER, for every claim whose truth changes with
 * time rather than with data.
 *
 * WHY A HOOK AND NOT `new Date()`
 * -------------------------------
 * Kokpit is pre-rendered with `revalidate: 60` (app/page.tsx). A component that
 * reads `new Date()` during render therefore reads the SERVER's clock at
 * pre-render time, and that reading is then frozen into the HTML and served for
 * as long as the cache holds it. Measured on production: markup built from an
 * 18:03 UTC reading was still being served at 18:41 with the header's "Canlı"
 * dot lit -- a liveness claim that had been true when it was computed and was
 * a lie by the time anyone read it.
 *
 * The fix is not a shorter revalidate window. It is that "is this reading still
 * current?" is a question about the READER's clock, so it has to be answered on
 * the reader's machine, and re-answered while they sit there.
 *
 * NULL BEFORE THE FIRST TICK
 * --------------------------
 * The server snapshot is 0 and the hook returns `null` for it, exactly as
 * `formatLocalClock(null)` returns placeholders rather than the server's own
 * time (lib/clock.ts). The first client paint therefore matches the server's
 * markup -- no hydration mismatch -- and, more importantly, a surface holding
 * `null` has NO CLOCK and must not make a freshness claim: it prints the
 * reading's own timestamp and says nothing about whether that timestamp is
 * recent. The tick lands in the effect that runs immediately after mount, so
 * the honest-but-quiet state is a single frame in a real browser, and the
 * permanent state for anything that renders without JavaScript.
 */

/** One minute. Every claim this hook feeds is measured in minutes at its
 * finest (a 30-minute live window, a countdown in days), so a faster tick would
 * buy no accuracy and re-render the page for nothing. */
export const DEFAULT_TICK_MS = 60_000;

interface TickStore {
  subscribe: (listener: () => void) => () => void;
  getSnapshot: () => number;
}

/** One interval per period, shared by every component that asks for it: five
 * cells on one row wanting a minute clock is one `setInterval`, not five. */
const stores = new Map<number, TickStore>();

function storeFor(periodMs: number): TickStore {
  const existing = stores.get(periodMs);
  if (existing) return existing;

  const listeners = new Set<() => void>();
  let value = 0;
  let timer: ReturnType<typeof setInterval> | null = null;

  const store: TickStore = {
    subscribe(listener) {
      listeners.add(listener);
      if (timer === null) {
        // The first reading is taken HERE rather than a whole period later:
        // React re-reads the snapshot immediately after subscribing, so the
        // clock arrives on the commit after mount instead of a minute into
        // the page. Every subsequent reading comes from the interval.
        value = Date.now();
        timer = setInterval(() => {
          value = Date.now();
          for (const notify of listeners) notify();
        }, periodMs);
      }
      return () => {
        listeners.delete(listener);
        if (listeners.size === 0 && timer !== null) {
          clearInterval(timer);
          timer = null;
          // `value` survives so an immediate remount does not flash the
          // no-clock placeholder over a badge that was already earned -- but
          // it survives with an EXPIRY, see `getSnapshot`.
        }
      };
    },
    // A RETAINED reading is only served while it is still current.
    //
    // With no timer running, `value` is frozen at the instant the last
    // listener left. React reads this snapshot during the remount render and
    // commits it BEFORE the subscribe effect can refresh it, so leaving the
    // hut open let a stale clock judge freshness for one committed frame:
    // navigate off Kokpit at 10:00, come back at 13:10, and the first painted
    // frame reported `state === "live"` for a reading three hours old --
    // measured, and precisely the frozen-clock liveness claim this hook was
    // written to kill.
    //
    // A clock that has stopped is the same thing as having no clock, and
    // `pending` is already the honest answer for that: every consumer prints
    // the reading's own stamp and makes no freshness claim. So the retained
    // value expires after one period, which is exactly as long as it would
    // have been trusted had the timer kept running.
    //
    // Gated on `timer === null` on purpose. While the interval is live it
    // refreshes `value` itself, and an unconditional age check would race that
    // interval at every period boundary -- blinking the whole page to
    // `pending` for however long the callback was delayed.
    getSnapshot: () =>
      timer === null && value !== 0 && Date.now() - value >= periodMs ? 0 : value,
  };

  stores.set(periodMs, store);
  return store;
}

const serverSnapshot = () => 0;

/** The current instant, or `null` until the first client tick.
 *
 * `periodMs` is how often the answer is allowed to change, not how precise it
 * is: pass a coarser period for a claim measured in days.
 */
export function useNow(periodMs: number = DEFAULT_TICK_MS): Date | null {
  const store = storeFor(periodMs);
  const millis = useSyncExternalStore(store.subscribe, store.getSnapshot, serverSnapshot);
  // MEMOISED ON THE TICK, not rebuilt per render. `new Date(millis)` is a new
  // identity every time, so every `useMemo` downstream that lists `now` as a
  // dependency -- `buildFxRows` over nine rows with a forecast scan each
  // (kokpit/fx-board-table.tsx), `todayIso` on the campaigns page -- never once
  // hit its cache and re-ran on every unrelated render, which is the exact
  // opposite of why those memos were written. The identity now changes when
  // the clock does and not otherwise.
  return useMemo(() => (millis === 0 ? null : new Date(millis)), [millis]);
}
