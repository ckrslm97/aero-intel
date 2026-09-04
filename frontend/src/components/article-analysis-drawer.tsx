"use client";

import { motion } from "framer-motion";
import {
  ExternalLink,
  Minus,
  Sparkles,
  TrendingDown,
  TrendingUp,
  X,
} from "lucide-react";
import { useState } from "react";

import { AirlineLogo } from "@/components/airline-logo";
import { ArticleSourcesList } from "@/components/gazete/article-sources-list";
import { DrawerShell } from "@/components/ui/drawer-shell";
import {
  SCORE_BAND_LABELS_TR,
  type ScoreBand,
  scoreBand,
  scoreReasonTr,
  sourceTierLabelTr,
} from "@/lib/gazete";
import { confidenceBand } from "@/lib/risk";
import { drawerStagger, fadeUpItem } from "@/lib/motion";
import { DISPLAY_TIME_ZONE_TR, formatDateTr, formatStampTr } from "@/lib/format";
import { worldRegions } from "@/lib/nav";
import { categoryVar, getCategory, getSubcategoryLabel } from "@/lib/taxonomy";
import type { ArticleOut } from "@/lib/types";
import { cn } from "@/lib/utils";

const REGION_NAME: Record<string, string> = Object.fromEntries(
  worldRegions.map((r) => [r.slug, r.name]),
);

const SENTIMENT_META: Record<
  string,
  { label: string; icon: typeof TrendingUp; className: string }
> = {
  positive: { label: "Olumlu", icon: TrendingUp, className: "border-good/40 bg-good/10 text-good" },
  negative: {
    label: "Olumsuz",
    icon: TrendingDown,
    className: "border-critical/40 bg-critical/10 text-critical",
  },
  neutral: {
    label: "Nötr",
    icon: Minus,
    className: "border-border bg-muted text-muted-foreground",
  },
};

/** The publication stamp, in the SAME zone and with the same label as the card
 * this drawer opens from (components/article-card.tsx).
 *
 * It was built here with no `timeZone` at all, so it followed the runtime while
 * the card beside it was pinned to Europe/Istanbul: one `article.published_at`,
 * printed two ways, three hours apart, on one screen -- and only one of the two
 * said which clock it was on. */
function publishedStamp(iso: string | null): string {
  const stamp = formatStampTr(iso);
  return stamp === null ? "Tarih bilinmiyor" : `${stamp} ${DISPLAY_TIME_ZONE_TR}`;
}

/** Confidence -> the pill's Turkish word.
 *
 * The band comes from lib/risk.ts `confidenceBand`, which is the app's
 * existing 0.75/0.5 ladder -- the same split the campaign pill renders and the
 * risk drawer reads. A score computed by one formula and banded by three
 * different thresholds across three pages would be the same number meaning
 * three things.
 */
const CONFIDENCE_LABEL: Record<string, string> = {
  high: "Yüksek",
  medium: "Orta",
  low: "Düşük",
};

/** The intelligence band's pill, on the status palette rather than on a fifth
 * scale of its own. The word is always printed, so colour is never the only
 * carrier -- same rule as ui/status-pill.tsx. */
const INTELLIGENCE_BAND_STYLES: Record<ScoreBand, string> = {
  critical: "border-critical/40 bg-critical/10 text-critical",
  high: "border-warning/40 bg-warning/10 text-warning",
  medium: "border-primary/40 bg-primary/10 text-primary",
  low: "border-border bg-muted text-muted-foreground",
};

/** In-app analysis for one article.
 *
 * Almost everything shown here comes from the article object the list already
 * fetched -- category, region, sentiment, confidence, corroboration, named
 * carriers -- and none of it costs a model call: the drawer explains what the
 * pipeline already decided about the story.
 *
 * Two deliberate exceptions to "no second request":
 *
 *   * the corroborating-source list, fetched lazily per article opened
 *     (ArticleSourcesList). The count was already on this panel; the list
 *     under it is what makes the count checkable.
 *   * "Neden önemli?", which is not fetched at all -- it was written at
 *     enrichment time for the few stories that earned it and rides along in
 *     the payload. It is labelled as a model's assessment because that is
 *     what it is.
 */
