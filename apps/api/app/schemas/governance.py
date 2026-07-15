from pydantic import BaseModel, Field


class AuditRequest(BaseModel):
    data_root: str = "data/raw"
    sample_size: int = Field(default=50, ge=1, le=10000)
    seed: int = 2026
    include_failures: bool = True


class AuditRunResponse(BaseModel):
    run_id: str
    run_type: str
    created_at: str
    parameters: dict
    artifacts: dict[str, str]
    status: str
    errors: list[str]


class CompareRequest(BaseModel):
    baseline_run_id: str
    current_run_id: str
