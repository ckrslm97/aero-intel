"use client";

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { ExternalLink, X } from "lucide-react";
import { useEffect } from "react";

import { AirlineLogo } from "@/components/airline-logo";
import {
  drawerPanel,
  drawerStagger,
  fadeUpItem,
  overlayFade,
  reduceVariants,
} from "@/lib/motion";
import { worldRegions } from "@/lib/nav";
import type { PromotionOut } from "@/lib/types";

const REGION_NAME: Record<string, string> = Object.fromEntries(
  worldRegions.map((r) => [r.slug, r.name]),
);

const DETECTED_FORMAT = new Intl.DateTimeFormat("tr-TR", {
  dateStyle: "long",
  timeStyle: "short",
});

/** One campaign, in full.
 *
 * Deliberately NOT a shared abstraction with `article-analysis-drawer.tsx`.
 * The two panels share a shell -- backdrop, spring aside, Escape, scroll lock,
 * seam light -- and that shell is about sixty lines. Their interiors share
 * nothing at all: one explains a pipeline's verdict on a story, the other
 * states four dates and a discount. Factoring the shell out would put a
 * props-driven layer between every future change and both drawers, to save
 * less code than the layer itself costs.
 *
 * The rule the interior follows: every field here can be absent, and an absent
 * field says so. There is no cell that renders empty and no badge that renders
 * as a blank -- "Belirtilmedi" is a fact about the source, and hiding it would
 * make a half-known campaign look fully known.
 */
export function CampaignDrawer({
  promotion,
  brandHex,
  onClose,
}: {
  promotion: PromotionOut | null;
  brandHex: string;
  onClose: () => void;
}) {
  const reduceMotion = useReducedMotion();
  const item = reduceMotion ? reduceVariants(fadeUpItem) : fadeUpItem;

  useEffect(() => {
    if (!promotion) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKeyDown);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [promotion, onClose]);

  const markets = promotion?.markets
    ? promotion.markets
        .split(",")
        .map((m) => m.trim())
        .filter(Boolean)
    : [];

  return (
    <AnimatePresence>
      {promotion && (
        <>
          <motion.div
            key="campaign-drawer-overlay"
            variants={reduceMotion ? reduceVariants(overlayFade) : overlayFade}
            initial="hidden"
            animate="show"
            exit="exit"
            onClick={onClose}
            className="fixed inset-0 z-50 bg-black/50 backdrop-blur-[2px]"
          />
          <motion.aside
            key="campaign-drawer-panel"
            role="dialog"
            aria-modal="true"
            aria-label="Kampanya ayrıntısı"
            variants={reduceMotion ? reduceVariants(drawerPanel) : drawerPanel}
            initial="hidden"
            animate="show"
            exit="exit"
            // The carrier's own hex, not a category token: on this page the
            // airline IS the identity, and the seam light, the border-gradient
            // panel and the discount's text-glow all read from here.
            style={{ "--glow-color": brandHex } as React.CSSProperties}
            className="fixed inset-y-0 right-0 z-50 flex w-full max-w-lg flex-col border-l border-border bg-card shadow-2xl"
          >
            <span
              aria-hidden
              className="pointer-events-none absolute inset-y-0 left-0 w-0.5 bg-gradient-to-b from-[var(--glow-color)] via-[var(--glow-color)]/40 to-transparent"
            />

            <header className="flex items-start justify-between gap-4 border-b border-border px-6 py-5">
              <div className="flex items-center gap-3">
                <AirlineLogo
                  code={promotion.airline_code}
                  name={promotion.airline_name}
                  className="size-8"
                />
                <div className="flex flex-col">
                  <span className="text-sm font-semibold text-card-foreground">
                    {promotion.airline_name}
                  </span>
                  <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground tabular-nums">
                    {promotion.airline_code} · {promotion.source_name}
                  </span>
                </div>
              </div>
              <button
                type="button"
                onClick={onClose}
                aria-label="Kampanyayı kapat"
                className="shrink-0 rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
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
              <motion.h2
                variants={item}
                className="text-2xl font-semibold leading-snug tracking-tight text-card-foreground"
              >
                {promotion.title_tr}
              </motion.h2>

              <motion.div variants={item} className="flex flex-col gap-1">
                <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                  İndirim
                </span>
                {promotion.discount_pct !== null ? (
                  <span className="text-3xl font-bold tabular-nums text-glow">
                    %{promotion.discount_pct}&apos;a varan
                  </span>
                ) : (
                  // A fare campaign ("9 Euro'dan başlayan") genuinely has no
                  // percentage. Saying so beats an empty hero.
                  <span className="text-sm text-muted-foreground">Oran belirtilmedi</span>
                )}
              </motion.div>

              <motion.div
                variants={item}
                style={{ "--gradient-surface": "var(--card)" } as React.CSSProperties}
                className="border-gradient grid grid-cols-2 gap-4 rounded-xl p-5"
              >
                <Cell label="Satış dönemi" value={promotion.sale_range_tr} />
                <Cell label="Seyahat dönemi" value={promotion.travel_range_tr} />
                <Cell
                  label="Kapsam"
                  value={markets.length > 0 ? `${markets.length} pazar` : "Belirtilmedi"}
                />
                <Cell
                  label="Tespit"
                  value={DETECTED_FORMAT.format(new Date(promotion.detected_at))}
                />
              </motion.div>

              <motion.div variants={item} className="flex flex-col gap-2.5">
                <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                  Pazarlar
                </h3>
                {markets.length > 0 ? (
                  <div className="flex flex-wrap gap-1.5">
                    {markets.map((market) => (
                      <span
                        key={market}
                        className="rounded-full border border-border px-2.5 py-1 text-xs"
                      >
                        {/* Region slugs get their Turkish name; a city name is
                            already in the source's own words, so it stands. */}
                        {REGION_NAME[market] ?? market}
                      </span>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-muted-foreground">
                    Kapsam: kaynakta belirtilmemiş.
                  </p>
                )}
              </motion.div>

              {promotion.summary_tr && (
                <motion.p
                  variants={item}
                  className="whitespace-pre-line text-[15px] leading-relaxed text-muted-foreground"
                >
                  {promotion.summary_tr}
                </motion.p>
              )}

              <motion.p
                variants={item}
                className="text-[11px] leading-relaxed text-muted-foreground"
              >
                Tarihler kaynağın yayımladığı haliyle alınır; belirtilmeyen bir tarih
                tahmin edilmez. &quot;Tespit&quot;, kampanyanın yayına girdiği an değil,
                bizim ilk gördüğümüz andır.
              </motion.p>
            </motion.div>

            <footer className="border-t border-border px-6 py-4">
              <a
                href={promotion.url}
                target="_blank"
                rel="noopener noreferrer"
                style={{ "--glow-color": "var(--primary)" } as React.CSSProperties}
                className="flex w-full items-center justify-center gap-2 rounded-lg bg-gradient-to-r from-primary to-chart-4 px-4 py-2.5 text-sm font-semibold text-primary-foreground transition-shadow duration-300 hover:glow-soft"
              >
                Kaynağa git
                <ExternalLink className="size-4" />
              </a>
            </footer>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}

function Cell({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[11px] text-muted-foreground">{label}</span>
      <span className="text-sm font-medium leading-snug">{value || "—"}</span>
    </div>
  );
}
