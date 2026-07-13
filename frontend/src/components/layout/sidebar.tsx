"use client";

import { AnimatePresence, motion } from "framer-motion";
import { LogIn, Plane, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { useAuth } from "@/components/auth-provider";
import { primaryNav, secondaryNav } from "@/lib/nav";
import { cn } from "@/lib/utils";

function AccountStatus() {
  const { user, loading } = useAuth();

  if (loading) return null;

  if (!user) {
    return (
      <Link
        href="/login"
        className="flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium text-sidebar-foreground/70 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
      >
        <LogIn className="size-4 shrink-0" />
        Sign in
      </Link>
    );
  }

  return (
    <div className="flex items-center gap-3 rounded-md px-3 py-2 text-sm">
      <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">
        {user.email[0].toUpperCase()}
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-xs font-medium text-sidebar-foreground">{user.email}</p>
        <p className="text-[10px] uppercase tracking-wide text-muted-foreground">{user.role}</p>
      </div>
    </div>
  );
}

function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();

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
          className={cn(
            "group flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
            active
              ? "bg-sidebar-accent text-sidebar-accent-foreground"
              : "text-sidebar-foreground/70 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
          )}
        >
          <Icon className="size-4 shrink-0" />
          <span className="flex-1 truncate">{item.label}</span>
          {item.scaffold && (
            <span className="rounded-full border border-sidebar-border px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">
              soon
            </span>
          )}
        </Link>
      );
    });

  return (
    <nav className="flex flex-1 flex-col gap-6 overflow-y-auto px-3 py-4">
      <div className="flex flex-col gap-1">{renderItems(primaryNav)}</div>
      <div className="mt-auto flex flex-col gap-1 border-t border-sidebar-border pt-4">
        {renderItems(secondaryNav)}
        <AccountStatus />
      </div>
    </nav>
  );
}

function Brand({ children }: { children?: React.ReactNode }) {
  return (
    <div className="flex h-16 items-center gap-2 border-b border-sidebar-border px-4">
      <div className="flex size-8 items-center justify-center rounded-md bg-primary text-primary-foreground">
        <Plane className="size-4" />
      </div>
      <div className="leading-tight">
        <p className="text-sm font-semibold tracking-tight">AeroIntel</p>
        <p className="text-[11px] text-muted-foreground">
          Aviation Intelligence
        </p>
      </div>
      {children && <div className="ml-auto">{children}</div>}
    </div>
  );
}

export function Sidebar() {
  return (
    <aside className="hidden w-64 shrink-0 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground md:flex">
      <Brand />
      <NavLinks />
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
                aria-label="Close menu"
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
