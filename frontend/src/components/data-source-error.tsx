"use client";

import { RotateCw, TriangleAlert } from "lucide-react";

import { cn } from "@/lib/utils";

function formatLastUpdated(date: Date): string {
  return date.toLocaleTimeString("tr-TR", {
    timeZone: "UTC",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** The retry control, in both branches.
 *
 * It says which of the two states it is in. A retry that has been clicked and
 * is still waiting used to be indistinguishable from one that was never
 * clicked -- same label, same enabled button, and the error text underneath
 * unchanged -- so the honest reading of the screen was "nothing happened",
 * and the reader clicked again. `pending` comes from useDataSource and is
 * true for exactly as long as a request for this source is actually in
 * flight, so the label is a report, never an animation on a timer. */
function RetryButton({
  onRetry,
  pending,
  className,
  iconClassName,
}: {
  onRetry: () => void;
  pending: boolean;
  className?: string;
  iconClassName?: string;
}) {
  return (
    <button
      type="button"
      onClick={onRetry}
      disabled={pending}
      aria-busy={pending}
      className={cn("flex items-center gap-1.5", className)}
    >
      <RotateCw className={cn(iconClassName, pending && "animate-spin")} aria-hidden />
      {pending ? "Deneniyor…" : "Yeniden dene"}
    </button>
  );
}

/** Faz 12's per-source graceful-degradation UI, paired with useDataSource().
 * `lastUpdated` is the last time THIS source had real data, not "now" --
 * showing a fresh-looking timestamp on a stale or empty section is exactly
 * the kind of thing this phase exists to stop. */
export function DataSourceError({
  onRetry,
  lastUpdated,
  pending = false,
  className,
}: {
  onRetry: () => void;
  lastUpdated: Date | null;
  /** A request for THIS source is in flight (useDataSource's `pending`). */
  pending?: boolean;
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
      <RetryButton
        onRetry={onRetry}
        pending={pending}
        className="mt-1 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-accent disabled:cursor-progress disabled:opacity-70"
        iconClassName="size-3.5"
      />
    </div>
  );
}

/** A small inline banner for the stale case: real (old) data is still on
 * screen, this just says so instead of pretending the refresh succeeded. */
export function StaleDataBanner({
  onRetry,
  lastUpdated,
  pending = false,
}: {
  onRetry: () => void;
  lastUpdated: Date | null;
  /** A request for THIS source is in flight (useDataSource's `pending`). */
  pending?: boolean;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-md bg-warning/10 px-3 py-1.5 text-xs text-warning">
      <span>
        Güncellenemedi{lastUpdated ? ` — son başarılı: ${formatLastUpdated(lastUpdated)} UTC` : ""}.
      </span>
      <RetryButton
        onRetry={onRetry}
        pending={pending}
        className="ml-auto font-medium hover:underline disabled:cursor-progress disabled:opacity-70 disabled:hover:no-underline"
        iconClassName="size-3"
      />
    </div>
  );
}

/** The error branch where a bordered block would not fit: one line, inside a
 * list, a table cell, a drawer section or a filter strip.
 *
 * IT EXISTS BECAUSE THE ALTERNATIVE IS A NUMBER. A section that cannot render
 * `DataSourceError` without pushing the page around used to render nothing --
 * and "nothing" on a counting surface is drawn as `0`, on a list as "kayıt
 * yok", and on a search box as "sonuç yok". All three are claims about the
 * world made out of an HTTP failure. This says the one true thing instead:
 * the source was not read. Amber, with an icon, because it must survive being
 * skimmed -- a grey line the width of a caption is not a signal.
 *
 * `role="status"` rather than `alert`: a source that did not answer is worth
 * announcing once the reader gets there, not worth interrupting them for. */
export function InlineSourceError({
  message = "Okunamadı.",
  onRetry,
  pending = false,
  className,
}: {
  /** What could not be read, in the surface's own words. */
  message?: string;
  /** Omitted where the surface genuinely has no way to re-ask (a server
   * render, a source owned by a parent) -- never omitted to save space. */
  onRetry?: () => void;
  pending?: boolean;
  className?: string;
}) {
  return (
    <p
      role="status"
      className={cn("flex flex-wrap items-center gap-1.5 text-xs text-warning", className)}
    >
      <TriangleAlert className="size-3.5 shrink-0" aria-hidden />
      <span>{message}</span>
      {onRetry && (
        <RetryButton
          onRetry={onRetry}
          pending={pending}
          className="font-medium underline-offset-2 hover:underline disabled:cursor-progress disabled:opacity-70 disabled:hover:no-underline"
          iconClassName="size-3"
        />
      )}
    </p>
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
