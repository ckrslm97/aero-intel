"use client";

import { AnimatePresence } from "framer-motion";
import {
  Activity,
  CircleAlert,
  CloudLightning,
  ExternalLink,
  Flame,
  Info,
  Landmark,
  MapPin,
  Megaphone,
  Mountain,
  ShieldAlert,
  Swords,
  TriangleAlert,
  Waves,
  type LucideIcon,
} from "lucide-react";
import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";

import { MotionItem, MotionList, MotionRail } from "@/components/motion/motion-list";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api";
import { worldRegions } from "@/lib/nav";
import { RISK_TYPES, type RiskTypeSlug } from "@/lib/taxonomy.gen";
import type { RiskCountry, RiskItem, RiskRadarOut } from "@/lib/types";
import { cn } from "@/lib/utils";

// echarts only needed once the map renders -- Faz 14, same pattern as
// newspaper-browser.tsx's RegionMap.
const RiskMap = dynamic(
  () => import("@/components/risk-map").then((m) => m.RiskMap),
  { ssr: false, loading: () => <Skeleton className="h-[420px] w-full rounded-xl" /> },
);

const DAYS = 14;

/** Matches backend/app/api/v1/risks.py UNKNOWN_COUNTRY: events whose country
 * never resolved. They stay in the list -- the event is real, only its
 * placement is unknown -- but they are never a "hot spot". */
const UNKNOWN_COUNTRY = "Belirtilmemiş";

/** Icons only. The slugs, families and Turkish labels come from the backend via
 * taxonomy.gen.ts -- they used to be retyped here, which meant renaming a risk
 * type in Python left this file rendering a label for a slug the API no longer
 * sent.
 *
 * The icons are chosen so FAMILY reads from the icon alone, without colour:
 * natural hazards get weather/terrain glyphs, conflict gets institutional and
 * martial ones. The map encodes the same split again as marker shape. */
const TYPE_ICONS: Record<RiskTypeSlug, LucideIcon> = {
  earthquake: Activity,
  flood: Waves,
  wildfire: Flame,
  volcano: Mountain,
  storm: CloudLightning,
  war: Swords,
  coup: Landmark,
  attack: ShieldAlert,
  unrest: Megaphone,
};

const TYPE_META: Record<string, { label: string; family: string; icon: LucideIcon }> =
  Object.fromEntries(
    RISK_TYPES.map((type) => [
      type.slug,
      { label: type.labelTr, family: type.family, icon: TYPE_ICONS[type.slug] },
    ]),
  );

const TYPE_ORDER = RISK_TYPES.map((type) => type.slug);

const FAMILY_META: Record<string, string> = {
  natural: "Doğal",
  conflict: "Çatışma",
};

/** Severity is icon + word, always. The house rule that colour never carries
 * meaning alone applies here with full force -- this is the surface where a
 * misread costs the most.
 *
 * `low` is deliberately NOT the --good token. A "good" war is a category
 * error, and the events calendar's low-impact badge already set this neutral
 * precedent (see events-calendar.tsx IMPACT_META). */
const SEVERITY_META: Record<string, { label: string; icon: LucideIcon; className: string }> = {
  high: {
    label: "Yüksek",
    icon: TriangleAlert,
    className: "border-critical/40 bg-critical/10 text-critical",
  },
  medium: {
    label: "Orta",
    icon: CircleAlert,
    className: "border-warning/40 bg-warning/10 text-warning",
  },
  low: {
    label: "Düşük",
    icon: Info,
    className: "border-border bg-muted text-muted-foreground",
  },
};

const REGION_NAME: Record<string, string> = Object.fromEntries(
  worldRegions.map((r) => [r.slug, r.name]),
);

/** The lit-chip pattern shared with Gazete/İçgörüler/Öneriler. Note there is
 * no REGION_GLOW anywhere on this page: the chrome stays neutral so the only
 * saturated things on screen are the few item cards that earn it. */
