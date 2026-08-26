"use client";

import {
  AlertTriangle,
  ArrowUpRight,
  Building2,
  CircleAlert,
  Info,
  Route,
  Swords,
  TriangleAlert,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { AirlineLogo } from "@/components/airline-logo";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api";
import { worldRegions } from "@/lib/nav";
import type { BizOverviewOut } from "@/lib/types";
import { cn } from "@/lib/utils";

const REGION_NAME: Record<string, string> = Object.fromEntries(
  worldRegions.map((r) => [r.slug, r.name]),
);

const SEVERITY_META = {
  high: { label: "Yüksek", icon: TriangleAlert, className: "bg-critical/10 text-critical" },
  medium: { label: "Orta", icon: CircleAlert, className: "bg-warning/10 text-warning" },
  low: { label: "Düşük", icon: Info, className: "bg-muted text-muted-foreground" },
} as const;

const card = "rounded-xl border border-border bg-card bg-card-sheen p-5 shadow-elev-1";

/** The structural no-filler rule made visible: an unavailable section states
 * the fact plainly instead of rendering an empty grid or, worse, nothing at
 * all -- see backend/app/services/biz_service.py's `_section()`. */
function EmptyState({ message }: { message: string }) {
  return (
    <p className="rounded-xl border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
      {message}
    </p>
  );
}

function SectionHeading({
  icon: Icon,
  title,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
}) {
  return (
    <h2 className="flex items-center gap-2 text-sm font-semibold">
      <Icon className="size-4 text-muted-foreground" />
      {title}
    </h2>
  );
}

function CompetitorSignals({ section }: { section: BizOverviewOut["competitor_signals"] }) {
  return (
    <div className={cn(card, "flex flex-col gap-3")}>
      <SectionHeading icon={Swords} title="Rakip Sinyalleri" />
      {!section.available ? (
        <EmptyState message={section.empty_message ?? ""} />
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {section.items.map((rival) => (
            <div key={rival.airline_code} className="flex flex-col gap-2 rounded-lg border border-border p-3">
              <div className="flex items-center gap-2">
                <AirlineLogo code={rival.airline_code} name={rival.airline_name} className="size-4" />
                <span className="text-sm font-medium">{rival.airline_name}</span>
                <span className="ml-auto text-xs font-semibold tabular-nums text-muted-foreground">
                  {rival.count}
                </span>
              </div>
              <ul className="flex flex-col gap-1">
                {rival.events.slice(0, 3).map((event) => (
                  <li key={event.id} className="truncate text-xs text-muted-foreground">
                    {event.headline}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function NetworkSignals({ section }: { section: BizOverviewOut["network_signals"] }) {
  return (
    <div className={cn(card, "flex flex-col gap-3")}>
      <div className="flex items-center justify-between gap-2">
        <SectionHeading icon={Route} title="Ağ Sinyalleri" />
        <Link
          href="/hublar"
          className="flex items-center gap-0.5 text-xs font-medium text-primary hover:underline"
        >
          Hub&apos;da gör
          <ArrowUpRight className="size-3" />
        </Link>
      </div>
      {!section.available ? (
        <EmptyState message={section.empty_message ?? ""} />
      ) : (
        <ul className="flex flex-wrap gap-2">
          {section.items.map((group) => (
            <li
              key={group.region ?? "other"}
              className="rounded-full border border-border px-2.5 py-1 text-xs text-muted-foreground"
            >
              {REGION_NAME[group.region ?? ""] ?? "Diğer"}{" "}
              <span className="font-semibold text-foreground">{group.count}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function CommercialSignals({ section }: { section: BizOverviewOut["commercial_signals"] }) {
  return (
    <div className={cn(card, "flex flex-col gap-3")}>
      <SectionHeading icon={ArrowUpRight} title="Ticari Sinyaller" />
      {!section.available ? (
        <EmptyState message={section.empty_message ?? ""} />
      ) : (
        <ul className="flex flex-col divide-y divide-border">
          {section.items.slice(0, 6).map((item) => {
            const meta = SEVERITY_META[item.severity];
            const Icon = meta.icon;
            return (
              <li key={item.id} className="flex flex-col gap-1 py-2.5">
                <div className="flex items-start gap-2">
                  <span
                    className={cn(
                      "flex shrink-0 items-center gap-1 rounded-full px-1.5 py-0.5 text-[11px] font-medium",
                      meta.className,
                    )}
                  >
                    <Icon className="size-3" />
                    {meta.label}
                  </span>
                  <p className="text-sm font-medium leading-snug">{item.title}</p>
                </div>
                <p className="pl-[3.75rem] text-xs text-muted-foreground">{item.rationale}</p>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function StrategicDevelopments({ section }: { section: BizOverviewOut["strategic_developments"] }) {
  return (
    <div className={cn(card, "flex flex-col gap-3")}>
      <SectionHeading icon={Building2} title="Stratejik Gelişmeler" />
      {!section.available ? (
        <EmptyState message={section.empty_message ?? ""} />
      ) : (
        <ul className="flex flex-col divide-y divide-border">
          {section.items.slice(0, 8).map((event) => (
            <li key={event.id} className="flex items-center gap-2 py-2 text-sm">
              <AlertTriangle className="size-3.5 shrink-0 text-muted-foreground" />
              <span className="flex-1 truncate">{event.headline}</span>
              <span className="text-[11px] text-muted-foreground">{event.category}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** The four BİZ sections queried straight off pipeline-v2 tables -- see
 * backend/app/services/biz_service.py. No v1-style generated narrative text
 * here; every line is a counting statement over real rows. */
export function BizSignals() {
  const [data, setData] = useState<BizOverviewOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiFetch<BizOverviewOut>("/biz?days=30", { cache: "default" })
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch(() => {
        if (!cancelled) setError("Sinyaller yüklenemedi. Sunucu çalışıyor mu?");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return <p className="text-sm text-muted-foreground">{error}</p>;
  }
  if (!data) {
    return (
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-48 w-full rounded-xl" />
        ))}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      <CompetitorSignals section={data.competitor_signals} />
      <NetworkSignals section={data.network_signals} />
      <CommercialSignals section={data.commercial_signals} />
      <StrategicDevelopments section={data.strategic_developments} />
    </div>
  );
}
