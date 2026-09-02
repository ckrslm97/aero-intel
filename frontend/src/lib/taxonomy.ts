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
import {
  CATEGORY_LABELS_TR,
  CATEGORY_SLUGS,
  type CategorySlug,
  SUBCATEGORIES_BY_CATEGORY,
  type SubcategorySlug,
} from "@/lib/taxonomy.gen";

export interface SubcategoryDef {
  slug: SubcategorySlug;
  label: string;
}

export interface CategoryDef {
  slug: CategorySlug;
  label: string;
  /** Full Tailwind class names (not built dynamically -- Tailwind's scanner
   * needs the literal strings present in source to generate them). See the
   * matching --category-* tokens in globals.css. */
  textClass: string;
  bgClass: string;
  icon: LucideIcon;
  subcategories: SubcategoryDef[];
}

// The slugs are typed against taxonomy.gen.ts, which is generated from
// backend/app/taxonomy.py -- so a category that exists on one side and not the
// other fails `tsc`, and the exhaustiveness check below catches a slug the
// backend added and nobody gave a Turkish label to. Labels, colors and icons
// are frontend-only; the backend knows only the slugs.
export const CATEGORIES: CategoryDef[] = [
  {
    slug: "revenue_management",
    label: CATEGORY_LABELS_TR.revenue_management,
    textClass: "text-category-revenue-management",
    bgClass: "bg-category-revenue-management/10",
    icon: Banknote,
    subcategories: [
      { slug: "competitor", label: "Rakip" },
      { slug: "pricing", label: "Fiyatlandırma" },
      { slug: "promotion", label: "Kampanya" },
      // "Talep & Kapasite" used to be one chip. Talep is what the market wants
      // and Kapasite is what a carrier supplies -- the two sides of the trade
      // this desk exists to price, and the split is the point of the change.
      { slug: "demand", label: "Talep" },
      { slug: "capacity", label: "Kapasite" },
      { slug: "load_factor", label: "Yük Faktörü" },
      { slug: "ancillary", label: "Ek Gelir" },
      { slug: "distribution", label: "Dağıtım/NDC" },
      { slug: "forecasting", label: "Tahminleme" },
    ],
  },
  {
    slug: "fleet",
    label: CATEGORY_LABELS_TR.fleet,
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
    label: CATEGORY_LABELS_TR.network,
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
    label: CATEGORY_LABELS_TR.finance,
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
    label: CATEGORY_LABELS_TR.safety,
    textClass: "text-category-safety",
    bgClass: "bg-category-safety/10",
    icon: ShieldAlert,
    subcategories: [],
  },
  {
    slug: "regulatory",
    label: CATEGORY_LABELS_TR.regulatory,
    textClass: "text-category-regulatory",
    bgClass: "bg-category-regulatory/10",
    icon: Scale,
    subcategories: [],
  },
  {
    slug: "sustainability",
    label: CATEGORY_LABELS_TR.sustainability,
    textClass: "text-category-sustainability",
    bgClass: "bg-category-sustainability/10",
    icon: Sprout,
    subcategories: [],
  },
  {
    slug: "airport",
    label: CATEGORY_LABELS_TR.airport,
    textClass: "text-category-airport",
    bgClass: "bg-category-airport/10",
    icon: TowerControl,
    subcategories: [
      { slug: "slot", label: "Slot" },
      { slug: "airport_capacity", label: "Kapasite" },
      { slug: "terminal", label: "Terminal" },
      { slug: "infrastructure", label: "Pist & Altyapı" },
      { slug: "disruption", label: "Tıkanıklık & Aksama" },
      { slug: "traffic", label: "Trafik" },
      { slug: "new_service", label: "Yeni Hat & Taşıyıcı" },
      { slug: "ground_handling", label: "Yer Hizmetleri" },
      { slug: "passenger_experience", label: "Yolcu Deneyimi" },
    ],
  },
  {
    slug: "labor",
    label: CATEGORY_LABELS_TR.labor,
    textClass: "text-category-labor",
    bgClass: "bg-category-labor/10",
    icon: Users,
    subcategories: [],
  },
  {
    slug: "events",
    label: CATEGORY_LABELS_TR.events,
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
    label: CATEGORY_LABELS_TR.general,
    textClass: "text-category-general",
    bgClass: "bg-category-general/10",
    icon: CircleDashed,
    subcategories: [],
  },
];

