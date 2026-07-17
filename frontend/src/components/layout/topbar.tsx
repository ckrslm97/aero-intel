"use client";

import { Menu } from "lucide-react";
import { useSyncExternalStore } from "react";

import { QuickSearch } from "@/components/layout/quick-search";
import { ThemeToggle } from "@/components/theme-toggle";

function subscribeToClock(callback: () => void) {
  const id = setInterval(callback, 1000);
  return () => clearInterval(id);
}

function getClockSeconds() {
  return Math.floor(Date.now() / 1000);
}

function LiveClock() {
  const seconds = useSyncExternalStore(subscribeToClock, getClockSeconds, () => 0);

  if (seconds === 0) return <span className="tabular-nums">--:--:-- UTC</span>;

  return (
    <span className="tabular-nums">
      {new Date(seconds * 1000).toLocaleTimeString("tr-TR", { timeZone: "UTC" })}{" "}
      UTC
    </span>
  );
}

export function Topbar({ onMenuClick }: { onMenuClick: () => void }) {
  return (
    <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-border bg-background/80 px-4 backdrop-blur">
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
        <ThemeToggle />
      </div>
    </header>
  );
}
