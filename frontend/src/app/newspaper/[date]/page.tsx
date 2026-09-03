import { Download } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { ArticleCard } from "@/components/article-card";
import { MotionItem, MotionList } from "@/components/motion/motion-list";
import { API_BASE_URL, ApiError, apiFetch } from "@/lib/api";
import { formatDayTr } from "@/lib/format";
import { CATEGORY_LABELS_TR } from "@/lib/taxonomy.gen";
import type { EditionOut } from "@/lib/types";

// Cards open the in-app analysis drawer, which lives on ArticleDrawerProvider
// in the app shell (components/layout/app-shell.tsx) -- every route is inside
// it, so this page needs no wrapper of its own.

// Category names come from the taxonomy, which is generated from
// backend/app/taxonomy.py -- the same strings the newsletter and the PDF render,
// so a reader arriving from either lands on sections with the same names.
// "top_story" is the edition's lead slot, not a category.
const SECTION_LABELS: Record<string, string> = {
  top_story: "Öne Çıkanlar",
  ...CATEGORY_LABELS_TR,
};

/** The API's code for "this day's paper has not been assembled yet".
 *
 * GET /editions/{date} stopped assembling on demand (backend/app/api/v1/
 * editions.py): reading the paper no longer publishes it. The assembly job
 * runs from 03:00 UTC and, measured on this repo, actually starts 2-3 hours
 * later -- so every morning there is a window in which today's row does not
 * exist yet. "Günün Gazetesi" (components/newspaper-browser.tsx) links to the
 * current UTC date, straight into that window.
 *
 * Mapping every 404 to notFound() answered that reader with "Bu rota
 * bilinmiyor -- aradığınız sayfa taşınmış ya da hiç var olmamış olabilir",
 * which is false twice over: the route is right and the paper is coming. Only
 * the server can tell "not yet" from "never", and this is the code it uses to.
 */
const NOT_PREPARED = "not_prepared_yet";

/** What the card will actually print for this article -- the same rule
 * ArticleCard uses (Turkish only when a translator really produced it). */
function displayHeadline(article: EditionOut["sections"][number]["articles"][number] | undefined) {
  if (!article) return null;
  const enrichment = article.enrichment;
  const translated = enrichment?.translated_at != null;
  return (
    (translated ? enrichment?.headline_tr : null) ?? enrichment?.headline ?? article.title
  );
}

