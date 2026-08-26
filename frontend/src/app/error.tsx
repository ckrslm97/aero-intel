"use client";

import { RotateCw, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useEffect } from "react";

// Faz 12: a rendering error anywhere in a page previously showed nothing
// styled at all -- Next's own default error screen. This is the route-level
// boundary (per-page, not the whole app) so one broken section doesn't take
// the sidebar and nav down with it.
export default function ErrorBoundary({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  // No error-tracking service is wired up yet -- this is the same visibility
  // a server-side exception already gets, not a new integration.
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-5 text-center">
      <span
        aria-hidden
        style={{ "--glow-color": "var(--critical)" } as React.CSSProperties}
        className="flex size-16 items-center justify-center rounded-full bg-critical/10 text-critical ring-1 ring-critical/20 dark:glow"
      >
        <TriangleAlert className="size-8" />
      </span>
      <div className="flex flex-col gap-1.5">
        <h1 className="text-2xl font-semibold tracking-tight">Bir şeyler ters gitti</h1>
        <p className="max-w-sm text-sm leading-relaxed text-muted-foreground">
          Bu sayfa render edilirken beklenmeyen bir hata oluştu. Yeniden deneyin; devam
          ederse birkaç dakika sonra tekrar bakın.
        </p>
      </div>
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={reset}
          className="flex items-center gap-1.5 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
        >
          <RotateCw className="size-4" />
          Yeniden dene
        </button>
        <Link
          href="/"
          className="rounded-md border border-border px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-accent"
        >
          Kokpit&apos;e dön
        </Link>
      </div>
    </div>
  );
}
