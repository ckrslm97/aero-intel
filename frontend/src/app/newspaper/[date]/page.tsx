import { Download } from "lucide-react";
import { notFound } from "next/navigation";

import { ArticleCard } from "@/components/article-card";
import { API_BASE_URL, ApiError, apiFetch } from "@/lib/api";
import type { EditionOut } from "@/lib/types";

const SECTION_LABELS: Record<string, string> = {
  top_story: "Top Stories",
  general: "General",
  safety: "Safety",
  finance: "Finance",
  fleet: "Fleet",
  routes: "Routes",
  regulatory: "Regulatory",
  sustainability: "Sustainability",
  labor: "Labor",
  airport: "Airports",
};

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
      notFound();
    }
    throw err;
  }

  const topSection = edition.sections.find((s) => s.section === "top_story");
  const [leadStory, ...restTopStories] = topSection?.articles ?? [];
  const otherSections = edition.sections.filter((s) => s.section !== "top_story");

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between gap-4">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            {new Date(edition.edition_date).toLocaleDateString("en-GB", {
              weekday: "long",
              year: "numeric",
              month: "long",
              day: "numeric",
            })}
          </p>
          {edition.pdf_available && (
            <a
              href={`${API_BASE_URL}/editions/${edition.edition_date}/pdf`}
              className="flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-foreground hover:bg-accent"
            >
              <Download className="size-3.5" />
              Download PDF
            </a>
          )}
        </div>
        <h1 className="text-3xl font-semibold tracking-tight">{edition.headline}</h1>
        {edition.executive_summary && (
          <p className="max-w-3xl text-sm text-muted-foreground">{edition.executive_summary}</p>
        )}
      </div>

      {leadStory && (
        <section className="flex flex-col gap-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Top story
          </h2>
          <div className="rounded-xl border border-border bg-card">
            <ArticleCard article={leadStory} variant="top" />
          </div>

          {restTopStories.length > 0 && (
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              {restTopStories.map((article) => (
                <div key={article.id} className="rounded-xl border border-border bg-card">
                  <ArticleCard article={article} />
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      {otherSections.map((section) => (
        <section key={section.section} className="flex flex-col gap-2">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            {SECTION_LABELS[section.section] ?? section.section}
          </h2>
          <div className="flex flex-col divide-y divide-border rounded-xl border border-border bg-card">
            {section.articles.map((article) => (
              <ArticleCard key={article.id} article={article} />
            ))}
          </div>
        </section>
      ))}

      {!leadStory && otherSections.length === 0 && (
        <p className="rounded-lg border border-dashed border-border p-6 text-sm text-muted-foreground">
          No stories in this edition yet.
        </p>
      )}
    </div>
  );
}