const chip = (active: boolean) =>
  cn(
    "flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium transition-colors",
    active
      ? "bg-primary/12 text-primary ring-1 ring-primary/40 dark:glow-soft"
      : "border border-border text-muted-foreground hover:bg-accent",
  );

function formatDate(iso: string | null): string | null {
  if (!iso) return null;
  return new Date(iso).toLocaleDateString("tr-TR", { day: "numeric", month: "short" });
}

export function RiskRadarClient() {
  const [data, setData] = useState<RiskRadarOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [family, setFamily] = useState<string | null>(null);
  const [type, setType] = useState<string | null>(null);
  const [severity, setSeverity] = useState<string | null>(null);
  const [region, setRegion] = useState<string | null>(null);
  const [country, setCountry] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiFetch<RiskRadarOut>(`/risks?days=${DAYS}`, { cache: "default" })
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch(() => {
        if (!cancelled) setError("Risk verisi yüklenemedi. Sunucu çalışıyor mu?");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Filtering is client-side on purpose: /risks returns the whole (already
  // small) classified set for the window in one payload, so narrowing it in
  // memory is exact and costs no round trip. The server's per-country `score`
  // and `severity_counts` are recomputed for the *filtered* view below, since
  // a ranking that ignored the active filters would contradict the list.
  const visible = useMemo<RiskCountry[]>(() => {
    if (!data) return [];
    return data.countries
      .map((group) => {
        const items = group.items.filter((item) => {
          if (family && item.risk_family !== family) return false;
          if (type && item.risk_type !== type) return false;
          if (severity && item.severity !== severity) return false;
          if (region && item.region !== region) return false;
          if (country && group.country !== country) return false;
          return true;
        });
        if (items.length === 0) return null;
        const counts = { high: 0, medium: 0, low: 0 };
        let score = 0;
        for (const item of items) {
          if (item.severity in counts) counts[item.severity as keyof typeof counts] += 1;
          score += item.severity === "high" ? 3 : item.severity === "medium" ? 2 : 1;
        }
        return { ...group, items, count: items.length, score, severity_counts: counts };
      })
      .filter((g): g is RiskCountry => g !== null)
      // Mirrors the server's ordering exactly, including the rule that the
      // unplaced bucket sorts last regardless of score. Without that clause
      // "Belirtilmemiş" ranked #01 in Sıcak Noktalar -- a data-quality
      // residue presented as the worst-hit country.
      .sort(
        (a, b) =>
          Number(a.country === UNKNOWN_COUNTRY) - Number(b.country === UNKNOWN_COUNTRY) ||
          b.score - a.score ||
          b.count - a.count ||
          a.country.localeCompare(b.country),
      );
  }, [data, family, type, severity, region, country]);

  const totalVisible = useMemo(
    () => visible.reduce((sum, g) => sum + g.count, 0),
    [visible],
  );

  // Only offer chips that can match something.
  const availableTypes = useMemo(() => {
    if (!data) return [];
    return TYPE_ORDER.filter(
      (slug) =>
        (data.type_counts[slug] ?? 0) > 0 &&
        (!family || TYPE_META[slug].family === family),
    );
  }, [data, family]);

  const availableRegions = useMemo(() => {
    if (!data) return [];
    const seen = new Set<string>();
    for (const group of data.countries) {
      for (const item of group.items) if (item.region) seen.add(item.region);
    }
    return worldRegions.filter((r) => seen.has(r.slug));
  }, [data]);

  const availableSeverities = useMemo(() => {
    if (!data) return [];
    const seen = new Set<string>();
    for (const group of data.countries) {
      for (const item of group.items) seen.add(item.severity);
    }
    return ["high", "medium", "low"].filter((s) => seen.has(s));
  }, [data]);

  if (error) {
    return (
      <p className="rounded-lg border border-dashed border-border p-6 text-sm text-muted-foreground">
        {error}
      </p>
    );
  }

  if (!data) {
    return (
      <div className="flex flex-col gap-6">
        <Skeleton className="h-20 w-full rounded-xl" />
        <Skeleton className="h-[420px] w-full rounded-xl" />
        <Skeleton className="h-64 w-full rounded-xl" />
      </div>
    );
  }

  const hasAnySignal = data.total > 0;

  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-col gap-2">
        <h1 className="text-2xl font-semibold tracking-tight">Risk Radarı</h1>
        {/* Stating plainly what this is NOT is the strongest anti-alarmism
            move available, and it belongs above the fold rather than in a
            footnote. */}
        <p className="max-w-3xl text-sm leading-relaxed text-muted-foreground">
          Haber akışından sınıflandırılmış doğal afet ve çatışma sinyalleri —
          operasyonel farkındalık için; resmî uyarı sistemi değildir.
        </p>
      </header>

      {!hasAnySignal ? (
        <EmptyRadar />
      ) : (
        <>
          <RiskMap
            countries={visible}
            selectedCountry={country}
            onSelectCountry={setCountry}
          />

          <div className="flex flex-col gap-2 rounded-lg border border-border bg-background/50 p-4">
            <FilterRow label="Aile">
              <button type="button" onClick={() => { setFamily(null); setType(null); }} className={chip(!family)}>
                Tümü
              </button>
              {Object.entries(FAMILY_META).map(([slug, label]) => (
                <button
                  key={slug}
                  type="button"
                  onClick={() => {
                    const next = family === slug ? null : slug;
                    setFamily(next);
                    // A type chip from the other family would silently return
                    // zero rows; clear it rather than show an empty page.
                    if (next && type && TYPE_META[type]?.family !== next) setType(null);
                  }}
                  className={chip(family === slug)}
                >
                  {label}
                  <span className="ml-0.5 tabular-nums opacity-70">
                    {data.family_counts[slug] ?? 0}
                  </span>
                </button>
              ))}
            </FilterRow>

            {availableTypes.length > 0 && (
              <FilterRow label="Tür">
                <button type="button" onClick={() => setType(null)} className={chip(!type)}>
                  Tümü
                </button>
                {availableTypes.map((slug) => {
                  const meta = TYPE_META[slug];
                  const Icon = meta.icon;
                  return (
                    <button
                      key={slug}
                      type="button"
                      onClick={() => setType(type === slug ? null : slug)}
                      className={chip(type === slug)}
                    >
                      <Icon className="size-3.5" />
                      {meta.label}
                      <span className="ml-0.5 tabular-nums opacity-70">
                        {data.type_counts[slug] ?? 0}
                      </span>
                    </button>
                  );
                })}
              </FilterRow>
            )}

            {availableSeverities.length > 0 && (
              <FilterRow label="Şiddet">
                <button type="button" onClick={() => setSeverity(null)} className={chip(!severity)}>
                  Tümü
                </button>
                {availableSeverities.map((slug) => {
                  const meta = SEVERITY_META[slug];
                  const Icon = meta.icon;
                  return (
                    <button
                      key={slug}
                      type="button"
                      onClick={() => setSeverity(severity === slug ? null : slug)}
                      className={chip(severity === slug)}
                    >
                      <Icon className="size-3.5" />
                      {meta.label}
                    </button>
                  );
                })}
              </FilterRow>
            )}

            {availableRegions.length > 0 && (
              <FilterRow label="Bölge">
                <button type="button" onClick={() => setRegion(null)} className={chip(!region)}>
                  Tümü
                </button>
                {availableRegions.map((r) => (
                  <button
                    key={r.slug}
                    type="button"
                    onClick={() => setRegion(region === r.slug ? null : r.slug)}
                    className={chip(region === r.slug)}
                  >
                    {r.name}
                  </button>
                ))}
              </FilterRow>
            )}

            {country && (
              <FilterRow label="Ülke">
                <button type="button" onClick={() => setCountry(null)} className={chip(true)}>
                  {country} ✕
                </button>
              </FilterRow>
            )}
          </div>

          <div className="flex flex-col gap-6 xl:flex-row-reverse xl:items-start">
            <div className="xl:w-72 xl:shrink-0">
              <HotSpots
                countries={visible}
                selected={country}
                onSelect={setCountry}
              />
            </div>

            <div className="flex min-w-0 flex-1 flex-col gap-4">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h2 className="text-sm font-semibold">
                  Sınıflandırılan olaylar{" "}
                  <span className="font-normal text-muted-foreground">
                    (son {data.days} gün)
                  </span>
                </h2>
                <span className="text-xs tabular-nums text-muted-foreground">
                  {totalVisible} / {data.total} sinyal
                </span>
              </div>

              {visible.length === 0 ? (
                <p className="rounded-lg border border-dashed border-border py-16 text-center text-sm text-muted-foreground">
                  Bu filtrelerle sinyal yok. Tür, şiddet veya bölge seçimini kaldırın.
                </p>
              ) : (
                <MotionList className="flex flex-col gap-8">
                  <AnimatePresence mode="popLayout" initial={false}>
                    {visible.map((group) => (
                      <CountrySection key={group.country} group={group} />
                    ))}
                  </AnimatePresence>
                </MotionList>
              )}
            </div>
          </div>
        </>
      )}
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

/** "Sıcak Noktalar": the worst-hit countries by the weighted score.
 *
 * The segmented micro-bar is followed by the counts as literal text ("3Y · 1O")
 * so the bar is never the only encoding of the split -- a reader who cannot
 * separate the segments still gets the numbers. */
function HotSpots({
  countries,
  selected,
  onSelect,
}: {
  countries: RiskCountry[];
  selected: string | null;
  onSelect: (country: string | null) => void;
}) {
  // Excluded outright rather than merely sorted last: a ranking of the
  // worst-hit countries has no row for "we could not tell which country".
  const top = countries.filter((c) => c.country !== UNKNOWN_COUNTRY).slice(0, 8);
  if (top.length === 0) return null;

  return (
    <section className="flex flex-col gap-3 rounded-xl border border-border bg-card bg-card-sheen p-4 shadow-elev-1">
      <div className="flex flex-col gap-1.5">
        <h2 className="text-sm font-semibold">Sıcak Noktalar</h2>
        <p className="text-[11px] leading-relaxed text-muted-foreground">
          Ağırlıklı puana göre: yüksek 3, orta 2, düşük 1.
        </p>
      </div>
      <ol className="flex flex-col gap-2.5">
        {top.map((group, index) => {
          const { high, medium, low } = group.severity_counts;
          const total = Math.max(1, high + medium + low);
          const parts: { key: string; n: number; className: string }[] = [
            { key: "high", n: high, className: "bg-critical" },
            { key: "medium", n: medium, className: "bg-warning" },
            { key: "low", n: low, className: "bg-muted-foreground/40" },
          ];
          const active = selected === group.country;
          return (
            <li key={group.country}>
              <button
                type="button"
                onClick={() => onSelect(active ? null : group.country)}
                className={cn(
                  "flex w-full flex-col gap-1.5 rounded-lg border px-2.5 py-2 text-left transition-colors",
                  active
                    ? "border-primary/40 bg-primary/5"
                    : "border-transparent hover:border-border hover:bg-accent/50",
                )}
              >
                <div className="flex items-baseline gap-2">
                  <span className="w-5 shrink-0 font-mono text-[11px] tabular-nums text-muted-foreground">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-xs font-medium">
                    {group.country}
                  </span>
                  <span className="shrink-0 font-mono text-[11px] tabular-nums text-muted-foreground">
                    {group.score}
                  </span>
                </div>
                <div className="flex items-center gap-2 pl-7">
                  <div className="flex h-1.5 flex-1 gap-px overflow-hidden rounded-full">
                    {parts
                      .filter((p) => p.n > 0)
                      .map((p) => (
                        <span
                          key={p.key}
                          className={cn("rounded-full", p.className)}
                          style={{ width: `${(p.n / total) * 100}%` }}
                        />
                      ))}
                  </div>
                  {/* The bar is decorative; these counts are the real reading. */}
                  <span className="shrink-0 font-mono text-[10px] tabular-nums text-muted-foreground">
                    {[
                      high > 0 && `${high}Y`,
                      medium > 0 && `${medium}O`,
                      low > 0 && `${low}D`,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                </div>
              </button>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function CountrySection({ group }: { group: RiskCountry }) {
  return (
    <MotionItem exit="exit" className="flex flex-col gap-3">
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-sm font-semibold">{group.country}</h3>
          {group.region && (
            <span className="rounded-full bg-secondary px-2 py-0.5 text-[10px] font-medium text-secondary-foreground">
              {REGION_NAME[group.region] ?? group.region}
            </span>
          )}
          <span className="text-[11px] tabular-nums text-muted-foreground">
            {group.count} haber
          </span>
        </div>
        {/* Plain --border rail. No colour at country level: the page's whole
            colour budget is spent on item severity, one level down. */}
        <MotionRail
          staggered
          style={{ "--glow-color": "var(--border)" } as React.CSSProperties}
        />
      </div>

      <div className="flex flex-col gap-2.5">
        {group.items.map((item) => (
          <RiskCard key={item.id} item={item} />
        ))}
      </div>
    </MotionItem>
  );
}

function RiskCard({ item }: { item: RiskItem }) {
  const typeMeta = TYPE_META[item.risk_type];
  const severityMeta = SEVERITY_META[item.severity] ?? SEVERITY_META.low;
  const TypeIcon = typeMeta?.icon ?? Info;
  const SeverityIcon = severityMeta.icon;
  const isHigh = item.severity === "high";
  const isMedium = item.severity === "medium";

  return (
    <article
      style={isHigh ? ({ "--glow-color": "var(--critical)" } as React.CSSProperties) : undefined}
      className={cn(
        "flex flex-col gap-2 rounded-xl border bg-card p-4 transition-all duration-200",
        // The emphatic-but-sober dial. Only high severity gets a lit edge; it
        // is a static 3px rail, not a strobe. On a bad day the page visibly
        // carries more red -- that is the signal, and it needs no animation.
        isHigh && "edge-lit hover:glow-edge",
        isMedium && "border-l-2 border-l-warning",
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="flex items-center gap-1 rounded-full bg-secondary px-2 py-0.5 text-[10px] font-medium text-secondary-foreground">
          <TypeIcon className="size-3" />
          {item.risk_type_label_tr}
        </span>
        <span
          className={cn(
            "flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
            severityMeta.className,
          )}
        >
          <SeverityIcon className="size-3" />
          {severityMeta.label}
        </span>
        {/* Freshness is a quiet tag, never a flash. animate-pulse-once on
            disaster news would be theatre. */}
        {item.is_fresh && (
          <span className="text-[10px] text-muted-foreground">son 24 saat</span>
        )}
        {formatDate(item.published_at) && (
          <span className="ml-auto text-[10px] tabular-nums text-muted-foreground">
            {formatDate(item.published_at)}
          </span>
        )}
      </div>

      <h4 className="text-sm font-medium leading-snug">{item.headline}</h4>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
        {(item.city || item.country) && (
          <span className="flex items-center gap-1">
            <MapPin className="size-3" />
            {[item.city, item.country].filter(Boolean).join(" · ")}
          </span>
        )}
        {item.source_name && <span className="font-medium">{item.source_name}</span>}
        <a
          href={item.url}
          target="_blank"
          rel="noopener noreferrer"
          className="ml-auto flex items-center gap-1 font-medium text-primary hover:underline"
        >
          Kaynak
          <ExternalLink className="size-3" />
        </a>
      </div>
    </article>
  );
}

/** A quiet radar is a good outcome. This must read as "nothing happened",
 * never as "something is broken". */
function EmptyRadar() {
  return (
    <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed border-border px-6 py-16 text-center">
      <p className="text-sm text-muted-foreground">
        Son {DAYS} günde risk sinyali sınıflandırılmadı.
      </p>
      <p className="max-w-md text-xs leading-relaxed text-muted-foreground/80">
        Haber akışı taranıyor; doğal afet veya çatışma olarak sınıflanan bir haber
        bulunmadı.
      </p>
    </div>
  );
}
