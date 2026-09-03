/** The Hub page's URL contract, kept out of the component so it can be
 * asserted directly, and exercised end to end through
 * components/hubs-client.test.tsx.
 *
 * Modelled on `parseCampaignFilters` / `campaignFiltersToSearchParams` in
 * lib/campaigns.ts: parse the whole view state out of the address bar,
 * serialise it back onto the existing params so unrelated keys survive, and
 * drop any value the page does not recognise rather than passing it through.
 *
 * WHY THIS PAGE NEEDS IT. The Hub page holds five decisions at once -- which
 * tab, which hub, which window, which country, which topic -- and every one of
 * them changes the answer on screen. Held in component state they were
 * unsendable: "IST, son 365 gün, Gelir Yönetimi" was a thing you could look at
 * and not a thing you could show anyone. The Ağ Sinyalleri tab in particular
 * is now the product's only new-route surface (İçgörüler points here), so it
 * needs an address of its own.
 */

/** The two tabs. `hubs` is the default and therefore never written. */
export const HUB_VIEWS = ["hubs", "network-signals"] as const;
export type HubView = (typeof HUB_VIEWS)[number];
export const DEFAULT_HUB_VIEW: HubView = "hubs";

/** The windows the Dönem chips offer. Mirrors the `days` values the /hubs and
 * /taxonomy/countries endpoints are asked for. */
export const HUB_DAY_OPTIONS = [30, 90, 365] as const;
export type HubDays = (typeof HUB_DAY_OPTIONS)[number];
export const DEFAULT_HUB_DAYS: HubDays = 90;

/** The hub the page opens on when the URL names none. */
export const DEFAULT_HUB = "IST";

/** What `?hub=` says when the reader has deliberately deselected every hub.
 *
 * A sentinel rather than an absent key, because absent already means
 * something else here: "no opinion, open on IST". Without it, deselecting the
 * hub would produce a URL identical to the page's default, and sending that
 * link would re-select IST for whoever opened it -- the reader's own choice
 * silently reversed in transit. */
export const NO_HUB_PARAM = "none";

export interface HubViewState {
  view: HubView;
  days: HubDays;
  /** IATA code, or null for "no hub selected". */
  hub: string | null;
  /** Country name as /taxonomy/countries spelled it. Empty string is "all
   * countries" -- the value the <select> holds for its blank option. */
  country: string;
  /** Category slug narrowing the selected hub's own story list, or null. */
  category: string | null;
}

/** Whatever `?hub=` names, upper-cased, or null when it names nothing.
 *
 * NOT a membership check: the hub set is served by /hubs and is not known to
 * this bundle at parse time. The component reconciles the value against the
 * overview once that arrives -- a code the overview does not list gets an
 * honest note rather than a detail request that 404s into a generic
 * "yüklenemedi" (see `hubIsKnown` in components/hubs-client.tsx).
 *
 * And not a shape check either, any more. It used to return null for anything
 * that was not three letters, which the caller then read as "no opinion" and
 * replaced with IST. So the two ways a link can be wrong were answered with
 * opposite honesty: `?hub=XYZ` said "izlenen hub'lar arasında değil", while
 * `?hub=istanbul` silently showed IST's panel under an address bar still
 * claiming istanbul -- the reader had no way to know which hub they were
 * reading. Both are now the same case: a value we cannot vouch for, handed to
 * the overview to disown out loud. */
function readHubCode(raw: string | null): string | null {
  if (!raw) return null;
  return raw.trim().toUpperCase() || null;
}

export function parseHubViewState(
  params: URLSearchParams,
  knownCategories: readonly string[],
): HubViewState {
  const view = params.get("view");
  const days = Number(params.get("days"));
  const hubParam = params.get("hub");
  const category = params.get("category");

  return {
    view: (HUB_VIEWS as readonly string[]).includes(view ?? "")
      ? (view as HubView)
      : DEFAULT_HUB_VIEW,
    days: (HUB_DAY_OPTIONS as readonly number[]).includes(days)
      ? (days as HubDays)
      : DEFAULT_HUB_DAYS,
    hub:
      hubParam === NO_HUB_PARAM ? null : (readHubCode(hubParam) ?? DEFAULT_HUB),
    country: params.get("country")?.trim() || "",
    category:
      category && knownCategories.includes(category) ? category : null,
  };
}

/** State back into the address bar, onto `base` so unrelated params survive.
 * A value equal to the page's own default deletes its key, so an untouched
 * page has a clean URL and two readers who cleared the same chip hold the same
 * link. */
export function hubViewStateToSearchParams(
  state: HubViewState,
  base?: URLSearchParams,
): URLSearchParams {
  const params = new URLSearchParams(base?.toString() ?? "");

  if (state.view === DEFAULT_HUB_VIEW) params.delete("view");
  else params.set("view", state.view);

  if (state.days === DEFAULT_HUB_DAYS) params.delete("days");
  else params.set("days", String(state.days));

  if (state.hub === null) params.set("hub", NO_HUB_PARAM);
  else if (state.hub === DEFAULT_HUB) params.delete("hub");
  else params.set("hub", state.hub);

  if (state.country) params.set("country", state.country);
  else params.delete("country");

  // The category belongs to the selected hub's topic mix, so it cannot outlive
  // a hub being deselected -- a slug with no hub to narrow would sit in the
  // URL filtering a list that is no longer scoped to anything.
  if (state.category && state.hub) params.set("category", state.category);
  else params.delete("category");

  return params;
}
