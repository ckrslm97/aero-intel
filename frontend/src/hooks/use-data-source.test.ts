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
