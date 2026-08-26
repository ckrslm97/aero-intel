import type { LucideIcon } from "lucide-react";

import {
  Globe2,
  LayoutDashboard,
  Megaphone,
  Newspaper,
  Radar,
  Star,
} from "lucide-react";

import { REGION_LABELS_TR, REGION_SLUGS, type RegionSlug } from "@/lib/taxonomy.gen";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
}

// Exactly six destinations (Faz 11 of the Faz 7 rebuild plan): Kokpit,
// Gazete, Kampanya, Risk Radarı, Hub, Biz -- the owner's own menu line. Down
// from nine: İçgörüler's two pieces of real content each found a home with
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
  { href: "/hublar", label: "Hub", icon: Globe2 },
  { href: "/biz", label: "Biz", icon: Star },
];

export const airlineTabs = [
  { code: "AF", name: "Air France", color: "#002157" },
  { code: "BA", name: "British Airways", color: "#075aaa" },
  { code: "EK", name: "Emirates", color: "#d71921" },
  { code: "EY", name: "Etihad Airways", color: "#bd8b13" },
  { code: "KL", name: "KLM", color: "#00a1de" },
  { code: "LH", name: "Lufthansa", color: "#05164d" },
  { code: "QR", name: "Qatar Airways", color: "#5c0632" },
  { code: "PC", name: "Pegasus Airlines", color: "#fdb913" },
  { code: "VF", name: "AJet", color: "#f26722" },
  { code: "TK", name: "Turkish Airlines", color: "#c70a20" },
];

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
