"use client";

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import type { LucideIcon } from "lucide-react";
import {
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  Gauge,
  MapPin,
  Megaphone,
  Plane,
  Users,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { AirlineLogo } from "@/components/airline-logo";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api";
import { useMeasuredHeight } from "@/lib/motion";
import { airlineTabs } from "@/lib/nav";
import { EVENT_REGIONS } from "@/lib/taxonomy";
import type { EventOut, PromotionOut } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Carrier brand hex, by IATA code. Campaigns are drawn in their airline's own
 * colour -- deliberately a different colour *system* from the five --chart-*
 * event hues, so the two layers can never be confused for one scale. */
const BRAND_HEX: Record<string, string> = Object.fromEntries(
  airlineTabs.map((a) => [a.code, a.color]),
);

// Declared in --chart-1..5 order: this record drives both the type filter row
// and its legend dots, so its order is the order the reader meets the hues in.
const TYPE_LABELS: Record<EventOut["event_type"], string> = {
  airshow: "Fuar",
  sports: "Spor",
  holiday: "Bayram/Tatil",
  conference: "Konferans",
  festival: "Festival",
};

// Five event types, five chart tokens -- the app's validated dataviz hues,
// used here as *content* colour: every pill, bar and dot on the grid is the
// event's own type. Literal class strings so Tailwind's scanner sees them.
const TYPE_PILL: Record<EventOut["event_type"], string> = {
  airshow: "bg-chart-1/15 text-chart-1",
  sports: "bg-chart-2/15 text-chart-2",
  holiday: "bg-chart-3/15 text-chart-3",
  conference: "bg-chart-4/15 text-chart-4",
  festival: "bg-chart-5/15 text-chart-5",
};

/** Continuation days get a thin bar rather than a repeated pill: the name is
 * already stated on the start day, the bar just carries the run forward. */
const TYPE_BAR: Record<EventOut["event_type"], string> = {
  airshow: "bg-chart-1/60",
  sports: "bg-chart-2/60",
  holiday: "bg-chart-3/60",
  conference: "bg-chart-4/60",
  festival: "bg-chart-5/60",
};

const TYPE_DOT: Record<EventOut["event_type"], string> = {
  airshow: "bg-chart-1",
  sports: "bg-chart-2",
  holiday: "bg-chart-3",
  conference: "bg-chart-4",
  festival: "bg-chart-5",
};

const TYPE_GLOW: Record<EventOut["event_type"], string> = {
  airshow: "var(--chart-1)",
  sports: "var(--chart-2)",
  holiday: "var(--chart-3)",
  conference: "var(--chart-4)",
  festival: "var(--chart-5)",
};

/** Nine regions on nine of the eleven --category-* tokens. `general` is the
 * neutral hue (no identity) and `sustainability` would read as a second green
 * next to `network`, so both sit this one out.
 *
 * Region colour is *chrome*: filter chips, the month label's glow, the region
 * chip and the selected day's ring. It is never painted onto an individual
 * event -- with a region filter active every visible event already belongs to
 * it, so a per-event region mark would say nothing. */
const REGION_GLOW: Record<string, string> = {
  europe: "var(--category-regulatory)",
  "middle-east": "var(--category-revenue-management)",
  africa: "var(--category-airport)",
  "north-america": "var(--category-fleet)",
  "south-america": "var(--category-network)",
  "central-america": "var(--category-events)",
  asia: "var(--category-finance)",
  "southeast-asia": "var(--category-labor)",
  oceania: "var(--category-safety)",
};

// Impact rides on the status palette, not on the type tints above: it is a
// state (how hard this hits demand), not another category. Icon + word carry
// the meaning, so the colour is never the only signal.
const IMPACT_META: Record<EventOut["impact_level"], { label: string; className: string }> = {
  high: { label: "Yüksek etki", className: "border-critical/40 bg-critical/10 text-critical" },
  medium: { label: "Orta etki", className: "border-warning/40 bg-warning/10 text-warning" },
  low: { label: "Düşük etki", className: "border-border bg-muted text-muted-foreground" },
};

const ATTENDANCE_FORMAT = new Intl.NumberFormat("tr-TR");

/** Turkish weeks start on Monday. */
const WEEKDAYS = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"];

/** The seeded calendar covers the next 12 months; the nav refuses to walk off
 * either end of that rather than showing empty grids. */
const MONTH_HORIZON = 12;
/** Safety rail on the day-by-day walk: a malformed row (ends before starts, or
 * an ends decades out) must not spin the loop. Longer than any real entry. */
const MAX_EVENT_DAYS = 62;
/** Events a desktop cell shows before collapsing the rest into "+N daha". */
const DESKTOP_EVENT_SLOTS = 3;
/** Dots a phone-width cell shows before collapsing into "+N". */
const MOBILE_DOT_SLOTS = 4;
/** Campaign ribbons a cell shows before collapsing into "+N". Three thin
 * strips is the most that stays legible above a date; a fourth turns the row
 * into a texture. */
const RIBBON_SLOTS = 3;
/** How far past today an open-ended campaign keeps painting ribbons. Same rule
 * as the /kampanyalar timeline's fade-out: with no published end date the
 * window has to stop somewhere, and a week is the honest guess about how long
 * "still running" means without saying so on screen. */
const OPEN_ENDED_RUNOUT_DAYS = 7;

function toKey(y: number, m: number, d: number): string {
  return `${y}-${String(m + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}

/** "2026-08" -> "Ağustos 2026". Anchored at midday UTC so no reader's timezone
 * can shift it onto the previous month. */
function monthLabel(iso: string): string {
  return new Date(iso + "-01T12:00:00Z").toLocaleDateString("tr-TR", {
    month: "long",
    year: "numeric",
  });
}

/** Months since year 0, so cursor arithmetic and the horizon bounds are one
 * integer comparison instead of two. */
function monthIndex(y: number, m: number): number {
  return y * 12 + m;
}

export function EventsCalendar() {
  const reduceMotion = useReducedMotion();

  const [events, setEvents] = useState<EventOut[] | null>(null);
  const [promotions, setPromotions] = useState<PromotionOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  // On by default: a rival's sale window is the layer a revenue desk came to
  // this calendar for, and a layer nobody switches on is a layer nobody sees.
  const [showPromos, setShowPromos] = useState(true);
  const [regionSlug, setRegionSlug] = useState<string | null>(null);
  const [typeSlug, setTypeSlug] = useState<EventOut["event_type"] | null>(null);
  const [selectedDay, setSelectedDay] = useState<string | null>(null);

  // Read once per mount: `todayKey` has to be stable across renders, and the
  // page is not open across a midnight boundary in any meaningful sense.
  const [today] = useState(() => new Date());
  const todayKey = toKey(today.getFullYear(), today.getMonth(), today.getDate());
  const firstIndex = monthIndex(today.getFullYear(), today.getMonth());

  const [cursor, setCursor] = useState(() => ({
    y: today.getFullYear(),
    m: today.getMonth(),
  }));
  const cursorIndex = monthIndex(cursor.y, cursor.m);

  useEffect(() => {
    let cancelled = false;
    // From the first of the *viewed* month, not from today: the endpoint
    // filters on `ends >= date_from`, so an event already in progress (or one
    // that started in the previous month and runs into this one) still comes
    // back and still draws its continuation bars.
    const dateFrom = `${cursor.y}-${String(cursor.m + 1).padStart(2, "0")}-01`;
    const dateTo = toKey(cursor.y, cursor.m, new Date(cursor.y, cursor.m + 1, 0).getDate());
    apiFetch<EventOut[]>(`/events?date_from=${dateFrom}`)
      .then((data) => {
        if (cancelled) return;
        setEvents(data);
        setError(null);
      })
      .catch(() => {
        if (!cancelled) setError("Etkinlikler yüklenemedi. Sunucu çalışıyor mu?");
      });
    // A separate request, and a separate failure: campaigns are an overlay on
    // this calendar, not its subject. If /promotions is down the calendar is
    // still a calendar, so the ribbons simply do not appear.
    apiFetch<PromotionOut[]>(
      `/promotions?date_from=${dateFrom}&date_to=${dateTo}`,
    )
      .then((data) => {
        if (!cancelled) setPromotions(data);
      })
      .catch(() => {
        if (!cancelled) setPromotions([]);
      });
    return () => {
      cancelled = true;
    };
  }, [cursor]);

  const filtered = useMemo(
    () =>
      (events ?? []).filter(
        (e) =>
          (!regionSlug || e.region === regionSlug) && (!typeSlug || e.event_type === typeSlug),
      ),
    [events, regionSlug, typeSlug],
  );

  /** "YYYY-MM-DD" -> the events touching that day. Multi-day entries are walked
   * out day by day so a five-day fair paints five cells, not one. */
  const dayIndex = useMemo(() => {
    const index = new Map<string, { event: EventOut; isStart: boolean }[]>();
    for (const event of filtered) {
      const start = new Date(`${event.starts}T12:00:00Z`);
      const end = new Date(`${event.ends}T12:00:00Z`);
      if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) continue;
      const walker = new Date(start);
      for (let guard = 0; guard < MAX_EVENT_DAYS; guard += 1) {
        const key = toKey(
          walker.getUTCFullYear(),
          walker.getUTCMonth(),
          walker.getUTCDate(),
        );
        const entry = { event, isStart: key === event.starts };
        const bucket = index.get(key);
        if (bucket) bucket.push(entry);
        else index.set(key, [entry]);
        if (walker >= end) break;
        walker.setUTCDate(walker.getUTCDate() + 1);
      }
    }
    return index;
  }, [filtered]);

  /** Every cell the month needs, including the adjacent-month days that fill
   * the first and last weeks. Row count is variable: a 31-day month starting on
   * a Sunday needs six rows, February starting on a Monday needs four. */
  const cells = useMemo(() => {
    const offset = (new Date(cursor.y, cursor.m, 1).getDay() + 6) % 7;
    const daysInMonth = new Date(cursor.y, cursor.m + 1, 0).getDate();
    const rows = Math.ceil((offset + daysInMonth) / 7);
    return Array.from({ length: rows * 7 }, (_, i) => {
      const date = new Date(cursor.y, cursor.m, i - offset + 1);
      return {
        key: toKey(date.getFullYear(), date.getMonth(), date.getDate()),
        day: date.getDate(),
        inMonth: date.getMonth() === cursor.m && date.getFullYear() === cursor.y,
      };
    });
  }, [cursor]);

  /** "YYYY-MM-DD" -> the campaigns whose SALE window touches that day.
   *
   * Sale rather than travel, matching the /kampanyalar timeline: the sale
   * window is the one a revenue desk has to react to inside this week.
   *
   * Built by comparing ISO strings against the ~42 visible cells rather than
   * by walking each campaign day by day. A campaign window is routinely seven
   * months long, so the walk that suits a five-day fair would be thousands of
   * iterations here for the same forty-two answers.
   *
   * A campaign with no published start date contributes no ribbon at all --
   * there is no window to lay along a row of days, and inventing one would be
   * indistinguishable from a measured one. Those campaigns live on the
   * /kampanyalar timeline as point markers instead. */
  const promoDayIndex = useMemo(() => {
    const index = new Map<string, PromotionOut[]>();
    if (!showPromos || promotions.length === 0) return index;

    const runout = new Date(today);
    runout.setDate(runout.getDate() + OPEN_ENDED_RUNOUT_DAYS);
    const runoutKey = toKey(runout.getFullYear(), runout.getMonth(), runout.getDate());

    const windows: { promo: PromotionOut; start: string; end: string }[] = [];
    for (const promo of promotions) {
      const start = promo.sale_starts;
      if (!start) continue;
      const end = promo.sale_ends ?? (runoutKey > start ? runoutKey : start);
      if (end < start) continue;
      windows.push({ promo, start, end });
    }

    for (const cell of cells) {
      const hits = windows.filter((w) => w.start <= cell.key && cell.key <= w.end);
      if (hits.length > 0) index.set(cell.key, hits.map((h) => h.promo));
    }
    return index;
  }, [promotions, cells, showPromos, today]);

  const step = (delta: number) =>
    setCursor((prev) => {
      const next = monthIndex(prev.y, prev.m) + delta;
      return { y: Math.floor(next / 12), m: ((next % 12) + 12) % 12 };
    });

  const goToday = () => {
    setCursor({ y: today.getFullYear(), m: today.getMonth() });
    setSelectedDay(todayKey);
  };

  const regionName = regionSlug
    ? (EVENT_REGIONS.find((r) => r.slug === regionSlug)?.name ?? regionSlug)
    : null;
  const activeRegionGlow = regionSlug ? REGION_GLOW[regionSlug] : null;

  return (
    // One override point drives every piece of region-coloured chrome below:
    // the selection ring, the month label's glow and the region chip.
    <div
      className="flex flex-col gap-6"
      style={{ "--glow-color": activeRegionGlow ?? "var(--primary)" } as React.CSSProperties}
    >
      <div className="flex flex-col gap-1">
        <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">Etkinlik Takvimi</h1>
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
        <FilterChip label="Tümü" active={!regionSlug} onClick={() => setRegionSlug(null)} />
        {EVENT_REGIONS.map((r) => (
          <FilterChip
            key={r.slug}
            label={r.name}
            active={regionSlug === r.slug}
            // Single-select on purpose: exactly one region's colour owns the
            // heading, and two would have nothing to arbitrate between.
            onClick={() => setRegionSlug(regionSlug === r.slug ? null : r.slug)}
            glow={REGION_GLOW[r.slug]}
            dotColor={REGION_GLOW[r.slug]}
          />
        ))}
      </div>

      {/* Doubles as the grid's legend: the dots are permanent, so the reader can
          decode a pill's colour without selecting anything. */}
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Tür
        </span>
        <FilterChip label="Tümü" active={!typeSlug} onClick={() => setTypeSlug(null)} />
        {(Object.keys(TYPE_LABELS) as EventOut["event_type"][]).map((t) => (
          <FilterChip
            key={t}
            label={TYPE_LABELS[t]}
            active={typeSlug === t}
            onClick={() => setTypeSlug(typeSlug === t ? null : t)}
            glow={TYPE_GLOW[t]}
            dotClass={TYPE_DOT[t]}
          />
        ))}
        {/* A toggle, not a sixth type: campaigns are a separate layer over the
            grid, so this switches a layer on and off rather than joining the
            single-select that filters events. --signal amber is the chip's own
            identity -- chrome for "there is another layer here" -- and never
            appears on a ribbon, which always wears its carrier's colour. */}
        <FilterChip
          label="Kampanyalar"
          active={showPromos}
          onClick={() => setShowPromos((v) => !v)}
          glow="var(--signal)"
          dotColor="var(--signal)"
          icon={Megaphone}
        />
      </div>

      {error ? (
        <p className="rounded-lg border border-dashed border-border p-6 text-sm text-muted-foreground">
          {error}
        </p>
      ) : events === null ? (
        <Skeleton className="h-105 w-full rounded-xl" />
      ) : (
        <>
          <MonthHeader
            label={monthLabel(`${cursor.y}-${String(cursor.m + 1).padStart(2, "0")}`)}
            regionName={regionName}
            regionColor={activeRegionGlow}
            canPrev={cursorIndex > firstIndex}
            canNext={cursorIndex < firstIndex + MONTH_HORIZON}
            onPrev={() => step(-1)}
            onNext={() => step(1)}
            onToday={goToday}
            reduceMotion={Boolean(reduceMotion)}
          />

          <div className="overflow-hidden rounded-xl border border-border bg-card shadow-elev-1">
            <div className="grid grid-cols-7 border-b border-border bg-muted/40">
              {WEEKDAYS.map((label) => (
                <div
                  key={label}
                  className="py-2 text-center text-[11px] font-semibold uppercase tracking-wide text-muted-foreground"
                >
                  {label}
                </div>
              ))}
            </div>
            {/* gap-px over the border colour: every cell paints its own surface,
                so the gaps read as hairlines instead of costing 42 borders. */}
            <div className="grid grid-cols-7 gap-px bg-border/60">
              {cells.map((cell) => (
                <DayCell
                  key={cell.key}
                  day={cell.day}
                  inMonth={cell.inMonth}
                  isToday={cell.key === todayKey}
                  isSelected={cell.key === selectedDay}
                  entries={dayIndex.get(cell.key) ?? []}
                  promos={promoDayIndex.get(cell.key) ?? []}
                  onSelect={() =>
                    setSelectedDay((prev) => (prev === cell.key ? null : cell.key))
                  }
                />
              ))}
            </div>
          </div>

          {/* Kept from the agenda view: a filter that matches nothing says so
              rather than leaving the reader staring at a blank grid. */}
          {filtered.length === 0 && (
            <p className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
              Bu filtreyle önümüzdeki dönemde etkinlik bulunamadı.
            </p>
          )}

          {/* A constant key on purpose: moving between two selected days swaps
              the panel's contents in place, so only opening and closing the
              panel animates its height. */}
          <AnimatePresence initial={false}>
            {selectedDay && (
              <DayDetailPanel
                key="day-detail"
                dayKey={selectedDay}
                entries={dayIndex.get(selectedDay) ?? []}
                promos={promoDayIndex.get(selectedDay) ?? []}
                reduceMotion={Boolean(reduceMotion)}
              />
            )}
          </AnimatePresence>
        </>
      )}
    </div>
  );
}

/** One chip for both filter rows. `glow` is the chip's identity hue (absent on
 * "Tümü", which has none); `dotColor`/`dotClass` are the same hue as a
 * permanent legend mark, inline for regions and as a class for types. */
function FilterChip({
  label,
  active,
  onClick,
  glow,
  dotClass,
  dotColor,
  icon: Icon,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
  glow?: string;
  dotClass?: string;
  dotColor?: string;
  /** Stands in for the legend dot. The campaign toggle uses one because it is
   * a layer switch rather than a colour key -- an icon says "this is a
   * different kind of control" where a dot would say "this is a sixth hue". */
  icon?: LucideIcon;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={
        active && glow
          ? ({ "--glow-color": glow, color: glow } as React.CSSProperties)
          : undefined
      }
      className={cn(
        "flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium transition-colors",
        active
          ? glow
            ? "edge-lit border font-semibold"
            : "bg-primary text-primary-foreground"
          : "border border-border text-muted-foreground hover:bg-accent",
      )}
    >
      {Icon ? (
        <Icon aria-hidden className="size-3.5 shrink-0" />
      ) : (
        (dotClass || dotColor) && (
          <span
            aria-hidden
            className={cn("size-2 shrink-0 rounded-full", dotClass)}
            style={dotColor ? { backgroundColor: dotColor } : undefined}
          />
        )
      )}
      {label}
    </button>
  );
}

function MonthHeader({
  label,
  regionName,
  regionColor,
  canPrev,
  canNext,
  onPrev,
  onNext,
  onToday,
  reduceMotion,
}: {
  label: string;
  regionName: string | null;
  regionColor: string | null;
  canPrev: boolean;
  canNext: boolean;
  onPrev: () => void;
  onNext: () => void;
  onToday: () => void;
  reduceMotion: boolean;
}) {
  const navButton =
    "inline-flex size-8 items-center justify-center rounded-lg border border-border text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:pointer-events-none disabled:opacity-40";

  return (
    <div className="flex flex-wrap items-center gap-3">
      <h2
        className={cn(
          "text-xl font-semibold tracking-tight tabular-nums sm:text-2xl",
          regionName && "text-glow",
        )}
      >
        {label}
      </h2>

      <AnimatePresence initial={false}>
        {regionName && (
          <motion.span
            key={regionName}
            initial={reduceMotion ? { opacity: 0 } : { opacity: 0, x: -6 }}
            animate={reduceMotion ? { opacity: 1 } : { opacity: 1, x: 0 }}
            exit={reduceMotion ? { opacity: 0 } : { opacity: 0, x: -6 }}
            // Inherits --glow-color from the calendar root, so `edge-lit`
            // already wears this region's hue on its border and wash.
            className="edge-lit rounded-full border px-3 py-1 text-sm font-semibold"
            style={regionColor ? { color: regionColor } : undefined}
          >
            {regionName}
          </motion.span>
        )}
      </AnimatePresence>

      <div className="ml-auto flex items-center gap-1">
        <button
          type="button"
          aria-label="Önceki ay"
          onClick={onPrev}
          disabled={!canPrev}
          className={navButton}
        >
          <ChevronLeft className="size-4" />
        </button>
        <button
          type="button"
          aria-label="Sonraki ay"
          onClick={onNext}
          disabled={!canNext}
          className={navButton}
        >
          <ChevronRight className="size-4" />
        </button>
        <button
          type="button"
          onClick={onToday}
          className="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
        >
          Bugün
        </button>
      </div>
    </div>
  );
}

function DayCell({
  day,
  inMonth,
  isToday,
  isSelected,
  entries,
  promos,
  onSelect,
}: {
  day: number;
  inMonth: boolean;
  isToday: boolean;
  isSelected: boolean;
  entries: { event: EventOut; isStart: boolean }[];
  promos: PromotionOut[];
  onSelect: () => void;
}) {
  // Past three, the third slot becomes the counter -- two named events plus
  // "+N daha" beats three names and a silently dropped fourth.
  const hasOverflow = entries.length > DESKTOP_EVENT_SLOTS;
  const shown = hasOverflow ? entries.slice(0, DESKTOP_EVENT_SLOTS - 1) : entries;
  const hiddenCount = entries.length - shown.length;

  const dots = entries.slice(0, MOBILE_DOT_SLOTS);
  const promoDots = promos.slice(0, MOBILE_DOT_SLOTS);
  const dotOverflow = entries.length - dots.length + (promos.length - promoDots.length);

  const ribbons = promos.slice(0, RIBBON_SLOTS);
  const ribbonOverflow = promos.length - ribbons.length;

  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "group relative flex min-h-24 flex-col items-stretch gap-1 p-1.5 text-left transition-colors hover:bg-accent/40 sm:min-h-28",
        inMonth ? "bg-card" : "bg-card/50",
        isSelected && "z-10 ring-2 ring-inset ring-(--glow-color) glow-soft",
      )}
    >
      {/* Adjacent-month days stay clickable but recede; dimming the wrapper
          rather than the button keeps the selection ring at full strength. */}
      <div className={cn("flex flex-1 flex-col gap-1", !inMonth && "opacity-50")}>
        {/* Campaign ribbons, above the date and geometrically unlike anything
            else in the cell: thin strips spanning the day's width, where every
            event mark is a named pill or a dot below the date. The two layers
            therefore never compete for the five-colour scheme -- shape tells
            them apart before colour is even read. */}
        {ribbons.length > 0 && (
          <div className="flex gap-0.5 pb-0.5">
            {ribbons.map((promo) => (
              <span
                key={promo.id}
                title={`${promo.airline_code} — ${promo.title_tr}`}
                className="h-1 flex-1 rounded-full"
                style={{ backgroundColor: BRAND_HEX[promo.airline_code] ?? "var(--signal)" }}
              />
            ))}
            {ribbonOverflow > 0 && (
              <span className="text-[9px] text-muted-foreground">+{ribbonOverflow}</span>
            )}
          </div>
        )}

        {isToday ? (
          <span className="flex size-6 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">
            {day}
          </span>
        ) : (
          <span className="text-xs font-medium tabular-nums text-muted-foreground">
            {day}
          </span>
        )}

        <div className="hidden flex-col gap-1 sm:flex">
          {shown.map(({ event, isStart }) =>
            isStart ? (
              <span
                key={event.id}
                title={event.name}
                className={cn(
                  // currentColor = the pill's own text colour, so the 2px lit
                  // left edge is always the event type's hue.
                  "h-5 truncate rounded-md px-1.5 text-[10px] font-medium leading-5 shadow-[inset_2px_0_0_0_currentColor]",
                  TYPE_PILL[event.event_type],
                )}
              >
                {event.name}
              </span>
            ) : (
              <span
                key={event.id}
                title={event.name}
                className={cn("h-1 rounded-full", TYPE_BAR[event.event_type])}
              />
            ),
          )}
          {hiddenCount > 0 && (
            <span className="text-[10px] font-medium text-muted-foreground">
              +{hiddenCount} daha
            </span>
          )}
        </div>

        {/* Phone width has no room for names: dots carry "something happens
            here, of these types", the detail panel carries the rest. */}
        <div className="flex flex-wrap gap-0.5 pt-0.5 sm:hidden">
          {dots.map(({ event }) => (
            <span
              key={event.id}
              className={cn("size-1.5 rounded-full", TYPE_DOT[event.event_type])}
            />
          ))}
          {/* Squares, not circles. Shape distinguishes the layer here for the
              same reason the ribbons do it upstairs: at 6px a hue is barely a
              hue, and the event dots have already spent all five of them. */}
          {promoDots.map((promo) => (
            <span
              key={promo.id}
              className="size-1.5 rounded-[2px]"
              style={{ backgroundColor: BRAND_HEX[promo.airline_code] ?? "var(--signal)" }}
            />
          ))}
          {dotOverflow > 0 && (
            <span className="text-[9px] text-muted-foreground">+{dotOverflow}</span>
          )}
        </div>
      </div>
    </button>
  );
}

function DayDetailPanel({
  dayKey,
  entries,
  promos,
  reduceMotion,
}: {
  dayKey: string;
  entries: { event: EventOut; isStart: boolean }[];
  promos: PromotionOut[];
  reduceMotion: boolean;
}) {
  const heading = new Date(`${dayKey}T12:00:00Z`).toLocaleDateString("tr-TR", {
    day: "numeric",
    month: "long",
    year: "numeric",
    weekday: "long",
  });

  // The panel opens to a measured pixel height instead of to `"auto"`, which
  // forces a layout pass per frame. The measurement rides a ResizeObserver, so
  // swapping days (the panel keeps a constant key and changes contents in
  // place) and viewport reflows both move the target with the content.
  const [contentRef, measuredHeight] = useMeasuredHeight<HTMLDivElement>();

  return (
    <motion.div
      initial={reduceMotion ? false : { opacity: 0, height: 0 }}
      // Under reduced motion `height` is left out of the animation target
      // entirely, so the panel is simply laid out at its natural height and
      // nothing about it animates -- the same full bypass as before, which a
      // pixel target would otherwise have broken (`initial={false}` starts at
      // the animate values, and on the first render that height is still 0).
      animate={reduceMotion ? { opacity: 1 } : { opacity: 1, height: measuredHeight }}
      exit={reduceMotion ? { opacity: 0 } : { opacity: 0, height: 0 }}
      transition={reduceMotion ? { duration: 0 } : { duration: 0.25, ease: "easeOut" }}
      className="overflow-hidden"
    >
      <div ref={contentRef} className="flex flex-col gap-3">
        <h3 className="text-lg font-semibold">{heading}</h3>

        {entries.length === 0 && promos.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Bu günde etkinlik veya kampanya yok.
          </p>
        ) : (
          entries.map(({ event }) => (
            <a
              key={event.id}
              href={event.url}
              target="_blank"
              rel="noopener noreferrer"
              style={{ "--glow-color": TYPE_GLOW[event.event_type] } as React.CSSProperties}
              className="edge-lit group flex flex-col gap-2 rounded-xl border bg-card p-4 transition-all duration-200 hover:-translate-y-0.5 hover:shadow-sm motion-reduce:transform-none motion-reduce:transition-none"
            >
              <div className="flex flex-wrap items-center gap-2">
                <span
                  className={cn(
                    "rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
                    TYPE_PILL[event.event_type],
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
                  {event.country && event.country !== event.city ? `, ${event.country}` : ""}
                </span>
                <span
                  className={cn(
                    "flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
                    IMPACT_META[event.impact_level].className,
                  )}
                >
                  <Gauge className="size-3" />
                  {IMPACT_META[event.impact_level].label}
                </span>
                {event.attendance !== null && (
                  <span className="flex items-center gap-1 text-xs text-muted-foreground">
                    <Users className="size-3.5" />
                    {ATTENDANCE_FORMAT.format(event.attendance)} katılımcı
                  </span>
                )}
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
              {/* The line the calendar exists for: dates are public, the read on
                  demand is the part a desk can act on. */}
              {event.demand_effect_tr && (
                <p className="rounded-lg bg-muted/60 p-2.5 text-xs leading-relaxed">
                  <span className="font-medium">Talebe etkisi: </span>
                  <span className="text-muted-foreground">{event.demand_effect_tr}</span>
                </p>
              )}
            </a>
          ))
        )}

        {/* Campaigns, under their own heading and wearing their carrier's
            colour rather than a --chart-* hue. Same card recipe as the events
            above -- edge-lit, one glow token, a source link -- so they read as
            the same kind of object, and the "Kampanya" pill plus the megaphone
            make sure they are never mistaken for one. */}
        {promos.length > 0 && (
          <>
            <h4 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Kampanyalar
            </h4>
            {promos.map((promo) => (
              <a
                key={promo.id}
                href={promo.url}
                target="_blank"
                rel="noopener noreferrer"
                style={
                  {
                    "--glow-color": BRAND_HEX[promo.airline_code] ?? "var(--signal)",
                  } as React.CSSProperties
                }
                className="edge-lit group flex flex-col gap-2 rounded-xl border bg-card p-4 transition-all duration-200 hover:-translate-y-0.5 hover:shadow-sm motion-reduce:transform-none motion-reduce:transition-none"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="flex items-center gap-1 rounded-full bg-signal/15 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-signal">
                    <Megaphone className="size-3" />
                    Kampanya
                  </span>
                  <span className="flex items-center gap-1.5 text-xs font-medium text-foreground">
                    <AirlineLogo
                      code={promo.airline_code}
                      name={promo.airline_name}
                      className="size-4"
                    />
                    {promo.airline_name}
                  </span>
                  {promo.discount_pct !== null && (
                    <span className="text-xs font-bold tabular-nums">
                      %{promo.discount_pct}
                    </span>
                  )}
                </div>
                <div className="flex items-start justify-between gap-3">
                  <span className="font-medium text-card-foreground group-hover:text-primary">
                    {promo.title_tr}
                  </span>
                  <ExternalLink className="mt-1 size-3.5 shrink-0 opacity-0 transition-opacity group-hover:opacity-100" />
                </div>
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
                  <span className="flex items-center gap-1">
                    <CalendarDays className="size-3.5" />
                    Satış: {promo.sale_range_tr}
                  </span>
                  <span className="flex items-center gap-1">
                    <Plane className="size-3.5" />
                    Seyahat: {promo.travel_range_tr}
                  </span>
                </div>
                <p className="text-[11px] text-muted-foreground">{promo.source_name}</p>
              </a>
            ))}
          </>
        )}
      </div>
    </motion.div>
  );
}
