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
      { slug: "pricing", label: "Fiyatlandırma" },
      { slug: "promotion", label: "Kampanya" },
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

/** The Gazete's visible categories, in the product owner's priority order:
 * Gelir Yönetimi first, Etkinlik second, then Filo, Finans, Havalimanı, and
 * Genel last as the fallback bucket.
 *
 * A display allow-list, NOT a taxonomy change. Every slug above still exists
 * and is still classified server-side -- `network` in particular keeps
 * powering "Yeni hat sinyalleri"; it simply isn't a newspaper tab. The four
 * omitted slugs (safety, regulatory, sustainability, labor) are additionally
 * filtered out of the Gazete's article list via the API's
 * `exclude_categories` param, so they don't leak in under Genel either.
 * Reverting the simplification is deleting this list's use, nothing more. */
export const NEWSPAPER_CATEGORY_SLUGS = [
  "revenue_management",
  "events",
  "fleet",
  "finance",
  "airport",
  "general",
] as const;

export const NEWSPAPER_CATEGORIES: CategoryDef[] = NEWSPAPER_CATEGORY_SLUGS.map(
  (slug) => CATEGORY_BY_SLUG[slug],
);

/** Classified server-side but deliberately absent from the Gazete -- sent to
 * the API as `exclude_categories` so these stories never appear in the paper's
 * list or its tab badges. `network` is NOT here: it stays out of the tab row
 * but its articles are still legitimate reading. */
export const NEWSPAPER_EXCLUDED_CATEGORY_SLUGS = [
  "safety",
  "regulatory",
  "sustainability",
  "labor",
] as const;

/** A taxonomy slug as a CSS custom-property reference, e.g.
 * `revenue_management` -> `var(--category-revenue-management)`.
 *
 * The slug uses underscores and the token hyphens, which is exactly the sort
 * of transform Tailwind's scanner cannot follow -- so category color is
 * carried through a CSS variable (usually assigned to `--glow-color`) rather
 * than through a dynamically-built class name. Unknown slugs fall back to the
 * "general" hue instead of producing an undefined var. */
export function categoryVar(slug: string | null | undefined): string {
  const known = slug && CATEGORY_BY_SLUG[slug] ? slug : "general";
  return `var(--category-${known.replace(/_/g, "-")})`;
}

export function getSubcategoryLabel(categorySlug: string, subcategorySlug: string | null): string | null {
  if (!subcategorySlug) return null;
  const category = CATEGORY_BY_SLUG[categorySlug];
  return category?.subcategories.find((s) => s.slug === subcategorySlug)?.label ?? null;
}

// Regions reuse the shared worldRegions list (frontend/src/lib/nav.ts), which
// mirrors backend/app/taxonomy.py COUNTRY_TO_REGION's slugs.
export const EVENT_REGIONS = worldRegions;
