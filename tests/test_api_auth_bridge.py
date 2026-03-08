from __future__ import annotations

from fastapi.testclient import TestClient
from itsdangerous import URLSafeTimedSerializer

from radcast.api import app


def test_auth_bridge_sets_session_and_redirects_home():
    client = TestClient(app)
    serializer = URLSafeTimedSerializer("radcast-dev-session-secret", salt="app-bridge-radcast-v1")
    token = serializer.dumps(
        {
            "sub": 123,
            "email": "user@example.com",
            "display_name": "Test User",
            "is_admin": False,
            "issuer": "psychek",
        }
    )

    response = client.get(f"/auth/bridge?token={token}", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers.get("location") == "/"

    home = client.get("/")
    assert home.status_code == 200
    assert "RADcast Studio" in home.text
