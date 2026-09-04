"use client";

import dynamic from "next/dynamic";
import { createContext, useCallback, useContext, useMemo, useState } from "react";

import type { ArticleOut } from "@/lib/types";

// framer-motion + the drawer markup are only needed once a card is actually
// clicked, so the panel is code-split and mounted lazily. The provider itself
// stays a bare context so wrapping the whole app costs nothing on first paint.
const ArticleAnalysisDrawer = dynamic(
  () => import("@/components/article-analysis-drawer").then((m) => m.ArticleAnalysisDrawer),
  { ssr: false },
);

interface ArticleDrawerValue {
  selected: ArticleOut | null;
  open: (article: ArticleOut) => void;
  close: () => void;
}

const ArticleDrawerContext = createContext<ArticleDrawerValue | null>(null);

export function ArticleDrawerProvider({ children }: { children: React.ReactNode }) {
  const [selected, setSelected] = useState<ArticleOut | null>(null);

  const open = useCallback((article: ArticleOut) => setSelected(article), []);
  const close = useCallback(() => setSelected(null), []);

  const value = useMemo(() => ({ selected, open, close }), [selected, open, close]);

  return (
    <ArticleDrawerContext.Provider value={value}>
      {children}
      {/* `selected && ...` and nothing else. There used to be an `everOpened`
          flag here that stuck true after the first open, keeping the drawer
          mounted forever so `AnimatePresence` could play its exit animation --
          and in this stack that animation never completes, so what actually
          stayed mounted was a full-screen `fixed inset-0` backdrop that
          swallowed every click on the page behind it. Nothing plays an exit
          any more (components/ui/drawer-shell.tsx), so nothing has to outlive
          the selection. */}
      {selected && <ArticleAnalysisDrawer article={selected} onClose={close} />}
    </ArticleDrawerContext.Provider>
  );
}

/** Opens the in-app analysis drawer for an article.
 *
 * Fails soft on purpose: if some future page renders an `ArticleCard` outside
 * the provider, the card falls back to opening the source in a new tab rather
 * than throwing and taking the whole page down.
 */
export function useArticleDrawer(): ArticleDrawerValue {
  const context = useContext(ArticleDrawerContext);
  const fallback = useMemo<ArticleDrawerValue>(
    () => ({
      selected: null,
      open: (article: ArticleOut) => {
        if (typeof window !== "undefined") {
          window.open(article.url, "_blank", "noopener,noreferrer");
        }
      },
      close: () => {},
    }),
    [],
  );
  return context ?? fallback;
}
