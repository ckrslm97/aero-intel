import { useSyncExternalStore } from "react";
import { vi } from "vitest";

/** A working stand-in for `next/navigation` in jsdom.
 *
 * Not a spy that swallows the call: `router.replace` here actually MOVES the
 * address bar and re-renders every component reading `useSearchParams`, the
 * way the real router does. That matters because the surfaces under test now
 * hold their filters in the URL -- with an inert `replace`, a test could click
 * a chip, see nothing change, and pass anyway while the feature was broken.
 *
 * `useSyncExternalStore` rather than a module variable read during render:
 * a component has to actually re-render when the URL moves, and that is the
 * one thing a plain variable cannot make happen.
 *
 * Use it as:
 *   vi.mock("next/navigation", async () =>
 *     await import("@/lib/__fixtures__/next-navigation"));
 * and call `resetNavigation()` in `beforeEach`.
 */

let pathname = "/";
let params = new URLSearchParams();
const listeners = new Set<() => void>();

function emit() {
  for (const listener of [...listeners]) listener();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Put the fake browser on a URL, as if the reader had opened that link. */
export function setUrl(url: string) {
  const [path, query = ""] = url.split("?");
  pathname = path || "/";
  params = new URLSearchParams(query);
  emit();
}

/** The address bar as it stands, for assertions. */
export function currentUrl(): string {
  const query = params.toString();
  return query ? `${pathname}?${query}` : pathname;
}

export function currentParams(): URLSearchParams {
  return new URLSearchParams(params.toString());
}

export function resetNavigation(url = "/") {
  replace.mockClear();
  push.mockClear();
  setUrl(url);
}

export const replace = vi.fn((href: string) => setUrl(href));
export const push = vi.fn((href: string) => setUrl(href));
const refresh = vi.fn();
const prefetch = vi.fn();
const back = vi.fn();
const forward = vi.fn();

export function useRouter() {
  return { replace, push, refresh, prefetch, back, forward };
}

export function usePathname() {
  return useSyncExternalStore(
    subscribe,
    () => pathname,
    () => pathname,
  );
}

export function useSearchParams() {
  return useSyncExternalStore(
    subscribe,
    () => params,
    () => params,
  );
}
