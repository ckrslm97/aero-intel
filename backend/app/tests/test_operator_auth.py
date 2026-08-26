"""The operator endpoints used to be reachable by anyone.

/admin/status returned source counts, article-status breakdowns, subscriber
counts, delivery failures and the configured LLM provider -- a map of the
deployment. GET /subscribers returned email addresses, under a docstring that
claimed it was already admin-only. Neither had any authentication at all.

These tests are the reason that cannot come back unnoticed.
"""
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1 import admin as admin_api
from app.api.v1 import editions as editions_api
from app.api.v1 import subscribers as subscribers_api
from app.core.config import get_settings
from app.core.db import get_db

TOKEN = "test-operator-token"

GUARDED_READS = ("/api/v1/admin/status", "/api/v1/subscribers")


@pytest.fixture
def client_factory(db_session, monkeypatch):
    def build(token: str | None) -> AsyncClient:
        get_settings.cache_clear()
        if token is None:
            monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        else:
            monkeypatch.setenv("ADMIN_TOKEN", token)

        app = FastAPI()
        app.include_router(admin_api.router, prefix="/api/v1")
        app.include_router(subscribers_api.router, prefix="/api/v1")
        app.include_router(editions_api.router, prefix="/api/v1")

        async def override_get_db():
            yield db_session

        app.dependency_overrides[get_db] = override_get_db
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    yield build
    get_settings.cache_clear()


@pytest.mark.parametrize("path", GUARDED_READS)
async def test_no_token_is_rejected(client_factory, path):
    async with client_factory(TOKEN) as client:
        response = await client.get(path)
    assert response.status_code == 401, path


@pytest.mark.parametrize("path", GUARDED_READS)
async def test_wrong_token_is_rejected(client_factory, path):
    async with client_factory(TOKEN) as client:
        response = await client.get(path, headers={"Authorization": "Bearer nope"})
    assert response.status_code == 401, path


@pytest.mark.parametrize("path", GUARDED_READS)
async def test_correct_token_is_accepted(client_factory, path):
    async with client_factory(TOKEN) as client:
        response = await client.get(path, headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 200, path


@pytest.mark.parametrize("path", GUARDED_READS)
async def test_unconfigured_token_denies_rather_than_opens(client_factory, path):
    """A deployment that forgets ADMIN_TOKEN gets a closed door, not an open one.
    Failing open on a missing variable is how these endpoints were public in the
    first place."""
    async with client_factory(None) as client:
        response = await client.get(path, headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 503, path


async def test_edition_rebuild_is_operator_only(client_factory):
    """A POST that reassembles a published day and spends the LLM budget doing
    it. Anyone could call it."""
    async with client_factory(TOKEN) as client:
        response = await client.post("/api/v1/editions/2026-01-01/rebuild")
    assert response.status_code == 401


async def test_subscriber_signup_stays_public(client_factory):
    """The gate is on reading the list, not on joining it -- POST is the only
    way a subscriber is ever created."""
    async with client_factory(TOKEN) as client:
        response = await client.post(
            "/api/v1/subscribers", json={"email": "reader@example.com"}
        )
    assert response.status_code == 201
