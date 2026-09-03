"use client";

import { useEffect, useState } from "react";

import { apiFetch } from "@/lib/api";
import { formatDayTr } from "@/lib/format";
import type { InsightsOut } from "@/lib/types";

/** How much of the digest the paper prints. */
const MAX_SENTENCES = 3;

/** The first `max` sentences of a body of prose.
 *
 * The stored digest is a paragraph written for the İçgörüler page, where it
 * has a card to itself; at the top of the paper it is a standfirst, and a
 * standfirst is two or three sentences. Trimming rather than reflowing keeps
 * this honest -- every word printed is a word the generator wrote, in its
 * order, and the reader can open İçgörüler for the rest.
 *
 * A period is only a full stop when whitespace (or the end of the text)
 * follows it: "10 üzerinden 5.7" and "1. çeyrek" are one sentence, not three.
 * A trailing fragment with no terminator at all is kept rather than dropped --
 * a generator that ends without punctuation still said something.
 */
export function firstSentences(text: string, max: number = MAX_SENTENCES): string {
  const sentences: string[] = [];
  let start = 0;
  for (let index = 0; index < text.length && sentences.length < max; index += 1) {
    if (!".!?".includes(text[index])) continue;
    // Absorb a run of terminators ("...", "?!") so it stays one boundary.
    let end = index;
    while (end + 1 < text.length && ".!?".includes(text[end + 1])) end += 1;
    const next = text[end + 1];
    if (next !== undefined && !/\s/.test(next)) {
      index = end;
      continue;
    }
    sentences.push(text.slice(start, end + 1).trim());
    start = end + 1;
    index = end;
  }
  if (sentences.length < max && start < text.length) {
    const tail = text.slice(start).trim();
    if (tail) sentences.push(tail);
  }
  return sentences.join(" ").trim();
}

/** Where the sentences came from, in the reader's words rather than the
 * column's. `provider` is a backend enum: "openai_compat" when a model wrote
 * the paragraph, "heuristic" when the deterministic fallback did (see
 * backend/app/services/insights_service.py `_fallback_digest`). The two are
 * not the same claim and the label must not blur them. */
function providerLabel(provider: string): string {
  return provider === "heuristic" ? "Kural tabanlı özet" : "Yapay zekâ özeti";
}

/** The digest's day, in the zone the rest of the paper prints in. Built here
 * with no `timeZone`, this line could name a different day from the article
 * stamps directly beneath it. */

/** "Today's Intelligence" -- two or three sentences about the shape of the
 * day, above the sections.
 *
 * RENDERS NOTHING WHEN THERE IS NO DIGEST, and that is the important part of
 * this component. The `daily` digest row is written by a scheduled job; a
 * fresh database, a local checkout or a morning before the job has run all
 * legitimately have none. A framed box saying "özet bulunamadı" would put an
 * error where the paper's first sentence belongs, on a page that is working
 * perfectly. No digest, no block.
 *
 * It is also deliberately not an editorial: three sentences, trimmed, with the
 * generator named. The long "executive summary" belongs to the per-date
 * edition page, which is where a reader who wants one goes.
 */
export function TodayIntelligence() {
  const [digest, setDigest] = useState<InsightsOut["digest"]>(null);

  useEffect(() => {
    const controller = new AbortController();
    apiFetch<InsightsOut>("/insights", { cache: "default", signal: controller.signal })
      .then((data) => setDigest(data.digest))
      .catch(() => {
        /* the standfirst is an addition to the paper, never a precondition */
      });
    return () => controller.abort();
  }, []);

  if (!digest) return null;
  const body = firstSentences(digest.body);
  if (!body) return null;

  // The digest's own day. `formatDayTr` carries the midday anchor that used to
  // be open-coded here, so the label cannot slide onto the previous day.
  const dayLabel = formatDayTr(digest.date);

  return (
    <section aria-label="Today's Intelligence" className="flex flex-col gap-2">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        {/* Already uppercase in the source, not lowercase under
            `text-transform: uppercase`. The document is lang="tr", and Turkish
            casing maps "i" to "İ" -- so the CSS transform rendered this
            English heading as "TODAY'S INTELLİGENCE". Same reason the two
            event blocks below pass pre-uppercased titles. */}
        <h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
          TODAY&rsquo;S INTELLIGENCE
        </h2>
        <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
          {providerLabel(digest.provider)}
        </span>
        <span className="text-[10px] tabular-nums text-muted-foreground">
          {dayLabel ?? digest.date}
        </span>
      </div>
      {/* Typography carries this, not a card: it is the paper's opening
          paragraph, so it is set larger than the body and given no box. */}
      <p className="max-w-3xl text-pretty text-[17px] leading-relaxed text-foreground sm:text-lg">
        {body}
      </p>
    </section>
  );
}
