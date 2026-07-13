"""Command-line entrypoints for local/manual runs of the daily pipeline stages.
Mirrors what the APScheduler jobs call in production -- see app/scheduler/jobs.py.

Usage: python -m app.cli <command>
"""
import argparse
import asyncio

from app.core.db import AsyncSessionLocal
from app.core.logging import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)


async def _ingest() -> None:
    from app.services.ingestion_service import run_ingestion

    async with AsyncSessionLocal() as db:
        inserted = await run_ingestion(db)
        print(f"Ingestion complete: {inserted} new articles")


async def _full_cycle() -> None:
    from app.services.daily_cycle import run_daily_ingest_and_enrich

    await run_daily_ingest_and_enrich()
    print("Ingest + dedup + enrichment complete")


async def _build_edition() -> None:
    from datetime import date

    from app.services.edition_service import assemble_edition

    async with AsyncSessionLocal() as db:
        edition = await assemble_edition(db, date.today())
        print(f"Edition assembled for {edition.edition_date}: {edition.headline}")


async def _refresh_kpis() -> None:
    from app.services.kpi_service import refresh_all_kpis

    async with AsyncSessionLocal() as db:
        recorded = await refresh_all_kpis(db)
        print(f"KPI refresh complete: {recorded} observations recorded")


async def _send_newsletter() -> None:
    from app.services.daily_cycle import run_daily_edition_and_newsletter

    await run_daily_edition_and_newsletter()
    print("Edition assembled, PDF rendered (if available), newsletter dispatched")


async def _create_admin(email: str, password: str) -> None:
    from app.repositories.user_repository import UserRepository

    async with AsyncSessionLocal() as db:
        repo = UserRepository(db)
        if await repo.get_by_email(email) is not None:
            print(f"A user with email {email} already exists")
            return
        await repo.create(email, password, role="admin")
        await db.commit()
        print(f"Admin account created: {email}")


def main() -> None:
    parser = argparse.ArgumentParser(description="AeroIntel pipeline CLI")
    parser.add_argument(
        "command",
        choices=[
            "ingest",
            "full-cycle",
            "build-edition",
            "refresh-kpis",
            "send-newsletter",
            "create-admin",
        ],
    )
    parser.add_argument("--email", help="Required for create-admin")
    parser.add_argument("--password", help="Required for create-admin")
    args = parser.parse_args()

    if args.command == "ingest":
        asyncio.run(_ingest())
    elif args.command == "full-cycle":
        asyncio.run(_full_cycle())
    elif args.command == "build-edition":
        asyncio.run(_build_edition())
    elif args.command == "refresh-kpis":
        asyncio.run(_refresh_kpis())
    elif args.command == "send-newsletter":
        asyncio.run(_send_newsletter())
    elif args.command == "create-admin":
        if not args.email or not args.password:
            parser.error("create-admin requires --email and --password")
        asyncio.run(_create_admin(args.email, args.password))


if __name__ == "__main__":
    main()
