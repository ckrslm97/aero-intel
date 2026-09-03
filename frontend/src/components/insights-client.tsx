"use client";

import { ArrowRight, Lightbulb, Route } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api";
import type { InsightsOut } from "@/lib/types";

/** Where new-route announcements live now. Both params are URL-owned by
 * HubsClient, so this is a real deep link and not just a route: the reader
 * lands on the Ağ Sinyalleri tab itself rather than on the hub map with a tab
 * still to find. */
const NETWORK_SIGNALS_HREF = "/hublar?view=network-signals";

/**
 * İÇGÖRÜLER → Örüntüler.
 *
 * WHAT WAS REMOVED, AND WHY. This tab used to open on a new-route signal
 * ledger: a map, four stat tiles, three chip rows and a per-carrier card
 * ledger, all built from `/insights`'s `new_route_signals`. That block counted
 * one signal per ARTICLE, while the Hub page's Ağ Sinyalleri tab counted the
 * same announcements per EVENT -- so a launch three outlets ran was three
 * signals here and one there, and the two pages published two different sizes
 * for the same competitor activity. The backend now publishes the count in
 * exactly one place (app/services/network_signals_service.py) and `/insights`
 * carries no `new_route_signals` key at all.
 *
 * The ledger is therefore not re-pointed at the v2 endpoint here -- that would
 * put the same instrument on two pages and hand a reader two places to look
 * for one answer. It is a signpost instead: the Hub page owns new routes,
 * whole, and this tab says so out loud rather than going quietly empty. A
 * section that vanishes without explanation reads as a broken build; one that
 * names where its content went is a navigation aid.
 *
 * WHAT IS LEFT is the digest -- the one thing on this tab that was never about
 * routes. `airline_momentum` and `sentiment_by_category` are still in the
 * payload and still drawn where they already had a home (Kokpit's
 * competitive-pulse.tsx reads the momentum); nothing here re-draws them.
 */
export function InsightsClient() {
  const [data, setData] = useState<InsightsOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiFetch<InsightsOut>("/insights", { cache: "default" })
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch(() => {
        if (!cancelled) setError("İçgörüler yüklenemedi. Sunucu çalışıyor mu?");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return (
      <p className="rounded-lg border border-dashed border-border p-6 text-sm text-muted-foreground">
        {error}
      </p>
    );
  }
  if (!data) {
    return (
      <div className="flex flex-col gap-6">
        <Skeleton className="h-28 w-full rounded-xl" />
        <Skeleton className="h-32 w-full rounded-xl" />
      </div>
    );
  }

  /** Each card carries its lead color as its edge light. */
  const glow = (token: string) => ({ "--glow-color": token }) as React.CSSProperties;

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">İçgörüler</h1>
        <p className="text-sm leading-relaxed text-muted-foreground">
          Haber arşivinden otomatik çıkarılan örüntüler — her sayı veritabanındaki
          satırlara kadar izlenebilir.
        </p>
      </div>

      {data.digest ? (
        <div
          style={glow("var(--category-revenue-management)")}
          className="border-gradient flex flex-col gap-2 rounded-xl p-5 shadow-elev-1"
        >
          <div className="flex items-center gap-2">
            <Lightbulb className="size-4 text-category-revenue-management" />
            <h2 className="text-sm font-semibold">Günün Örüntüsü</h2>
            <span className="rounded-full bg-secondary px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-secondary-foreground">
              {data.digest.provider === "openai_compat" ? "AI özeti" : "otomatik özet"}
            </span>
            <span className="text-[10px] text-muted-foreground">{data.digest.date}</span>
          </div>
          <p className="text-sm leading-relaxed text-muted-foreground">{data.digest.body}</p>
        </div>
      ) : (
        // Said out loud rather than left as a gap: the digest is assembled by a
        // cron job, and "henüz derlenmedi" is a different fact from "bugün
        // örüntü yok".
        <p className="rounded-xl border border-dashed border-border p-5 text-sm text-muted-foreground">
          Günün örüntü özeti henüz derlenmedi.
        </p>
      )}

      {/* The signpost. Not a teaser and not a count: this page no longer has a
          new-route number of its own, and printing one here from a second
          fetch would recreate exactly the two-answers problem the backend
          just closed. */}
      <Link
        href={NETWORK_SIGNALS_HREF}
        className="group flex flex-col gap-2 rounded-xl border border-border bg-card bg-card-sheen p-5 shadow-elev-1 transition-colors hover:border-primary/50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
      >
        <span className="flex items-center gap-2 text-sm font-semibold">
          <Route className="size-4 text-muted-foreground" aria-hidden />
          Yeni hat sinyalleri Hub sayfasına taşındı
          <ArrowRight
            className="size-3.5 text-muted-foreground transition-transform group-hover:translate-x-0.5 motion-reduce:transition-none"
            aria-hidden
          />
        </span>
        <span className="text-sm leading-relaxed text-muted-foreground">
          Rakiplerin yeni hat duyuruları artık tek yerde sayılıyor:{" "}
          <span className="font-medium text-foreground">Hub → Ağ Sinyalleri</span>. Orada
          her duyuru bir olaydır, aynı haberi üç kaynak yazdığında üç sinyal
          görünmez — bu sayfadaki eski liste haber başına sayıyordu ve iki ekran
          aynı hareket için iki farklı sayı yazıyordu.
        </span>
      </Link>
    </div>
  );
}
