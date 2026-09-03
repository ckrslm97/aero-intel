import { act, render, screen } from "@testing-library/react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useNow } from "./use-now";

/** Each test asks for its own period, which gives it its own interval and its
 * own module-level store -- otherwise a fake-timer test would inherit the
 * value a real-timer test left behind. */
function Probe({ period }: { period?: number }) {
  const now = useNow(period);
  return <span data-testid="now">{now === null ? "saat yok" : now.toISOString()}</span>;
}

afterEach(() => {
  vi.useRealTimers();
});

describe("useNow", () => {
  it("has NO clock on the server render", () => {
    // This is the whole point of the hook. Kokpit is pre-rendered and cached
    // (`revalidate: 60`), so anything the server computes from its own clock is
    // frozen into HTML that will be read minutes later -- production served an
    // 18:03 UTC reading under a lit "Canlı" badge at 18:41. The server snapshot
    // is therefore "I have no clock", and every freshness claim downstream is
    // built to say nothing when it gets that answer.
    expect(renderToStaticMarkup(<Probe period={101} />)).toContain("saat yok");
  });

  it("takes its first reading on the commit after mount, not a period later", () => {
    // A badge that stayed blank for a whole minute would be honest and
    // useless. React re-reads the store immediately after subscribing, which is
    // where the first reading is taken.
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-03T08:00:00Z"));
    render(<Probe period={102} />);
    expect(screen.getByTestId("now")).toHaveTextContent("2026-09-03T08:00:00.000Z");
  });

  it("keeps ticking, so a verdict cannot go stale under the reader", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-03T08:00:00Z"));
    render(<Probe period={60_000} />);

    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(screen.getByTestId("now")).toHaveTextContent("2026-09-03T08:01:00.000Z");

    // Twenty minutes in a tab nobody touched: the same reading that was "Canlı"
    // when the page loaded is now outside a 30-minute window, and the only way
    // the page can know that is by asking again.
    act(() => {
      vi.advanceTimersByTime(19 * 60_000);
    });
    expect(screen.getByTestId("now")).toHaveTextContent("2026-09-03T08:20:00.000Z");
  });

  it("does not serve a RETAINED clock to a later remount", () => {
    // THE REMOUNT TRAP. The store keeps `value` after its last listener leaves
    // so an immediate remount does not flash the no-clock placeholder over a
    // badge already earned. But `getSnapshot` is read during the remount RENDER
    // and committed before the subscribe effect can refresh it -- so a reader
    // who left Kokpit at 10:00 and came back at 13:10 had the first painted
    // frame judged against a clock frozen three hours earlier. That is exactly
    // the frozen-clock liveness claim this hook exists to delete, coming back
    // in through the door marked "no flashing".
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-03T10:00:00Z"));
    const first = render(<Probe period={104} />);
    expect(screen.getByTestId("now")).toHaveTextContent("2026-09-03T10:00:00.000Z");
    first.unmount();

    // Away for three hours.
    vi.setSystemTime(new Date("2026-09-03T13:10:00Z"));
    const seen: string[] = [];
    function Recorder() {
      const now = useNow(104);
      seen.push(now === null ? "saat yok" : now.toISOString());
      return null;
    }
    render(<Recorder />);

    // The FIRST render is the one that matters: it must not report the old
    // clock. A stopped clock is the same thing as no clock, and `pending` is
    // already every consumer's honest answer for that.
    expect(seen[0]).toBe("saat yok");
    // ...and the subscribe effect supplies the real one on the very next
    // commit, so the placeholder is a single frame rather than a state.
    expect(seen[seen.length - 1]).toBe("2026-09-03T13:10:00.000Z");
  });

  it("still retains a clock across a remount INSIDE one period", () => {
    // The negative half, and the reason the retention exists at all: a tab
    // switch or a re-key must not blink the badge off. Within one period the
    // retained reading is as good as a fresh one, so the first render keeps it.
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-03T10:00:00Z"));
    const first = render(<Probe period={60_000} />);
    first.unmount();

    vi.setSystemTime(new Date("2026-09-03T10:00:30Z"));
    const seen: string[] = [];
    function Recorder() {
      const now = useNow(60_000);
      seen.push(now === null ? "saat yok" : now.toISOString());
      return null;
    }
    render(<Recorder />);
    expect(seen[0]).toBe("2026-09-03T10:00:00.000Z");
  });

  it("returns the SAME Date object until the clock actually ticks", () => {
    // `new Date(millis)` per render is a new identity per render, so every
    // downstream `useMemo` keyed on `now` missed its cache and re-ran on every
    // unrelated render -- `buildFxRows` over nine rows with a forecast scan
    // each, `todayIso` on the campaigns page. The identity must change with the
    // tick and with nothing else.
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-03T08:00:00Z"));
    const seen: (Date | null)[] = [];
    function Recorder({ tag }: { tag: number }) {
      seen.push(useNow(105));
      return <span>{tag}</span>;
    }
    const view = render(<Recorder tag={1} />);
    // A re-render that changes nothing about the clock.
    view.rerender(<Recorder tag={2} />);
    const ticked = seen.filter((value): value is Date => value !== null);
    expect(ticked.length).toBeGreaterThan(1);
    expect(ticked[ticked.length - 1]).toBe(ticked[ticked.length - 2]);
  });

  it("shares one interval between every component on the same period", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-03T08:00:00Z"));
    const spy = vi.spyOn(globalThis, "setInterval");

    render(
      <>
        <Probe period={103} />
        <Probe period={103} />
        <Probe period={103} />
      </>,
    );

    // Five Market Pulse cells wanting a minute clock is one timer, not five.
    expect(spy.mock.calls.filter(([, ms]) => ms === 103)).toHaveLength(1);
    spy.mockRestore();
  });
});
