"use client";

import { ExternalLink } from "lucide-react";
import { useEffect, useState } from "react";

import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api";
import type { IataIndicatorOut } from "@/lib/types";
import { cn } from "@/lib/utils";

const METRIC_LABEL_TR: Record<string, string> = {
  ebit: "Faiz ve vergi öncesi kâr (EBIT)",
  load_factor: "Doluluk oranı",
  passenger_demand: "Yolcu talebi",
  rpk_growth: "RPK büyümesi",
};

const KIND_LABEL: Record<IataIndicatorOut["kind"], string> = {
  actual: "Gerçekleşme",
  forecast: "Tahmin",
};

const tab = (active: boolean) =>
  cn(
    "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
    active ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-accent",
  );

/** IATA's own published figures, forecast and actual kept structurally
 * separate -- see backend/app/models/curated.py's INDICATOR_KINDS. */
export function IataIndicatorTable() {
  const [kind, setKind] = useState<IataIndicatorOut["kind"]>("forecast");
  const [rows, setRows] = useState<IataIndicatorOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch driven by kind change; must flip synchronously so switching tabs shows a skeleton instead of stale rows from the other kind
    setRows(null);
    apiFetch<IataIndicatorOut[]>(`/kokpit/iata?kind=${kind}`, {
      cache: "default",
      signal: controller.signal,
    })
      .then((data) => {
        if (!cancelled) setRows(data);
      })
      .catch((err: unknown) => {
        if (cancelled || (err as Error)?.name === "AbortError") return;
        setError("IATA göstergeleri yüklenemedi.");
      });
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [kind]);

  if (error) {
    return <p className="text-sm text-muted-foreground">{error}</p>;
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex w-fit items-center gap-1 self-start rounded-lg border border-border p-0.5">
        {(["forecast", "actual"] as const).map((k) => (
          <button key={k} type="button" onClick={() => setKind(k)} className={tab(kind === k)}>
            {KIND_LABEL[k]}
          </button>
        ))}
      </div>

      {!rows ? (
        <Skeleton className="h-48 w-full rounded-xl" />
      ) : rows.length === 0 ? (
        <p className="rounded-xl border border-dashed border-border p-6 text-sm text-muted-foreground">
          Bu tür için henüz küratörlü bir IATA göstergesi yok.
        </p>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {rows.map((row) => (
            <Card key={`${row.metric}-${row.period_end}`} className="p-4">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="text-sm font-semibold">
                    {METRIC_LABEL_TR[row.metric] ?? row.metric}
                  </p>
                  <p className="text-[11px] text-muted-foreground">{row.period_label_tr}</p>
                </div>
                <a
                  href={row.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label="Kaynağa git"
                  className="text-muted-foreground hover:text-primary"
                >
                  <ExternalLink className="size-3.5" />
                </a>
              </div>
              <p className="mt-2 text-2xl font-semibold tabular-nums">
                {row.value.toLocaleString("tr-TR")}
                <span className="ml-1 text-sm font-normal text-muted-foreground">{row.unit}</span>
              </p>
              {row.interpretation_tr && (
                <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                  {row.interpretation_tr}
                </p>
              )}
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