export function ArticleAnalysisDrawer({
  article,
  onClose,
}: {
  article: ArticleOut | null;
  onClose: () => void;
}) {
  /** The corroboration list is revealed on demand, not on open: most readers
   * want the story, and the ones who question the "3 kaynak" ask for it.
   *
   * Holds the article id rather than a boolean, so opening a second story
   * cannot inherit the first one's expanded state -- and so nothing has to be
   * reset in an effect (a synchronous setState in an effect body is a
   * cascading render, and this stack's exit animations are already fragile
   * enough without one). */
  const [sourcesFor, setSourcesFor] = useState<string | null>(null);

  // Closed is NOT rendered -- and until this round it was, which is the whole
  // point of the change. The panel used to live inside an `AnimatePresence`
  // whose exit-complete callback never fires in this stack, so closing the
  // drawer left its `fixed inset-0` backdrop in the DOM: invisible, full
  // screen, and swallowing every click on the newspaper behind it. See
  // components/ui/drawer-shell.tsx.
  if (!article) return null;

  const enrichment = article.enrichment ?? null;
  const category = enrichment ? getCategory(enrichment.category) : null;
  const subcategoryLabel = enrichment
    ? getSubcategoryLabel(enrichment.category, enrichment.subcategory)
    : null;
  const CategoryIcon = category?.icon;
  const sentiment = enrichment
    ? (SENTIMENT_META[enrichment.sentiment] ?? SENTIMENT_META.neutral)
    : null;
  const SentimentIcon = sentiment?.icon;

  // Same rule the card uses: Turkish only when a translator actually ran.
  const headline =
    (enrichment?.is_translated && enrichment.headline_tr) ||
    enrichment?.headline ||
    article.title ||
    "";
  const summary =
    (enrichment?.is_translated && enrichment.summary_tr) || enrichment?.summary || null;

  const band = enrichment ? confidenceBand(enrichment.confidence_score) : null;
  const intelligenceBand = scoreBand(enrichment?.intelligence_score);
  const selectionReason = scoreReasonTr(enrichment?.score_detail);
  const impactChips: [string, number][] = (
    [
      ["Gelir etkisi", enrichment?.rm_impact],
      ["Talep etkisi", enrichment?.demand_impact],
      ["Kapasite etkisi", enrichment?.capacity_impact],
    ] as [string, number | null | undefined][]
  ).filter((entry): entry is [string, number] => typeof entry[1] === "number");

  return (
    <DrawerShell
      onClose={onClose}
      label="Haber analizi"
      // The story's category color, as a lit edge down the seam where the
      // panel meets the page.
      glowColor={categoryVar(enrichment?.category)}
      className="max-w-lg"
    >
      <header className="flex items-start justify-between gap-4 border-b border-border px-6 py-5">
        <div className="flex flex-wrap items-center gap-2">
          {category && CategoryIcon && (
            <span
              className={cn(
                "flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide",
                category.textClass,
                category.bgClass,
              )}
            >
              <CategoryIcon className="size-3.5" />
              {category.label}
              {subcategoryLabel && (
                <span className="font-normal normal-case opacity-80">
                  · {subcategoryLabel}
                </span>
              )}
            </span>
          )}
          {enrichment?.region && (
            <span className="rounded-full bg-secondary px-2.5 py-1 text-[11px] font-medium text-secondary-foreground">
              {REGION_NAME[enrichment.region] ?? enrichment.region}
            </span>
          )}
          {sentiment && SentimentIcon && (
            <span
              className={cn(
                "flex items-center gap-1 rounded-full border px-2.5 py-1 text-[11px] font-semibold",
                sentiment.className,
              )}
            >
              <SentimentIcon className="size-3.5" />
              {sentiment.label}
            </span>
          )}
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Analizi kapat"
          className="shrink-0 rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
        >
          <X className="size-4" />
        </button>
      </header>

      {/* Interior cascades in after the panel spring has landed
          (drawerStagger's delayChildren), so nothing is sliding while
          the panel is still travelling. */}
      <motion.div
        variants={drawerStagger}
        initial="hidden"
        animate="show"
        className="flex flex-1 flex-col gap-6 overflow-y-auto px-6 py-6"
      >
        <motion.div variants={fadeUpItem} className="flex flex-col gap-2">
          <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
            <span className="font-semibold text-foreground">{article.source.name}</span>
            {/* Which rung of the source ladder this outlet sits on --
                the same word the Risk Radarı's chronology prints for
                the same outlet. */}
            <span className="rounded-full border border-border px-1.5 py-px text-[10px] font-semibold">
              {sourceTierLabelTr(article.source.tier)}
            </span>
            <span aria-hidden>·</span>
            <span>{publishedStamp(article.published_at)}</span>
            <span aria-hidden>·</span>
            <span>{article.reading_time_minutes} dk okuma</span>
          </p>
          <h2 className="text-2xl font-semibold leading-snug tracking-tight text-card-foreground">
            {headline}
          </h2>
          {enrichment && !enrichment.is_translated && (
            <span className="w-fit rounded-full bg-secondary px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-secondary-foreground">
              otomatik çeviri yok
            </span>
          )}
        </motion.div>

        {summary && (
          <motion.p
            variants={fadeUpItem}
            className="whitespace-pre-line text-[15px] leading-relaxed text-muted-foreground"
          >
            {summary}
          </motion.p>
        )}

        {enrichment && (
          <motion.div
            variants={fadeUpItem}
            style={
              { "--gradient-surface": "var(--card)" } as React.CSSProperties
            }
            className="border-gradient flex flex-col gap-4 rounded-xl p-5"
          >
            <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Doğrulama
            </h3>
            <div className="grid grid-cols-2 gap-4">
              <div className="flex flex-col gap-1">
                <span className="text-[11px] text-muted-foreground">Güven skoru</span>
                {/* Band + score, the same pairing the campaign table's
                    pill uses. A bare "%76" invites the reader to grade
                    it themselves against a scale nobody published. */}
                <span className="flex items-center gap-1.5">
                  <span
                    className={cn(
                      "rounded-full border px-2 py-0.5 text-[11px] font-medium",
                      band === "high"
                        ? "border-good/40 bg-good/10 text-good"
                        : band === "medium"
                          ? "border-warning/40 bg-warning/10 text-warning"
                          : "border-dashed border-border text-muted-foreground",
                    )}
                  >
                    {band ? CONFIDENCE_LABEL[band] : "Bilinmiyor"}
                  </span>
                  {/* No number when nobody produced one. The backend
                      column is NOT NULL and defaults to 0.0, so an
                      unscored article used to arrive here as a hard
                      zero and render "Düşük güven · %0" -- a verdict the
                      system never reached, drawn with the same
                      confidence as one it did. */}
                  {enrichment.confidence_score !== null && (
                    <span className="text-sm font-semibold tabular-nums">
                      %{Math.round(enrichment.confidence_score * 100)}
                    </span>
                  )}
                </span>
                <span className="text-[10px] leading-tight text-muted-foreground">
                  {enrichment.confidence_score !== null
                    ? "kaynak-güven temelli skor"
                    : "bu haber için güven skoru hesaplanmadı"}
                </span>
              </div>

              <div className="flex flex-col gap-1">
                <span className="text-[11px] text-muted-foreground">
                  Doğrulayan kaynak
                </span>
                {/* The number opens the list it counts. It was printed
                    here for a year with nothing behind it. */}
                <button
                  type="button"
                  onClick={() =>
                    setSourcesFor(sourcesFor === article.id ? null : article.id)
                  }
                  aria-expanded={sourcesFor === article.id}
                  className="flex w-fit items-center gap-1 text-lg font-semibold tabular-nums transition-colors hover:text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
                >
                  {enrichment.corroborating_source_count} kaynak
                  <span aria-hidden className="text-xs">
                    {sourcesFor === article.id ? "▲" : "→"}
                  </span>
                </button>
              </div>

              {/* There used to be an "Önem skoru" metric here, printing
                  `importance_score`. That column does not measure
                  importance: at the corroboration count every production
                  row actually has, its formula reduces to
                  `0.34 + 0.21 * source.trust_weight` -- the same number
                  for a fare war and for an airport cat, as long as the
                  same outlet filed both. It was a publisher id dressed
                  as a judgement, so it is gone; the intelligence block
                  below is what replaces it. */}
              <Metric label="Doğrulama" value={formatDateTr(enrichment.verified_at) ?? "—"} />
            </div>

            {sourcesFor === article.id && (
              <div className="border-t border-border pt-4">
                <ArticleSourcesList articleId={article.id} />
              </div>
            )}
          </motion.div>
        )}

        {/* WHY THIS STORY IS IN THE PAPER AT ALL.
            Deliberately a band and a reason rather than a number: the
            score is a weighted mean of eight sub-scores where three are
            frequently absent, so its decimals are noise dressed as
            precision, and two stories cannot honestly be compared on
            0.61 vs 0.58. Absent entirely for a row the scoring pass
            never reached -- there is nothing to say about it, and a "0"
            would be a claim nobody made. */}
        {intelligenceBand && (
          <motion.div variants={fadeUpItem} className="flex flex-col gap-3">
            <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              İstihbarat değeri
            </h3>
            <div className="flex flex-wrap items-center gap-2">
              <span
                className={cn(
                  "rounded-full border px-2.5 py-0.5 text-[11px] font-semibold",
                  INTELLIGENCE_BAND_STYLES[intelligenceBand],
                )}
              >
                {SCORE_BAND_LABELS_TR[intelligenceBand]}
              </span>
              {selectionReason && (
                <span className="text-xs text-muted-foreground">
                  Neden seçildi: {selectionReason}
                </span>
              )}
            </div>
            {/* The model's three axes. NULL and 0.0 are different
                claims: only the day's shortlist is scored by the model,
                so an unscored axis draws no chip at all, while a scored
                zero draws "%0" -- "the model read this and found no
                capacity angle". Conflating them would put a made-up
                reading on ~95% of the archive. */}
            {impactChips.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {impactChips.map(([label, value]) => (
                  <span
                    key={label}
                    className="flex items-center gap-1.5 rounded-full border border-border px-2.5 py-1 text-[11px]"
                  >
                    <span className="text-muted-foreground">{label}</span>
                    <span className="font-semibold tabular-nums">
                      %{Math.round(value * 100)}
                    </span>
                  </span>
                ))}
              </div>
            )}
          </motion.div>
        )}

        {enrichment?.why_important_tr && (
          <motion.div
            variants={fadeUpItem}
            className="flex flex-col gap-2 rounded-xl border-l-2 border-primary bg-secondary/40 px-4 py-3"
          >
            <h3 className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              <Sparkles className="size-3.5 text-primary" aria-hidden />
              Neden önemli?
            </h3>
            <p className="text-[14px] leading-relaxed text-card-foreground">
              {enrichment.why_important_tr}
            </p>
            {/* Labelled, not blended into the summary above it: this
                sentence is a model's reading of the story, while
                everything else in this panel is a fact the pipeline
                recorded about it. */}
            <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
              Yapay zekâ değerlendirmesi
            </span>
          </motion.div>
        )}

        {article.airlines.length > 0 && (
          <motion.div variants={fadeUpItem} className="flex flex-col gap-2.5">
            <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Adı geçen taşıyıcılar
            </h3>
            <div className="flex flex-wrap gap-2">
              {article.airlines.map((airline) => (
                <span
                  key={airline.code ?? airline.name}
                  className="flex items-center gap-2 rounded-full border border-border px-2.5 py-1 text-xs"
                >
                  {airline.code && (
                    <AirlineLogo
                      code={airline.code}
                      name={airline.name}
                      className="size-4"
                    />
                  )}
                  {airline.name}
                </span>
              ))}
            </div>
          </motion.div>
        )}

        {article.airports.length > 0 && (
          <motion.div variants={fadeUpItem} className="flex flex-col gap-2.5">
            <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Adı geçen havalimanları
            </h3>
            <div className="flex flex-wrap gap-2">
              {article.airports.map((airport) => (
                <span
                  key={airport.code ?? airport.name}
                  className="rounded-full border border-border px-2.5 py-1 text-xs"
                >
                  {airport.name}
                  {airport.code && (
                    <span className="ml-1 font-mono text-[10px] text-muted-foreground">
                      {airport.code}
                    </span>
                  )}
                </span>
              ))}
            </div>
          </motion.div>
        )}

        {/* There used to be an "Etiketler" section here. It rendered
            `enrichment.tags`, which the pipeline writes as the sorted
            set of ENTITY TYPES an article mentions -- so on every story
            in the paper it printed the same three words: "airline,
            airport, country". Not a topic vocabulary, not filterable,
            and identical on every row. The carrier and airport chips
            above already say what those types were pointing at, so the
            section is gone rather than replaced: inventing a real tag
            vocabulary is a classification change, not a drawer change. */}

        <motion.p
          variants={fadeUpItem}
          className="text-[11px] leading-relaxed text-muted-foreground"
        >
          Bu analiz, haber alındığında boru hattının ürettiği sınıflandırma ve
          doğrulama verisinden oluşur; panel açılırken yeni bir model çağrısı
          yapılmaz. &ldquo;Neden önemli?&rdquo; bölümü varsa, o da haber
          işlenirken bir kez üretilmiştir.
        </motion.p>
      </motion.div>

      <footer className="border-t border-border px-6 py-4">
        <a
          href={article.url}
          target="_blank"
          rel="noopener noreferrer"
          style={{ "--glow-color": "var(--primary)" } as React.CSSProperties}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-gradient-to-r from-primary to-chart-4 px-4 py-2.5 text-sm font-semibold text-primary-foreground transition-shadow duration-300 hover:glow-soft"
        >
          Kaynağa git
          <ExternalLink className="size-4" />
        </a>
      </footer>
    </DrawerShell>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[11px] text-muted-foreground">{label}</span>
      <span className="text-lg font-semibold tabular-nums">{value}</span>
    </div>
  );
}
