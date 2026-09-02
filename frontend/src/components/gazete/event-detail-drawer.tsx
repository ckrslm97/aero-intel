"use client";

import { motion } from "framer-motion";
import { CalendarDays, ExternalLink, Gauge, MapPin, Plane, X } from "lucide-react";
import { useEffect } from "react";

import { daysUntilTr } from "@/lib/event-timeline";
import {
  ATTENDANCE_FORMAT,
  EVENT_IMPACT_META,
  EVENT_TYPE_GLOW,
  EVENT_TYPE_LABELS_TR,
  EVENT_TYPE_PILL,
} from "@/lib/events";
import { drawerPanel, drawerStagger, fadeUpItem, overlayFade } from "@/lib/motion";
import { worldRegions } from "@/lib/nav";
import type { EventOut } from "@/lib/types";
import { cn } from "@/lib/utils";

const REGION_NAME: Record<string, string> = Object.fromEntries(
  worldRegions.map((region) => [region.slug, region.name]),
);

/** One event, in full: the panel both the radar and the timeline open.
 *
 * Everything on it is a stored, curated field. `impact_level` and
 * `demand_effect_tr` in particular are somebody's recorded judgement (see
 * backend/app/models/event.py) -- which is exactly why "Talebe etkisi" carries
 * NO "yapay zekâ değerlendirmesi" caption, unlike the article drawer's "Neden
 * önemli?". Labelling a curated sentence as a model's output would be a lie
 * about its provenance in the more damaging direction: it would let a reader
 * discount an editor.
 *
 * Mounted and unmounted outright -- deliberately NOT wrapped in
 * `AnimatePresence`. Measured in this stack (framer-motion 12 + React 19), an
 * exit animation runs but its completion callback never fires, so the subtree
 * is never unmounted and the `fixed inset-0` backdrop stays over the page: the
 * first close leaves every later click landing on an invisible overlay. Same
 * decision, and the same reason, as components/risk/risk-detail-drawer.tsx.
 */
