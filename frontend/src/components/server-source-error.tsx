"use client";

import { useRouter } from "next/navigation";
import { useTransition } from "react";

import { InlineSourceError } from "@/components/data-source-error";

/** The error branch for a source fetched on the SERVER.
 *
 * Kokpit is rendered on the server (app/page.tsx), so there is no
 * `useDataSource` to hold this page's sections and no per-source `retry()` to
 * call: the request that failed was made during the render itself. What there
 * IS, is `router.refresh()` -- re-running that render against the same URL,
 * which re-issues exactly the fetches that failed. So the reader gets the same
 * two things a client-side source gives them: the sentence that says the
 * source was not read, and a control that asks again.
 *
 * `useTransition`'s `isPending` is the honest in-flight flag: it stays true
 * for as long as the refresh is actually running, so the button reports
 * "Deneniyor…" rather than flashing and leaving a reader who saw nothing
 * change to conclude the click did nothing. Same reasoning as `RetryButton`'s
 * `pending` in data-source-error.tsx.
 *
 * The whole page refreshes, not one section -- a server render is indivisible.
 * That is why the label names the source: after the refresh the reader can see
 * whether THIS line is still there.
 */
export function ServerSourceError({
  /** The sources this section wanted, named as the reader would name them. */
  sources,
  className,
}: {
  sources: readonly string[];
  className?: string;
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  if (sources.length === 0) return null;

  return (
    <InlineSourceError
      // Listed, not counted: "2 kaynak okunamadı" tells a reader that
      // something is missing without telling them WHAT, which on a page of six
      // sections is the same as telling them nothing.
      message={`Okunamadı: ${sources.join(", ")}. Bu bölümdeki sayılar eksik olabilir.`}
      onRetry={() => startTransition(() => router.refresh())}
      pending={pending}
      className={className}
    />
  );
}
