"use client";

import { ExternalLink, Newspaper } from "lucide-react";
import { useCallback } from "react";

import { InlineSourceError } from "@/components/data-source-error";
import { useDataSource } from "@/hooks/use-data-source";
import { apiFetch } from "@/lib/api";
import { DISPLAY_TIME_ZONE_TR, formatShortDateTr } from "@/lib/format";
import { sourceTierLabelTr } from "@/lib/gazete";
import type { ArticleSourceOut } from "@/lib/types";
import { cn } from "@/lib/utils";

/** The same pinned stamp the article card and the drawer around this list
 * print. Built here with no `timeZone`, these rows followed the runtime while
 * the drawer's own header did not -- two publication times for the same story,
 * a centimetre apart. The zone is named once, in the section caption below,
 * rather than on every one of N rows. */
function stamp(iso: string | null): string {
  return formatShortDateTr(iso) ?? "Tarih yok";
}

/** The list behind "Doğrulayan N kaynak".
 *
 * That number has been on the analysis drawer since it shipped with nothing
 * underneath it -- a "3" the reader could neither check nor open. The group it
 * counts was already stored (Article.duplicate_of_id) and simply never
 * exposed; this renders it.
 *
 * Fetched lazily, per article opened, for the same reason the campaign
 * drawer's source history is: riding it along with every list row would be
 * thirty joins to serve the one story anyone actually opens.
 *
 * A failure empties the section rather than breaking the drawer -- the article
 * is already on screen, and the corroboration is an elaboration on it. It says
 * so, though, and it offers a way back: an unread source list is not a story
 * nobody else picked up.
 *
 * `useDataSource` RATHER THAN TWO HAND-ROLLED FLAGS. The rows were already
 * keyed by article id -- "could this be another article's sources" had to be
 * unaskable -- but the failure flag was not, and it was never cleared. One
 * failed request therefore followed the reader from article to article: the
 * next story's sources arrived, were held in state, and were hidden behind the
 * previous story's error, which is the same "another question's answer" bug
 * the hook's `sameSelection` gate exists to prevent, seen from the other side.
 * The hook keys BOTH, and brings the retry with it.
 */
export function ArticleSourcesList({ articleId }: { articleId: string }) {
  const fetcher = useCallback(
    (signal: AbortSignal) =>
      apiFetch<ArticleSourceOut[]>(`/articles/${articleId}/sources`, {
        cache: "default",
        signal,
      }),
    [articleId],
  );
  const source = useDataSource(fetcher, [articleId]);
  const rows = source.data;

  // `error && !data` is the full-error branch: a failed refresh that still has
  // this article's rows keeps showing them (hooks/use-data-source.ts).
  if (source.error && rows === null) {
    return (
      <InlineSourceError
        message="Kaynak listesi okunamadı; bu haberi başka kaynağın işlemediği anlamına gelmez."
        onRetry={source.retry}
        pending={source.pending}
        className="text-[11px]"
      />
    );
  }
  if (rows === null) {
    return <p className="text-[11px] text-muted-foreground">Kaynaklar yükleniyor…</p>;
  }

  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex flex-col gap-1">
        <h4 className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          <Newspaper className="size-3.5" aria-hidden />
          Bu haberi işleyen kaynaklar
          <span className="rounded-full bg-muted px-1.5 text-[10px] tabular-nums">
            {rows.length}
          </span>
        </h4>
        {/* The same sentence the Risk Radarı's chronology carries, for the same
            reason: a vertical list of timestamps reads as the event's own
            timeline unless it says otherwise, and this is publication order. */}
        <p className="text-[11px] leading-relaxed text-muted-foreground">
          Haberlerin yayın sırası ({DISPLAY_TIME_ZONE_TR}) — olayın kendi zaman çizelgesi
          değildir.
        </p>
      </div>

      <ol className="flex flex-col gap-2.5 border-l border-border pl-4">
        {rows.map((row) => (
          <li key={row.url} className="relative flex flex-col gap-1">
            <span
              aria-hidden
              className={cn(
                "absolute -left-[21px] top-1.5 size-1.5 rounded-full",
                row.is_primary ? "bg-primary" : "bg-border",
              )}
            />
            <span className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
              <span className="tabular-nums">{stamp(row.published_at)}</span>
              <span className="rounded-full border border-border px-1.5 py-px text-[10px] font-semibold">
                {sourceTierLabelTr(row.source_tier)}
              </span>
              <span className="font-medium text-foreground">{row.source_name}</span>
              {row.is_primary && (
                <span
                  title="Gazete'nin yayımladığı asıl haber"
                  className="rounded-full bg-muted px-1.5 py-px text-[10px] font-medium"
                >
                  asıl
                </span>
              )}
            </span>
            <a
              href={row.url}
              target="_blank"
              rel="noopener noreferrer"
              className="group flex items-start gap-1.5 text-[13px] leading-snug hover:text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
            >
              <span className="min-w-0 flex-1">{row.title}</span>
              <ExternalLink className="mt-0.5 size-3 shrink-0 text-muted-foreground group-hover:text-primary" />
            </a>
          </li>
        ))}
      </ol>
    </div>
  );
}
