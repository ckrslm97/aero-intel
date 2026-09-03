import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useDataSource } from "./use-data-source";

describe("useDataSource", () => {
  it("starts loading and resolves to the fetched data", async () => {
    const fetcher = vi.fn().mockResolvedValue("hello");
    const { result } = renderHook(() => useDataSource(fetcher, []));

    expect(result.current.loading).toBe(true);
    expect(result.current.loaded).toBe(false);

    await waitFor(() => expect(result.current.loaded).toBe(true));

    expect(result.current.data).toBe("hello");
    expect(result.current.error).toBeNull();
    expect(result.current.stale).toBe(false);
    expect(result.current.lastUpdated).toBeInstanceOf(Date);
  });

  // --- "son güncelleme" is the server's clock, not the browser's ----------
  //
  // The stamp printed on every card used to be `new Date()` at the moment the
  // fetch resolved. That is a fact about the reader's network: it reads "now"
  // on a cached response, it moves on every reload, and over a feed whose cron
  // stopped last week it keeps climbing -- the freshest possible label on the
  // stalest possible numbers. Aggregate endpoints now stamp themselves.

  it("stamps the card with the server's generated_at when the payload has one", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue({ generated_at: "2026-08-30T06:15:00Z", items: [] });
    const { result } = renderHook(() => useDataSource(fetcher, []));

    await waitFor(() => expect(result.current.loaded).toBe(true));

    expect(result.current.lastUpdated?.toISOString()).toBe("2026-08-30T06:15:00.000Z");
  });

  it("falls back to the fetch time only when the payload carries no stamp", async () => {
    // A card with no timestamp at all is worse than one honestly showing the
    // client's; the server's answer just wins wherever there is one.
    const fetcher = vi.fn().mockResolvedValue([1, 2, 3]);
    const { result } = renderHook(() => useDataSource(fetcher, []));

    await waitFor(() => expect(result.current.loaded).toBe(true));

    expect(result.current.lastUpdated).toBeInstanceOf(Date);
  });

  it("ignores a stamp it cannot parse rather than printing an Invalid Date", async () => {
    const fetcher = vi.fn().mockResolvedValue({ generated_at: "hiçbir zaman" });
    const { result } = renderHook(() => useDataSource(fetcher, []));

    await waitFor(() => expect(result.current.loaded).toBe(true));

    expect(Number.isNaN(result.current.lastUpdated!.getTime())).toBe(false);
  });

  it("sets error and leaves data null on a first-ever failure", async () => {
    const fetcher = vi.fn().mockRejectedValue(new Error("network down"));
    const { result } = renderHook(() => useDataSource(fetcher, []));

    await waitFor(() => expect(result.current.loaded).toBe(true));

    expect(result.current.data).toBeNull();
    expect(result.current.error).toBe("network down");
    // No prior data to be stale relative to.
    expect(result.current.stale).toBe(false);
  });

  it("keeps the previous data and marks it stale when a refetch fails", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce("first").mockRejectedValueOnce(new Error("boom"));
    const { result } = renderHook(() => useDataSource(fetcher, []));

    await waitFor(() => expect(result.current.data).toBe("first"));

    act(() => {
      result.current.retry();
    });

    await waitFor(() => expect(result.current.error).toBe("boom"));

    // The graceful-degradation contract: a failed refresh never blanks a
    // section that was showing real data a moment ago.
    expect(result.current.data).toBe("first");
    expect(result.current.stale).toBe(true);
  });

  it("re-fetches when retry() is called after a success", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce("v1").mockResolvedValueOnce("v2");
    const { result } = renderHook(() => useDataSource(fetcher, []));

    await waitFor(() => expect(result.current.data).toBe("v1"));

    act(() => {
      result.current.retry();
    });

    await waitFor(() => expect(result.current.data).toBe("v2"));
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("re-fetches when a dependency changes", async () => {
    const fetcher = vi.fn().mockResolvedValue("data");
    const { rerender } = renderHook(({ dep }) => useDataSource(fetcher, [dep]), {
      initialProps: { dep: "a" },
    });

    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));

    rerender({ dep: "b" });

    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
  });

  // --- `deps` IS THE QUESTION, NOT JUST A RE-FETCH TRIGGER -----------------
  //
  // The hook used to keep `data`, `lastUpdated` and `stale` across a
  // dependency change. A reader switching the window from 5 days to 90 saw the
  // 5-day counters under a lit "90g" chip, and if the 90-day request then
  // failed, StaleDataBanner stamped those 5-day numbers with a "son başarılı
  // güncelleme" time -- vouching for the answer to a question nobody had
  // asked. Data fetched for another selection is not stale, it is wrong.

  /** Hand-driven fetches, one per selection, so the frame between "the
   * dependency changed" and "the new answer arrived" can be inspected. */
  function deferredFetches() {
    const settle = new Map<string, { resolve: (v: string) => void; reject: (e: Error) => void }>();
    const fetcher = vi.fn(
      (key: string) =>
        new Promise<string>((resolve, reject) => {
          settle.set(key, { resolve, reject });
        }),
    );
    return { fetcher, settle };
  }

  it("blanks the previous selection's result the moment a dependency changes", async () => {
    const { fetcher, settle } = deferredFetches();
    const { result, rerender } = renderHook(
      ({ days }: { days: number }) => useDataSource(() => fetcher(String(days)), [days]),
      { initialProps: { days: 5 } },
    );

    await act(async () => settle.get("5")!.resolve("5 günlük sayaçlar"));
    expect(result.current.data).toBe("5 günlük sayaçlar");
    expect(result.current.lastUpdated).toBeInstanceOf(Date);

    rerender({ days: 90 });

    // The very first render after the switch -- the frame that already carries
    // the "90g" chip. Nothing from the 5-day window survives into it.
    expect(result.current.data).toBeNull();
    expect(result.current.loaded).toBe(false);
    expect(result.current.lastUpdated).toBeNull();
    expect(result.current.stale).toBe(false);
    // And the reader is told a request is on its way, not that there is
    // nothing here: an empty section with no pending request reads as "no
    // records", which is a claim about the world.
    expect(result.current.pending).toBe(true);
    expect(result.current.loading).toBe(true);

    await act(async () => settle.get("90")!.resolve("90 günlük sayaçlar"));
    expect(result.current.data).toBe("90 günlük sayaçlar");
    expect(result.current.loaded).toBe(true);
  });

  it("never calls another selection's data stale when the new selection fails", async () => {
    const { fetcher, settle } = deferredFetches();
    const { result, rerender } = renderHook(
      ({ days }: { days: number }) => useDataSource(() => fetcher(String(days)), [days]),
      { initialProps: { days: 5 } },
    );

    await act(async () => settle.get("5")!.resolve("5 günlük sayaçlar"));

    rerender({ days: 90 });
    await act(async () => settle.get("90")!.reject(new Error("okunamadı")));

    // "Okunamadı" with a retry -- the error branch. NOT the 5-day numbers
    // under a stale badge, and no "son başarılı güncelleme" time, because this
    // window has never been read successfully.
    expect(result.current.error).toBe("okunamadı");
    expect(result.current.data).toBeNull();
    expect(result.current.stale).toBe(false);
    expect(result.current.lastUpdated).toBeNull();
    expect(result.current.loaded).toBe(true);
    expect(result.current.pending).toBe(false);
  });

  it("keeps showing data through a same-selection refresh, and says one is in flight", async () => {
    const { fetcher, settle } = deferredFetches();
    const { result } = renderHook(() => useDataSource(() => fetcher("only"), []));

    await act(async () => settle.get("only")!.resolve("ilk"));
    expect(result.current.pending).toBe(false);

    act(() => result.current.retry());

    // Same question, so the answer on screen is still an answer: it stays,
    // undimmed by a skeleton, while `pending` lets the caller show that the
    // retry is actually running.
    expect(result.current.data).toBe("ilk");
    expect(result.current.pending).toBe(true);
    expect(result.current.loading).toBe(false);
    expect(result.current.loaded).toBe(true);

    await act(async () => settle.get("only")!.resolve("ikinci"));
    expect(result.current.data).toBe("ikinci");
    expect(result.current.pending).toBe(false);
  });

  it("does not re-ask, or blank, when a re-render leaves the dependencies alone", async () => {
    // The other half of the contract. A hook that reset on every render would
    // pass the tests above and flicker a skeleton over data that is still the
    // right answer -- the comparison is `Object.is` per element, exactly what
    // the effect's own dependency check does.
    const fetcher = vi.fn().mockResolvedValue("veri");
    const { result, rerender } = renderHook(
      ({ days }: { days: number }) => useDataSource(fetcher, [days]),
      { initialProps: { days: 5 } },
    );

    await waitFor(() => expect(result.current.data).toBe("veri"));

    rerender({ days: 5 });

    expect(result.current.data).toBe("veri");
    expect(result.current.loaded).toBe(true);
    expect(result.current.pending).toBe(false);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
});
