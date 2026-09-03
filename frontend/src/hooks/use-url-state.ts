"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo } from "react";

/** URL-owned view state, as Kampanyalar has done it since v2.
 *
 * THE PATTERN, NOT A NEW ONE. `campaigns-client.tsx` established the shape --
 * parse the whole filter state out of `useSearchParams`, serialise it back
 * onto the existing params so unrelated keys survive, and navigate with
 * `router.replace(..., { scroll: false })` so a chip press is neither a
 * history entry nor a jump to the top of the page. Every other filtered
 * surface now reads and writes through this hook instead of re-deriving those
 * three decisions, and `lib/campaigns.ts`'s own `parseCampaignFilters` /
 * `campaignFiltersToSearchParams` remain the model each surface's parse and
 * serialise functions follow.
 *
 * WHY IT MATTERS HERE. This product's output is usually a view pasted into a
 * message. A filter that lives only in component state cannot be sent to
 * anyone: the recipient opens the bare page and sees a different answer to the
 * question the sender was asking. A view that cannot be shared is half a
 * feature.
 *
 * `useSearchParams` opts its subtree out of prerendering, so every page
 * rendering a component that calls this hook needs its own `<Suspense>`
 * boundary -- without one the whole route falls back to client-side rendering
 * and the first paint goes blank. */
export interface UrlState {
  /** A mutable copy, safe to hand to a serialiser. Never the live object
   * Next.js hands back -- writing to that one would mutate router state. */
  params: URLSearchParams;
  /** Replace the address bar with these params. `replace`, not `push`: a chip
   * is not a page, so Back should leave the surface rather than walk every
   * chip the reader tried. */
  replaceParams: (next: URLSearchParams) => void;
}

export function useUrlState(): UrlState {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const params = useMemo(
    () => new URLSearchParams(searchParams.toString()),
    [searchParams],
  );

  const replaceParams = useCallback(
    (next: URLSearchParams) => {
      router.replace(next.size ? `${pathname}?${next.toString()}` : pathname, {
        scroll: false,
      });
    },
    [pathname, router],
  );

  return { params, replaceParams };
}

/* --- shared readers ------------------------------------------------------
 * Every reader drops a value it does not recognise rather than keeping it.
 * A hand-edited (or stale-bookmarked) `?days=999` kept verbatim would narrow
 * a page to nothing while every chip still read "Son 5 gün", which looks
 * exactly like a broken build -- the same rule `parseCampaignFilters` states
 * for `?band=purple`.
 */

/** One value out of an allowed set, or `fallback`. */
export function readEnum<T extends string>(
  params: URLSearchParams,
  name: string,
  allowed: readonly T[],
  fallback: T,
): T {
  const value = params.get(name);
  return allowed.includes(value as T) ? (value as T) : fallback;
}

/** One value out of an allowed set, or null when absent/unknown. */
export function readOptionalEnum<T extends string>(
  params: URLSearchParams,
  name: string,
  allowed: readonly T[],
): T | null {
  const value = params.get(name);
  return allowed.includes(value as T) ? (value as T) : null;
}

/** One number out of an allowed set of rungs, or `fallback`. */
export function readNumber<T extends number>(
  params: URLSearchParams,
  name: string,
  allowed: readonly T[],
  fallback: T,
): T {
  const value = Number(params.get(name));
  return allowed.includes(value as T) ? (value as T) : fallback;
}

/* --- shared writers ------------------------------------------------------ */

/** Set a key, or delete it when the value is the page's default. A cleared
 * filter deletes its key rather than writing an empty one, so an unfiltered
 * page has a clean URL and two readers who cleared the same chip hold the
 * same link. */
export function writeParam(
  params: URLSearchParams,
  name: string,
  value: string | null | undefined,
): void {
  if (value) params.set(name, value);
  else params.delete(name);
}
