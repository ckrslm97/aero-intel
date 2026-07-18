import type { LucideIcon } from "lucide-react";
import {
  BarChart3,
  CalendarDays,
  Globe2,
  LayoutDashboard,
  Lightbulb,
  Newspaper,
  Plane,
  Route,
  Search,
  ShieldCheck,
  Star,
} from "lucide-react";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  /** Sections still scaffolded per the M0-M6 roadmap -- shown with a "soon" hint. */
  scaffold?: boolean;
}

export const primaryNav: NavItem[] = [
  { href: "/", label: "Kontrol Paneli", icon: LayoutDashboard },
  { href: "/newspaper", label: "Gazete", icon: Newspaper },
  { href: "/events", label: "Takvim", icon: CalendarDays },
  { href: "/insights", label: "İçgörüler", icon: Lightbulb },
  { href: "/archive", label: "Arşiv", icon: BarChart3 },
  { href: "/regions", label: "Bölgeler", icon: Globe2, scaffold: true },
  { href: "/airlines", label: "Havayolları", icon: Plane, scaffold: true },
  { href: "/routes", label: "Rotalar", icon: Route, scaffold: true },
  { href: "/finance", label: "Finans", icon: BarChart3, scaffold: true },
  { href: "/biz", label: "BİZ", icon: Star, scaffold: true },
  { href: "/search", label: "Ara", icon: Search },
];

export const secondaryNav: NavItem[] = [
  { href: "/admin", label: "Yönetim", icon: ShieldCheck },
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

// slugs mirror backend/app/taxonomy.py COUNTRY_TO_REGION values -- keep both in sync.
export const worldRegions = [
  { slug: "europe", name: "Avrupa" },
  { slug: "middle-east", name: "Orta Doğu" },
  { slug: "africa", name: "Afrika" },
  { slug: "north-america", name: "Kuzey Amerika" },
  { slug: "south-america", name: "Güney Amerika" },
  { slug: "central-america", name: "Orta Amerika" },
  { slug: "asia", name: "Asya" },
  { slug: "southeast-asia", name: "Güneydoğu Asya" },
  { slug: "oceania", name: "Okyanusya" },
];
