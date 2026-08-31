"use client";

import { GraduationCap, Menu } from "lucide-react";
import Link from "next/link";
import { useSyncExternalStore } from "react";

import { QuickSearch } from "@/components/layout/quick-search";
import { ThemeToggle } from "@/components/theme-toggle";
import { formatLocalClock, LOCAL_CITY_TR, LOCAL_TIME_ZONE } from "@/lib/clock";

function subscribeToClock(callback: () => void) {
  const id = setInterval(callback, 1000);
  return () => clearInterval(id);
}

function getClockSeconds() {
  return Math.floor(Date.now() / 1000);
}

/** Instrument-panel styling: a static amber pilot lamp beside the readout.
 * Deliberately not blinking -- the clock's digits are the only thing on this
 * page that is allowed to keep changing. */
function ClockDot() {
  return (
    <span
      aria-hidden
      style={{ "--glow-color": "var(--signal)" } as React.CSSProperties}
      className="size-1.5 shrink-0 rounded-full bg-signal dark:glow"
    />
  );
}

/** The desk's own wall clock: İstanbul, live to the second, dated, with its
 * offset stated.
 *
 * It used to read UTC, which is the timezone every stored timestamp is in and
 * the one nobody on this desk works in -- a reader comparing "son güncelleme
 * 14:20" against a header saying 11:20 was doing arithmetic the header should
 * have done. It now shows local time and says which local time it is, so the
 * number is directly usable and cannot be mistaken for UTC.
 *
 * Deliberately ONE clock. A row of world clocks was considered and dropped:
 * this sits on every page of the app, and four cities' worth of digits at the
 * top of every screen is clutter charged to every reader for a question a few
 * of them ask occasionally.
 *
 * `useSyncExternalStore` rather than an effect: the server snapshot is 0, so
 * the first client paint matches the server's markup exactly and there is no
 * hydration mismatch to suppress -- the digits appear on the tick after
 * mount, not during it.
 */
function LiveClock() {
  const seconds = useSyncExternalStore(subscribeToClock, getClockSeconds, () => 0);
  const clock = formatLocalClock(seconds === 0 ? null : new Date(seconds * 1000));

  return (
    <span className="flex items-center gap-2">
      <span className="flex items-center gap-1.5 font-medium text-signal">
        <ClockDot />
        {/* The city label is the first thing to go on a narrow viewport: the
            search box shares this row and a phone has no width to spare. The
            reading itself never goes -- and the zone is still announced, from
            the sr-only line below. */}
        <span className="hidden sm:inline">{LOCAL_CITY_TR}</span>
        <span className="tabular-nums">{clock.time}</span>
      </span>
      {/* The date and the offset are reference, not readout: quieter, and the
          first to go when the viewport cannot carry the whole line. */}
      <span className="hidden items-center gap-1.5 text-muted-foreground sm:flex">
        <span aria-hidden className="h-3 w-px bg-border" />
        <span className="tabular-nums">{clock.date}</span>
        <span className="tabular-nums">{clock.offset}</span>
      </span>
      <span className="sr-only">{LOCAL_TIME_ZONE}</span>
    </span>
  );
}

export function Topbar({ onMenuClick }: { onMenuClick: () => void }) {
  return (
    <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-border bg-background/80 px-4 backdrop-blur">
      {/* Static approach-light rail along the bottom edge of the chrome. */}
      <span
        aria-hidden
        className="hairline-glow pointer-events-none absolute inset-x-0 bottom-0"
      />
      <button
        onClick={onMenuClick}
        aria-label="Menüyü aç"
        className="rounded-md p-2 text-foreground/70 hover:bg-accent md:hidden"
      >
        <Menu className="size-5" />
      </button>

      <QuickSearch />

      <div className="ml-auto flex items-center gap-4 text-xs text-muted-foreground">
        <LiveClock />
        {/* Know How stays a real route (Faz 11: six-page nav) -- just off the
            primary sidebar, reached from here instead. */}
        <Link
          href="/know-how"
          title="Know How"
          aria-label="Know How"
          className="rounded-md p-1.5 text-foreground/70 transition-colors hover:bg-accent hover:text-foreground"
        >
          <GraduationCap className="size-4" />
        </Link>
        <ThemeToggle />
      </div>
    </header>
  );
}
