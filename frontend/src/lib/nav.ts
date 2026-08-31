import type { LucideIcon } from "lucide-react";

import {
  Activity,
  Globe2,
  LayoutDashboard,
  Megaphone,
  Newspaper,
  Radar,
  Star,
} from "lucide-react";

import {
  CARRIER_CODES,
  CARRIER_NAMES,
  REGION_LABELS_TR,
  REGION_SLUGS,
  type CarrierCode,
  type RegionSlug,
} from "@/lib/taxonomy.gen";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
}

// Seven destinations: Kokpit, Gazete, Kampanya, Risk Radarı, Sinyaller, Hub,
// Biz.
//
// Six of them are Faz 11's own list (the owner's menu line). Sinyaller is the
// seventh, added on the owner's explicit request to lift the signal block out
// of Biz and give it a page: it composes seven existing streams -- Kokpit's
// four tiles, the campaign alert inbox, the Risk Radarı's high-severity
// clusters, Biz's rival and strategic events, the Hub page's new routes,
// İçgörüler' airline momentum -- into one early-warning list. That is a
// destination in its own right rather than a section of Biz, which is a page
// about THY; nothing about "Emirates just cut fares" belongs under a heading
// that means "us". It sits directly after Risk Radarı so the three surfaces a
// desk checks for something to react to are adjacent.
//
// The six were down from nine: İçgörüler's two pieces of real content each found a home with
// its own audience (new-route signals -> Hub's Ağ Sinyalleri tab, Öneriler ->
// Biz's ticari sinyaller section), and Know How and Arşiv are still real
// routes -- reachable from the topbar help menu and the Gazete masthead
// respectively -- just not one of the six primary destinations. /insights and
// /oneriler are left exactly as they are (nothing 404s), simply off this
// list. The old Takvim page folded into Gazete's Etkinlik category earlier;
// the former scaffold sections, the admin/login surface and the Analiz pivot
// table are gone. Ara has no entry either: the topbar's search box is on
// every page already, so a nav slot for it would buy nothing -- /search is
// still a real route, just reached from there.
export const primaryNav: NavItem[] = [
  { href: "/", label: "Kokpit", icon: LayoutDashboard },
  { href: "/newspaper", label: "Gazete", icon: Newspaper },
  // Directly after Gazete because a campaign is the same kind of thing as a
  // news story -- something a rival just did -- only with a window attached.
  { href: "/kampanyalar", label: "Kampanya", icon: Megaphone },
  { href: "/risk-radari", label: "Risk Radarı", icon: Radar },
  { href: "/sinyaller", label: "Sinyaller", icon: Activity },
  { href: "/hublar", label: "Hub", icon: Globe2 },
  { href: "/biz", label: "Biz", icon: Star },
];

// Every carrier the system can serve, with the identity it is drawn with: the
// name comes from the backend (CARRIER_NAMES, generated from taxonomy.py, the
// same string the API puts on each row), the hex is ours. The logo is not
// listed because it does not need to be -- components/airline-logo.tsx keys the
// carrier's real logo off the IATA code alone, falling back to the drawn tail
// fin in components/tail-icon.tsx, which is where a new carrier's second colour
// goes.
//
// Order is display order: the foreign carriers alphabetically, then the three
// Turkish ones, the home carrier last.
export const airlineTabs: { code: CarrierCode; name: string; color: string }[] = [
  { code: "AF", name: CARRIER_NAMES["AF"], color: "#002157" },
  { code: "BA", name: CARRIER_NAMES["BA"], color: "#075aaa" },
  { code: "EK", name: CARRIER_NAMES["EK"], color: "#d71921" },
  { code: "EY", name: CARRIER_NAMES["EY"], color: "#bd8b13" },
  { code: "KL", name: CARRIER_NAMES["KL"], color: "#00a1de" },
  { code: "LH", name: CARRIER_NAMES["LH"], color: "#05164d" },
  { code: "QR", name: CARRIER_NAMES["QR"], color: "#5c0632" },
  // Singapore Airlines' logo blue, not its corporate Pantone 289 navy
  // (#00205b): 289 is four points of blue away from Air France's #002157 and
  // the two lanes would be the same colour on the timeline. #1d4886 is the
  // blue the SIA wordmark and bird are actually drawn in, and it reads as SQ
  // next to AF instead of as a second Air France. The gold half of the
  // identity is the tail fin's accent band (tail-icon.tsx).
  { code: "SQ", name: CARRIER_NAMES["SQ"], color: "#1d4886" },
  { code: "PC", name: CARRIER_NAMES["PC"], color: "#fdb913" },
  { code: "VF", name: CARRIER_NAMES["VF"], color: "#f26722" },
  { code: "TK", name: CARRIER_NAMES["TK"], color: "#c70a20" },
];

// The same guard the regions get below, for the same reason and after the same
// bug: Singapore Airlines was added to the backend's carrier master, started
// producing campaigns, and drew itself on the Kampanyalar timeline as the bare
// string "SQ" in the default accent colour, because nothing checked. A carrier
// the pipeline can attribute a campaign to and nobody gave a brand hex to now
// fails the build instead of the page.
for (const code of CARRIER_CODES) {
  if (!airlineTabs.some((airline) => airline.code === code)) {
    throw new Error(`nav.ts: backend carrier "${code}" has no brand entry.`);
  }
}

// Slugs come from backend/app/taxonomy.py COUNTRY_TO_REGION, via taxonomy.gen.ts.
// The RegionSlug type means a renamed region fails `tsc`; the check below means a
// region the backend added but nobody named in Turkish fails the build too.
// The order here is display order and is deliberately not alphabetical.
export const worldRegions: { slug: RegionSlug; name: string }[] = [
  { slug: "europe", name: REGION_LABELS_TR["europe"] },
  { slug: "middle-east", name: REGION_LABELS_TR["middle-east"] },
  { slug: "africa", name: REGION_LABELS_TR["africa"] },
  { slug: "north-america", name: REGION_LABELS_TR["north-america"] },
  { slug: "south-america", name: REGION_LABELS_TR["south-america"] },
  { slug: "central-america", name: REGION_LABELS_TR["central-america"] },
  { slug: "asia", name: REGION_LABELS_TR["asia"] },
  { slug: "southeast-asia", name: REGION_LABELS_TR["southeast-asia"] },
  { slug: "oceania", name: REGION_LABELS_TR["oceania"] },
];

for (const slug of REGION_SLUGS) {
  if (!worldRegions.some((region) => region.slug === slug)) {
    throw new Error(`nav.ts: backend region "${slug}" has no Turkish name.`);
  }
}
