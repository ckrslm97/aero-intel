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
});