export const CATEGORY_BY_SLUG: Record<string, CategoryDef> = Object.fromEntries(
  CATEGORIES.map((c) => [c.slug, c]),
);

// Drift guards. They run once at import, so a mismatch fails the build rather
// than quietly emptying a filter in production. The slug *types* above already
// catch a renamed slug; these two catch the other direction -- a slug that
// exists on both sides but was never given a label or was filed under the
// wrong parent.
//
// 1. Every category the backend can emit has a row above (icon, colors, label).
for (const slug of CATEGORY_SLUGS) {
  if (!CATEGORY_BY_SLUG[slug]) {
    throw new Error(
      `taxonomy.ts: backend category "${slug}" has no entry. Add one, or ` +
        `regenerate taxonomy.gen.ts if the backend dropped it.`,
    );
  }
}

// 2. Every subcategory listed here is one the backend actually classifies into.
for (const category of CATEGORIES) {
  const allowed: readonly SubcategorySlug[] = SUBCATEGORIES_BY_CATEGORY[category.slug];
  for (const sub of category.subcategories) {
    if (!allowed.includes(sub.slug)) {
      throw new Error(
        `taxonomy.ts: "${sub.slug}" is not a subcategory of "${category.slug}" in ` +
          `backend/app/taxonomy.py. Regenerate taxonomy.gen.ts or fix the label.`,
      );
    }
  }
}

export function getCategory(slug: string): CategoryDef {
  return CATEGORY_BY_SLUG[slug] ?? CATEGORY_BY_SLUG.general;
}

/** The Gazete's three sections, in the product owner's priority order: Gelir
 * Yönetimi, Havalimanı, Etkinlik.
 *
 * Down from six. The paper was six tabs deep and the desk read one of them:
 * Filo, Finans and Genel were shelf-fillers next to the beat this portal was
 * built for, and Genel in particular was where everything the classifier could
 * not place went to be scrolled past. Three sections that are each worth
 * opening beat six where the reader has to pick.
 *
 * A display allow-list, NOT a taxonomy change. Every slug above still exists
 * and is still classified server-side -- `network` in particular keeps powering
 * "Yeni hat sinyalleri", and Filo/Finans stories still reach Öneriler, arama
 * and the newsletter. What changes for the paper is that a fleet or finance
 * story only appears here when it is genuinely an RM story, and then it is
 * filed as one: see RM_SHIFT_KEYWORDS in backend/app/taxonomy.py. Reverting the
 * simplification is putting the slugs back in these two lists, nothing more. */
export const NEWSPAPER_CATEGORY_SLUGS: readonly CategorySlug[] = [
  "revenue_management",
  "airport",
  "events",
] as const;

export const NEWSPAPER_CATEGORIES: CategoryDef[] = NEWSPAPER_CATEGORY_SLUGS.map(
  (slug) => CATEGORY_BY_SLUG[slug],
);

/* There used to be a NEWSPAPER_EXCLUDED_CATEGORY_SLUGS list here -- the eight
 * slugs the paper sent as `exclude_categories` so their stories could not pile
 * up behind whichever tab happened to be showing. The paper no longer has one
 * list under a tab row: each of the three sections above issues its own query
 * with an explicit `category=`, and a query that asks for one category cannot
 * return another. The exclusion is now structural rather than a parameter, so
 * the list it needed is gone. Nothing about what is INGESTED or classified
 * changed -- the excluded beats still reach Öneriler, arama and the newsletter. */

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
