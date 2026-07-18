import { Info } from "lucide-react";

import { AnalysisPanel } from "@/components/funds/analysis-panel";
import { FundCard } from "@/components/funds/fund-card";
import { PortfolioAllocationChart } from "@/components/funds/portfolio-allocation-chart";
import { getFunds, getFundsPortfolio } from "@/lib/api";
import type { FundOut, PortfoliosOut } from "@/lib/types";

export const metadata = {
  title: "Yatırım — AeroIntel",
};

function PortfolioSection({
  heading,
  description,
  funds,
  portfolio,
}: {
  heading: string;
  description: string;
  funds: FundOut[];
  portfolio: PortfoliosOut["us"] | null;
}) {
  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h2 className="text-lg font-semibold tracking-tight">{heading}</h2>
        <p className="text-sm text-muted-foreground">{description}</p>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="flex flex-col gap-4 rounded-xl border border-border bg-card p-5 lg:col-span-1">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Örnek dağılım
          </h3>
          {portfolio ? (
            <PortfolioAllocationChart
              funds={portfolio.funds}
              weightedReturn1yPct={portfolio.weighted_return_1y_pct}
            />
          ) : (
            <p className="text-sm text-muted-foreground">Portföy verisi yüklenemedi.</p>
          )}
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:col-span-2">
          {funds.map((fund) => (
            <FundCard key={fund.symbol} fund={fund} />
          ))}
        </div>
      </div>

      {portfolio && <AnalysisPanel analysis={portfolio.analysis} title="Portföy değerlendirmesi" />}
    </section>
  );
}

export default async function InvestPage() {
  let funds: FundOut[] = [];
  let portfolios: PortfoliosOut | null = null;
  let error: string | null = null;

  try {
    [funds, portfolios] = await Promise.all([getFunds(), getFundsPortfolio()]);
  } catch {
    error = "Fon API'sine ulaşılamadı. Sunucu çalışıyor mu?";
  }

  const usFunds = funds.filter((f) => f.market === "us");
  const trFunds = funds.filter((f) => f.market === "tr");
  const disclaimer =
    portfolios?.disclaimer ??
    "Bu içerik yatırım tavsiyesi değildir; yalnızca bilgilendirme amaçlıdır.";

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">Yatırım</h1>
        <p className="text-sm text-muted-foreground">
          ABD ETF&apos;leri ve TEFAS fonları için fiyat, portföy dağılımı ve analiz —
          her veri kaynağıyla birlikte doğrulama durumu gösterilir.
        </p>
      </div>

      <div className="flex items-start gap-2 rounded-lg border border-warning/30 bg-warning/5 p-3 text-sm text-muted-foreground">
        <Info className="mt-0.5 size-4 shrink-0 text-warning" />
        <span>{disclaimer}</span>
      </div>

      {error ? (
        <p className="rounded-lg border border-dashed border-border p-6 text-sm text-muted-foreground">
          {error}
        </p>
      ) : (
        <div className="flex flex-col gap-10">
          <PortfolioSection
            heading="ABD ETF Portföyü"
            description="Sağlık ve finans sektörü ağırlıklı örnek dağılım (XLV %40 · VHT %20 · XLF %20 · XBI %10 · ARKG %10)."
            funds={usFunds}
            portfolio={portfolios?.us ?? null}
          />
          <PortfolioSection
            heading="TEFAS Fon Portföyü"
            description="TEFAS üzerinden erişilebilen fonlarla örnek dağılım (AFS %35 · TBE %25 · TI2 %20 · MAC %20)."
            funds={trFunds}
            portfolio={portfolios?.tr ?? null}
          />
        </div>
      )}
    </div>
  );
}
