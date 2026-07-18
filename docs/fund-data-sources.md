# Fund / ETF Data Sources — Verification Record

The `/invest` module (backend `app/ingest/funds/`) pulls prices, history,
holdings, and allocations for 5 US ETFs (XLV, VHT, XLF, XBI, ARKG) and
4 TEFAS funds (AFS, TBE, TI2, MAC). This document records, per endpoint,
what was verified and from where — so nobody mistakes "written against the
documented shape" for "observed live".

## Probe results — Claude Code sandbox, 2026-07-18

Every endpoint below returned **CONNECT 403 (egress-proxy policy denial)**
from the development sandbox. That is a property of the sandbox's network
policy, not of the endpoints: this deployment already fetches
`query1.finance.yahoo.com` successfully in production (see
`app/ingest/markets.py`, live KPI dashboard). Adapters were therefore
written against documented/community-verified response shapes and **must be
confirmed on first production run** — which the code itself does: every
stored row carries a `verification_status`, and anything that could not be
cross-checked at runtime is labeled accordingly in the UI.

| Endpoint | Sandbox probe | Basis for the adapter |
|---|---|---|
| `GET query1.finance.yahoo.com/v8/finance/chart/{sym}?range=1y&interval=1d` | 403 (proxy) | Same endpoint already in production use by this repo (`markets.py`). Keyless. |
| `GET query1.finance.yahoo.com/v10/finance/quoteSummary/{sym}?modules=topHoldings,fundProfile` | 403 (proxy) | Community-documented; requires cookie+crumb handshake and is known-flaky (yfinance issues #2404/#2441). Secondary source only — the service treats `None` as normal. |
| `POST tefas.gov.tr/api/funds/fonGnlBlgSiraliGetir` (price/AUM/investors) | 403 (proxy) | Current TEFAS site API used by maintained libraries (pytefas, tefas-crawler ≥2026). Look-back enum months {1,3,6,12,36,60}; ~6 req/min rate limit — adapter sleeps 10s between funds. |
| `POST tefas.gov.tr/api/funds/dagilimSiraliGetirT` (asset allocation) | 403 (proxy) | Same basis as above. |
| `POST tefas.gov.tr/api/DB/BindHistoryInfo` (legacy) | 403 (proxy) | Pre-2026 API, possibly retired. Kept as a fallback code path; adapter logs which generation answered. |
| `GET assets.ark-funds.com/fund-documents/funds-etf-csv/ARK_GENOMIC_REVOLUTION_ETF_ARKG_HOLDINGS.csv` | 403 (proxy) | URL pattern confirmed via indexed sibling files (ARKX/ARKVX at the same path). Adapter also probes the older `..._MULTISECTOR_ETF_ARKG_...` filename. Issuer-authoritative full holdings, dated. |
| `GET ssga.com/library-content/products/fund-data/etfs/us/holdings-daily-us-en-{xlv,xlf,xbi}.xlsx` | 403 (proxy) | Pattern confirmed via indexed sibling files (xlb, prsd). XLSX parsed with openpyxl by scanning for the header row (SSGA shifts the preamble). Issuer-authoritative full holdings. |
| Vanguard VHT holdings | 403 (proxy); no clean keyless endpoint confirmed by research either | Weakest source. Adapter attempts Vanguard's unofficial JSON; on failure the service falls back to Yahoo topHoldings top-10 and stores `is_top10_only=True` + `single_source`. |
| `GET stockanalysis.com/api/symbol/e/{sym}` | 403 (proxy) | Unofficial but community-documented quote API. Used only as a price cross-check (the Frankfurter role). Unavailable ⇒ price rows stay `single_source`, never silently "verified". |

## Verification statuses (stored per row, rendered as UI badges)

- `verified` — two independent sources agreed within tolerance
  (price: ≤1% diff; holdings weight: ≤2pp absolute per name).
- `official_single_source` — TEFAS: the regulator-run platform is the
  authoritative record and has no independent mirror
  (fundturkey.com.tr is the same backend). Honest label, not "verified".
- `single_source` — only one source answered; cross-check unavailable.
- `discrepancy` — sources disagreed beyond tolerance; surfaced, not hidden.

## First-run checklist (network-enabled environment)

1. `POST /api/v1/funds/refresh` (admin) or wait for the scheduled job.
2. Check logs for `funds_refresh_summary`: which adapters answered, which
   fell back, which generation of the TEFAS API responded.
3. Spot-check `/invest`: every card must show a verification badge and a
   fresh `as_of`; `discrepancy` badges warrant a manual look at both sources.
