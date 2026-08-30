// Backend country name (as /risks returns it) -> GeoJSON feature name in
// public/geo/world.json, for the Risk Radarı map's country-polygon fill.
//
// The two vocabularies agree for almost every country a risk event has ever
// been placed in: the backend's names come from app/data/countries.json
// ("united states", "turkey", "united kingdom") and the world outline's are the
// same words in title case, so a case-fold is the whole mapping for ~180 of
// them. This file exists for the sixty-odd that diverge, and only the ones a
// classified risk event can plausibly land in are listed -- the rest are
// uninhabited territories that would be dead entries.
//
// An unmapped country simply gets no polygon fill. Its scatter marker still
// draws (that comes from a centroid table, not from the outline), so the event
// is never hidden -- only its country's shape is left neutral. That is the
// right failure: a missing fill is a missing emphasis, while a wrong fill would
// colour the wrong country.

import { COUNTRY_REGION } from "@/lib/geo/region-countries";

/** The divergences. Left side is the backend's lowercase country name, right
 * side is the exact GeoJSON `properties.name`. Natural Earth abbreviates
 * ("Czech Rep.") and picks sides on divided states ("Korea" for the South,
 * "Dem. Rep. Korea" for the North), neither of which a case-fold can guess. */
const NAME_OVERRIDES: Record<string, string> = {
  "bosnia and herzegovina": "Bosnia and Herz.",
  "central african republic": "Central African Rep.",
  "czech republic": "Czech Rep.",
  "democratic republic of the congo": "Dem. Rep. Congo",
  "dominican republic": "Dominican Rep.",
  "equatorial guinea": "Eq. Guinea",
  eswatini: "Swaziland",
  laos: "Lao PDR",
  "north korea": "Dem. Rep. Korea",
  "north macedonia": "Macedonia",
  "palestinian territory": "Palestine",
  "republic of the congo": "Congo",
  "south korea": "Korea",
  "south sudan": "S. Sudan",
  "solomon islands": "Solomon Is.",
  "western sahara (disputed territory)": "W. Sahara",
};

/** Lowercase country name -> GeoJSON feature name.
 *
 * Derived from COUNTRY_REGION's key set rather than hand-listed: that file is
 * generated from the actual feature-name list, so every value here is
 * guaranteed to be a name the outline really carries. A hand-written table
 * would drift the first time the outline is regenerated, and a fill keyed on a
 * name no feature has fails silently -- no error, just a country that never
 * lights up. */
export const GEO_FEATURE_BY_COUNTRY: Record<string, string> = {
  ...Object.fromEntries(Object.keys(COUNTRY_REGION).map((name) => [name.toLowerCase(), name])),
  ...NAME_OVERRIDES,
};
