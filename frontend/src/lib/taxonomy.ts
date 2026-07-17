import type { LucideIcon } from "lucide-react";
import {
  Banknote,
  CalendarDays,
  CircleDashed,
  Landmark,
  Plane,
  PlaneTakeoff,
  Scale,
  ShieldAlert,
  Sprout,
  TowerControl,
  Users,
} from "lucide-react";

import { worldRegions } from "@/lib/nav";

export interface SubcategoryDef {
  slug: string;
  label: string;
}

export interface CategoryDef {
  slug: string;
  label: string;
  /** Full Tailwind class names (not built dynamically -- Tailwind's scanner
   * needs the literal strings present in source to generate them). See the
   * matching --category-* tokens in globals.css. */
  textClass: string;
  bgClass: string;
  icon: LucideIcon;
  subcategories: SubcategoryDef[];
}

// Mirrors backend/app/taxonomy.py CATEGORIES exactly (slug-for-slug) -- keep
// both files in sync when the taxonomy changes. Turkish labels, colors, and
// icons are frontend-only; the backend only knows the slugs.
export const CATEGORIES: CategoryDef[] = [
  {
    slug: "revenue_management",
    label: "Gelir Yönetimi",
    textClass: "text-category-revenue-management",
    bgClass: "bg-category-revenue-management/10",
    icon: Banknote,
    subcategories: [
      { slug: "competitor", label: "Rakip" },
      { slug: "region", label: "Bölge" },
      { slug: "pricing", label: "Fiyatlandırma" },
      { slug: "demand_capacity", label: "Talep & Kapasite" },
      { slug: "load_factor", label: "Yük Faktörü" },
      { slug: "ancillary", label: "Ek Gelir" },
      { slug: "distribution", label: "Dağıtım/NDC" },
    ],
  },
  {
    slug: "fleet",
    label: "Filo",
    textClass: "text-category-fleet",
    bgClass: "bg-category-fleet/10",
    icon: Plane,
    subcategories: [
      { slug: "order_delivery", label: "Sipariş & Teslimat" },
      { slug: "maintenance", label: "Bakım" },
    ],
  },
  {
    slug: "network",
    label: "Ağ & Rota",
    textClass: "text-category-network",
    bgClass: "bg-category-network/10",
    icon: PlaneTakeoff,
    subcategories: [
      { slug: "new_route", label: "Yeni Hat" },
      { slug: "cancellation", label: "İptal" },
      { slug: "seasonal", label: "Sezonluk" },
    ],
  },
  {
    slug: "finance",
    label: "Finans",
    textClass: "text-category-finance",
    bgClass: "bg-category-finance/10",
    icon: Landmark,
    subcategories: [
      { slug: "results", label: "Sonuçlar" },
      { slug: "equity", label: "Hisse" },
    ],
  },
  {
    slug: "safety",
    label: "Emniyet",
    textClass: "text-category-safety",
    bgClass: "bg-category-safety/10",
    icon: ShieldAlert,
    subcategories: [],
  },
  {
    slug: "regulatory",
    label: "Regülasyon",
    textClass: "text-category-regulatory",
    bgClass: "bg-category-regulatory/10",
    icon: Scale,
    subcategories: [],
  },
  {
    slug: "sustainability",
    label: "Sürdürülebilirlik",
    textClass: "text-category-sustainability",
    bgClass: "bg-category-sustainability/10",
    icon: Sprout,
    subcategories: [],
  },
  {
    slug: "airport",
    label: "Havalimanı",
    textClass: "text-category-airport",
    bgClass: "bg-category-airport/10",
    icon: TowerControl,
    subcategories: [],
  },
  {
    slug: "labor",
    label: "İşgücü",
    textClass: "text-category-labor",
    bgClass: "bg-category-labor/10",
    icon: Users,
    subcategories: [],
  },
  {
    slug: "events",
    label: "Etkinlik",
    textClass: "text-category-events",
    bgClass: "bg-category-events/10",
    icon: CalendarDays,
    subcategories: [
      { slug: "general", label: "Genel" },
      { slug: "regional", label: "Bölgeler" },
    ],
  },
  {
    slug: "general",
    label: "Genel",
    textClass: "text-category-general",
    bgClass: "bg-category-general/10",
    icon: CircleDashed,
    subcategories: [],
  },
];

export const CATEGORY_BY_SLUG: Record<string, CategoryDef> = Object.fromEntries(
  CATEGORIES.map((c) => [c.slug, c]),
);

export function getCategory(slug: string): CategoryDef {
  return CATEGORY_BY_SLUG[slug] ?? CATEGORY_BY_SLUG.general;
}

export function getSubcategoryLabel(categorySlug: string, subcategorySlug: string | null): string | null {
  if (!subcategorySlug) return null;
  const category = CATEGORY_BY_SLUG[categorySlug];
  return category?.subcategories.find((s) => s.slug === subcategorySlug)?.label ?? null;
}

// Regions reuse the shared worldRegions list (frontend/src/lib/nav.ts), which
// mirrors backend/app/taxonomy.py COUNTRY_TO_REGION's slugs.
export const EVENT_REGIONS = worldRegions;