export function EventDetailDrawer({
  event,
  onClose,
}: {
  event: EventOut | null;
  onClose: () => void;
}) {
  useEffect(() => {
    if (!event) return;
    function onKeyDown(keyEvent: KeyboardEvent) {
      if (keyEvent.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKeyDown);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [event, onClose]);

  if (!event) return null;

  const impact = EVENT_IMPACT_META[event.impact_level];
  const region = event.region ? (REGION_NAME[event.region] ?? event.region) : null;
  const place = [event.city, event.country].filter(Boolean).join(", ");

  return (
    <>
      <motion.div
        variants={overlayFade}
        initial="hidden"
        animate="show"
        onClick={onClose}
        className="fixed inset-0 z-50 bg-black/50 backdrop-blur-[2px]"
      />
      <motion.aside
        role="dialog"
        aria-modal="true"
        aria-label="Etkinlik detayı"
        variants={drawerPanel}
        initial="hidden"
        animate="show"
        style={{ "--glow-color": EVENT_TYPE_GLOW[event.event_type] } as React.CSSProperties}
        className="fixed inset-y-0 right-0 z-50 flex w-full max-w-lg flex-col border-l border-border bg-card shadow-2xl"
      >
        <span
          aria-hidden
          className="pointer-events-none absolute inset-y-0 left-0 w-0.5 bg-gradient-to-b from-[var(--glow-color)] via-[var(--glow-color)]/40 to-transparent"
        />

        <header className="flex items-start justify-between gap-4 border-b border-border px-6 py-5">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={cn(
                "rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide",
                EVENT_TYPE_PILL[event.event_type],
              )}
            >
              {EVENT_TYPE_LABELS_TR[event.event_type]}
            </span>
            <span
              className={cn(
                "flex items-center gap-1 rounded-full border px-2.5 py-1 text-[11px] font-semibold",
                impact.className,
              )}
            >
              <Gauge className="size-3.5" aria-hidden />
              {impact.label}
            </span>
            {region && (
              <span className="rounded-full bg-secondary px-2.5 py-1 text-[11px] font-medium text-secondary-foreground">
                {region}
              </span>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Etkinlik detayını kapat"
            className="shrink-0 rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            <X className="size-4" />
          </button>
        </header>

        <motion.div
          variants={drawerStagger}
          initial="hidden"
          animate="show"
          className="flex flex-1 flex-col gap-6 overflow-y-auto px-6 py-6"
        >
          <motion.div variants={fadeUpItem} className="flex flex-col gap-2">
            <h2 className="text-2xl font-semibold leading-snug tracking-tight text-card-foreground">
              {event.name}
            </h2>
            <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
              <span className="flex items-center gap-1 font-medium text-foreground">
                <CalendarDays className="size-3.5" aria-hidden />
                {/* Pre-formatted server-side so the frontend never
                    re-implements Turkish month names. */}
                {event.date_range_tr}
              </span>
              <span aria-hidden>·</span>
              <span className="tabular-nums">{daysUntilTr(event.days_until)}</span>
              {place && (
                <>
                  <span aria-hidden>·</span>
                  <span className="flex items-center gap-1">
                    <MapPin className="size-3.5" aria-hidden />
                    {place}
                  </span>
                </>
              )}
            </p>
          </motion.div>

          {event.summary_tr && (
            <motion.p
              variants={fadeUpItem}
              className="whitespace-pre-line text-[15px] leading-relaxed text-muted-foreground"
            >
              {event.summary_tr}
            </motion.p>
          )}

          {/* The line the calendar exists for: dates are public, the read on
              demand is the part a desk can act on. Curated Turkish text, so it
              is presented as the editorial statement it is. */}
          {event.demand_effect_tr && (
            <motion.div
              variants={fadeUpItem}
              className="flex flex-col gap-1.5 rounded-xl border-l-2 border-(--glow-color) bg-secondary/40 px-4 py-3"
            >
              <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                Talebe etkisi
              </h3>
              <p className="text-[14px] leading-relaxed text-card-foreground">
                {event.demand_effect_tr}
              </p>
            </motion.div>
          )}

          <motion.dl variants={fadeUpItem} className="grid grid-cols-2 gap-4">
            <Fact
              label="Katılımcı"
              // Null is "the organiser publishes no headcount", not "nobody
              // comes" -- so it is a dash, and the importance score below it
              // is absent for the same row rather than being computed as zero.
              value={
                event.attendance === null
                  ? "—"
                  : `${ATTENDANCE_FORMAT.format(event.attendance)} kişi`
              }
            />
            <Fact
              label="Önem skoru"
              value={
                event.importance_score === null
                  ? "—"
                  : event.importance_score.toFixed(2)
              }
              note={
                event.importance_score === null
                  ? "katılımcı sayısı yayımlanmadığı için ölçülemedi"
                  : undefined
              }
            />
          </motion.dl>

          {/* Empty for entries that are not cities ("Çin geneli", "Küresel")
              and for a city nobody has curated yet -- see
              backend/app/data/event_airports.py. An empty list draws no
              block at all rather than an "Havalimanı: —" row, because the
              honest answer there is silence. */}
          {event.relevant_airports.length > 0 && (
            <motion.div variants={fadeUpItem} className="flex flex-col gap-2.5">
              <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                İlgili havalimanları
              </h3>
              <div className="flex flex-wrap gap-2">
                {event.relevant_airports.map((code) => (
                  <span
                    key={code}
                    className="flex items-center gap-1.5 rounded-full border border-border px-2.5 py-1 font-mono text-xs"
                  >
                    <Plane className="size-3 text-muted-foreground" aria-hidden />
                    {code}
                  </span>
                ))}
              </div>
            </motion.div>
          )}
        </motion.div>

        <footer className="border-t border-border px-6 py-4">
          <a
            href={event.url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex w-full items-center justify-center gap-2 rounded-lg border border-border px-4 py-2.5 text-sm font-semibold transition-colors hover:bg-accent"
          >
            Organizatör sayfası
            <ExternalLink className="size-4" />
          </a>
        </footer>
      </motion.aside>
    </>
  );
}

function Fact({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-[11px] text-muted-foreground">{label}</dt>
      <dd className="text-lg font-semibold tabular-nums">{value}</dd>
      {note && <span className="text-[10px] leading-tight text-muted-foreground">{note}</span>}
    </div>
  );
}
