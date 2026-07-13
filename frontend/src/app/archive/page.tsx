import Link from "next/link";
import { Download, Newspaper } from "lucide-react";

import { ComingSoon } from "@/components/coming-soon";
import { Badge } from "@/components/ui/badge";
import { API_BASE_URL, apiFetch } from "@/lib/api";
import type { EditionSummaryOut } from "@/lib/types";

export default async function ArchivePage() {
  let editions: EditionSummaryOut[] = [];
  try {
    editions = await apiFetch<EditionSummaryOut[]>("/editions");
  } catch {
    // backend unreachable -- fall through to empty state below
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">Historical archive</h1>
        <p className="text-sm text-muted-foreground">Browse every past daily edition.</p>
      </div>

      {editions.length === 0 ? (
        <ComingSoon
          icon={Newspaper}
          title="No editions yet"
          description="Editions appear here once the daily newspaper has been assembled at least once."
        />
      ) : (
        <ul className="flex flex-col divide-y divide-border rounded-xl border border-border bg-card">
          {editions.map((edition) => (
            <li key={edition.id} className="flex items-center justify-between gap-4 p-4">
              <Link
                href={`/newspaper/${edition.edition_date}`}
                className="flex min-w-0 flex-1 flex-col gap-1 hover:text-primary"
              >
                <div className="flex items-center gap-2">
                  <span className="text-xs font-medium text-muted-foreground">
                    {new Date(edition.edition_date).toLocaleDateString("en-GB", {
                      weekday: "short",
                      year: "numeric",
                      month: "short",
                      day: "numeric",
                    })}
                  </span>
                  <Badge variant="secondary" className="text-[10px] uppercase">
                    {edition.story_count} stories
                  </Badge>
                </div>
                <span className="truncate text-sm font-medium text-card-foreground">
                  {edition.headline}
                </span>
              </Link>
              {edition.pdf_available && (
                <a
                  href={`${API_BASE_URL}/editions/${edition.edition_date}/pdf`}
                  title="Download PDF"
                  className="flex shrink-0 items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs font-medium text-foreground hover:bg-accent"
                >
                  <Download className="size-3.5" />
                </a>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
