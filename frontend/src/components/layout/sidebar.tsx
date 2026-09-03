"use client";

import { AnimatePresence, motion } from "framer-motion";
import { ChevronLeft, ChevronRight, Plane, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { primaryNav } from "@/lib/nav";
import { cn } from "@/lib/utils";

/** The pathname the nav should compare against.
 *
 * Vercel's runtime ISR re-render of `/` serves an RSC payload whose canonical
 * path is "/index" (`"c":["","index"]`), so `usePathname()` returns "/index"
 * on the server for the one route in this app that carries `revalidate`. No
 * nav item matches that, and the Kokpit link prerenders inactive. Measured on
 * production: `grep -c 'ring-primary/25'` returns 0 for `/` and 1 for every
 * other route.
 *
 * Normalising here rather than at each call site: this is the only place that
 * turns a path into a "you are here", and a second copy of the rule is a
 * second chance to forget it.
 */
export function navPathname(pathname: string): string {
  if (pathname === "/index") return "/";
  return pathname;
}

export function NavLinks({
  onNavigate,
  collapsed,
  /** Distinct per mounted nav so the desktop rail and the mobile drawer don't
   * share (and fight over) one shared-element pill. */
}: {
  onNavigate?: () => void;
  collapsed?: boolean;
}) {
  const pathname = navPathname(usePathname());

  const renderItems = (items: typeof primaryNav) =>
    items.map((item) => {
      const active =
        item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
      const Icon = item.icon;
      return (
        <Link
          key={item.href}
          href={item.href}
          onClick={onNavigate}
          title={collapsed ? item.label : undefined}
          className={cn(
            "group relative flex items-center gap-3 overflow-hidden rounded-md px-3 py-2 text-sm font-medium transition-colors",
            collapsed && "justify-center px-0",
            active
              ? "text-sidebar-accent-foreground"
              : "text-sidebar-foreground/70 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
          )}
        >
          {/* ALWAYS MOUNTED, never conditionally rendered -- the marker
              changes CLASSES, not the number of children.
              …
              Measured in production: Vercel's runtime ISR re-render of `/`
              serves an RSC payload whose canonical path is "/index", not "/"
              (`"c":["","index"]`). `usePathname()` therefore returned
              "/index" on the server, no nav item matched, and the Kokpit link
              was prerendered with TWO children -- while the browser, where
              the path really is "/", rendered FOUR. React walks the tree
              expecting a <span> and finds the <svg>, throws #418 and tears
              down the whole <body> to re-render it client-side. Kokpit was
              the only page affected (it is the only route carrying
              `revalidate`), and it looked like every page because the console
              was never cleared across soft navigations.
              `navPathname` above fixes the path; this fixes the CLASS of bug:
              a marker whose presence depends on state the server can get
              wrong must not be able to change the shape of the tree.
              The shared-element `layoutId` slide went with it. It required
              exactly one mounted instance, which is the thing that cannot be
              guaranteed here -- and a pill sliding between menu items is not
              a fact a revenue-management desk acts on. */}
          <span
            aria-hidden
            className={cn(
              "absolute inset-0 rounded-md bg-gradient-to-r from-primary/15 via-primary/8 to-transparent ring-1 ring-primary/25 transition-opacity duration-200",
              active ? "opacity-100" : "opacity-0",
            )}
          />
          <span
            aria-hidden
            className={cn(
              "absolute inset-y-1 left-0 w-0.5 rounded-full bg-gradient-to-b from-primary to-chart-4 transition-opacity duration-200",
              active ? "opacity-100" : "opacity-0",
            )}
          />
          <Icon className="relative z-10 size-4 shrink-0" aria-hidden />
          {/* The label is ALWAYS rendered, and merely hidden visually when the
              rail is collapsed. It used to be dropped from the tree entirely,
              leaving seven icon-only links whose accessible name came from
              `title` -- the last resort of the accname algorithm, which some
              screen readers never reach. These seven are the first seven stops
              of every page's tab order, so that was the whole product's
              keyboard entry point announcing nothing. */}
          <span className={cn("relative z-10 flex-1 truncate", collapsed && "sr-only")}>
            {item.label}
          </span>
        </Link>
      );
    });

  return (
    <nav className="flex flex-1 flex-col gap-6 overflow-y-auto px-3 py-4">
      <div className="flex flex-col gap-1">{renderItems(primaryNav)}</div>
    </nav>
  );
}

function Brand({
  children,
  collapsed,
}: {
  children?: React.ReactNode;
  collapsed?: boolean;
}) {
  return (
    <div
      className={cn(
        "flex h-16 items-center gap-2 border-b border-sidebar-border px-4",
        collapsed && "justify-center px-0",
      )}
    >
      <div className="flex size-8 shrink-0 items-center justify-center rounded-md bg-gradient-to-br from-primary to-chart-4 text-primary-foreground dark:glow">
        <Plane className="size-4" />
      </div>
      {!collapsed && (
        <div className="leading-tight">
          <p className="text-sm font-semibold tracking-tight">AeroIntel</p>
          <p className="text-[11px] text-muted-foreground">
            Havacılık İstihbaratı
          </p>
        </div>
      )}
      {children && <div className="ml-auto">{children}</div>}
    </div>
  );
}

export function Sidebar({
  collapsed,
  onToggleCollapsed,
}: {
  collapsed: boolean;
  onToggleCollapsed: () => void;
}) {
  return (
    <aside
      className={cn(
        "relative hidden shrink-0 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground transition-[width] duration-200 md:flex",
        collapsed ? "w-16" : "w-64",
      )}
    >
      <Brand collapsed={collapsed} />
      <NavLinks collapsed={collapsed} />
      <button
        onClick={onToggleCollapsed}
        aria-label={collapsed ? "Kenar çubuğunu genişlet" : "Kenar çubuğunu daralt"}
        title={collapsed ? "Kenar çubuğunu genişlet" : "Kenar çubuğunu daralt"}
        className="absolute -right-3 top-20 hidden size-6 items-center justify-center rounded-full border border-sidebar-border bg-sidebar text-sidebar-foreground/70 shadow-sm hover:bg-sidebar-accent hover:text-sidebar-accent-foreground md:flex"
      >
        {collapsed ? <ChevronRight className="size-3.5" /> : <ChevronLeft className="size-3.5" />}
      </button>
    </aside>
  );
}

export function MobileSidebar({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            className="fixed inset-0 z-40 bg-black/40 md:hidden"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
          />
          <motion.aside
            className="fixed inset-y-0 left-0 z-50 flex w-72 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground md:hidden"
            initial={{ x: "-100%" }}
            animate={{ x: 0 }}
            exit={{ x: "-100%" }}
            transition={{ type: "spring", stiffness: 320, damping: 32 }}
          >
            <Brand>
              <button
                onClick={onClose}
                aria-label="Menüyü kapat"
                className="rounded-md p-2 text-sidebar-foreground/70 hover:bg-sidebar-accent"
              >
                <X className="size-4" />
              </button>
            </Brand>
            <NavLinks onNavigate={onClose} />
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}
