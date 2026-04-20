from __future__ import annotations

from dataclasses import dataclass

from fastapi.testclient import TestClient


@dataclass(frozen=True, slots=True)
class AuthSession:
    access_token: str
    refresh_token: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}


def bootstrap_admin(
    client: TestClient,
    *,
    username: str = "admin",
    password: str = "super-secure-password",
) -> None:
    response = client.post(
        "/api/auth/bootstrap-admin",
        json={"username": username, "password": password},
    )
    assert response.status_code == 201, response.text


def login_user(
    client: TestClient,
    *,
    username: str = "admin",
    password: str = "super-secure-password",
) -> AuthSession:
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    return AuthSession(
        access_token=payload["access_token"],
        refresh_token=payload["refresh_token"],
    )
