"use client";

import { ExternalLink, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";

import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch, ApiError } from "@/lib/api";
import type { MarketPulseOut } from "@/lib/types";

/** The daily synthesis over Kokpit's own already-curated numbers -- never a
 * fresh claim of the model's own, see backend/app/services/market_pulse_service.py.
 * A 404 here (no pulse generated yet, or generation hasn't run today) is a
 * quiet empty state, not an error -- the honest "nothing generated" case. */
export function MarketPulseCard() {
  const [pulse, setPulse] = useState<MarketPulseOut | null>(null);
  const [state, setState] = useState<"loading" | "ok" | "empty" | "error">("loading");

  useEffect(() => {
    let cancelled = false;
    apiFetch<MarketPulseOut>("/kokpit/pulse", { cache: "default" })
      .then((data) => {
        if (cancelled) return;
        setPulse(data);
        setState("ok");
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setState(err instanceof ApiError && err.status === 404 ? "empty" : "error");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (state === "loading") {
    return <Skeleton className="h-32 w-full rounded-xl" />;
  }
  if (state === "error") {
    return <p className="text-sm text-muted-foreground">Market Pulse yüklenemedi.</p>;
  }
  if (state === "empty" || !pulse) {
    return (
      <Card className="p-5">
        <div className="flex items-center gap-2">
          <Sparkles className="size-4 text-muted-foreground" />
          <h2 className="text-sm font-semibold">Market Pulse</h2>
        </div>
        <p className="mt-2 text-sm text-muted-foreground">
          Henüz oluşturulmuş bir Market Pulse yok.
        </p>
      </Card>
    );
  }

  return (
    <Card
      style={{ "--glow-color": "var(--signal)" } as React.CSSProperties}
      className="p-5"
    >
      <div className="flex items-center gap-2">
        <Sparkles className="size-4 text-signal" />
        <h2 className="text-sm font-semibold">Market Pulse</h2>
        <span className="ml-auto text-[10px] text-muted-foreground">
          {new Date(pulse.generated_at).toLocaleString("tr-TR", {
            timeZone: "UTC",
            dateStyle: "medium",
            timeStyle: "short",
          })}{" "}
          UTC
        </span>
      </div>
      <p className="mt-2 text-sm leading-relaxed text-foreground">{pulse.summary_tr}</p>
      {pulse.citations.length > 0 && (
        <ul className="mt-3 flex flex-col gap-1 border-t border-border pt-3">
          {pulse.citations.map((citation, i) => (
            <li key={i} className="text-xs text-muted-foreground">
              <a
                href={citation.source_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 hover:text-primary hover:underline"
              >
                {citation.claim} — {citation.source}
                <ExternalLink className="size-3" />
              </a>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
