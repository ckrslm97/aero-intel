"use client";

import { ExternalLink, Newspaper } from "lucide-react";
import { useEffect, useState } from "react";

import { apiFetch } from "@/lib/api";
import { sourceTierLabelTr } from "@/lib/gazete";
import type { ArticleSourceOut } from "@/lib/types";
import { cn } from "@/lib/utils";

const STAMP = new Intl.DateTimeFormat("tr-TR", {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});

function stamp(iso: string | null): string {
  if (!iso) return "Tarih yok";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "Tarih yok" : STAMP.format(date);
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
 * is already on screen, and the corroboration is an elaboration on it.
 */
export function ArticleSourcesList({ articleId }: { articleId: string }) {
  /** Keyed by article id rather than cleared on change: a synchronous reset in
   * an effect body is a cascading render (and a lint error), and keying makes
   * "could this be another article's sources" unaskable. */
  const [loaded, setLoaded] = useState<{ id: string; rows: ArticleSourceOut[] } | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    apiFetch<ArticleSourceOut[]>(`/articles/${articleId}/sources`, { cache: "default" })
      .then((rows) => {
        if (!cancelled) setLoaded({ id: articleId, rows });
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [articleId]);

  const rows = loaded?.id === articleId ? loaded.rows : null;

  if (failed) {
    return (
      <p className="text-[11px] text-muted-foreground">Kaynak listesi yüklenemedi.</p>
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
          Haberlerin yayın sırası — olayın kendi zaman çizelgesi değildir.
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
