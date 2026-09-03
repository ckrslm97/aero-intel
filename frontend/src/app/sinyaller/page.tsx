import { Suspense } from "react";

import { SignalsClient } from "@/components/sinyaller/signals-client";
import { Skeleton } from "@/components/ui/skeleton";

export const metadata = {
  title: "Sinyaller — Erken Uyarı Merkezi",
  description:
    "Kokpit sinyal panosu, kampanya uyarıları, Risk Radarı, rakip ve stratejik olaylar, ağ sinyalleri ve haber momentumu tek listede: şiddete, sonra tazeliğe göre sıralı erken uyarı merkezi.",
};

// SignalsClient keeps ?kind and ?severity in the URL so "şu anda dört kritik
// risk sinyali var" is a link and not a screenshot. useSearchParams opts the
// subtree out of prerendering, so it needs its own Suspense boundary --
// without one the whole route falls back to client-side rendering and the
// first paint goes blank. Same reason app/kampanyalar/page.tsx has one.
export default function SinyallerPage() {
  return (
    <Suspense fallback={<Skeleton className="h-96 w-full rounded-xl" />}>
      <SignalsClient />
    </Suspense>
  );
}
