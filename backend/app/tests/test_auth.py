import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.deps import require_roles
from app.core.security import create_access_token, decode_access_token, hash_password, verify_password
from app.models.user import User


def test_password_hash_roundtrip():
    hashed = hash_password("correct-horse-battery-staple")
    assert verify_password("correct-horse-battery-staple", hashed)
    assert not verify_password("wrong-password", hashed)


def test_access_token_roundtrip():
    token = create_access_token(subject="user@example.com", role="admin")
    payload = decode_access_token(token)
    assert payload is not None
    assert payload["sub"] == "user@example.com"
    assert payload["role"] == "admin"


def test_decode_access_token_rejects_garbage():
    assert decode_access_token("not-a-real-token") is None


@pytest.fixture
def rbac_app(db_session, monkeypatch):
    """A tiny app exercising get_current_user + require_roles against a real
    user row, without needing the full FastAPI app's DB dependency wiring."""
    from app.core import deps

    app = FastAPI()

    @app.get("/admin-only")
    async def admin_only(user: User = Depends(require_roles("admin"))):
        return {"email": user.email}

    async def override_get_db():
        yield db_session

    app.dependency_overrides[deps.get_db] = override_get_db
    return app


async def _make_user(db_session, email: str, role: str) -> None:
    from app.repositories.user_repository import UserRepository

    repo = UserRepository(db_session)
    await repo.create(email, "password123", role=role)
    await db_session.commit()


async def test_require_roles_allows_matching_role(rbac_app, db_session):
    await _make_user(db_session, "admin@example.com", "admin")
    token = create_access_token(subject="admin@example.com", role="admin")

    transport = ASGITransport(app=rbac_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/admin-only", headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 200
    assert response.json() == {"email": "admin@example.com"}


async def test_require_roles_rejects_wrong_role(rbac_app, db_session):
    await _make_user(db_session, "reader@example.com", "reader")
    token = create_access_token(subject="reader@example.com", role="reader")

    transport = ASGITransport(app=rbac_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/admin-only", headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 403


async def test_require_roles_rejects_missing_token(rbac_app):
    transport = ASGITransport(app=rbac_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin-only")

    assert response.status_code == 401
