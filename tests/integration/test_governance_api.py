from pathlib import Path

from app.core.config import get_settings
from app.main import app
from fastapi.testclient import TestClient


def test_governance_api_runs_audit(tmp_path: Path) -> None:
    data_root = tmp_path / "audit-data"
    data_root.mkdir()
    (data_root / "sample.md").write_text(
        "# 示例\n\nPage ID: 99\n\n正文内容",
        encoding="utf-8",
    )
    settings = get_settings()
    original_reports = settings.data_reports_dir
    settings.data_reports_dir = tmp_path / "reports"
    from app.core.container import get_container

    get_container.cache_clear()
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/governance/audits",
            json={"data_root": str(data_root), "sample_size": 1, "seed": 1},
        )
        assert response.status_code == 200, response.text
        run_id = response.json()["run_id"]
        assert client.get(f"/api/v1/governance/audits/{run_id}").status_code == 200
        assert len(client.get("/api/v1/governance/audits").json()) == 1
    get_container.cache_clear()
    settings.data_reports_dir = original_reports
