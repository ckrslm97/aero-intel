import type { LucideIcon } from "lucide-react";

import {
  Archive,
  Globe2,
  GraduationCap,
  LayoutDashboard,
  Lightbulb,
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

// Nine destinations, one per question the product answers -- deliberately
// fewer than the pages behind them. Gazete, Kampanyalar and Risk Radarı say
// what happened (and what is about to); İçgörüler says what the data means
// across all of it, and carries Öneriler as its second tab
// (they answered the same question from two sidebar slots, so they are one
// destination now, /oneriler redirecting into the tab). The old Takvim page
// folded into Gazete's Etkinlik category; the former scaffold sections, the
// admin/login surface and the Analiz pivot table are gone. Ara has no entry
// either: the topbar's search box is on every page already, so a nav slot for
// it would buy nothing -- /search is still a real route, just reached from
// there.
export const primaryNav: NavItem[] = [
  { href: "/", label: "Kontrol Paneli", icon: LayoutDashboard },
  { href: "/newspaper", label: "Gazete", icon: Newspaper },
  // Directly after Gazete because a campaign is the same kind of thing as a
  // news story -- something a rival just did -- only with a window attached.
  { href: "/kampanyalar", label: "Kampanyalar", icon: Megaphone },
  { href: "/risk-radari", label: "Risk Radarı", icon: Radar },
  { href: "/insights", label: "İçgörüler", icon: Lightbulb },
  { href: "/hublar", label: "Hub'lar", icon: Globe2 },
  { href: "/biz", label: "BİZ", icon: Star },
  { href: "/know-how", label: "Know How", icon: GraduationCap },
  { href: "/archive", label: "Arşiv", icon: Archive },
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
