from pathlib import Path

from app.core.config import get_settings
from app.core.container import get_container
from app.main import app
from fastapi.testclient import TestClient


def test_governance_api_runs_audit(tmp_path: Path) -> None:
    data_root = tmp_path / "audit-data"
    data_root.mkdir()
    (data_root / "sample.md").write_text("# ??\n\nPage ID: 99\n\n????", encoding="utf-8")
    settings = get_settings()
    original_reports = settings.data_reports_dir
    settings.data_reports_dir = tmp_path / "reports"
    get_container.cache_clear()
    with TestClient(app) as client:
        bootstrap = client.post(
            "/api/v1/security/bootstrap",
            headers={"x-bootstrap-token": settings.security_bootstrap_token},
            json={
                "username": "governance-admin",
                "password": "StrongPassword123!",
                "tenant_name": "Governance Tenant",
                "tenant_slug": "governance-tenant",
            },
        )
        assert bootstrap.status_code == 201, bootstrap.text
        headers = {"authorization": f"Bearer {bootstrap.json()['access_token']}"}
        response = client.post(
            "/api/v1/governance/audits",
            headers=headers,
            json={"data_root": str(data_root), "sample_size": 1, "seed": 1},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["status"] == "completed"
        assert Path(payload["artifacts"]["overview"]).exists()
        listed = client.get("/api/v1/governance/audits", headers=headers)
        assert listed.status_code == 200
        assert listed.json()[0]["run_id"] == payload["run_id"]
    settings.data_reports_dir = original_reports
    get_container.cache_clear()
