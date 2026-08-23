"use client";

import { Lightbulb, Sparkles } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";

import { InsightsClient } from "@/components/insights-client";
import { RecommendationsClient } from "@/components/recommendations-client";
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

/** The two İçgörüler tabs. Each tab renders its own client whole and unedited --
 * Öneriler in particular owns its filters, multi-select state and fetches, and
 * absorbing them here would just be a second copy to keep in sync. */
export function InsightsTabs() {
  // Same idiom as NewspaperBrowser: the URL seeds the opening state so
  // /insights?tab=oneriler deep-links straight to the recommendations, and
  // after that the buttons own the tab -- re-reading the URL would fight them.
  const searchParams = useSearchParams();
  const initialTab = useMemo<TabKey>(() => {
    const wanted = searchParams.get("tab");
    return TABS.some((t) => t.key === wanted) ? (wanted as TabKey) : DEFAULT_TAB;
    // eslint-disable-next-line react-hooks/exhaustive-deps -- deliberately the first URL only
  }, []);

  const [tab, setTab] = useState<TabKey>(initialTab);

  function selectTab(next: TabKey) {
    setTab(next);
    // Keep the address bar addressable (copy the link, hit refresh, land on
    // the same tab) without a router navigation: router.replace would refetch
    // the route and remount both clients, throwing away Öneriler's filters.
    // replaceState rather than pushState -- a tab is not a page, so Back
    // should leave İçgörüler rather than walk the tabs the user clicked.
    const url = new URL(window.location.href);
    if (next === DEFAULT_TAB) {
      url.searchParams.delete("tab");
    } else {
      url.searchParams.set("tab", next);
    }
    window.history.replaceState(null, "", url);
  }

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
