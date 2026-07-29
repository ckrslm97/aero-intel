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
  // Sticks once true: the drawer has to stay mounted after the first open so
  // AnimatePresence can play its exit animation on close.
  const [everOpened, setEverOpened] = useState(false);

  const open = useCallback((article: ArticleOut) => {
    setSelected(article);
    setEverOpened(true);
  }, []);
  const close = useCallback(() => setSelected(null), []);

  const value = useMemo(() => ({ selected, open, close }), [selected, open, close]);

  return (
    <ArticleDrawerContext.Provider value={value}>
      {children}
      {everOpened && <ArticleAnalysisDrawer article={selected} onClose={close} />}
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
