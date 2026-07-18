// The public URL: baked into the client bundle at build time, and what every
// browser-facing href (PDF download links, etc) must use regardless of which
// component builds them.
export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

// In a multi-container deployment (see docker-compose.yml), server components
// running inside the frontend container can't reach the public URL (it's a
// mapped host port, not a routable in-container address) -- API_INTERNAL_URL
// lets server-side fetches go straight to the backend service over the
// Docker network instead. Unset in local dev, where both sides share
// localhost, so behavior there is unchanged.
function resolveFetchBaseUrl(): string {
  if (typeof window === "undefined" && process.env.API_INTERNAL_URL) {
    return process.env.API_INTERNAL_URL;
  }
  return API_BASE_URL;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function apiFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const res = await fetch(`${resolveFetchBaseUrl()}${path}`, {
    ...init,
    cache: "no-store",
    headers: { "Content-Type": "application/json", ...init?.headers },
  });

  if (!res.ok) {
    throw new ApiError(`API request failed: ${res.status}`, res.status);
  }
  return res.json() as Promise<T>;
}

// --- /invest module fetchers (backend/app/api/v1/funds.py) ------------------

import type {
  FundDetailOut,
  FundHistoryOut,
  FundHoldingsOut,
  FundOut,
  FundPeriod,
  PortfoliosOut,
} from "@/lib/types";

export function getFunds(): Promise<FundOut[]> {
  return apiFetch<FundOut[]>("/funds");
}

export function getFundsPortfolio(): Promise<PortfoliosOut> {
  return apiFetch<PortfoliosOut>("/funds/portfolio");
}

export function getFundDetail(symbol: string): Promise<FundDetailOut> {
  return apiFetch<FundDetailOut>(`/funds/${encodeURIComponent(symbol)}`);
}

export function getFundHistory(symbol: string, period: FundPeriod): Promise<FundHistoryOut> {
  return apiFetch<FundHistoryOut>(`/funds/${encodeURIComponent(symbol)}/history?period=${period}`);
}

export function getFundHoldings(symbol: string): Promise<FundHoldingsOut> {
  return apiFetch<FundHoldingsOut>(`/funds/${encodeURIComponent(symbol)}/holdings`);
}
