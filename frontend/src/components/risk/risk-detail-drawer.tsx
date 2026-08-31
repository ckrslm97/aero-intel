"use client";

import { motion, useReducedMotion } from "framer-motion";
import { ExternalLink, MapPin, Newspaper, X } from "lucide-react";
import { useEffect, useRef } from "react";

import {
  ConfidencePill,
  CoverageBadge,
  TypePill,
  UntranslatedTag,
} from "@/components/risk/risk-meta";
import { SeverityPill } from "@/components/risk/severity-pill";
import {
  drawerPanel,
  drawerStagger,
  fadeUpItem,
  overlayFade,
  reduceVariants,
} from "@/lib/motion";
import { worldRegions } from "@/lib/nav";
import { aviationLinkLabel, headlinePresentation, riskSourceTierLabel } from "@/lib/risk";
import type { RiskItem } from "@/lib/types";

const REGION_NAME: Record<string, string> = Object.fromEntries(
  worldRegions.map((r) => [r.slug, r.name]),
);

/** UTC throughout, and said out loud in the section caption.
 *
 * The chronology's whole job is to let a reader compare when outlets published
 * relative to each other; rendering each row in the reader's own zone would be
 * fine for that, but the drawer also shows "İlk haber"/"Son haber" as facts
 * about the record, and a record's timestamp that shifts with who is looking at
 * it is not a fact. One zone, stated once. */
