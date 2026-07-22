"use client";

import { Plane } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { AirlineLogo } from "@/components/airline-logo";
import { ArticleCard } from "@/components/article-card";
import { HubMap } from "@/components/hub-map";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api";
import { worldRegions } from "@/lib/nav";
import { CATEGORY_BY_SLUG } from "@/lib/taxonomy";
import type {
  ArticleListOut,
  CountryOut,
  HubDetailOut,
  HubOverviewOut,
} from "@/lib/types";
import { cn } from "@/lib/utils";

const DAY_OPTIONS = [30, 90, 365] as const;

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

export function HubsClient() {
  const [days, setDays] = useState<number>(DAY_OPTIONS[1]);
  const [selected, setSelected] = useState<string | null>("IST");
  const [country, setCountry] = useState<string>("");

  const [overview, setOverview] = useState<HubOverviewOut | null>(null);
  const [detail, setDetail] = useState<HubDetailOut | null>(null);
  const [countries, setCountries] = useState<CountryOut[]>([]);
  const [articles, setArticles] = useState<ArticleListOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    Promise.all([
      apiFetch<HubOverviewOut>(`/hubs?days=${days}`, {
        cache: "default",
        signal: controller.signal,
      }),
      apiFetch<CountryOut[]>(`/taxonomy/countries?days=${days}`, {
        cache: "default",
        signal: controller.signal,
      }),
    ])
      .then(([hubData, countryData]) => {
        if (cancelled) return;
        setOverview(hubData);
        setCountries(countryData);
        setError(null);
      })
      .catch((err: unknown) => {
        if (cancelled || (err as Error)?.name === "AbortError") return;
        setError("Hub verisi yüklenemedi. Sunucu çalışıyor mu?");
      });
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [days]);

  // The detail panel and the story list answer the same question from two
  // sides, so they move together: pick a hub or a country and both follow.
  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    const params = new URLSearchParams({ limit: "12" });
    if (selected) params.set("airport", selected);
    if (country) params.set("country", country);

    const detailRequest = selected
      ? apiFetch<HubDetailOut>(`/hubs/${selected}?days=${days}`, {
          cache: "default",
          signal: controller.signal,
        })
      : Promise.resolve(null);

    Promise.all([
      detailRequest,
      apiFetch<ArticleListOut>(`/articles?${params.toString()}`, {
        cache: "default",
        signal: controller.signal,
      }),
    ])
      .then(([hubDetail, articleData]) => {
        if (cancelled) return;
        setDetail(hubDetail);
        setArticles(articleData);
      })
      .catch((err: unknown) => {
        if (cancelled || (err as Error)?.name === "AbortError") return;
        setError("Haberler yüklenemedi.");
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [selected, country, days]);

  const countriesByRegion = useMemo(() => {
    const groups = new Map<string, CountryOut[]>();
    for (const item of countries) {
      const key = item.region ?? "other";
      const bucket = groups.get(key);
      if (bucket) bucket.push(item);
      else groups.set(key, [item]);
    }
    return [...groups.entries()].sort(([a], [b]) =>
      (REGION_NAME[a] ?? "Diğer").localeCompare(REGION_NAME[b] ?? "Diğer", "tr"),
    );
  }, [countries]);

  return (
    <div className="flex flex-col gap-5 p-4 md:p-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">Hub&apos;lar</h1>
        <p className="max-w-2xl text-sm text-muted-foreground">
          İzlenen aktarma merkezleri ve haber arşivinin onlar hakkında biriktirdikleri.
          Bir hub seçin ya da ülkeye göre daraltın.
        </p>
      </header>

      {error && (
        <p className="rounded-lg border border-critical/40 bg-critical/10 p-3 text-sm text-critical">
          {error}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border border-border bg-card p-3">
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Dönem
          </span>
          {DAY_OPTIONS.map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => setDays(option)}
              className={chip(days === option)}
            >
              Son {option} gün
            </button>
          ))}
        </div>

        <div className="flex items-center gap-2">
          <label
            htmlFor="hub-country"
            className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground"
          >
            Ülke
          </label>
          {/* Only countries the archive can actually filter by are listed --
              the backend counts them rather than offering all 51 names. */}
          <select
            id="hub-country"
            value={country}
            onChange={(event) => setCountry(event.target.value)}
            className="rounded-lg border border-border bg-background px-2.5 py-1.5 text-xs"
          >
            <option value="">Tüm ülkeler</option>
            {countriesByRegion.map(([region, list]) => (
              <optgroup key={region} label={REGION_NAME[region] ?? "Diğer"}>
                {list.map((item) => (
                  <option key={item.name} value={item.name}>
                    {item.name} ({item.article_count})
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
          {country && (
            <button type="button" onClick={() => setCountry("")} className={chip(false)}>
              Temizle
            </button>
          )}
        </div>
      </div>

      {overview ? (
        <HubMap
          hubs={overview.hubs}
          routes={overview.routes}
          selected={selected}
          onSelect={setSelected}
        />
      ) : (
        <Skeleton className="h-[380px] w-full rounded-xl" />
      )}

      <div className="flex flex-wrap gap-1.5">
        {overview?.hubs.map((hub) => (
          <button
            key={hub.code}
            type="button"
            onClick={() => setSelected(hub.code === selected ? null : hub.code)}
            className={cn(
              chip(selected === hub.code),
              "flex items-center gap-1.5",
              hub.article_count === 0 && selected !== hub.code && "opacity-60",
            )}
          >
            <span className="font-semibold">{hub.code}</span>
            <span className="opacity-70">{hub.article_count}</span>
          </button>
        ))}
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,20rem)_minmax(0,1fr)]">
        {detail && (
          <aside className="flex h-fit flex-col gap-3 rounded-xl border border-border bg-card p-4">
            <div className="flex items-start justify-between gap-2">
              <div>
                <h2 className="text-lg font-semibold leading-tight">{detail.name}</h2>
                <p className="text-xs text-muted-foreground">
                  {detail.city} · {detail.country} · {REGION_NAME[detail.region] ?? detail.region}
                </p>
              </div>
              <span className="rounded-md bg-muted px-2 py-1 font-mono text-xs font-semibold">
                {detail.code}
              </span>
            </div>

            <p className="text-sm text-muted-foreground">{detail.note_tr}</p>

            {detail.carriers.length > 0 && (
              <div className="flex flex-col gap-1.5">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                  Üssü burada
                </span>
                <div className="flex flex-wrap gap-1.5">
                  {detail.carriers.map((code) => (
                    <span
                      key={code}
                      className="flex items-center gap-1.5 rounded-full border border-border px-2 py-1 text-xs"
                    >
                      <AirlineLogo code={code} className="size-3.5" />
                      {code}
                    </span>
                  ))}
                </div>
              </div>
            )}

            <div className="flex flex-col gap-1.5">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Son {detail.days} günde adı geçen taşıyıcılar
              </span>
              {detail.carriers_seen.length > 0 ? (
                <div className="flex flex-col gap-1">
                  {detail.carriers_seen.map((carrier) => (
                    <div key={carrier.code} className="flex items-center gap-2 text-xs">
                      <AirlineLogo code={carrier.code} name={carrier.name} className="size-3.5" />
                      <span className="flex-1 truncate">{carrier.name}</span>
                      <span className="font-mono tabular-nums text-muted-foreground">
                        {carrier.article_count}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-muted-foreground">
                  Bu dönemde bu hub&apos;la birlikte anılan taşıyıcı yok.
                </p>
              )}
            </div>

            {detail.categories.length > 0 && (
              <div className="flex flex-col gap-1.5">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                  Konu dağılımı
                </span>
                <div className="flex flex-wrap gap-1.5">
                  {detail.categories.map((entry) => (
                    <span
                      key={entry.slug}
                      className="rounded-full border border-border px-2 py-0.5 text-[11px] text-muted-foreground"
                    >
                      {CATEGORY_BY_SLUG[entry.slug]?.label ?? entry.slug} · {entry.count}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </aside>
        )}

        <section className="flex flex-col gap-2">
          <h2 className="flex items-center gap-2 text-sm font-semibold">
            <Plane className="size-4 text-muted-foreground" />
            {selected ? `${selected} haberleri` : "Haberler"}
            {country && <span className="text-muted-foreground">· {country}</span>}
          </h2>

          {articles ? (
            articles.items.length > 0 ? (
              <div className="divide-y divide-border rounded-xl border border-border bg-card">
                {articles.items.map((article) => (
                  <ArticleCard key={article.id} article={article} />
                ))}
              </div>
            ) : (
              <p className="rounded-xl border border-border bg-card p-6 text-sm text-muted-foreground">
                Bu seçim için haber yok. Arşiv bu hub ya da ülke hakkında henüz bir şey
                toplamamış — uydurma yerine boş gösteriyoruz.
              </p>
            )
          ) : (
            <Skeleton className="h-64 w-full rounded-xl" />
          )}
        </section>
      </div>
    </div>
  );
}
