"use client";

import { AnimatePresence } from "framer-motion";
import { ChevronDown, CircleAlert, ExternalLink, Info, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";

import { AirlineLogo } from "@/components/airline-logo";
// Only the ordering helper: this page renders its own multi-select category
// row (the shared component is single-select by construction, and Gazete's
// sliding pill depends on that).
import { orderCategories } from "@/components/filters/category-chip-row";
import { CountUp } from "@/components/motion/count-up";
import { MotionItem, MotionList } from "@/components/motion/motion-list";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api";
import { airlineTabs, worldRegions } from "@/lib/nav";
import { CATEGORY_BY_SLUG } from "@/lib/taxonomy";
import { cn } from "@/lib/utils";

// Mirrors the dict built by backend/app/services/recommendations.py. Declared
// here rather than in lib/types so this page owns its own contract.
interface Evidence {
  headline: string;
  url: string;
  source_name: string;
  published_at: string | null;
}

interface Metric {
  label: string;
  value: number;
  previous: number | null;
}

interface Recommendation {
  id: string;
  title: string;
  rationale: string;
  severity: "high" | "medium" | "low";
  category: string | null;
  region: string | null;
  airline_code: string | null;
  evidence: Evidence[];
  metric: Metric | null;
}

interface RecommendationsOut {
  days: number;
  count: number;
  items: Recommendation[];
}

// Severity is the visual lead on this page: it drives the card's edge light,
// its gradient border and its badge, so a high-severity item visibly burns
// hotter than a low one -- in dark mode especially.
//
// Color still never carries the meaning on its own: every badge is icon +
// word, exactly as before.
const SEVERITY_META = {
  high: {
    label: "Yüksek",
    icon: TriangleAlert,
    className: "bg-critical/12 text-critical ring-1 ring-critical/40",
    glow: "var(--critical)",
  },
  medium: {
    label: "Orta",
    icon: CircleAlert,
    className: "bg-warning/12 text-warning ring-1 ring-warning/40",
    glow: "var(--warning)",
  },
  low: {
    label: "Düşük",
    icon: Info,
    className: "bg-good/12 text-good ring-1 ring-good/35",
    glow: "var(--good)",
  },
} as const;

// The windows the backend compares against the window before them.
const DAY_OPTIONS = [7, 14, 30] as const;

// Gelir Yönetimi is the portal's focus category, so it leads the row here the
// same way it does everywhere else.
const PINNED_CATEGORY = "revenue_management";
const ORDERED_CATEGORIES = orderCategories(PINNED_CATEGORY);

const REGION_NAME: Record<string, string> = Object.fromEntries(
  worldRegions.map((r) => [r.slug, r.name]),
);

const AIRLINE_NAME: Record<string, string> = Object.fromEntries(
  airlineTabs.map((a) => [a.code, a.name]),
);

/** The lit-chip pattern shared with Gazete/İçgörüler. */
const chip = (active: boolean) =>
  cn(
    "rounded-full px-2.5 py-1 text-xs font-medium transition-colors",
    active
      ? "bg-primary/12 text-primary ring-1 ring-primary/40 dark:glow-soft"
      : "border border-border text-muted-foreground hover:bg-accent",
  );

function formatEvidenceDate(iso: string | null): string | null {
  if (!iso) return null;
  // Calendar and review evidence carry a bare date; anchor it at midday UTC so
  // the reader's timezone can't shift it onto the previous day.
  const value = new Date(iso.includes("T") ? iso : `${iso}T12:00:00Z`);
  if (Number.isNaN(value.getTime())) return null;
  return value.toLocaleDateString("tr-TR", { day: "numeric", month: "short", year: "numeric" });
}

/** Add or remove one value from a multi-select filter. An empty array is the
 * "no filter" state -- which is also what "hepsini seç" means in practice, so
 * "Tümü" simply clears rather than listing every slug explicitly. */
function toggleValue(list: string[], value: string): string[] {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
}

export function RecommendationsClient() {
  const [days, setDays] = useState<number>(DAY_OPTIONS[0]);
  // Gelir Yönetimi is the portal's focus category, so it is both pinned first
  // and pre-selected; "Tümü" still clears back to every category.
  const [category, setCategory] = useState<string[]>([PINNED_CATEGORY]);
  const [region, setRegion] = useState<string[]>([]);
  const [airline, setAirline] = useState<string[]>([]);

  const [items, setItems] = useState<Recommendation[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const params = new URLSearchParams({ days: String(days) });
    // Repeated keys, one per selected value -- FastAPI parses `?region=a&region=b`
    // straight into a list. `days` stays single: a comparison window is not a
    // set. An empty array appends nothing, which is exactly "no filter".
    category.forEach((c) => params.append("category", c));
    region.forEach((r) => params.append("region", r));
    airline.forEach((a) => params.append("airline", a));

    // eslint-disable-next-line react-hooks/set-state-in-effect -- the fetch is driven by the filter change; the loading flag must flip with it
    setLoading(true);
    apiFetch<RecommendationsOut>(`/recommendations?${params.toString()}`, {
      cache: "default",
      signal: controller.signal,
    })
      .then((data) => {
        if (cancelled) return;
        setItems(data.items);
        setError(null);
      })
      .catch((err: unknown) => {
        if (cancelled || (err as Error)?.name === "AbortError") return;
        setError("Öneriler yüklenemedi. Sunucu çalışıyor mu?");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [days, category, region, airline]);

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">Öneriler</h1>
        <p className="text-sm text-muted-foreground">
          Verideki örüntülerden türetilen aksiyon önerileri. Her öneri, dayandığı haberlere
          bağlıdır — kanıtı olmayan öneri üretilmez.
        </p>
      </div>

      {/* Filters. Each row narrows the same question: hangi dönem, hangi başlık,
          hangi bölge, hangi taşıyıcı. */}
      <div className="flex flex-col gap-3 rounded-xl border border-border bg-card p-5">
        <FilterRow label="Dönem">
          {DAY_OPTIONS.map((option) => (
            <button
              key={option}
              onClick={() => setDays(option)}
              className={chip(days === option)}
            >
              Son {option} gün
            </button>
          ))}
        </FilterRow>

        {/* Kategori/Bölge/Havayolu are all multi-select: the backend now takes
            repeated query params, so "Avrupa + Orta Doğu" is one question
            rather than two page loads. "Tümü" is the clear-all. */}
        <FilterRow label="Kategori">
          <button
            type="button"
            onClick={() => setCategory([])}
            className={chip(category.length === 0)}
          >
            Tümü
          </button>
          {ORDERED_CATEGORIES.map((c) => (
            <button
              key={c.slug}
              type="button"
              onClick={() => setCategory((prev) => toggleValue(prev, c.slug))}
              className={chip(category.includes(c.slug))}
            >
              {c.label}
            </button>
          ))}
        </FilterRow>

        <FilterRow label="Bölge">
          <button
            type="button"
            onClick={() => setRegion([])}
            className={chip(region.length === 0)}
          >
            Tümü
          </button>
          {worldRegions.map((r) => (
            <button
              key={r.slug}
              type="button"
              onClick={() => setRegion((prev) => toggleValue(prev, r.slug))}
              className={chip(region.includes(r.slug))}
            >
              {r.name}
            </button>
          ))}
        </FilterRow>

        <FilterRow label="Havayolu">
          <button
            type="button"
            onClick={() => setAirline([])}
            className={chip(airline.length === 0)}
          >
            Tümü
          </button>
          {airlineTabs.map((a) => (
            <button
              key={a.code}
              type="button"
              title={a.name}
              onClick={() => setAirline((prev) => toggleValue(prev, a.code))}
              className={cn(
                chip(airline.includes(a.code)),
                "flex items-center gap-1 tabular-nums",
              )}
            >
              <span
                className={cn(
                  "flex size-4 items-center justify-center overflow-hidden rounded-[3px]",
                  airline.includes(a.code) && "bg-white/85",
                )}
              >
                <AirlineLogo code={a.code} name={a.name} className="size-4" />
              </span>
              {a.code}
            </button>
          ))}
        </FilterRow>
      </div>

      {error ? (
        <p className="rounded-lg border border-dashed border-border p-6 text-sm text-muted-foreground">
          {error}
        </p>
      ) : loading && items === null ? (
        <div className="flex flex-col gap-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-36 w-full rounded-xl" />
          ))}
        </div>
      ) : items && items.length > 0 ? (
        <MotionList
          className={cn("flex flex-col gap-5 transition-opacity", loading && "opacity-60")}
        >
          {/* popLayout: filter changes swap the whole set, so outgoing cards
              must leave the flow instead of shoving the incoming ones down. */}
          <AnimatePresence mode="popLayout" initial={false}>
            {items.map((item) => (
              <MotionItem key={item.id} lift exit="exit" variant="scalePop">
                <RecommendationCard item={item} />
              </MotionItem>
            ))}
          </AnimatePresence>
        </MotionList>
      ) : (
        <div className="rounded-lg border border-dashed border-border p-10 text-center">
          <p className="text-sm font-medium text-foreground">
            Bu filtrelerle öne çıkan bir örüntü yok
          </p>
          <p className="mt-1 text-sm text-muted-foreground">
            Veri bir öneriyi destekleyecek yoğunluğa ulaşmadı. Dönemi genişletin ya da
            filtreleri kaldırın.
          </p>
        </div>
      )}

      <p className="text-[11px] leading-relaxed text-muted-foreground">
        Öneriler; haber arşivi, havayolu etiketleri, yolcu yorumları ve etkinlik takvimi
        üzerindeki sayımlardan üretilir. Tahmin yoktur: eşiğin altında kalan bir sinyal
        öneriye dönüşmez, kanıt listesi her zaman kaynağa bağlanır.
      </p>
    </div>
  );
}

