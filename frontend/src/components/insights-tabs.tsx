"use client";

import { Lightbulb, Sparkles } from "lucide-react";
import { useCallback } from "react";

import { InsightsClient } from "@/components/insights-client";
import { RecommendationsClient } from "@/components/recommendations-client";
import { readEnum, useUrlState, writeParam } from "@/hooks/use-url-state";
import { cn } from "@/lib/utils";

/** The two lenses on the same question -- "what does the data say". Örüntüler
 * is what the archive shows on its own; Öneriler is what to do about it. They
 * used to be two sidebar entries; they are one destination with two tabs now. */
const TABS = [
  { key: "oruntuler", label: "Örüntüler", icon: Lightbulb },
  { key: "oneriler", label: "Öneriler", icon: Sparkles },
] as const;

type TabKey = (typeof TABS)[number]["key"];

const DEFAULT_TAB: TabKey = "oruntuler";

const TAB_KEYS = TABS.map((t) => t.key) as readonly TabKey[];

/** The two İçgörüler tabs. Each tab renders its own client whole and unedited --
 * Öneriler in particular owns its filters, multi-select state and fetches, and
 * absorbing them here would just be a second copy to keep in sync. */
export function InsightsTabs() {
  // THE URL OWNS THE TAB, continuously -- it does not merely seed it.
  //
  // This used to hold the tab in state and write `?tab=` with
  // `window.history.replaceState`, on the reasoning that a router navigation
  // would remount both clients and throw away Öneriler's filters. Öneriler's
  // filters are in the URL now (lib/recommendations.ts), so there is nothing
  // left to throw away -- and the old trick had a cost that outlived its
  // reason: `history.replaceState` is invisible to `useSearchParams`, so the
  // moment Öneriler wrote a filter it serialised onto params that had never
  // heard of `?tab=oneriler` and silently dropped the reader's tab out of the
  // link. One writer per address bar, and it is the router.
  const { params, replaceParams } = useUrlState();
  const tab = readEnum(params, "tab", TAB_KEYS, DEFAULT_TAB);

  const selectTab = useCallback(
    (next: TabKey) => {
      const updated = new URLSearchParams(params.toString());
      writeParam(updated, "tab", next === DEFAULT_TAB ? null : next);
      replaceParams(updated);
    },
    [params, replaceParams],
  );

  return (
    <div className="flex flex-col gap-6">
      {/* The same segmented switch as Gazete's Haberler | Takvim -- one border,
          a filled pill on the active side. */}
      <div
        role="tablist"
        aria-label="İçgörüler görünümü"
        className="flex items-center gap-1 self-start rounded-lg border border-border p-0.5"
      >
        {TABS.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            id={`insights-tab-${key}`}
            role="tab"
            aria-selected={tab === key}
            aria-controls="insights-tabpanel"
            onClick={() => selectTab(key)}
            className={cn(
              "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
              tab === key
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:bg-accent",
            )}
          >
            <Icon className="size-3.5" />
            {label}
          </button>
        ))}
      </div>

      <div id="insights-tabpanel" role="tabpanel" aria-labelledby={`insights-tab-${tab}`}>
        {tab === "oneriler" ? <RecommendationsClient /> : <InsightsClient />}
      </div>
    </div>
  );
}
