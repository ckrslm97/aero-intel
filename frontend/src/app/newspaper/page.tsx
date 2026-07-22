import { Suspense } from "react";

import { NewspaperBrowser } from "@/components/newspaper-browser";
import { Skeleton } from "@/components/ui/skeleton";

// NewspaperBrowser reads ?category / ?subcategory / ?region / ?airline off the
// URL so the Know How page (and any shared link) can open the paper already
// filtered. useSearchParams opts the subtree out of prerendering, so it needs
// its own Suspense boundary -- without one the whole route falls back to
// client-side rendering and the first paint goes blank.
export default function NewspaperPage() {
  return (
    <Suspense fallback={<Skeleton className="m-4 h-96 rounded-xl md:m-6" />}>
      <NewspaperBrowser />
    </Suspense>
  );
}
