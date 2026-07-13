"use client";

import { Menu, Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, useSyncExternalStore } from "react";

import { ThemeToggle } from "@/components/theme-toggle";
import { Input } from "@/components/ui/input";

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
      {new Date(seconds * 1000).toLocaleTimeString("en-GB", { timeZone: "UTC" })}{" "}
      UTC
    </span>
  );
}

export function Topbar({ onMenuClick }: { onMenuClick: () => void }) {
  const router = useRouter();
  const [query, setQuery] = useState("");

  return (
    <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-border bg-background/80 px-4 backdrop-blur">
      <button
        onClick={onMenuClick}
        aria-label="Open menu"
        className="rounded-md p-2 text-foreground/70 hover:bg-accent md:hidden"
      >
        <Menu className="size-5" />
      </button>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (query.trim()) {
            router.push(`/search?q=${encodeURIComponent(query.trim())}`);
          }
        }}
        className="relative w-full max-w-md"
      >
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search airlines, airports, routes, news…"
          className="pl-9"
        />
      </form>

      <div className="ml-auto flex items-center gap-4 text-xs text-muted-foreground">
        <LiveClock />
        <ThemeToggle />
      </div>
    </header>
  );
}
