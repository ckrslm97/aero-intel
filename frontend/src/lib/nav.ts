import type { LucideIcon } from "lucide-react";
import {
  BarChart3,
  Globe2,
  LayoutDashboard,
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
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/newspaper", label: "Newspaper", icon: Newspaper },
  { href: "/archive", label: "Archive", icon: BarChart3 },
  { href: "/regions", label: "Regions", icon: Globe2, scaffold: true },
  { href: "/airlines", label: "Airlines", icon: Plane, scaffold: true },
  { href: "/routes", label: "Routes", icon: Route, scaffold: true },
  { href: "/finance", label: "Finance", icon: BarChart3, scaffold: true },
  { href: "/biz", label: "BİZ", icon: Star, scaffold: true },
  { href: "/search", label: "Search", icon: Search },
];

export const secondaryNav: NavItem[] = [
  { href: "/admin", label: "Admin", icon: ShieldCheck },
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

export const worldRegions = [
  { slug: "europe", name: "Europe" },
  { slug: "middle-east", name: "Middle East" },
  { slug: "africa", name: "Africa" },
  { slug: "north-america", name: "North America" },
  { slug: "south-america", name: "South America" },
  { slug: "central-america", name: "Central America" },
  { slug: "asia", name: "Asia" },
  { slug: "southeast-asia", name: "Southeast Asia" },
  { slug: "oceania", name: "Oceania" },
];
