import { Suspense } from "react";

import { ArchiveClient } from "@/components/archive-client";
import { Skeleton } from "@/components/ui/skeleton";

export const metadata = {
  title: "Arşiv",
};

// ArchiveClient keeps ?category and ?date in the URL: Gazete's "Arşivde tümü"
// link deep-links a beat here, and a narrowed archive is a link worth sending.
// useSearchParams opts the subtree out of prerendering, so it needs its own
// Suspense boundary -- without one the whole route falls back to client-side
// rendering and the first paint goes blank. Same reason
// app/kampanyalar/page.tsx has one.
export default function ArchivePage() {
  return (
    <Suspense fallback={<Skeleton className="h-96 w-full rounded-xl" />}>
      <ArchiveClient />
    </Suspense>
  );
}
