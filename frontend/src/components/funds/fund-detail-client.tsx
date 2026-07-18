"use client";

import { ArrowDownRight, ArrowUpRight, BadgeCheck, ExternalLink, Minus } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { AllocationPie } from "@/components/funds/allocation-pie";
import { AnalysisPanel } from "@/components/funds/analysis-panel";
import { FundTrendChart } from "@/components/funds/fund-trend-chart";
import { HoldingsChart } from "@/components/funds/holdings-chart";
import { VerificationBadge } from "@/components/funds/verification-badge";
import { Badge } from "@/components/ui/badge";
import { getFundHistory } from "@/lib/api";
import { formatCompactNumber, formatFundValue, formatPercent } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { FundDetailOut, FundHistoryOut, FundHoldingsOut, FundPeriod } from "@/lib/types";

const PERIODS: { value: FundPeriod; label: string }[] = [
  { value: "1m", label: "1M" },
  { value: "3m", label: "3M" },
  { value: "6m", label: "6M" },
  { value: "1y", label: "12M" },
];

export function FundDetailClient({
  detail,
  holdings,
}: {
  detail: FundDetailOut;
  holdings: FundHoldingsOut | null;
}) {
  const [period, setPeriod] = useState<FundPeriod>("1y");
  const [history, setHistory] = useState<FundHistoryOut | null>(null);
  const [historyError, setHistoryError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getFundHistory(detail.symbol, period)
      .then((data) => {
        if (!cancelled) {
          setHistory(data);
          setHistoryError(false);
        }
      })
      .catch(() => {
        if (!cancelled) setHistoryError(true);
      });
    return () => {
      cancelled = true;
    };
  }, [detail.symbol, period]);

  const hasValue = detail.value !== null;
  const delta = detail.delta_pct ?? 0;
  const isFlat = delta === 0;
  const isPositive = delta >= 0;
  const deltaColor = isFlat
    ? "text-muted-foreground"
    : isPositive
      ? "text-good"
      : "text-critical";

  const allocationTitle =
    detail.market === "tr" ? "Varlık dağılımı" : "Sektör dağılımı";

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-1">
        <Link href="/invest" className="text-xs text-muted-foreground hover:underline">
          ← Yatırım
        </Link>
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-2xl font-semibold tracking-tight">{detail.symbol}</h1>
          <Badge variant="secondary">%{Math.round(detail.target_weight * 100)} hedef ağırlık</Badge>
        </div>
        <p className="text-sm text-muted-foreground">
          {detail.name}
          {detail.issuer ? ` · ${detail.issuer}` : ""}
        </p>
      </div>

      {/* Value + verification */}
      <div className="flex flex-wrap items-end justify-between gap-6 rounded-xl border border-border bg-card p-5">
        <div className="flex flex-col gap-1">
          {hasValue ? (
            <div className="flex items-baseline gap-2">
              <span className="text-4xl font-semibold tracking-tight">
                {formatFundValue(detail.value!, detail.currency)}
              </span>
              {detail.delta_pct !== null && (
                <span className={cn("flex items-center gap-0.5 text-sm font-medium", deltaColor)}>
                  {isFlat ? (
                    <Minus className="size-4" />
                  ) : isPositive ? (
                    <ArrowUpRight className="size-4" />
                  ) : (
                    <ArrowDownRight className="size-4" />
                  )}
                  {formatPercent(detail.delta_pct, 1)}
                </span>
              )}
            </div>
          ) : (
            <span className="text-lg text-muted-foreground">
              Fiyat verisi ilk güncellemede gelecek
            </span>
          )}
          <VerificationBadge status={detail.verification_status} asOf={detail.as_of} />
          {detail.as_of && (
            <p className="text-xs text-muted-foreground">
              {new Date(detail.as_of).toLocaleString("tr-TR", {
                dateStyle: "medium",
                timeStyle: "short",
              })}{" "}
              itibarıyla
              {detail.source && (
                <>
                  {" · "}
                  {detail.source_url ? (
                    <a
                      href={detail.source_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 text-primary hover:underline"
                    >
                      {detail.source}
                      <ExternalLink className="size-3" />
                    </a>
                  ) : (
                    detail.source
                  )}
                </>
              )}
            </p>
          )}
        </div>

        {/* Metadata */}
        <div className="flex flex-col gap-1 text-sm">
          {detail.expense_ratio !== null && (
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground">Gider oranı:</span>
              <span className="font-medium">%{detail.expense_ratio.toFixed(2)}</span>
            </div>
          )}
          {detail.aum !== null && (
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground">Fon büyüklüğü:</span>
              <span className="font-medium">
                {formatCompactNumber(detail.aum)} {detail.currency}
              </span>
            </div>
          )}
          {detail.metadata_source && (
            <div className="flex items-center gap-1 text-xs text-muted-foreground">
              {detail.metadata_verified && <BadgeCheck className="size-3.5 text-good" />}
              Meta veri kaynağı: {detail.metadata_source}
            </div>
          )}
        </div>
      </div>

      {/* Corroborations */}
      {detail.corroborations.length > 0 && (
        <div className="flex flex-col gap-2 rounded-xl border border-border bg-card p-5">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Çapraz doğrulama kaynakları
          </h2>
          {detail.corroborations.map((c) => (
            <div key={c.source} className="flex items-center gap-2 text-sm">
              <Badge variant="outline" className="text-[10px]">
                {c.diff_pct < 0.5 ? "Eşleşiyor" : `Δ %${c.diff_pct.toFixed(2)}`}
              </Badge>
              {c.source_url ? (
                <a
                  href={c.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-primary hover:underline"
                >
                  {c.source}
                </a>
              ) : (
                <span>{c.source}</span>
              )}
              <span className="text-muted-foreground">
                {formatFundValue(c.value, detail.currency)}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Trend chart */}
      <div className="flex flex-col gap-3 rounded-xl border border-border bg-card p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Fiyat trendi
          </h2>
          <div className="flex gap-1 rounded-lg border border-border p-0.5">
            {PERIODS.map((p) => (
              <button
                key={p.value}
                onClick={() => setPeriod(p.value)}
                className={cn(
                  "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                  period === p.value
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
                )}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>
        {historyError ? (
          <p className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
            Geçmiş veri yüklenemedi.
          </p>
        ) : history && history.points.length > 1 ? (
          <FundTrendChart points={history.points} period={period} currency={detail.currency} />
        ) : (
          <p className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
            Bu dönem için henüz yeterli geçmiş veri kaydedilmedi.
          </p>
        )}
      </div>

      {/* Holdings + allocation */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="flex flex-col gap-3 rounded-xl border border-border bg-card p-5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              Pozisyonlar
            </h2>
            {holdings?.verification_status && (
              <VerificationBadge status={holdings.verification_status} asOf={holdings.as_of} />
            )}
          </div>
          <HoldingsChart
            holdings={holdings?.holdings ?? []}
            isTop10Only={holdings?.is_top10_only ?? false}
          />
          {holdings?.source && (
            <p className="text-xs text-muted-foreground">
              Kaynak: {holdings.source}
              {holdings.as_of &&
                ` · ${new Date(holdings.as_of).toLocaleDateString("tr-TR", { dateStyle: "medium" })}`}
            </p>
          )}
        </div>

        <div className="flex flex-col gap-3 rounded-xl border border-border bg-card p-5">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            {allocationTitle}
          </h2>
          <AllocationPie allocations={holdings?.allocations ?? []} />
        </div>
      </div>

      {/* Analysis */}
      <AnalysisPanel analysis={detail.analysis} title="Analiz ve görünüm" />
    </div>
  );
}
