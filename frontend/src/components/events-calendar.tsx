"use client";

import { CalendarDays, ExternalLink, MapPin } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api";
import { EVENT_REGIONS } from "@/lib/taxonomy";
import type { EventOut } from "@/lib/types";
import { cn } from "@/lib/utils";

const TYPE_LABELS: Record<EventOut["event_type"], string> = {
  airshow: "Fuar",
  conference: "Konferans",
  sports: "Spor",
  holiday: "Bayram/Tatil",
  festival: "Festival",
};

// Distinct tint per type -- literal class strings so Tailwind's scanner sees them.
const TYPE_CLASSES: Record<EventOut["event_type"], string> = {
  airshow: "bg-category-fleet/10 text-category-fleet",
  conference: "bg-category-regulatory/10 text-category-regulatory",
  sports: "bg-category-network/10 text-category-network",
  holiday: "bg-category-revenue-management/10 text-category-revenue-management",
  festival: "bg-category-events/10 text-category-events",
};

function monthKey(iso: string): string {
  return iso.slice(0, 7); // YYYY-MM
}

function monthLabel(iso: string): string {
  return new Date(iso + "-01T12:00:00Z").toLocaleDateString("tr-TR", {
    month: "long",
    year: "numeric",
  });
}

export function EventsCalendar() {
  const [events, setEvents] = useState<EventOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [regionSlug, setRegionSlug] = useState<string | null>(null);
  const [typeSlug, setTypeSlug] = useState<EventOut["event_type"] | null>(null);

  useEffect(() => {
    let cancelled = false;
    // ~30 curated events: fetch once (from today onward), filter client-side.
    const today = new Date().toISOString().slice(0, 10);
    apiFetch<EventOut[]>(`/events?date_from=${today}`)
      .then((data) => {
        if (!cancelled) setEvents(data);
      })
      .catch(() => {
        if (!cancelled) setError("Etkinlikler yüklenemedi. Sunucu çalışıyor mu?");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const filtered = useMemo(
    () =>
      (events ?? []).filter(
        (e) =>
          (!regionSlug || e.region === regionSlug) && (!typeSlug || e.event_type === typeSlug),
      ),
    [events, regionSlug, typeSlug],
  );

  const byMonth = useMemo(() => {
    const groups = new Map<string, EventOut[]>();
    for (const event of filtered) {
      const key = monthKey(event.starts);
      groups.set(key, [...(groups.get(key) ?? []), event]);
    }
    return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [filtered]);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">Etkinlik Takvimi</h1>
        <p className="text-sm text-muted-foreground">
          Önümüzdeki 12 ayın doğrulanmış havacılık fuarları, konferansları ve talep
          etkileyen tatil/spor dönemleri. Tarihler organizatör kaynaklarından; hilale
          bağlı bayramlar ±1 gün oynayabilir.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Bölge
        </span>
        <button
          onClick={() => setRegionSlug(null)}
          className={cn(
            "rounded-full px-2.5 py-1 text-xs font-medium transition-colors",
            !regionSlug
              ? "bg-primary text-primary-foreground"
              : "border border-border text-muted-foreground hover:bg-accent",
          )}
        >
          Tümü
        </button>
        {EVENT_REGIONS.map((r) => (
          <button
            key={r.slug}
            onClick={() => setRegionSlug(regionSlug === r.slug ? null : r.slug)}
            className={cn(
              "rounded-full px-2.5 py-1 text-xs font-medium transition-colors",
              regionSlug === r.slug
                ? "bg-primary text-primary-foreground"
                : "border border-border text-muted-foreground hover:bg-accent",
            )}
          >
            {r.name}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Tür
        </span>
        <button
          onClick={() => setTypeSlug(null)}
          className={cn(
            "rounded-full px-2.5 py-1 text-xs font-medium transition-colors",
            !typeSlug
              ? "bg-primary text-primary-foreground"
              : "border border-border text-muted-foreground hover:bg-accent",
          )}
        >
          Tümü
        </button>
        {(Object.keys(TYPE_LABELS) as EventOut["event_type"][]).map((t) => (
          <button
            key={t}
            onClick={() => setTypeSlug(typeSlug === t ? null : t)}
            className={cn(
              "rounded-full px-2.5 py-1 text-xs font-medium transition-colors",
              typeSlug === t
                ? "bg-primary text-primary-foreground"
                : "border border-border text-muted-foreground hover:bg-accent",
            )}
          >
            {TYPE_LABELS[t]}
          </button>
        ))}
      </div>

      {error ? (
        <p className="rounded-lg border border-dashed border-border p-6 text-sm text-muted-foreground">
          {error}
        </p>
      ) : events === null ? (
        <div className="flex flex-col gap-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-24 w-full rounded-xl" />
          ))}
        </div>
      ) : byMonth.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
          Bu filtreyle önümüzdeki dönemde etkinlik bulunamadı.
        </p>
      ) : (
        <div className="flex flex-col gap-8">
          {byMonth.map(([key, monthEvents]) => (
            <section key={key} className="flex flex-col gap-3">
              <h2 className="sticky top-0 z-10 -mx-2 bg-background/80 px-2 py-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground backdrop-blur">
                {monthLabel(key)}
              </h2>
              <div className="flex flex-col gap-3">
                {monthEvents.map((event) => (
                  <a
                    key={event.id}
                    href={event.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="group flex flex-col gap-2 rounded-xl border border-border bg-card p-4 transition-all duration-200 hover:-translate-y-0.5 hover:border-primary/50 hover:shadow-sm"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={cn(
                          "rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
                          TYPE_CLASSES[event.event_type],
                        )}
                      >
                        {TYPE_LABELS[event.event_type]}
                      </span>
                      <span className="flex items-center gap-1 text-xs font-medium text-foreground">
                        <CalendarDays className="size-3.5 text-muted-foreground" />
                        {event.date_range_tr}
                      </span>
                      <span className="flex items-center gap-1 text-xs text-muted-foreground">
                        <MapPin className="size-3.5" />
                        {event.city}
                        {event.country && event.country !== event.city
                          ? `, ${event.country}`
                          : ""}
                      </span>
                    </div>
                    <div className="flex items-start justify-between gap-3">
                      <span className="font-medium text-card-foreground group-hover:text-primary">
                        {event.name}
                      </span>
                      <ExternalLink className="mt-1 size-3.5 shrink-0 opacity-0 transition-opacity group-hover:opacity-100" />
                    </div>
                    <p className="text-xs leading-relaxed text-muted-foreground">
                      {event.summary_tr}
                    </p>
                  </a>
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
