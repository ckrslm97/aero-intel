"use client";

import { ChevronFirst, ChevronLast, ChevronLeft, ChevronRight } from "lucide-react";
import { useRef } from "react";

import { cn } from "@/lib/utils";

/** First/Previous/Next/Last with a "Sayfa X / Y" readout, arrow-key and
 * Home/End keyboard navigation, and no URL opinion of its own -- the caller
 * owns the page as a `?page=` search param (Next.js's `useSearchParams`
 * already re-renders on back/forward, so wiring `page` there instead of
 * local state is what makes a paged link shareable and the back button
 * correct; see the Gazete list's usage). `page` is 1-indexed throughout, to
 * match the "Sayfa 3 / 12" reading a person expects, not a zero-based index. */
export function Pagination({
  page,
  totalPages,
  onPageChange,
  className,
}: {
  page: number;
  totalPages: number;
  onPageChange: (page: number) => void;
  className?: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);

  if (totalPages <= 1) return null;

  const atFirst = page <= 1;
  const atLast = page >= totalPages;
  const go = (target: number) => onPageChange(Math.min(totalPages, Math.max(1, target)));

  function handleKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    switch (event.key) {
      case "ArrowLeft":
        event.preventDefault();
        go(page - 1);
        break;
      case "ArrowRight":
        event.preventDefault();
        go(page + 1);
        break;
      case "Home":
        event.preventDefault();
        go(1);
        break;
      case "End":
        event.preventDefault();
        go(totalPages);
        break;
    }
  }

  const buttonClass =
    "flex size-8 items-center justify-center rounded-md border border-border text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:pointer-events-none disabled:opacity-40";

  return (
    <div
      ref={containerRef}
      role="navigation"
      aria-label="Sayfalama"
      tabIndex={0}
      onKeyDown={handleKeyDown}
      className={cn(
        "flex items-center gap-1.5 rounded-lg border border-border bg-card p-1.5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50",
        className,
      )}
    >
      <button
        type="button"
        onClick={() => go(1)}
        disabled={atFirst}
        aria-label="İlk sayfa"
        title="İlk sayfa (Home)"
        className={buttonClass}
      >
        <ChevronFirst className="size-4" />
      </button>
      <button
        type="button"
        onClick={() => go(page - 1)}
        disabled={atFirst}
        aria-label="Önceki sayfa"
        title="Önceki sayfa (←)"
        className={buttonClass}
      >
        <ChevronLeft className="size-4" />
      </button>

      <span className="min-w-[6.5rem] px-2 text-center text-xs font-medium tabular-nums text-foreground">
        Sayfa {page} / {totalPages}
      </span>

      <button
        type="button"
        onClick={() => go(page + 1)}
        disabled={atLast}
        aria-label="Sonraki sayfa"
        title="Sonraki sayfa (→)"
        className={buttonClass}
      >
        <ChevronRight className="size-4" />
      </button>
      <button
        type="button"
        onClick={() => go(totalPages)}
        disabled={atLast}
        aria-label="Son sayfa"
        title="Son sayfa (End)"
        className={buttonClass}
      >
        <ChevronLast className="size-4" />
      </button>
    </div>
  );
}
