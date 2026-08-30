"use client";

import { CalendarDays, MapPin } from "lucide-react";
import { useEffect, useState } from "react";

import { apiFetch } from "@/lib/api";
import type { EventOut } from "@/lib/types";
import { cn } from "@/lib/utils";

/** How far ahead the radar looks. Roughly two months: far enough that a
 * capacity decision can still be made, near enough that the row is not a
 * year-planner nobody scrolls. */
const HORIZON_DAYS = 60;

const IMPACT_META: Record<EventOut["impact_level"], { label: string; className: string; rank: number }> = {
  high: { label: "Yüksek etki", className: "border-critical/40 bg-critical/10 text-critical", rank: 0 },
  medium: { label: "Orta etki", className: "border-warning/40 bg-warning/10 text-warning", rank: 1 },
  low: { label: "Düşük etki", className: "border-border bg-muted text-muted-foreground", rank: 2 },
};

const MAX_EVENTS = 8;

function isoDay(offsetDays: number): string {
  const date = new Date();
  date.setDate(date.getDate() + offsetDays);
  return date.toISOString().slice(0, 10);
}

/** "Etkinlik Radarı" -- the curated demand events coming up.
 *
 * Reads the existing /events endpoint; nothing new server-side. Sorted by
 * impact first and date second, because the question this row answers is
 * "what is big enough to plan around", not "what is next on the calendar" --
 * the calendar itself already answers the second one and is one click away.
 *
 * `impact_level` is hand-curated (backend/app/models/event.py), never
 * inferred, which is exactly why it is safe to sort on: it is somebody's
 * judgement, recorded, rather than a model's guess restated as a number.
 */
export function EventRadarStrip({ onOpenCalendar }: { onOpenCalendar?: () => void }) {
  const [events, setEvents] = useState<EventOut[]>([]);

  useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams({
      date_from: isoDay(0),
      date_to: isoDay(HORIZON_DAYS),
    });
    apiFetch<EventOut[]>(`/events?${params.toString()}`, {
      cache: "default",
      signal: controller.signal,
    })
      .then((rows) =>
        setEvents(
          [...rows]
            .sort(
              (a, b) =>
                IMPACT_META[a.impact_level].rank - IMPACT_META[b.impact_level].rank ||
                a.starts.localeCompare(b.starts),
            )
            .slice(0, MAX_EVENTS),
        ),
      )
      .catch(() => {
        /* the radar is an addition to the paper, never a precondition */
      });
    return () => controller.abort();
  }, []);

  if (events.length === 0) return null;

  return (
    <section aria-label="Etkinlik radarı" className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          <CalendarDays className="size-4" aria-hidden />
          Etkinlik Radarı
        </h2>
        <span className="text-[11px] text-muted-foreground">önümüzdeki {HORIZON_DAYS} gün</span>
        {onOpenCalendar && (
          <button
            type="button"
            onClick={onOpenCalendar}
            className="ml-auto rounded-md border border-border px-2 py-1 text-[11px] font-medium transition-colors hover:bg-accent"
          >
            Takvimi aç
          </button>
        )}
      </div>
      <div className="flex gap-2 overflow-x-auto pb-1">
        {events.map((event) => (
          <a
            key={event.id}
            href={event.url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex w-56 shrink-0 flex-col gap-1.5 rounded-lg border border-border bg-card p-3 transition-colors hover:bg-accent/40"
          >
            <span
              className={cn(
                "w-fit rounded-full border px-2 py-0.5 text-[10px] font-semibold",
                IMPACT_META[event.impact_level].className,
              )}
            >
              {IMPACT_META[event.impact_level].label}
            </span>
            <span className="line-clamp-2 text-xs font-medium leading-snug text-card-foreground">
              {event.name}
            </span>
            {/* Pre-formatted server-side so the frontend never re-implements
                Turkish month names. */}
            <span className="text-[11px] tabular-nums text-muted-foreground">
              {event.date_range_tr}
            </span>
            <span className="flex items-center gap-1 text-[11px] text-muted-foreground">
              <MapPin className="size-3 shrink-0" aria-hidden />
              <span className="truncate">
                {event.city}
                {event.country ? `, ${event.country}` : ""}
              </span>
            </span>
          </a>
        ))}
      </div>
    </section>
  );
}