export default async function EditionPage({
  params,
}: {
  params: Promise<{ date: string }>;
}) {
  const { date } = await params;

  let edition: EditionOut;
  try {
    edition = await apiFetch<EditionOut>(`/editions/${date}`);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      // Only "not yet" gets a page of its own. Anything else 404 -- a past day
      // nobody built, a date this route never had -- is genuinely not found,
      // and saying "henüz hazırlanmadı" about 2024 would be the same lie in
      // the other direction.
      if (err.code === NOT_PREPARED) {
        return <EditionNotPrepared date={date} />;
      }
      notFound();
    }
    throw err;
  }

  const topSection = edition.sections.find((s) => s.section === "top_story");
  const [leadStory, ...restTopStories] = topSection?.articles ?? [];
  const otherSections = edition.sections.filter((s) => s.section !== "top_story");

  // The masthead headline IS the lead story's headline, so rendering the lead
  // as a big "top" card printed the same sentence twice at display size --
  // with an aggregator title of 20+ words that filled the screen before any
  // news appeared. When they match, the lead joins the other top stories as a
  // normal card and the masthead carries it alone.
  const leadHeadline = displayHeadline(leadStory);
  const leadRepeatsMasthead =
    leadHeadline !== null && leadHeadline.trim() === edition.headline.trim();
  const topStoryCards = leadRepeatsMasthead && leadStory
    ? [leadStory, ...restTopStories]
    : restTopStories;

  return (
    <div className="flex flex-col gap-10">
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between gap-4">
          {/* THE MASTHEAD DAY, and it must be the day in the URL.
              `new Date("2026-09-04")` is UTC midnight, formatted with no
              `timeZone` in whatever zone the renderer sits in -- so the edition
              of the 4th was mastheaded "3 Eylül 2026 Perşembe" for every reader
              west of Greenwich, one day off from the route they had just
              clicked. `formatDayTr` anchors a date-only value at midday UTC and
              pins the zone, which no offset from UTC-11 to UTC+12 can shift. */}
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            {formatDayTr(edition.edition_date)}
          </p>
          {edition.pdf_available && (
            <a
              href={`${API_BASE_URL}/editions/${edition.edition_date}/pdf`}
              className="flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-foreground hover:bg-accent"
            >
              <Download className="size-3.5" />
              PDF İndir
            </a>
          )}
        </div>
        <h1 className="max-w-4xl text-balance text-xl font-semibold leading-tight tracking-tight sm:text-2xl lg:text-[28px]">
          {edition.headline}
        </h1>
        {edition.executive_summary && (
          <p className="line-clamp-3 max-w-3xl text-sm leading-relaxed text-muted-foreground">
            {edition.executive_summary}
          </p>
        )}
      </div>

      {leadStory && (
        <section className="flex flex-col gap-4">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            {leadRepeatsMasthead ? "Öne çıkan haberler" : "Öne çıkan haber"}
          </h2>
          {!leadRepeatsMasthead && (
            <MotionList>
              <MotionItem className="rounded-xl border border-border bg-card">
                <ArticleCard article={leadStory} variant="top" />
              </MotionItem>
            </MotionList>
          )}

          {topStoryCards.length > 0 && (
            <MotionList className="grid grid-cols-1 gap-5 md:grid-cols-2">
              {topStoryCards.map((article) => (
                <MotionItem
                  key={article.id}
                  className="rounded-xl border border-border bg-card"
                >
                  <ArticleCard article={article} />
                </MotionItem>
              ))}
            </MotionList>
          )}
        </section>
      )}

      {/* This page stays section-grouped -- it is already one date, so the
          Gazete browser's day headers would say the same thing nine times. */}
      {otherSections.map((section) => (
        <section key={section.section} className="flex flex-col gap-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            {SECTION_LABELS[section.section] ?? section.section}
          </h2>
          <MotionList className="flex flex-col divide-y divide-border rounded-xl border border-border bg-card">
            {section.articles.map((article) => (
              <MotionItem key={article.id}>
                <ArticleCard article={article} />
              </MotionItem>
            ))}
          </MotionList>
        </section>
      ))}

      {!leadStory && otherSections.length === 0 && (
        <p className="rounded-lg border border-dashed border-border p-6 text-sm text-muted-foreground">
          Bu sayıda henüz haber yok.
        </p>
      )}
    </div>
  );
}

/** The honest wait. A date, a reason, and two ways onward -- because a reader
 * who arrived here still wants today's news, and the archive has it. */
function EditionNotPrepared({ date }: { date: string }) {
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {new Date(date).toLocaleDateString("tr-TR", {
            weekday: "long",
            year: "numeric",
            month: "long",
            day: "numeric",
          })}
        </p>
        <h1 className="text-2xl font-semibold tracking-tight">
          Bu günün baskısı henüz hazırlanmadı
        </h1>
      </div>
      <p className="rounded-lg border border-dashed border-border p-6 text-sm text-muted-foreground">
        Günün gazetesi her sabah otomatik olarak derleniyor. Bu tarihin baskısı
        henüz derlenmedi; kısa süre sonra tekrar deneyebilir ya da yayımlanmış
        sayılara göz atabilirsiniz.
      </p>
      <div className="flex flex-wrap gap-3">
        <Link
          href="/newspaper"
          className="rounded-md border border-border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-accent"
        >
          Gazete
        </Link>
        <Link
          href="/archive"
          className="rounded-md border border-border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-accent"
        >
          Arşiv
        </Link>
      </div>
    </div>
  );
}
