import type { NetworkSignalGroup, NetworkSignalsOut } from "@/lib/types";

/** The region groups out of `GET /hubs/network-signals`, in EITHER shape.
 *
 * The endpoint changed from a bare `NetworkSignalGroup[]` to an envelope
 * (`{ generated_at, window, regions }`) so the Ağ Sinyalleri tab would have a
 * real "son güncelleme" to print instead of the browser's fetch time. The
 * change is not atomic at the edge: `public_cache(response, AGGREGATES)` marks
 * this response cacheable for 300s with `stale-while-revalidate` for 1500 more
 * (backend/app/api/cache_headers.py), so for up to ~30 minutes after a deploy
 * the NEW javascript can be handed the OLD array body out of a shared cache.
 *
 * Read as an envelope only, `data.regions` would be `undefined` in that window
 * and both surfaces would render their empty state -- "sinyal yok" over a
 * payload that is full of signals, with no error to notice. This repo's worst
 * failure mode is showing nothing where there is something, so the array shape
 * is still understood. It costs one line and can be deleted once no cache can
 * still be holding a pre-envelope body.
 *
 * `null` is preserved as `null` and never flattened to `[]`: "the source has
 * not answered" and "the source answered with nothing" are different states,
 * and the callers draw them differently.
 */
export function regionsOf(
  data: NetworkSignalsOut | NetworkSignalGroup[] | null,
): NetworkSignalGroup[] | null {
  if (data === null) return null;
  return Array.isArray(data) ? data : (data.regions ?? null);
}
