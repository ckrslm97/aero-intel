"use client";

import { RotateCw } from "lucide-react";

import { cn } from "@/lib/utils";

function formatLastUpdated(date: Date): string {
  return date.toLocaleTimeString("tr-TR", {
    timeZone: "UTC",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Faz 12's per-source graceful-degradation UI, paired with useDataSource().
 * `lastUpdated` is the last time THIS source had real data, not "now" --
 * showing a fresh-looking timestamp on a stale or empty section is exactly
 * the kind of thing this phase exists to stop. */
export function DataSourceError({
  onRetry,
  lastUpdated,
  className,
}: {
  onRetry: () => void;
  lastUpdated: Date | null;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center gap-2 rounded-lg border border-dashed border-border p-6 text-center",
        className,
      )}
    >
      <p className="text-sm text-muted-foreground">Veri geçici olarak kullanılamıyor.</p>
      {lastUpdated && (
        <p className="text-xs text-muted-foreground">
          Son başarılı güncelleme: {formatLastUpdated(lastUpdated)} UTC
        </p>
      )}
      <button
        type="button"
        onClick={onRetry}
        className="mt-1 flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-accent"
      >
        <RotateCw className="size-3.5" />
        Yeniden dene
      </button>
    </div>
  );
}

/** A small inline banner for the stale case: real (old) data is still on
 * screen, this just says so instead of pretending the refresh succeeded. */
export function StaleDataBanner({
  onRetry,
  lastUpdated,
}: {
  onRetry: () => void;
  lastUpdated: Date | null;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-md bg-warning/10 px-3 py-1.5 text-xs text-warning">
      <span>
        Güncellenemedi{lastUpdated ? ` — son başarılı: ${formatLastUpdated(lastUpdated)} UTC` : ""}.
      </span>
      <button
        type="button"
        onClick={onRetry}
        className="ml-auto flex items-center gap-1 font-medium hover:underline"
      >
        <RotateCw className="size-3" />
        Yeniden dene
      </button>
    </div>
  );
}

/** LastUpdated stamp for a card footer -- Faz 12: "her kartta son güncelleme". */
export function LastUpdatedStamp({ date, className }: { date: Date | null; className?: string }) {
  if (!date) return null;
  return (
    <p className={cn("text-[11px] text-muted-foreground", className)}>
      Son güncelleme: {formatLastUpdated(date)} UTC
    </p>
  );
}
