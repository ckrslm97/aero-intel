"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";

import { ArticleDrawerProvider } from "@/components/article-drawer-context";
import { Sidebar } from "@/components/layout/sidebar";
import { Topbar } from "@/components/layout/topbar";

// The mobile drawer is the only framer-motion user in the shell and is
// md:hidden -- loading it eagerly put ~124KB of animation library in every
// desktop route's baseline for markup that never renders.
const MobileSidebar = dynamic(
  () => import("@/components/layout/sidebar").then((m) => m.MobileSidebar),
  { ssr: false },
);

const COLLAPSE_KEY = "aerointel_sidebar_collapsed";

export function AppShell({ children }: { children: React.ReactNode }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- restoring a persisted UI preference on mount
    setCollapsed(window.localStorage.getItem(COLLAPSE_KEY) === "true");
  }, []);

  function toggleCollapsed() {
    setCollapsed((prev) => {
      const next = !prev;
      window.localStorage.setItem(COLLAPSE_KEY, String(next));
      return next;
    });
  }

  return (
    // ArticleCard opens the analysis drawer instead of navigating away, so the
    // provider lives at the shell: six different pages render article cards
    // (Gazete, edition, Hub'lar, BİZ, Arşiv, Ara) and a per-page wrap would be
    // one missed import away from a dead card. The drawer itself is lazily
    // loaded from inside the provider, so the shell pays nothing until a card
    // is actually clicked.
    <ArticleDrawerProvider>
      <div className="flex min-h-screen bg-background">
        <Sidebar collapsed={collapsed} onToggleCollapsed={toggleCollapsed} />
        <MobileSidebar open={mobileOpen} onClose={() => setMobileOpen(false)} />
        <div className="flex min-w-0 flex-1 flex-col">
          <Topbar onMenuClick={() => setMobileOpen(true)} />
          <main className="flex-1 px-4 py-6 md:px-8 md:py-8">{children}</main>
        </div>
      </div>
    </ArticleDrawerProvider>
  );
}