/** Label above its chips, not beside them: the rows carry up to eleven chips
 * each, and a fixed-width inline label pushed them into one cramped line. */
function FilterRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      <div className="flex flex-wrap gap-1.5">{children}</div>
    </div>
  );
}

function RecommendationCard({ item }: { item: Recommendation }) {
  const severity = SEVERITY_META[item.severity] ?? SEVERITY_META.low;
  const SeverityIcon = severity.icon;
  const categoryLabel = item.category ? CATEGORY_BY_SLUG[item.category]?.label : null;
  const regionLabel = item.region ? (REGION_NAME[item.region] ?? item.region) : null;

  // The "kuyruk görseli": the carrier's real logo, falling back to our drawn
  // tail fin (components/tail-icon.tsx) when the CDN image doesn't load.
  const airlineName = item.airline_code
    ? (AIRLINE_NAME[item.airline_code] ?? item.airline_code)
    : null;

  return (
    // glow-edge is the severity-colored runway light down the leading edge;
    // border-gradient carries the same hue around the frame. No bg-card here
    // -- border-gradient paints the surface itself (see globals.css).
    <article
      style={{ "--glow-color": severity.glow } as React.CSSProperties}
      className="border-gradient glow-edge flex h-full flex-col gap-3 rounded-xl p-5"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={cn(
            "flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold",
            severity.className,
          )}
        >
          <SeverityIcon className="size-3" />
          {severity.label} önem
        </span>
        {categoryLabel && <Tag>{categoryLabel}</Tag>}
        {regionLabel && <Tag>{regionLabel}</Tag>}
        {item.airline_code && airlineName && (
          <span className="flex items-center gap-1.5 rounded-full border border-border px-2 py-0.5 text-[11px] font-medium">
            <AirlineLogo
              code={item.airline_code}
              name={airlineName}
              className="size-4"
            />
            {airlineName}
          </span>
        )}
      </div>

      <h2 className="text-base font-semibold leading-snug">{item.title}</h2>
      {/* Clamped: the title is the recommendation, the rationale is context.
          The evidence block below is the deep-dive path. */}
      <p className="line-clamp-2 text-sm leading-relaxed text-muted-foreground">
        {item.rationale}
      </p>

      {item.metric && (
        <p className="text-xs text-muted-foreground">
          <span className="font-medium text-foreground">{item.metric.label}:</span>{" "}
          {item.metric.previous !== null && (
            <span className="tabular-nums">{item.metric.previous} → </span>
          )}
          <CountUp
            value={item.metric.value}
            className="font-semibold tabular-nums text-foreground"
          />
        </p>
      )}

      <details className="group mt-1">
        <summary className="flex w-fit cursor-pointer list-none items-center gap-1 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground [&::-webkit-details-marker]:hidden">
          <ChevronDown className="size-3.5 transition-transform group-open:rotate-180" />
          Dayandığı haberler ({item.evidence.length})
        </summary>
        <ul className="mt-2 flex flex-col divide-y divide-border border-t border-border">
          {item.evidence.map((evidence) => (
            <li key={evidence.url + evidence.headline.slice(0, 24)}>
              <a
                href={evidence.url}
                target="_blank"
                rel="noopener noreferrer"
                className="group/link flex flex-col gap-0.5 py-2"
              >
                <span className="text-sm leading-snug group-hover/link:text-primary">
                  {evidence.headline}
                  <ExternalLink className="ml-1 inline size-3 opacity-0 transition-opacity group-hover/link:opacity-100" />
                </span>
                <span className="flex flex-wrap items-center gap-x-2 text-[11px] text-muted-foreground">
                  <span>{evidence.source_name || "Kaynak"}</span>
                  {formatEvidenceDate(evidence.published_at) && (
                    <span>{formatEvidenceDate(evidence.published_at)}</span>
                  )}
                </span>
              </a>
            </li>
          ))}
        </ul>
      </details>
    </article>
  );
}

function Tag({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded-full bg-secondary px-2 py-0.5 text-[11px] font-medium text-secondary-foreground">
      {children}
    </span>
  );
}
