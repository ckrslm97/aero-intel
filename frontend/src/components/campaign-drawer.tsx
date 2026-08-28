"use client";

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import {
  CalendarClock,
  ChevronDown,
  ExternalLink,
  History,
  Quote,
  Split,
  TriangleAlert,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";

import { AirlineLogo } from "@/components/airline-logo";
import { CampaignStatusPill, ConfidencePill } from "@/components/campaign-analyst-table";
import { apiFetch } from "@/lib/api";
import {
  campaignFieldLabel,
  campaignRouteLabel,
  formatChangeValue,
  sourceTierLabel,
} from "@/lib/campaigns";
import {
  drawerPanel,
  drawerStagger,
  fadeUpItem,
  overlayFade,
  reduceVariants,
} from "@/lib/motion";
import { worldRegions } from "@/lib/nav";
import {
  CAMPAIGN_BUSINESS_CLASS_LABELS_TR,
  CAMPAIGN_TYPE_LABELS_TR,
  type CampaignBusinessClass,
  type CampaignType,
} from "@/lib/taxonomy.gen";
import type { PromotionOut, PromotionSource, PromotionVersion } from "@/lib/types";

const REGION_NAME: Record<string, string> = Object.fromEntries(
  worldRegions.map((r) => [r.slug, r.name]),
);

const DETECTED_FORMAT = new Intl.DateTimeFormat("tr-TR", {
  dateStyle: "long",
  timeStyle: "short",
});

const DAY_FORMAT = new Intl.DateTimeFormat("tr-TR", { dateStyle: "medium" });

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
 *
 * PR7 added the provenance half: why the classifier called this a campaign,
 * the sentences each field was read from, what has changed since we first saw
 * it, and which pages told us. All four are fetched or revealed only when the
 * drawer is actually open -- the list endpoint carries the evidence inline, but
 * the version and source histories are one request each, made per campaign the
 * reader opens rather than for every row they scroll past.
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

  /** Keyed by campaign id rather than reset on close: clearing it in an effect
   * would be a synchronous setState in an effect body (a cascading render, and
   * a lint error), and keying makes the stale-history question unaskable --
   * history for another campaign simply is not this campaign's. */
  const [history, setHistory] = useState<{
    id: string;
    versions: PromotionVersion[];
    sources: PromotionSource[];
  } | null>(null);

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

  const promotionId = promotion?.id ?? null;
  useEffect(() => {
    // Lazy, and per campaign: history is read one campaign at a time, so
    // riding it along with every list row would be hundreds of joins to serve
    // the handful anyone opens. A failure here empties the two sections rather
    // than breaking the drawer -- the campaign itself is already on screen.
    if (!promotionId) return;
    let cancelled = false;
    Promise.all([
      apiFetch<PromotionVersion[]>(`/promotions/${promotionId}/versions`, {
        cache: "default",
      }).catch(() => []),
      apiFetch<PromotionSource[]>(`/promotions/${promotionId}/sources`, {
        cache: "default",
      }).catch(() => []),
    ]).then(([versionRows, sourceRows]) => {
      if (cancelled) return;
      setHistory({ id: promotionId, versions: versionRows, sources: sourceRows });
    });
    return () => {
      cancelled = true;
    };
  }, [promotionId]);

  const versions = history?.id === promotionId ? history.versions : [];
  const sources = history?.id === promotionId ? history.sources : [];

  const markets = promotion?.markets
    ? promotion.markets
        .split(",")
        .map((m) => m.trim())
        .filter(Boolean)
    : [];

  const evidence = Object.entries(promotion?.evidence_json ?? {}).filter(
    ([, entry]) => entry && typeof entry.source_text === "string" && entry.source_text.trim(),
  );
  const inferredYear = Boolean(
    promotion?.date_flags_json &&
      (promotion.date_flags_json as { inferred_year?: unknown }).inferred_year,
  );

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

              {/* Status, type and the two warning badges sit above everything
                  else: they are what tells a reader whether the numbers below
                  are worth reading at all. */}
              <motion.div variants={item} className="flex flex-wrap items-center gap-1.5">
                <CampaignStatusPill status={promotion.status} />
                {promotion.campaign_type && (
                  <span className="rounded-full border border-border px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
                    {CAMPAIGN_TYPE_LABELS_TR[promotion.campaign_type as CampaignType] ??
                      promotion.campaign_type}
                  </span>
                )}
                {promotion.business_class && (
                  <span className="rounded-full border border-border px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
                    {CAMPAIGN_BUSINESS_CLASS_LABELS_TR[
                      promotion.business_class as CampaignBusinessClass
                    ] ?? promotion.business_class}
                  </span>
                )}
                {promotion.conflict_detected === true && (
                  <span
                    title="İki kaynak bir alanda çelişti; daha resmî olan kazandı. Kaybeden değer değişiklik geçmişinde duruyor."
                    className="inline-flex items-center gap-1 rounded-full border border-critical/40 bg-critical/10 px-2 py-0.5 text-[11px] font-medium text-critical"
                  >
                    <Split className="size-3" aria-hidden />
                    Kaynak çelişkisi
                  </span>
                )}
                {promotion.review_required === true && (
                  <span
                    title="Güven eşiğinin altında kaldı: bir insanın doğrulaması bekleniyor."
                    className="inline-flex items-center gap-1 rounded-full border border-warning/40 bg-warning/10 px-2 py-0.5 text-[11px] font-medium text-warning"
                  >
                    <TriangleAlert className="size-3" aria-hidden />
                    İnceleme gerekli
                  </span>
                )}
              </motion.div>

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
                <Cell
                  label="Satış dönemi"
                  value={promotion.sale_range_tr}
                  warning={
                    inferredYear
                      ? "Yıl kaynakta yazmıyordu; metinden çıkarıldı."
                      : undefined
                  }
                />
                <Cell label="Seyahat dönemi" value={promotion.travel_range_tr} />
                <Cell label="Rota" value={campaignRouteLabel(promotion)} />
                <Cell
                  label="Kapsam"
                  value={markets.length > 0 ? `${markets.length} pazar` : "Belirtilmedi"}
                />
                <Cell
                  label="Tespit"
                  value={DETECTED_FORMAT.format(new Date(promotion.detected_at))}
                />
                <div className="flex flex-col gap-0.5">
                  <span className="text-[11px] text-muted-foreground">Güven</span>
                  <ConfidencePill
                    band={promotion.confidence_band}
                    score={promotion.confidence_score}
                  />
                </div>
              </motion.div>

              {promotion.classification_reason && (
                <motion.div variants={item} className="flex flex-col gap-2">
                  <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                    Neden kampanya?
                  </h3>
                  {/* The classifier's own sentence, quoted rather than
                      paraphrased: an unexplained verdict is an unfixable one. */}
                  <blockquote className="border-l-2 border-[var(--glow-color)] pl-3 text-sm leading-relaxed text-muted-foreground">
                    {promotion.classification_reason}
                  </blockquote>
                </motion.div>
              )}

              {evidence.length > 0 && (
                <motion.div variants={item}>
                  <Collapsible
                    title="Kanıt alıntıları"
                    count={evidence.length}
                    icon={<Quote className="size-3.5" />}
                  >
                    <ul className="flex flex-col gap-3">
                      {evidence.map(([field, entry]) => (
                        <li key={field} className="flex flex-col gap-1">
                          <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                            {campaignFieldLabel(field)}
                            {entry.value !== undefined && entry.value !== null && (
                              <span className="ml-1 font-normal normal-case text-foreground">
                                {formatChangeValue(entry.value)}
                              </span>
                            )}
                          </span>
                          {/* The sentence the value was read from. This is the
                              difference between a number and a citation. */}
                          <blockquote className="border-l-2 border-border pl-3 text-[13px] italic leading-relaxed text-muted-foreground">
                            “{entry.source_text}”
                          </blockquote>
                        </li>
                      ))}
                    </ul>
                  </Collapsible>
                </motion.div>
              )}

              {versions.length > 0 && (
                <motion.div variants={item}>
                  <Collapsible
                    title="Değişiklik geçmişi"
                    count={versions.length}
                    icon={<History className="size-3.5" />}
                    defaultOpen
                  >
                    <ol className="flex flex-col gap-4">
                      {versions.map((version) => (
                        <li key={version.version_no} className="flex flex-col gap-1.5">
                          <span className="flex items-center gap-2 text-[11px] font-medium tabular-nums text-muted-foreground">
                            <CalendarClock className="size-3" aria-hidden />
                            {DAY_FORMAT.format(new Date(version.created_at))}
                            <span className="rounded-full bg-muted px-1.5 text-[10px]">
                              v{version.version_no}
                            </span>
                          </span>
                          <ul className="flex flex-col gap-1 border-l-2 border-border pl-3">
                            {Object.entries(version.changed_fields).map(([field, change]) => (
                              <li key={field} className="text-[13px] leading-snug">
                                <span className="font-medium">{campaignFieldLabel(field)}: </span>
                                <span className="text-muted-foreground line-through">
                                  {formatChangeValue(change?.previous)}
                                </span>
                                <span className="text-muted-foreground"> → </span>
                                <span className="font-medium">
                                  {formatChangeValue(change?.new)}
                                </span>
                                {change?.conflict && (
                                  <span className="ml-1 text-[11px] text-critical">
                                    (çelişki: resmî kaynak kazandı)
                                  </span>
                                )}
                              </li>
                            ))}
                          </ul>
                        </li>
                      ))}
                    </ol>
                  </Collapsible>
                </motion.div>
              )}

              {sources.length > 0 && (
                <motion.div variants={item} className="flex flex-col gap-2.5">
                  <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                    Kaynaklar ({sources.length})
                  </h3>
                  <ul className="flex flex-col gap-1.5">
                    {sources.map((source) => (
                      <li key={source.url} className="flex items-center gap-2 text-[13px]">
                        <span
                          className={
                            source.source_tier === "official"
                              ? "rounded-full border border-good/40 bg-good/10 px-1.5 py-px text-[10px] font-semibold text-good"
                              : source.source_tier === "newsroom"
                                ? "rounded-full border border-primary/40 bg-primary/10 px-1.5 py-px text-[10px] font-semibold text-primary"
                                : "rounded-full border border-border px-1.5 py-px text-[10px] font-semibold text-muted-foreground"
                          }
                        >
                          {sourceTierLabel(source.source_tier)}
                        </span>
                        <a
                          href={source.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="min-w-0 flex-1 truncate text-muted-foreground hover:text-primary"
                        >
                          {source.source_name ?? source.url}
                        </a>
                        <ExternalLink className="size-3 shrink-0 text-muted-foreground" />
                      </li>
                    ))}
                  </ul>
                </motion.div>
              )}

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
                bizim ilk gördüğümüz andır. Durum, tarihlerden okunarak her istekte
                yeniden hesaplanır.
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

function Cell({
  label,
  value,
  warning,
}: {
  label: string;
  value: string;
  warning?: string;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[11px] text-muted-foreground">{label}</span>
      <span className="flex items-start gap-1 text-sm font-medium leading-snug">
        {value || "—"}
        {warning && (
          // A guessed year draws the same bar as a stated one, so the guess has
          // to be visible where the date is, not in a footnote.
          <TriangleAlert className="mt-0.5 size-3 shrink-0 text-warning" aria-label={warning} />
        )}
      </span>
      {warning && <span className="text-[10px] text-warning">{warning}</span>}
    </div>
  );
}

/** A section that opens on click. Used for the two blocks that are reference
 * material rather than headline: nobody reads eleven evidence quotes on the
 * way to the sale window, but the one time they do, they need all of them. */
function Collapsible({
  title,
  count,
  icon,
  defaultOpen = false,
  children,
}: {
  title: string;
  count: number;
  icon: React.ReactNode;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="flex flex-col gap-2.5">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground transition-colors hover:text-foreground"
      >
        {icon}
        {title}
        <span className="rounded-full bg-muted px-1.5 text-[10px] tabular-nums">{count}</span>
        <ChevronDown
          className={`size-3.5 transition-transform ${open ? "rotate-180" : ""}`}
          aria-hidden
        />
      </button>
      {open && children}
    </div>
  );
}
