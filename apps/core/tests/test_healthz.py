"""Healthz: public, no DB, answers ok."""

from rest_framework.test import APIClient


def test_healthz_is_public_and_ok():
    client = APIClient()
    response = client.get("/api/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "fitlog-django"}
