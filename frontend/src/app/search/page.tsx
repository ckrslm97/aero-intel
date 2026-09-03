import { Suspense } from "react";

import { SearchClient } from "@/components/search-client";
import { Skeleton } from "@/components/ui/skeleton";

export const metadata = {
  title: "Ara",
  description: "Doğrulanmış tüm haberlerde tam metin arama.",
};

// SearchClient owns ?q, ?category and ?window in the URL -- the query used to
// arrive that way and never went back, so a search anyone would want to send
// was the one thing that could not be sent. useSearchParams opts the subtree
// out of prerendering, so it needs its own Suspense boundary -- without one
// the whole route falls back to client-side rendering and the first paint goes
// blank. Same reason app/kampanyalar/page.tsx has one.
export default function SearchPage() {
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">Ara</h1>
        <p className="text-sm text-muted-foreground">
          Doğrulanmış tüm haberlerde tam metin arama.
        </p>
      </div>
      <Suspense fallback={<Skeleton className="h-96 w-full rounded-xl" />}>
        <SearchClient />
      </Suspense>
    </div>
  );
}
