"""The fund/ETF catalog behind the /invest module -- plain data, no dependencies
(same role taxonomy.py plays for article categories).

The two portfolios' target weights were chosen by the user, not by us; the API
labels them "örnek dağılım" and the UI carries a fixed not-investment-advice
disclaimer. Frontend reads all of this through the API -- never duplicated there.
"""
from dataclasses import dataclass

MARKET_US = "us"
MARKET_TR = "tr"

# Where each fund's authoritative holdings file lives (drives adapter dispatch
# in fund_service; "tefas" funds get asset-class allocation instead of holdings).
HOLDINGS_SOURCE_SSGA = "ssga"
HOLDINGS_SOURCE_ARK = "ark"
HOLDINGS_SOURCE_VANGUARD = "vanguard"
HOLDINGS_SOURCE_TEFAS = "tefas"


@dataclass(frozen=True)
class FundSpec:
    symbol: str
    market: str  # MARKET_US | MARKET_TR
    name: str
    currency: str  # "USD" | "TRY"
    target_weight: float  # user's example allocation within its market's portfolio
    issuer: str
    holdings_source: str


FUND_CATALOG: tuple[FundSpec, ...] = (
    # US portfolio: 40/20/20/10/10
    FundSpec("XLV", MARKET_US, "Health Care Select Sector SPDR Fund", "USD", 0.40, "State Street (SSGA)", HOLDINGS_SOURCE_SSGA),
    FundSpec("VHT", MARKET_US, "Vanguard Health Care ETF", "USD", 0.20, "Vanguard", HOLDINGS_SOURCE_VANGUARD),
    FundSpec("XLF", MARKET_US, "Financial Select Sector SPDR Fund", "USD", 0.20, "State Street (SSGA)", HOLDINGS_SOURCE_SSGA),
    FundSpec("XBI", MARKET_US, "SPDR S&P Biotech ETF", "USD", 0.10, "State Street (SSGA)", HOLDINGS_SOURCE_SSGA),
    FundSpec("ARKG", MARKET_US, "ARK Genomic Revolution ETF", "USD", 0.10, "ARK Invest", HOLDINGS_SOURCE_ARK),
    # TR portfolio: 35/25/20/20. Official fund titles (FONUNVAN) and issuers are
    # overwritten from the TEFAS API on every refresh -- the placeholders below
    # exist only so the UI renders something before the first successful fetch,
    # and they stay flagged unverified (metadata_verified=False) until then.
    FundSpec("AFS", MARKET_TR, "AFS — TEFAS fonu (resmî ad ilk veri çekiminde gelecek)", "TRY", 0.35, "", HOLDINGS_SOURCE_TEFAS),
    FundSpec("TBE", MARKET_TR, "TBE — TEFAS fonu (resmî ad ilk veri çekiminde gelecek)", "TRY", 0.25, "", HOLDINGS_SOURCE_TEFAS),
    FundSpec("TI2", MARKET_TR, "TI2 — TEFAS fonu (resmî ad ilk veri çekiminde gelecek)", "TRY", 0.20, "", HOLDINGS_SOURCE_TEFAS),
    FundSpec("MAC", MARKET_TR, "MAC — TEFAS fonu (resmî ad ilk veri çekiminde gelecek)", "TRY", 0.20, "", HOLDINGS_SOURCE_TEFAS),
)


def get_fund_spec(symbol: str) -> FundSpec | None:
    for spec in FUND_CATALOG:
        if spec.symbol == symbol.upper():
            return spec
    return None


def specs_for_market(market: str) -> list[FundSpec]:
    return [spec for spec in FUND_CATALOG if spec.market == market]
