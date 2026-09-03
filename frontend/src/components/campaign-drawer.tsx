"use client";

import { motion, useReducedMotion } from "framer-motion";
import {
  BadgeCheck,
  CalendarClock,
  ChevronDown,
  ExternalLink,
  History,
  Quote,
  Split,
  TriangleAlert,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { AirlineLogo } from "@/components/airline-logo";
import { CampaignStatusPill, ConfidencePill } from "@/components/campaign-analyst-table";
import { CampaignWindows } from "@/components/campaign-windows";
import { apiFetch } from "@/lib/api";
import {
  campaignAttr,
  campaignFieldLabel,
  campaignRouteLabel,
  formatChangeValue,
  sourceTierLabel,
} from "@/lib/campaigns";
import { drawerPanel, drawerStagger, fadeUpItem, overlayFade, reduceVariants } from "@/lib/motion";
import { worldRegions } from "@/lib/nav";
import {
  CAMPAIGN_BUSINESS_CLASS_LABELS_TR,
  CAMPAIGN_KIND_LABELS_TR,
  CAMPAIGN_TYPE_LABELS_TR,
  type CampaignBusinessClass,
  type CampaignKind,
  type CampaignType,
} from "@/lib/taxonomy.gen";
import type { PromotionOut, PromotionSource, PromotionVersion } from "@/lib/types";

const REGION_NAME: Record<string, string> = Object.fromEntries(
  worldRegions.map((r) => [r.slug, r.name]),
);

/** UTC, and the cells that use it say "UTC" out loud.
 *
 * These three stamps -- last check, first sighting, and the source article's
 * publication -- are facts about the RECORD, and a record's timestamp that
 * shifts with who is looking at it is not a fact (the same rule
 * risk/risk-detail-drawer.tsx states, and the one LastUpdatedStamp follows).
 * Left in the reader's own zone, one row's "İlk tespit" would print two
 * different hours, and across midnight two different days, to two analysts
 * comparing the same campaign. */
const DETECTED_FORMAT = new Intl.DateTimeFormat("tr-TR", {
  timeZone: "UTC",
  dateStyle: "medium",
  timeStyle: "short",
});

const DAY_FORMAT = new Intl.DateTimeFormat("tr-TR", { dateStyle: "medium" });

function formatDay(iso: string | null): string | null {
  if (!iso) return null;
  const at = new Date(`${iso.slice(0, 10)}T00:00:00Z`);
  return Number.isNaN(at.getTime()) ? null : DAY_FORMAT.format(at);
}

/** A window the carrier stated SEPARATELY from the sale and travel ones.
 *
 * Almost always empty, and that emptiness is the information: a filled
 * ticketing or campaign period means the carrier published one, never that we
 * assumed it from the booking window. So the row is rendered only when at
 * least one edge exists -- an always-present "Belirtilmedi" here would be two
 * more lines of nothing in a panel whose job is the four dates above it. */
function statedRange(start: string | null, end: string | null): string | null {
  const from = formatDay(start);
  const to = formatDay(end);
  if (!from && !to) return null;
  if (from && to) return `${from} → ${to}`;
  return from ? `${from} → belirtilmedi` : `belirtilmedi → ${to}`;
}

/** One campaign, in full.
 *
 * Deliberately NOT a shared abstraction with `article-analysis-drawer.tsx`.
 * The two panels share a shell -- backdrop, spring aside, Escape, scroll lock,
 * seam light -- and that shell is about sixty lines. Their interiors share
 * nothing at all: one explains a pipeline's verdict on a story, the other
 * states four dates and a discount.
 *
 * The rule the interior follows: every field here can be absent, and an absent
 * field says so. There is no cell that renders empty and no badge that renders
 * as a blank -- "Belirtilmedi" is a fact about the source, and hiding it would
 * make a half-known campaign look fully known.
 *
 * v2 compressed it. The dates are now the same two-track drawing the feed row
 * uses (campaign-windows.tsx) rather than two prose cells, the identity badges
 * are one wrapping row, and the four provenance sections -- why the classifier
 * called this a campaign, the sentences each field was read from, what has
 * changed since we first saw it, and which pages told us -- are all collapsed
 * by default rather than three of four being open. Nothing was dropped: a
 * reader auditing a record still gets every quote, every version diff and
 * every source URL, one click in.
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
  const closeRef = useRef<HTMLButtonElement>(null);

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

  // Hooks first, then the early return: `promotion === null` is the closed
  // state and this component is mounted for the whole page's life.
  if (!promotion) return null;

  const versions = history?.id === promotionId ? history.versions : [];
  const sources = history?.id === promotionId ? history.sources : [];

  const markets = promotion.markets
    ? promotion.markets
        .split(",")
        .map((m) => m.trim())
        .filter(Boolean)
    : [];

  const evidence = Object.entries(promotion.evidence_json ?? {}).filter(
    ([, entry]) => entry && typeof entry.source_text === "string" && entry.source_text.trim(),
  );
  const inferredYear = Boolean(
    promotion.date_flags_json &&
      (promotion.date_flags_json as { inferred_year?: unknown }).inferred_year,
  );

  const ticketing = statedRange(promotion.ticketing_start, promotion.ticketing_end);
  const campaignPeriod = statedRange(promotion.campaign_start, promotion.campaign_end);
  const cabin = campaignAttr(promotion, "cabin");
  const promoCode = campaignAttr(promotion, "promo_code");
  // "Son kontrol" = the last time a scan CONFIRMED this campaign still on its
  // page, which is `last_seen_at` and nothing else. It used to print
  // `last_changed_at ?? detected_at`: a campaign re-checked hourly and
  // unchanged for a week was shown as last checked a week ago, and a row that
  // has never been re-checked at all was shown as checked at the moment we
  // first saw it. Both are answers to questions the reader did not ask.
  //
  // `null` stays null: a write path that never re-checks anything has not
  // checked, and "—" says that. It does not fall back to another timestamp.
  const lastChecked = promotion.last_seen_at;

  return (
    // Mounted and unmounted outright -- deliberately NOT wrapped in
    // `AnimatePresence`. Measured in this stack (framer-motion 12 + React 19):
    // the exit animation runs, then the exit-complete callback never fires, so
    // the subtree is never unmounted -- the panel ends off-screen but its
    // `fixed inset-0` backdrop stays over the page and every click after the
    // first close lands on a black overlay. A modal that cannot be dismissed
    // is a far worse failure than one that closes without a 200ms slide, so
    // the entrance is kept and the exit is dropped. See
    // risk-detail-drawer.tsx, where this was first diagnosed.
    <>
      <motion.div
        key="campaign-drawer-overlay"
        variants={reduceMotion ? reduceVariants(overlayFade) : overlayFade}
        initial="hidden"
        animate="show"
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
        // The carrier's own hex, not a category token: on this page the
        // airline IS the identity, and the seam light reads from here.
        style={{ "--glow-color": brandHex } as React.CSSProperties}
        className="fixed inset-y-0 right-0 z-50 flex w-full max-w-md flex-col border-l border-border bg-card shadow-2xl"
      >
        <span
          aria-hidden
          className="pointer-events-none absolute inset-y-0 left-0 w-0.5 bg-gradient-to-b from-[var(--glow-color)] via-[var(--glow-color)]/40 to-transparent"
        />

        <header className="flex items-start justify-between gap-3 border-b border-border px-5 py-3.5">
          <div className="flex min-w-0 items-center gap-2.5">
            <AirlineLogo
              code={promotion.airline_code}
              name={promotion.airline_name}
              className="size-7 shrink-0"
            />
            <div className="flex min-w-0 flex-col">
              <span className="truncate text-xs font-semibold text-card-foreground">
                {promotion.airline_name}
              </span>
              <span className="truncate text-[10px] font-medium uppercase tracking-wider text-muted-foreground tabular-nums">
                {promotion.airline_code} · {promotion.source_name}
              </span>
            </div>
          </div>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            aria-label="Kampanyayı kapat"
            className="shrink-0 rounded p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          >
            <X className="size-4" />
          </button>
        </header>

        <motion.div
          variants={reduceMotion ? reduceVariants(drawerStagger) : drawerStagger}
          initial="hidden"
          animate="show"
          className="flex flex-1 flex-col gap-4 overflow-y-auto px-5 py-4"
        >
          <motion.h2
            variants={item}
            className="text-lg font-semibold leading-snug tracking-tight text-card-foreground"
          >
            {promotion.title_tr}
          </motion.h2>

          {/* Status, class and the warning badges sit above everything else:
              they are what tells a reader whether the numbers below are worth
              reading at all. */}
          <motion.div variants={item} className="flex flex-wrap items-center gap-1">
            <CampaignStatusPill status={promotion.status} />
            {promotion.campaign_kind && (
              <Tag>{CAMPAIGN_KIND_LABELS_TR[promotion.campaign_kind as CampaignKind]}</Tag>
            )}
            {promotion.campaign_type && (
              <Tag>
                {CAMPAIGN_TYPE_LABELS_TR[promotion.campaign_type as CampaignType] ??
                  promotion.campaign_type}
              </Tag>
            )}
            {promotion.business_class && (
              <Tag>
                {CAMPAIGN_BUSINESS_CLASS_LABELS_TR[
                  promotion.business_class as CampaignBusinessClass
                ] ?? promotion.business_class}
              </Tag>
            )}
            {/* Both states, unlike the feed row: a reader who opened the panel
                came to ask, and "no official source" is an answer. */}
            {promotion.official_source_verified ? (
              <span
                title="Havayolunun kendi sayfası bu kampanya için kaynak olarak kayıtlı."
                className="inline-flex items-center gap-1 rounded-full border border-good/40 bg-good/10 px-1.5 py-0.5 text-[10px] font-medium text-good"
              >
                <BadgeCheck className="size-3" aria-hidden />
                Resmî kaynak
              </span>
            ) : (
              <span
                title="Bu kampanya için havayolunun kendi sayfasından bir kaynak kaydedilmedi; bilgi ikincil kaynaklardan geliyor."
                className="inline-flex items-center gap-1 rounded-full border border-dashed border-border px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground"
              >
                Resmî kaynak yok
              </span>
            )}
            {promotion.conflict_detected === true && (
              <span
                title="İki kaynak bir alanda çelişti; daha resmî olan kazandı. Kaybeden değer değişiklik geçmişinde duruyor."
                className="inline-flex items-center gap-1 rounded-full border border-critical/40 bg-critical/10 px-1.5 py-0.5 text-[10px] font-medium text-critical"
              >
                <Split className="size-3" aria-hidden />
                Kaynak çelişkisi
              </span>
            )}
            {promotion.review_required === true && (
              <span
                title="Güven eşiğinin altında kaldı: bir insanın doğrulaması bekleniyor."
                className="inline-flex items-center gap-1 rounded-full border border-warning/40 bg-warning/10 px-1.5 py-0.5 text-[10px] font-medium text-warning"
              >
                <TriangleAlert className="size-3" aria-hidden />
                İnceleme gerekli
              </span>
            )}
          </motion.div>

          <motion.div variants={item} className="flex items-baseline gap-2">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              İndirim
            </span>
            {promotion.discount_pct !== null ? (
              <span className="text-2xl font-semibold tabular-nums leading-none">
                %{promotion.discount_pct}
                <span className="ml-1 text-xs font-normal text-muted-foreground">
                  &apos;a varan
                </span>
              </span>
            ) : (
              // A fare campaign ("9 Euro'dan başlayan") genuinely has no
              // percentage. Saying so beats an empty hero.
              <span className="text-sm text-muted-foreground">Oran belirtilmedi</span>
            )}
          </motion.div>

          {/* The two windows, as the two windows -- not as two sentences. */}
          <motion.div
            variants={item}
            className="flex flex-col gap-2 rounded-lg border border-border bg-background/40 p-3"
          >
            <CampaignWindows promo={promotion} />
            {inferredYear && (
              <p className="flex items-start gap-1 text-[10px] leading-relaxed text-warning">
                <TriangleAlert className="mt-px size-3 shrink-0" aria-hidden />
                Yıl kaynakta yazmıyordu; metinden çıkarıldı.
              </p>
            )}
            {(ticketing || campaignPeriod) && (
              <dl className="grid grid-cols-[5.5rem_1fr] gap-x-2 gap-y-0.5 border-t border-border pt-2">
                {ticketing && (
                  <>
                    <dt className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                      Biletleme
                    </dt>
                    <dd className="text-[11px] tabular-nums">{ticketing}</dd>
                  </>
                )}
                {campaignPeriod && (
                  <>
                    <dt className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                      Kampanya
                    </dt>
                    <dd className="text-[11px] tabular-nums">{campaignPeriod}</dd>
                  </>
                )}
              </dl>
            )}
          </motion.div>

          <motion.dl
            variants={item}
            className="grid grid-cols-2 gap-x-4 gap-y-2.5 rounded-lg border border-border p-3"
          >
            <Cell label="Rota" value={campaignRouteLabel(promotion)} />
            <Cell label="Kabin" value={cabin ?? "Belirtilmedi"} />
            <Cell label="Promosyon kodu" value={promoCode ?? "Belirtilmedi"} />
            <Cell
              label="Kapsam"
              value={markets.length > 0 ? `${markets.length} pazar` : "Belirtilmedi"}
            />
            <Cell
              label="Son kontrol"
              value={
                lastChecked ? `${DETECTED_FORMAT.format(new Date(lastChecked))} UTC` : "—"
              }
              hint={
                lastChecked
                  ? "Kampanyanın sayfasında en son doğrulandığı an (UTC)"
                  : "Bu kayıt ilk tespitten sonra yeniden kontrol edilmedi"
              }
            />
            <Cell
              label="İlk tespit"
              value={`${DETECTED_FORMAT.format(new Date(promotion.detected_at))} UTC`}
              hint={
                promotion.source_published_at
                  ? `Kampanyayı ilk gördüğümüz an. Kaynak haberin yayın tarihi: ${DETECTED_FORMAT.format(
                      new Date(promotion.source_published_at),
                    )} UTC`
                  : "Kampanyayı ilk gördüğümüz an"
              }
            />
            <div className="flex flex-col gap-0.5">
              <dt className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Güven
              </dt>
              <dd>
                <ConfidencePill
                  band={promotion.confidence_band}
                  score={promotion.confidence_score}
                />
              </dd>
            </div>
          </motion.dl>

          {markets.length > 0 && (
            <motion.div variants={item} className="flex flex-wrap gap-1">
              {markets.map((market) => (
                <span
                  key={market}
                  className="rounded-md border border-border px-1.5 py-0.5 text-[11px] text-muted-foreground"
                >
                  {/* Region slugs get their Turkish name; a city name is
                      already in the source's own words, so it stands. */}
                  {REGION_NAME[market] ?? market}
                </span>
              ))}
            </motion.div>
          )}

          {promotion.summary_tr && (
            <motion.div variants={item}>
              <Collapsible title="Özet" icon={<Quote className="size-3" />}>
                <p className="whitespace-pre-line text-[13px] leading-relaxed text-muted-foreground">
                  {promotion.summary_tr}
                </p>
              </Collapsible>
            </motion.div>
          )}

          {promotion.classification_reason && (
            <motion.div variants={item}>
              <Collapsible title="Neden kampanya?" icon={<Quote className="size-3" />}>
                {/* The classifier's own sentence, quoted rather than
                    paraphrased: an unexplained verdict is an unfixable one. */}
                <blockquote className="border-l-2 border-[var(--glow-color)] pl-2.5 text-[13px] leading-relaxed text-muted-foreground">
                  {promotion.classification_reason}
                </blockquote>
              </Collapsible>
            </motion.div>
          )}

          {evidence.length > 0 && (
            <motion.div variants={item}>
              <Collapsible
                title="Kanıt alıntıları"
                count={evidence.length}
                icon={<Quote className="size-3" />}
              >
                <ul className="flex flex-col gap-2">
                  {evidence.map(([field, entry]) => (
                    <li key={field} className="flex flex-col gap-0.5">
                      <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                        {campaignFieldLabel(field)}
                        {entry.value !== undefined && entry.value !== null && (
                          <span className="ml-1 font-normal normal-case text-foreground">
                            {formatChangeValue(entry.value)}
                          </span>
                        )}
                      </span>
                      {/* The sentence the value was read from. This is the
                          difference between a number and a citation. */}
                      <blockquote className="border-l-2 border-border pl-2.5 text-[12px] italic leading-relaxed text-muted-foreground">
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
                icon={<History className="size-3" />}
              >
                <ol className="flex flex-col gap-2.5">
                  {versions.map((version) => (
                    <li key={version.version_no} className="flex flex-col gap-1">
                      <span className="flex items-center gap-1.5 text-[10px] font-medium tabular-nums text-muted-foreground">
                        <CalendarClock className="size-3" aria-hidden />
                        {DAY_FORMAT.format(new Date(version.created_at))}
                        <span className="rounded-full bg-muted px-1.5 text-[10px]">
                          v{version.version_no}
                        </span>
                      </span>
                      <ul className="flex flex-col gap-0.5 border-l-2 border-border pl-2.5">
                        {Object.entries(version.changed_fields).map(([field, change]) => (
                          <li key={field} className="text-[12px] leading-snug">
                            <span className="font-medium">{campaignFieldLabel(field)}: </span>
                            <span className="text-muted-foreground line-through">
                              {formatChangeValue(change?.previous)}
                            </span>
                            <span className="text-muted-foreground"> → </span>
                            <span className="font-medium">
                              {formatChangeValue(change?.new)}
                            </span>
                            {change?.conflict && (
                              <span className="ml-1 text-[10px] text-critical">
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
            <motion.div variants={item}>
              <Collapsible
                title="Kaynaklar"
                count={sources.length}
                icon={<ExternalLink className="size-3" />}
              >
                <ul className="flex flex-col gap-1">
                  {sources.map((source) => (
                    <li key={source.url} className="flex items-center gap-1.5 text-[12px]">
                      <span
                        className={
                          source.source_tier === "official"
                            ? "shrink-0 rounded-full border border-good/40 bg-good/10 px-1.5 py-px text-[10px] font-semibold text-good"
                            : source.source_tier === "newsroom"
                              ? "shrink-0 rounded-full border border-primary/40 bg-primary/10 px-1.5 py-px text-[10px] font-semibold text-primary"
                              : "shrink-0 rounded-full border border-border px-1.5 py-px text-[10px] font-semibold text-muted-foreground"
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
                    </li>
                  ))}
                </ul>
              </Collapsible>
            </motion.div>
          )}

          <motion.p
            variants={item}
            className="text-[10px] leading-relaxed text-muted-foreground"
          >
            Tarihler kaynağın yayımladığı haliyle alınır; belirtilmeyen bir tarih tahmin
            edilmez. Durum, tarihlerden okunarak her istekte yeniden hesaplanır.
          </motion.p>
        </motion.div>

        <footer className="border-t border-border px-5 py-3">
          <a
            href={promotion.url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex w-full items-center justify-center gap-1.5 rounded-md border border-border bg-background px-3 py-2 text-xs font-semibold transition-colors hover:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          >
            Kaynağı gör
            <ExternalLink className="size-3.5" aria-hidden />
          </a>
        </footer>
      </motion.aside>
    </>
  );
}

function Tag({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded-full border border-border px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
      {children}
    </span>
  );
}

function Cell({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <dt className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        {label}
      </dt>
      <dd className="text-[13px] font-medium leading-snug" title={hint}>
        {value || "—"}
      </dd>
    </div>
  );
}

/** A section that opens on click. Every reference block in this panel is one:
 * nobody reads eleven evidence quotes on the way to the sale window, but the
 * one time they do, they need all of them. */
function Collapsible({
  title,
  count,
  icon,
  children,
}: {
  title: string;
  count?: number;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="flex flex-col gap-2">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-fit items-center gap-1.5 rounded text-[10px] font-semibold uppercase tracking-wider text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
      >
        {icon}
        {title}
        {count !== undefined && (
          <span className="rounded-full bg-muted px-1.5 text-[10px] tabular-nums">{count}</span>
        )}
        <ChevronDown
          className={`size-3 transition-transform ${open ? "rotate-180" : ""}`}
          aria-hidden
        />
      </button>
      {open && children}
    </div>
  );
}
