"""OpenSky Network -- free, keyless, anonymous-rate-limited ADS-B state vectors.
Used for the one KPI that's genuinely observable without a licensed feed:
how many aircraft are airborne right now.
"""
import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)
REQUEST_TIMEOUT = httpx.Timeout(15.0)


async def fetch_airborne_count(base_url: str) -> int | None:
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.get(f"{base_url}/states/all")
            response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("opensky_fetch_failed", error=str(exc))
        return None

    data = response.json()
    states = data.get("states") or []
    # state vector index 8 is on_ground (bool)
    airborne = sum(1 for s in states if s[8] is False)
    logger.info("opensky_fetch_ok", total_states=len(states), airborne=airborne)
    return airborne
