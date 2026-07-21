"use client";

import { ChevronDown, CircleAlert, ExternalLink, Info, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";

import { AirlineLogo } from "@/components/airline-logo";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api";
import { airlineTabs, worldRegions } from "@/lib/nav";
import { CATEGORY_BY_SLUG, CATEGORIES } from "@/lib/taxonomy";
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

// Color never carries the meaning on its own: every badge is icon + word.
const SEVERITY_META = {
  high: { label: "Yüksek", icon: TriangleAlert, className: "border-critical/40 bg-critical/10 text-critical" },
  medium: { label: "Orta", icon: CircleAlert, className: "border-warning/40 bg-warning/10 text-warning" },
  low: { label: "Düşük", icon: Info, className: "border-border bg-muted text-muted-foreground" },
} as const;

// The windows the backend compares against the window before them.
const DAY_OPTIONS = [7, 14, 30] as const;

const REGION_NAME: Record<string, string> = Object.fromEntries(
  worldRegions.map((r) => [r.slug, r.name]),
);

const chip = (active: boolean) =>
  cn(
    "rounded-full px-2.5 py-1 text-xs font-medium transition-colors",
    active
      ? "bg-primary text-primary-foreground"
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

export function RecommendationsClient() {
  const [days, setDays] = useState<number>(DAY_OPTIONS[0]);
  const [category, setCategory] = useState<string | null>(null);
  const [region, setRegion] = useState<string | null>(null);
  const [airline, setAirline] = useState<string | null>(null);

  const [items, setItems] = useState<Recommendation[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const params = new URLSearchParams({ days: String(days) });
    if (category) params.set("category", category);
    if (region) params.set("region", region);
    if (airline) params.set("airline", airline);

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

  const sortedCategories = [...CATEGORIES].sort((a, b) => a.label.localeCompare(b.label, "tr"));

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">Öneriler</h1>
        <p className="text-sm text-muted-foreground">
          Verideki örüntülerden türetilen aksiyon önerileri. Her öneri, dayandığı haberlere
          bağlıdır — kanıtı olmayan öneri üretilmez.
        </p>
      </div>

      {/* Filters. Each row narrows the same question: hangi dönem, hangi başlık,
          hangi bölge, hangi taşıyıcı. */}
      <div className="flex flex-col gap-2 rounded-xl border border-border bg-card p-3">
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

        <FilterRow label="Kategori">
          <button onClick={() => setCategory(null)} className={chip(!category)}>
            Tümü
          </button>
          {sortedCategories.map((c) => (
            <button
              key={c.slug}
              onClick={() => setCategory(category === c.slug ? null : c.slug)}
              className={chip(category === c.slug)}
            >
              {c.label}
            </button>
          ))}
        </FilterRow>

        <FilterRow label="Bölge">
          <button onClick={() => setRegion(null)} className={chip(!region)}>
            Tümü
          </button>
          {worldRegions.map((r) => (
            <button
              key={r.slug}
              onClick={() => setRegion(region === r.slug ? null : r.slug)}
              className={chip(region === r.slug)}
            >
              {r.name}
            </button>
          ))}
        </FilterRow>

        <FilterRow label="Havayolu">
          <button onClick={() => setAirline(null)} className={chip(!airline)}>
            Tümü
          </button>
          {airlineTabs.map((a) => (
            <button
              key={a.code}
              title={a.name}
              onClick={() => setAirline(airline === a.code ? null : a.code)}
              className={cn(chip(airline === a.code), "flex items-center gap-1 tabular-nums")}
            >
              <span
                className={cn(
                  "flex size-4 items-center justify-center overflow-hidden rounded-[3px]",
                  airline === a.code && "bg-white/85",
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
        <div className={cn("flex flex-col gap-3 transition-opacity", loading && "opacity-60")}>
          {items.map((item) => (
            <RecommendationCard key={item.id} item={item} />
          ))}
        </div>
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

function FilterRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="w-16 shrink-0 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      {children}
    </div>
  );
}

function RecommendationCard({ item }: { item: Recommendation }) {
  const severity = SEVERITY_META[item.severity] ?? SEVERITY_META.low;
  const SeverityIcon = severity.icon;
  const categoryLabel = item.category ? CATEGORY_BY_SLUG[item.category]?.label : null;
  const regionLabel = item.region ? (REGION_NAME[item.region] ?? item.region) : null;

  return (
    <article className="flex flex-col gap-2 rounded-xl border border-border bg-card p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={cn(
            "flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-semibold",
            severity.className,
          )}
        >
          <SeverityIcon className="size-3" />
          {severity.label} önem
        </span>
        {categoryLabel && <Tag>{categoryLabel}</Tag>}
        {regionLabel && <Tag>{regionLabel}</Tag>}
        {item.airline_code && <Tag>{item.airline_code}</Tag>}
      </div>

      <h2 className="text-base font-semibold leading-snug">{item.title}</h2>
      <p className="text-sm leading-relaxed text-muted-foreground">{item.rationale}</p>

      {item.metric && (
        <p className="text-xs text-muted-foreground">
          <span className="font-medium text-foreground">{item.metric.label}:</span>{" "}
          {item.metric.previous !== null && (
            <span className="tabular-nums">{item.metric.previous} → </span>
          )}
          <span className="font-semibold tabular-nums text-foreground">{item.metric.value}</span>
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
