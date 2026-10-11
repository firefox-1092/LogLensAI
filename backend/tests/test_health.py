from fastapi.testclient import TestClient

from backend.app.main import create_app


def test_health_endpoint_reports_healthy_and_cors() -> None:
    app = create_app("sqlite://")
    with TestClient(app) as client:
        response = client.get(
            "/health", headers={"Origin": "http://127.0.0.1:5173"}
        )

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