const STAMP = new Intl.DateTimeFormat("tr-TR", {
  timeZone: "UTC",
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

const SHORT_STAMP = new Intl.DateTimeFormat("tr-TR", {
  timeZone: "UTC",
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});

function stamp(iso: string | null, format = STAMP): string {
  if (!iso) return "Belirtilmedi";
  const at = new Date(iso);
  return Number.isNaN(at.getTime()) ? "Belirtilmedi" : format.format(at);
}

/** One risk signal, in full.
 *
 * Deliberately NOT a shared abstraction with campaign-drawer.tsx or
 * article-analysis-drawer.tsx -- the same call those two already made about
 * each other. The three share a shell (backdrop, spring aside, Escape, scroll
 * lock, seam light) of about sixty lines and share nothing at all inside it.
 *
 * What this drawer exists to show is the EVIDENCE behind a card. All of it was
 * already loaded by the /risks query and thrown away before serialization: the
 * cluster's member articles, their outlets and tiers, the airports named in
 * them, the primary's summary and confidence. A reader could previously see
 * that "there was a wildfire in Greece" and had no way to ask who said so.
 *
 * The rule the interior follows, inherited from campaign-drawer: every field
 * here can be absent, and an absent field says so. And the rule this page adds:
 * no cell may imply knowledge this pipeline does not have -- the timeline is
 * labelled as publications, the airports as named, the aviation link as a link.
 */
export function RiskDetailDrawer({
  item,
  onClose,
}: {
  item: RiskItem | null;
  onClose: () => void;
}) {
  const reduceMotion = useReducedMotion();
  const entry = reduceMotion ? reduceVariants(fadeUpItem) : fadeUpItem;
  const closeRef = useRef<HTMLButtonElement>(null);

  /** Whatever had focus when the drawer opened -- a card, a map popover row, a
   * feed item. Captured on open and focused again on close, so a keyboard
   * reader is returned to the row they came from instead of to the top of the
   * document. Stored in a ref rather than state: it must not cause a render,
   * and it must survive the item changing while the drawer stays open. */
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const isOpen = item !== null;

  useEffect(() => {
    if (!isOpen) return;
    returnFocusRef.current = document.activeElement as HTMLElement | null;
    // Focus lands on the close button, not on the panel: it is the one control
    // every reader needs and it makes Tab start inside the dialog rather than
    // behind it.
    closeRef.current?.focus();

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKeyDown);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
      returnFocusRef.current?.focus?.();
    };
  }, [isOpen, onClose]);

  // Hooks first, then the early return: `item === null` is the closed state and
  // this component is mounted for the whole page's life.
  if (!item) return null;

  const aviation = aviationLinkLabel(item.aviation_link);
  const place = [item.city, item.country].filter(Boolean).join(" · ") || "Belirtilmedi";
  const headline = headlinePresentation(item);

  return (
    // Mounted and unmounted outright -- deliberately NOT wrapped in
    // `AnimatePresence`, which is the house idiom for the other two drawers.
    //
    // Measured in this stack (framer-motion 12 + React 19): the exit animation
    // RUNS -- the panel ends at translateX(100%) -- and then the exit-complete
    // callback never fires, so the subtree is never unmounted. The panel is
    // off-screen and invisible, but its `fixed inset-0` backdrop stays over the
    // page, and every click after the first close lands on a black overlay
    // instead of on the radar. A modal that cannot be dismissed is a far worse
    // failure than one that closes without a 200ms slide, so the entrance
    // animation is kept (initial/animate below) and the exit is dropped.
    <>
      <motion.div
        key="risk-drawer-overlay"
        variants={reduceMotion ? reduceVariants(overlayFade) : overlayFade}
        initial="hidden"
        animate="show"
        onClick={onClose}
        className="fixed inset-0 z-50 bg-black/50 backdrop-blur-[2px]"
      />
          <motion.aside
            key="risk-drawer-panel"
            role="dialog"
            aria-modal="true"
            aria-label="Risk sinyali ayrıntısı"
            variants={reduceMotion ? reduceVariants(drawerPanel) : drawerPanel}
            initial="hidden"
            animate="show"
            // Severity drives the seam light, because severity is this page's
            // only identity axis. Low severity gets the plain border rather
            // than a colour: a "low" war is still a war, and --good has no
            // place anywhere on this surface.
            style={
                {
                  "--glow-color":
                    item.severity === "high"
                      ? "var(--critical)"
                      : item.severity === "medium"
                        ? "var(--warning)"
                        : "var(--border)",
                } as React.CSSProperties
            }
            className="fixed inset-y-0 right-0 z-50 flex w-full max-w-lg flex-col border-l border-border bg-card shadow-2xl"
          >
            <span
              aria-hidden
              className="pointer-events-none absolute inset-y-0 left-0 w-0.5 bg-gradient-to-b from-[var(--glow-color)] via-[var(--glow-color)]/40 to-transparent"
            />

            <header className="flex items-start justify-between gap-4 border-b border-border px-6 py-5">
              <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                <TypePill item={item} />
                <SeverityPill severity={item.severity} />
                <CoverageBadge item={item} />
              </div>
              <button
                ref={closeRef}
                type="button"
                onClick={onClose}
                aria-label="Ayrıntıyı kapat"
                className="shrink-0 rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
              >
                <X className="size-4" />
              </button>
            </header>

            <motion.div
              variants={reduceMotion ? reduceVariants(drawerStagger) : drawerStagger}
              initial="hidden"
              animate="show"
              className="flex flex-1 flex-col gap-6 overflow-y-auto px-6 py-6"
            >
              <motion.div variants={entry} className="flex flex-col items-start gap-2">
                <h2
                  // The source-language original on hover, exactly as the card
                  // offers it: the drawer is where a reader goes to check a
                  // signal, and a translation whose original is hidden is the
                  // one thing on this panel that cannot be checked.
                  title={headline.original ?? undefined}
                  className="text-xl font-semibold leading-snug tracking-tight text-card-foreground"
                >
                  {headline.text}
                </h2>
                {headline.untranslated && <UntranslatedTag />}
              </motion.div>

              <motion.div
                variants={entry}
                style={{ "--gradient-surface": "var(--card)" } as React.CSSProperties}
                className="border-gradient grid grid-cols-2 gap-4 rounded-xl p-5"
              >
                <Cell label="Yer" value={place} icon={<MapPin className="size-3" aria-hidden />} />
                <Cell
                  label="Bölge"
                  value={item.region ? (REGION_NAME[item.region] ?? item.region) : "Belirtilmedi"}
                />
                {/* Never "olay zamanı": these bracket the COVERAGE. Nothing
                    upstream knows when the event itself began. */}
                <Cell label="İlk haber" value={stamp(item.first_reported_at)} />
                <Cell label="Son haber" value={stamp(item.last_reported_at)} />
                <div className="flex flex-col gap-0.5">
                  <span className="text-[11px] text-muted-foreground">Güven</span>
                  <ConfidencePill score={item.confidence_score} />
                  {item.corroborating_source_count !== null && (
                    <span className="text-[11px] tabular-nums text-muted-foreground">
                      {item.corroborating_source_count} bağımsız kaynak
                    </span>
                  )}
                </div>
                <div className="flex flex-col gap-0.5">
                  <span className="text-[11px] text-muted-foreground">Havacılık bağlantısı</span>
                  <span
                    title={aviation?.title}
                    className="text-sm font-medium leading-snug"
                  >
                    {aviation ? "Doğrudan" : "Dolaylı"}
                  </span>
                  <span className="text-[10px] leading-snug text-muted-foreground">
                    {aviation
                      ? "Haberde havalimanı anılıyor"
                      : "Havacılığa doğrudan bağlanan bir işaret yok"}
                  </span>
                </div>
              </motion.div>

              {item.summary_tr && (
                <motion.p
                  variants={entry}
                  className="whitespace-pre-line text-[15px] leading-relaxed text-muted-foreground"
                >
                  {item.summary_tr}
                </motion.p>
              )}

              {item.airports.length > 0 && (
                <motion.div variants={entry} className="flex flex-col gap-2">
                  <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                    Anılan havalimanları
                  </h3>
                  <div className="flex flex-wrap gap-1.5">
                    {item.airports.map((airport) => (
                      <span
                        key={airport.code}
                        className="flex items-baseline gap-1.5 rounded-full border border-border px-2.5 py-1 text-xs"
                      >
                        <span className="font-mono font-semibold tabular-nums">
                          {airport.code}
                        </span>
                        <span className="text-muted-foreground">{airport.name}</span>
                      </span>
                    ))}
                  </div>
                  <p className="text-[11px] leading-relaxed text-muted-foreground">
                    Bu havalimanları haber metninde anılıyor. Etkilendikleri anlamına
                    gelmez — bu ürüne bağlı bir uçuş/operasyon verisi yok.
                  </p>
                </motion.div>
              )}

              <motion.div variants={entry} className="flex flex-col gap-3">
                <div className="flex flex-col gap-1">
                  <h3 className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                    <Newspaper className="size-3.5" aria-hidden />
                    Yayın kronolojisi
                    <span className="rounded-full bg-muted px-1.5 text-[10px] tabular-nums">
                      {item.source_count}
                    </span>
                  </h3>
                  {/* The single most important sentence in this drawer. A
                      vertical timeline over a disaster reads as the event's own
                      chronology unless it says otherwise, and this data has no
                      such thing -- only publication timestamps. */}
                  <p className="text-[11px] leading-relaxed text-muted-foreground">
                    Haberlerin yayın akışı — olayın kendi zaman çizelgesi değildir.
                    Saatler UTC.
                  </p>
                </div>

                <ol className="flex flex-col gap-3 border-l border-border pl-4">
                  {item.members.map((member) => (
                    <li key={member.url} className="relative flex flex-col gap-1">
                      <span
                        aria-hidden
                        className="absolute -left-[21px] top-1.5 size-1.5 rounded-full bg-border"
                      />
                      <span className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                        <span className="tabular-nums">
                          {stamp(member.published_at, SHORT_STAMP)}
                        </span>
                        <span className="rounded-full border border-border px-1.5 py-px text-[10px] font-semibold">
                          {riskSourceTierLabel(member.source_tier)}
                        </span>
                        <span className="font-medium text-foreground">{member.source_name}</span>
                      </span>
                      <a
                        href={member.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="group flex items-start gap-1.5 text-[13px] leading-snug hover:text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
                      >
                        <span className="min-w-0 flex-1">{member.title}</span>
                        <ExternalLink className="mt-0.5 size-3 shrink-0 text-muted-foreground group-hover:text-primary" />
                      </a>
                    </li>
                  ))}
                </ol>

                {item.members_truncated && (
                  <p className="text-[11px] text-muted-foreground">
                    Bu olayı işleyen daha fazla haber var; kronoloji ilk{" "}
                    <span className="tabular-nums">{item.members.length}</span> yayınla
                    sınırlandırıldı.
                  </p>
                )}
              </motion.div>

              <motion.p
                variants={entry}
                className="text-[11px] leading-relaxed text-muted-foreground"
              >
                Konum, ülke veya şehir merkezine göre gösterilir; olayın kendi
                koordinatı bu veride yok. Sinyal, haber akışından sınıflandırılmıştır;
                resmî bir uyarı değildir.
              </motion.p>
            </motion.div>

            <footer className="border-t border-border px-6 py-4">
              <a
                href={item.url}
                target="_blank"
                rel="noopener noreferrer"
                style={{ "--glow-color": "var(--primary)" } as React.CSSProperties}
                className="flex w-full items-center justify-center gap-2 rounded-lg bg-gradient-to-r from-primary to-chart-4 px-4 py-2.5 text-sm font-semibold text-primary-foreground transition-shadow duration-300 hover:glow-soft focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
              >
                Birincil kaynağa git
                <ExternalLink className="size-4" />
              </a>
            </footer>
          </motion.aside>
    </>
  );
}

function Cell({
  label,
  value,
  icon,
}: {
  label: string;
  value: string;
  icon?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[11px] text-muted-foreground">{label}</span>
      <span className="flex items-center gap-1 text-sm font-medium leading-snug">
        {icon}
        {value}
      </span>
    </div>
  );
}
