import { notFound } from "next/navigation";

import { FundDetailClient } from "@/components/funds/fund-detail-client";
import { ApiError, getFundDetail, getFundHoldings } from "@/lib/api";
import type { FundDetailOut, FundHoldingsOut } from "@/lib/types";

export default async function FundDetailPage({
  params,
}: {
  params: Promise<{ symbol: string }>;
}) {
  const { symbol } = await params;

  let detail: FundDetailOut;
  let holdings: FundHoldingsOut | null = null;
  try {
    [detail, holdings] = await Promise.all([
      getFundDetail(symbol),
      getFundHoldings(symbol).catch(() => null),
    ]);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      notFound();
    }
    throw err;
  }

  return <FundDetailClient detail={detail} holdings={holdings} />;
}
